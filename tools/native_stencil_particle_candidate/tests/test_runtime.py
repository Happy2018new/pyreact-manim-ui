"""Exercise the particle carrier without importing or starting ModSDK."""
import builtins
from contextlib import contextmanager
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parent / 'runtime.py'
VIEWPORT = [720, 1080]
ROI = [8, 128, 512, 512]
ROLES = ('base', 'bit64', 'bit128')


@contextmanager
def forbid_runtime_files():
    """The client lifecycle must not depend on reading or writing disk files."""
    with patch.object(builtins, 'open', side_effect=AssertionError('runtime file access')), \
            patch.object(io, 'open', side_effect=AssertionError('runtime file access')), \
            patch('os.open', side_effect=AssertionError('runtime file access')):
        yield


class FakeParticleControl(object):
    def __init__(self, probe, entity):
        self.probe, self.entity = probe, entity

    def _accepted(self, name, *values):
        self.probe.calls.append((name, self.entity) + values)
        return self.probe.accepted.get(name, True)

    def SetLayer(self, layer):
        return self._accepted('layer', layer)

    def SetGlobal(self, enabled):
        return self._accepted('global', enabled)

    def SetFadeDistance(self, distance):
        return self._accepted('fade', distance)

    def Play(self):
        return self._accepted('play')

    def Pause(self):
        return self._accepted('pause')

    def Stop(self):
        return self._accepted('stop')

    def GetParticleMaxNum(self):
        return self.probe.capacity

    def GetParticleEmissionRate(self):
        return (20., 20.)


class FakeFactory(object):
    def __init__(self, probe):
        self.probe = probe

    def CreateParticleControl(self, entity):
        self.probe.calls.append(('control', entity))
        return FakeParticleControl(self.probe, entity)

    def CreateFrameAniControl(self, entity):
        raise AssertionError('FrameAni must not carry candidate draws')


class FakeCamera(object):
    def GetPosition(self):
        return (11., 17., 23.)

    def GetForward(self):
        return (0., 0., 1.)


class FakeIntegratedProbe(object):
    """Record only the inherited interface used by the candidate adapter."""
    def __init__(self, namespace, name):
        self.namespace, self.name = namespace, name
        self.calls, self.created, self.destroyed = [], [], []
        self.accepted, self.capacity = {}, 1
        self.load_begin_calls, self.configure_calls = [], []
        self.render_event = 0
        self.effects, self.controls = [], []
        self.factory, self.camera = FakeFactory(self), FakeCamera()
        self.anchor = (11., 17., 27.)
        self.viewport, self.roi = list(VIEWPORT), list(ROI)
        self.mode, self.byte_count = 'off', 0
        self.payload_visible, self.clear_visible = False, False
        self.known_fixture = None

    def _idle(self):
        pass

    def CreateEngineParticle(self, path, position):
        entity = 100 + len(self.created)
        self.created.append((entity, path, position))
        self.calls.append(('create', entity, path, position))
        return entity

    def CreateEngineSfxFromEditor(self, *args):
        raise AssertionError('FrameAni must not carry candidate draws')

    def DestroyEntity(self, entity):
        self.calls.append(('destroy', entity))
        accepted = self.accepted.get('destroy', True)
        if accepted:
            self.destroyed.append(entity)
        return accepted

    def load_begin(self, byte_count, actual_host_sha, viewport, roi):
        self.load_begin_calls.append((byte_count, actual_host_sha, viewport, roi))
        self.byte_count = byte_count
        self.viewport, self.roi = list(viewport), list(roi)
        return self.snapshot()

    def configure(self, mode='all'):
        self.configure_calls.append(mode)
        self.mode = mode
        self.payload_visible, self.clear_visible = mode == 'all', mode != 'off'
        return self.snapshot()

    def snapshot(self):
        return {'base_snapshot': True, 'mode': self.mode,
                'effects': list(self.effects), 'controls': list(self.controls)}

    def Destroy(self):
        self.calls.append(('integrated_destroy',))
        if self.known_fixture is not None:
            self.known_fixture.destroy()


def load_runtime():
    # Read the source before installing the client disk-access guard. Imports of
    # generated runtime dependencies are supplied in memory, like the SDK fakes.
    source = RUNTIME.read_text(encoding='utf-8-sig')
    package = types.ModuleType('stencil_large')
    package.__path__ = []
    integrated = types.ModuleType('stencil_large.integrated_runtime')
    integrated.ProbeSystem = FakeIntegratedProbe
    config = types.ModuleType('stencil_large.particle_candidate_config')
    config.VIEWPORT, config.ROI = tuple(VIEWPORT), tuple(ROI)
    config.ROLES = ROLES
    module = types.ModuleType('stencil_large.particle_candidate_runtime_test')
    module.__file__, module.__package__ = str(RUNTIME), 'stencil_large'
    modules = {'stencil_large': package,
               'stencil_large.integrated_runtime': integrated,
               'stencil_large.particle_candidate_config': config}
    with patch.dict(sys.modules, modules), forbid_runtime_files():
        exec(compile(source, str(RUNTIME), 'exec'), module.__dict__)
    return module


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = load_runtime()

    def probe(self):
        return self.runtime.ProbeSystem('test_particle_candidate', 'probe')

    def test_draw_requires_capacity_one_with_explicit_state_and_idempotent_show(self):
        probe = self.probe()
        draw = self.runtime.ParticleDraw(probe, 'base', 13)
        with forbid_runtime_files():
            self.assertTrue(draw.show())
            self.assertTrue(draw.show())
            snapshot = draw.snapshot()
        self.assertIsInstance(snapshot, dict)
        self.assertEqual(len(probe.created), 1)
        entity, path, _ = probe.created[0]
        self.assertEqual(path, 'effects/pmanim_particle_candidate/base.json')
        self.assertIn(('layer', entity, 13), probe.calls)
        self.assertIn(('global', entity, True), probe.calls)
        self.assertIn(('fade', entity, 0.), probe.calls)
        self.assertEqual(probe.calls.count(('play', entity)), 1)
        self.assertNotIn(('pause', entity), probe.calls)
        self.assertEqual(snapshot['capacity'], 1)
        self.assertEqual(snapshot['emission_rate'], (20., 20.))
        self.assertIs(snapshot['live_particle_count_verified'], False)

    def test_pause_requires_a_later_render_turn_and_destroy_releases_entity(self):
        probe = self.probe()
        probe.render_event = 41
        draw = self.runtime.ParticleDraw(probe, 'bit64', 14)
        with forbid_runtime_files():
            draw.show()
            entity = probe.created[0][0]
            with self.assertRaises(RuntimeError):
                draw.pause()
            self.assertNotIn(('pause', entity), probe.calls)
            probe.render_event += 1
            self.assertTrue(draw.pause())
            self.assertIn(('pause', entity), probe.calls)
            draw.destroy()
        self.assertEqual(probe.destroyed, [entity])

    def test_rejected_capacity_remains_available_for_explicit_cleanup(self):
        probe = self.probe()
        probe.capacity = 2
        draw = self.runtime.ParticleDraw(probe, 'base', 13)
        with forbid_runtime_files():
            with self.assertRaises(RuntimeError):
                draw.show()
            entity = probe.created[0][0]
            self.assertEqual(draw.snapshot()['entity'], entity)
            draw.destroy()
            self.assertIsNone(draw.snapshot()['entity'])
        self.assertEqual(probe.destroyed, [entity])

    def test_failed_cleanup_keeps_the_entity_for_a_later_retry(self):
        probe = self.probe()
        draw = self.runtime.ParticleDraw(probe, 'bit128', 15)
        with forbid_runtime_files():
            draw.show()
            entity = probe.created[0][0]
            probe.accepted['stop'] = False
            with self.assertRaises(RuntimeError):
                draw.destroy()
            self.assertEqual(probe.destroyed, [])
            self.assertEqual(draw.snapshot()['entity'], entity)
            probe.accepted['stop'] = True
            probe.accepted['destroy'] = False
            with self.assertRaises(RuntimeError):
                draw.destroy()
            self.assertEqual(probe.destroyed, [])
            self.assertEqual(draw.snapshot()['entity'], entity)
            probe.accepted['destroy'] = True
            draw.destroy()
            self.assertIsNone(draw.snapshot()['entity'])
        self.assertEqual(probe.destroyed, [entity])

    def test_all_off_all_recreates_three_draws_and_keeps_frameani_empty(self):
        probe = self.probe()
        with forbid_runtime_files():
            probe._effects_ready()
            probe.configure('all')
            self.assertEqual(len(probe.created), 3)
            probe.configure('all')
            probe._effects_ready()
            self.assertEqual(len(probe.created), 3)
            first_entities = [item[0] for item in probe.created]
            probe.configure('off')
            self.assertCountEqual(probe.destroyed, first_entities)
            probe.configure('off')
            self.assertEqual(len(probe.destroyed), 3)
            probe.configure('all')
            self.assertEqual(len(probe.created), 6)
            snapshot = probe.snapshot()
        self.assertEqual(probe.effects, [])
        self.assertEqual(probe.controls, [])
        self.assertEqual(probe.configure_calls, ['all', 'all', 'off', 'off', 'all'])
        self.assertTrue(snapshot['base_snapshot'])
        candidate = snapshot['particle_candidate']
        self.assertEqual(list(candidate['viewport']), VIEWPORT)
        self.assertEqual(list(candidate['roi']), ROI)
        self.assertIn('draws', candidate)
        expected = {'effects/pmanim_particle_candidate/'+role+'.json' for role in ROLES}
        self.assertEqual({item[1] for item in probe.created}, expected)

    def test_probe_destroy_releases_data_draws_and_delegates_reference_cleanup(self):
        probe = self.probe()
        with forbid_runtime_files():
            probe.configure('all')
            probe.known_fixture.configure(True, True)
            entities = [entity for entity, _, _ in probe.created]
            probe.Destroy()
        self.assertCountEqual(probe.destroyed, entities)
        self.assertIn(('integrated_destroy',), probe.calls)
        self.assertTrue(all(item['entity'] is None
                            for item in probe.snapshot()['particle_candidate']['draws'].values()))

    def test_existing_shared_frameani_draws_are_rejected(self):
        probe = self.probe()
        probe.effects.append('unexpected shared FrameAni')
        with forbid_runtime_files(), self.assertRaises(RuntimeError):
            probe._effects_ready()
        self.assertEqual(probe.created, [])

    def test_pause_particles_can_leave_reference_running_until_its_own_gate(self):
        probe = self.probe()
        with forbid_runtime_files():
            probe.configure('all')
            probe.known_fixture.configure(True, True)
            with self.assertRaises(RuntimeError):
                probe.pause_particles()
            self.assertFalse(any(call[0] == 'pause' for call in probe.calls))
            probe.render_event += 1
            probe.pause_particles(include_reference=False)
            data_entities = {entity for entity, path, _ in probe.created
                             if not path.endswith('/reference.json')}
            self.assertEqual({call[1] for call in probe.calls if call[0] == 'pause'}, data_entities)
            probe.pause_particles(include_reference=True)
            self.assertEqual({call[1] for call in probe.calls if call[0] == 'pause'},
                             {entity for entity, _, _ in probe.created})

    def test_compiled_layout_rejection_happens_before_inherited_upload(self):
        probe = self.probe()
        digest = 'a' * 64
        with forbid_runtime_files():
            with self.assertRaises(ValueError):
                probe.load_begin(65536, digest, [721, 1080], list(ROI))
            with self.assertRaises(ValueError):
                probe.load_begin(65536, digest, list(VIEWPORT), [12, 128, 512, 512])
            self.assertEqual(probe.load_begin_calls, [])
            probe.load_begin(65536, digest, list(VIEWPORT), list(ROI))
        self.assertEqual(len(probe.load_begin_calls), 1)
        self.assertEqual(probe.load_begin_calls[0][0:2], (65536, digest))

    def test_reference_modes_use_private_particles_and_disable_destroys_them(self):
        probe = self.probe()
        fixture = self.runtime.KnownFixture(probe)
        with forbid_runtime_files():
            fixture.configure(True, True)
            fixture.configure(True, True)
            self.assertEqual(len(probe.created), 1)
            self.assertEqual(probe.created[0][1],
                             'effects/pmanim_particle_candidate/reference.json')
            first = probe.created[0][0]
            fixture.configure(True, False)
            self.assertIn(first, probe.destroyed)
            self.assertEqual(len(probe.created), 2)
            self.assertEqual(probe.created[-1][1],
                             'effects/pmanim_particle_candidate/reference_opaque.json')
            fixture.configure(False, False)
        self.assertCountEqual(probe.destroyed, [item[0] for item in probe.created])


if __name__ == '__main__':
    unittest.main()
