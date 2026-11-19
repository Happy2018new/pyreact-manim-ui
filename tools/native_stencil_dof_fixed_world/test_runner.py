"""Execute fixed-world server snippets against an offline fake SDK."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np


spec = importlib.util.spec_from_file_location('fixed_world_under_test', Path(__file__).with_name('runner.py'))
fixed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixed)


class FakeSDK:
    def __init__(self):
        self.blocks, self.changed = {}, []
        self.ticks = 1000
        self.rules = {'daylight_cycle': True, 'weather_cycle': True}
        self.local_weather = False
        self.weather = {'isWeatherCycle': True, 'rainLevel': .4, 'rainTime': 300,
                        'thunderLevel': .2, 'thunderTime': 400}
        self.local_time = False

    def GetBlockNew(self, pos, dim):
        return dict(self.blocks.get(tuple(pos), {'name': 'minecraft:air', 'aux': 0}))

    def SetBlockNew(self, pos, item, replace, dim, legacy, update):
        old = self.GetBlockNew(pos, dim)
        self.blocks[tuple(pos)] = dict(item)
        self.changed.append(tuple(pos))
        return old != item

    def GetTime(self): return self.ticks
    def SetTime(self, ticks): self.ticks = ticks; return True
    def GetUseLocalTime(self, dim): return self.local_time
    def GetGameRulesInfoServer(self): return {'cheat_info': dict(self.rules)}
    def SetGameRulesInfoServer(self, value): self.rules.update(value['cheat_info']); return True
    def GetDimensionUseLocalWeather(self, dim): return self.local_weather
    def GetDimensionLocalWeatherInfo(self, dim): return dict(self.weather)
    def SetDimensionUseLocalWeather(self, dim, value): self.local_weather = value; return True
    def SetDimensionLocalDoWeatherCycle(self, dim, value): self.weather['isWeatherCycle'] = value; return True
    def SetDimensionLocalRain(self, dim, value, duration):
        self.weather.update(rainLevel=value, rainTime=duration); return True
    def SetDimensionLocalThunder(self, dim, value, duration):
        self.weather.update(thunderLevel=value, thunderTime=duration); return True

    def api(self):
        factory = SimpleNamespace(**{name: lambda level: self for name in
            ('CreateBlockInfo', 'CreateTime', 'CreateGame', 'CreateDimension', 'CreateWeather')})
        return SimpleNamespace(GetEngineCompFactory=lambda: factory, GetLevelId=lambda: 'level')


class FixedWorldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sdk = FakeSDK()
        self.calls = []
        def server(label, code):
            self.calls.append(label)
            scope = {'api': self.sdk.api(), 'json': json}
            exec(code, scope)
            return json.loads(scope['_result'])
        frame = [0]
        def call(label, code='', expression=''):
            frame[0] += 10
            return {'frame': frame[0]}
        self.exp = SimpleNamespace(server=server, call=call, evidence=Path(self.tmp.name))
        self.world = fixed.FixedWorld(self.exp, 'dof-identity')

    def prepare(self):
        with patch.object(fixed.time, 'sleep'):
            self.world.prepare([0., -58., -3.])

    def test_room_plan_encloses_unchanged_fixture_and_has_static_shell(self):
        plan = fixed.room_plan([0., -58., -3.])
        self.assertEqual(plan['cell_count'], 3757)
        self.assertEqual(len({tuple(row[0]) for row in plan['rows']}), 3757)
        lookup = {tuple(pos): name for pos, name, aux in plan['rows']}
        self.assertEqual(lookup[(0, -59, 1)], 'minecraft:air')
        self.assertEqual(lookup[(0, -59, 5)], 'minecraft:glowstone')
        self.assertNotIn('minecraft:sea_lantern', set(lookup.values()))

    def test_full_prepare_executes_real_snippets_and_restores_all_blocks_environment(self):
        self.sdk.blocks[(0, -62, 0)] = {'name': 'minecraft:stone', 'aux': 0}
        self.prepare()
        self.assertTrue(self.world.receipt['prepared'])
        self.assertTrue(self.world.receipt['fixed_world_blocks_ready']['exact'])
        self.assertEqual(self.world.receipt['fixed_world_blocks_ready']['cells'], 3757)
        self.assertEqual(self.sdk.ticks, 6000)
        self.assertFalse(self.sdk.rules['daylight_cycle'])
        self.assertTrue(self.sdk.local_weather)
        self.world.check()
        self.world.cleanup()
        self.assertIsNone(self.world.receipt['cleanup_failure'])
        self.assertEqual(self.sdk.GetBlockNew((0, -62, 0), 0), {'name': 'minecraft:stone', 'aux': 0})
        self.assertEqual(self.sdk.GetBlockNew((8, -58, 0), 0)['name'], 'minecraft:air')
        self.assertEqual(self.sdk.ticks, 1000)
        self.assertEqual(self.sdk.rules, {'daylight_cycle': True, 'weather_cycle': True})
        self.assertFalse(self.sdk.local_weather)

    def test_modified_room_cell_or_weather_fails_readback(self):
        self.prepare()
        self.sdk.blocks[(8, -58, 0)] = {'name': 'minecraft:air', 'aux': 0}
        with self.assertRaisesRegex(RuntimeError, 'readback differs'):
            self.world.check()
        self.sdk.blocks[(8, -58, 0)] = {'name': 'minecraft:glowstone', 'aux': 0}
        self.sdk.weather['rainLevel'] = .1
        with self.assertRaisesRegex(RuntimeError, 'readback differs'):
            self.world.check()

    def test_local_dimension_time_rejected_before_mutation(self):
        self.sdk.local_time = True
        with self.assertRaisesRegex(RuntimeError, 'typed readbacks'):
            self.prepare()
        self.assertFalse(self.world.env_touched)
        self.assertEqual(self.sdk.changed, [])

    def test_cleanup_restores_environment_after_block_restore_transport_failure(self):
        self.prepare()
        original = self.exp.server
        def server(label, code):
            if label == 'fixed_world_blocks_restore': raise RuntimeError('transport')
            return original(label, code)
        self.exp.server = server
        self.world.cleanup()
        self.assertIn('blocks:', self.world.receipt['cleanup_failure'])
        self.assertEqual(self.sdk.ticks, 1000)
        self.assertTrue(self.sdk.rules['daylight_cycle'])

    def test_prior_local_weather_parameters_restore(self):
        self.sdk.local_weather = True
        prior = dict(self.sdk.weather)
        self.prepare()
        self.world.cleanup()
        self.assertIsNone(self.world.receipt['cleanup_failure'])
        self.assertEqual(self.sdk.weather, prior)
        self.assertTrue(self.sdk.local_weather)

    def test_exact_zero_exterior_is_additional_gate_and_roi_keeps_tolerance(self):
        image = np.zeros((1080,720,3), np.uint8)
        active = image.copy()
        active[128:640,8:520] = 2
        active[:120] = 255
        self.assertTrue(fixed.zero_match(image, active)['accepted'])
        active[640,8,0] = 1
        result = fixed.zero_match(image, active)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['exterior_exact_error_pixels'], 1)
        self.assertEqual(result['exterior_error_gt2_pixels'], 0)

    def test_zero_source_error_cannot_pass_even_with_identical_exterior(self):
        image = np.zeros((1080,720,3), np.uint8)
        active = image.copy(); active[128,8,0] = 3
        result = fixed.zero_match(image, active)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['source_error_gt2_pixels'], 1)


if __name__ == '__main__': unittest.main()
