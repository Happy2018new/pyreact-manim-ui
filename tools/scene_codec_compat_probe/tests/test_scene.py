"""Verify scene receipts handle identical blocks and deterministic controls."""
import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location('compat_scene', Path(__file__).resolve().parents[1] / 'scene_server.py')
SCENE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCENE)


class Components:
    def __init__(self):
        self.blocks = {}
        self.calls = []

    def GetGameRulesInfoServer(self):
        return {'cheat_info': {'daylight_cycle': True}}

    def SetGameRulesInfoServer(self, rules):
        self.calls.append(('rules', rules))
        return True

    def SetTimeOfDay(self, time):
        self.calls.append(('time', time))
        return True

    def SetDimensionUseLocalWeather(self, dimension, enabled):
        self.calls.append(('local', dimension, enabled))
        return True

    def SetDimensionLocalDoWeatherCycle(self, dimension, enabled):
        self.calls.append(('weather_cycle', dimension, enabled))
        return True

    def SetDimensionLocalRain(self, dimension, strength, duration):
        self.calls.append(('rain', dimension, strength, duration))
        return True

    def SetDimensionLocalThunder(self, dimension, strength, duration):
        self.calls.append(('thunder', dimension, strength, duration))
        return True

    def GetBlockNew(self, pos, dimension):
        return self.blocks.get(pos, {'name': 'minecraft:air', 'aux': 0})

    def SetBlockNew(self, pos, desired, mode, dimension, legacy, neighbors):
        changed = self.GetBlockNew(pos, dimension) != desired
        self.blocks[pos] = dict(desired)
        return changed


class Factory:
    def __init__(self):
        self.components = Components()

    def CreateGame(self, level):
        return self.components

    CreateTime = CreateGame
    CreateWeather = CreateGame
    CreateBlockInfo = CreateGame


class API:
    def __init__(self):
        self.factory = Factory()

    def GetEngineCompFactory(self):
        return self.factory


class SceneTests(unittest.TestCase):
    def test_repeated_fixture_accepts_false_changed_but_exact_block_state(self):
        api = API()
        first = SCENE.prepare(api, 'level', (10, 60, 20), 'water_glass')
        second = SCENE.prepare(api, 'level', (10, 60, 20), 'water_glass')
        self.assertTrue(all(edit['matches'] for edit in first['edits']))
        self.assertTrue(all(edit['matches'] and not edit['api_changed'] for edit in second['edits']))
        self.assertIn(('time', 6000), api.factory.components.calls)
        self.assertIn(('rain', 0, 0., 12000000), api.factory.components.calls)
        self.assertIn(('weather_cycle', 0, False), api.factory.components.calls)

    def test_scene_switch_resets_water_glass_and_emissive_voxels(self):
        api = API()
        for case in ('water_glass', 'glint_emissive', 'solid', 'rain'):
            receipt = SCENE.prepare(api, 'level', (0, 60, 0), case)
            self.assertTrue(all(item['matches'] for item in receipt['edits']))
        actual = api.factory.components.blocks
        self.assertNotIn('minecraft:water', [item['name'] for item in actual.values()])
        self.assertNotIn('minecraft:glowstone', [item['name'] for item in actual.values()])
        self.assertIn(('rain', 0, 1., 12000000), api.factory.components.calls)

    def test_unloaded_terrain_fails(self):
        api = API()
        api.factory.components.GetBlockNew = lambda pos, dimension: None
        with self.assertRaisesRegex(RuntimeError, 'loaded terrain'):
            SCENE.prepare(api, 'level', (0, 60, 0))


if __name__ == '__main__':
    unittest.main()
