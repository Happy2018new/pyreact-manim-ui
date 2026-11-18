"""Offline regression: actual installed assets, SDK lifecycle, and fail-closed pixels."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location('outline_test_' + name, HERE / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


builder, runtime, verifier = (_load(name) for name in ('build_fixture', 'runtime', 'verify'))


class Query(object):
    def __init__(self, factory, entity):
        self.factory, self.entity = factory, entity

    def Register(self, name, value):
        if name in self.factory.registered:
            return False
        self.factory.registered[name] = value
        return True

    def Set(self, name, value):
        if name not in self.factory.registered:
            return False
        self.factory.values[(self.entity, name)] = value
        return True

    def Get(self, name):
        return self.factory.values.get((self.entity, name), self.factory.registered.get(name))

    def UnRegister(self, name):
        return self.factory.registered.pop(name, None) is not None


class Camera(object):
    def GetPosition(self):
        return (0., 0., 0.)

    def GetForward(self):
        return (0., 0., 1.)

    def GetWorldRayFromScreenPoint(self, x, y):
        return {'origin': (0., 0., 0.), 'direction': ((x - 360.) / 1000., (540. - y) / 1000., 1.)}

    def WorldToScreenPoint(self, x, y, z):
        return {'screenX': 360. + x / z * 1000., 'screenY': 540. - y / z * 1000.,
                'depth': z / 100., 'isInScreen': True}


class Actor(object):
    def __init__(self, position):
        self.position, self.shadow = position, True

    def GetFootPos(self):
        return self.position

    def SetEntityShadowShow(self, show):
        self.shadow = show

    def GetActorRenderParams(self, entity, category, getValue=False):
        return list(builder.MATERIALS.values()) if category == 'materials' else list(runtime.CONTROLLERS)


class Factory(object):
    def __init__(self):
        self.registered, self.values, self.actors = {}, {}, {}

    def CreateQueryVariable(self, entity):
        return Query(self, entity)

    def CreateActorRender(self, entity):
        return self.actors[entity]

    CreateModel = CreateActorRender
    CreatePos = CreateActorRender


class Probe(object):
    def __init__(self, reject=False):
        self.factory, self.level, self.camera = Factory(), 'level', Camera()
        self.roi, self.viewport = [8, 128, 512, 512], [720, 1080]
        self.reject, self.destroyed, self.created = reject, [], []

    def CreateClientEntityByTypeStr(self, kind, position, rotation):
        if self.reject:
            return None
        entity = 'outline-native-client-entity'
        self.created.append((kind, position, rotation))
        self.factory.actors[entity] = Actor(position)
        return entity

    def DestroyClientEntity(self, entity):
        self.destroyed.append(entity)
        self.factory.actors.pop(entity)


class OutlineFixtureTests(unittest.TestCase):
    def test_build_references_native_recipe_without_overrides(self):
        runtime_root = ROOT / '.runtime'
        runtime_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='outline_offline_', dir=str(runtime_root)) as temporary:
            receipt = builder.build_assets(temporary)
            root = Path(temporary)
            self.assertEqual(receipt['shared_transport_bits'], 64)
            self.assertFalse(receipt['native_material_or_shader_modified'])
            self.assertFalse((root / 'resource_pack/materials/entity.material').exists())
            controllers = json.loads((root / 'resource_pack/render_controllers/integrated_outline_cube.json').read_text())
            base = controllers['render_controllers'][builder.CONTROLLER + 'base']
            outline = controllers['render_controllers'][builder.CONTROLLER + 'outline']
            self.assertEqual(base['arrays']['materials']['Array.base'], ['Material.plain', 'Material.stencil_base'])
            self.assertIn('? 1 : 0', base['materials'][0]['*'])
            self.assertEqual(outline['part_visibility'], [{'*': builder.QUERY + ' > 0.5'}])
            self.assertTrue(outline['ignore_lighting'] and outline['smooth_normal'])
            self.assertEqual((root / 'behavior_pack/stencil_large/outline_fixture.py').read_bytes(), (HERE / 'runtime.py').read_bytes())

    def test_fixed_entity_off_on_off_and_cleanup(self):
        probe = Probe()
        fixture = runtime.OutlineFixture(probe)
        before = fixture.create()
        on = fixture.set_enabled(True)
        after = fixture.set_enabled(False)
        self.assertTrue(verifier.compare_snapshots(before, on, after)['pass'])
        self.assertEqual(len(probe.created), 1)
        self.assertLess(on['projected_bounds'][0], 520)
        self.assertGreater(on['projected_bounds'][2], 520)
        self.assertFalse(probe.factory.actors[on['entity']].shadow)
        changed_projection = dict(on, projected_bounds=[0., 0., 1., 1.])
        self.assertFalse(verifier.compare_snapshots(before, changed_projection, after)['pass'])
        missing_materials = dict(on, native_material_recipe_present=False)
        self.assertFalse(verifier.compare_snapshots(before, missing_materials, after)['pass'])
        with self.assertRaises(ValueError):
            fixture.set_enabled(1)
        fixture.destroy()
        self.assertEqual(probe.destroyed, [on['entity']])
        self.assertEqual(probe.factory.registered, {})

    def test_failed_create_unregisters_query(self):
        probe = Probe(reject=True)
        fixture = runtime.OutlineFixture(probe)
        with self.assertRaises(RuntimeError):
            fixture.create()
        self.assertEqual(probe.factory.registered, {})
        self.assertIsNone(fixture.entity)

    def test_pixels_require_crossing_and_repeatable_off(self):
        before = np.zeros((100, 120, 3), dtype=np.uint8)
        before[25:55, 50:70] = 224
        active = before.copy()
        active[23:57, 48:72] = [255, 0, 255]
        active[25:55, 50:70] = 224
        arguments = {'roi': [10, 10, 50, 60], 'bounds': [50, 25, 70, 55]}
        control = verifier.compare_outline(before, active, before, **arguments)
        self.assertTrue(control['pass'], control)
        self.assertIsNone(control['native_data_compatibility'])
        self.assertFalse(verifier.compare_outline(before, before, before, **arguments)['pass'])
        body_tint = before.copy()
        body_tint[25:55, 50:70] = [255, 0, 255]
        self.assertFalse(verifier.compare_outline(before, body_tint, before, **arguments)['pass'])
        self.assertFalse(verifier.compare_outline(before, active, before, arguments['roi'])['pass'])
        moved = before.copy()
        moved[25:55, 50:70] = 0
        self.assertFalse(verifier.compare_outline(before, active, moved, **arguments)['pass'])


if __name__ == '__main__':
    unittest.main()
