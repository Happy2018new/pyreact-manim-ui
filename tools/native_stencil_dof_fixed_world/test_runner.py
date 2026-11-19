"""Execute fixed-world server snippets against an offline fake SDK."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import sys

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
        self.auto_orient_torch_zero = False
        self.refuse_state_restore = False
        self.state_calls = []
        self.block_calls = []

    def GetBlockNew(self, pos, dim):
        return dict(self.blocks.get(tuple(pos), {'name': 'minecraft:air', 'aux': 0}))

    def SetBlockNew(self, pos, item, replace, dim, legacy, update):
        old = self.GetBlockNew(pos, dim)
        value = dict(item)
        if self.auto_orient_torch_zero and value == {'name': 'minecraft:torch', 'aux': 0}:
            value['aux'] = 5
        self.blocks[tuple(pos)] = value
        self.changed.append(tuple(pos))
        self.block_calls.append((tuple(pos), dict(item), update))
        return old != value

    def GetBlockStates(self, pos, dim):
        item = self.GetBlockNew(pos, dim)
        if item['name'] != 'minecraft:torch':
            return {}
        return {'torch_facing_direction': {0: 'unknown', 5: 'top', 2: 'east'}[item['aux']]}

    def GetBlockAuxValueFromStates(self, name, states):
        if name == 'minecraft:torch':
            return {'unknown': 0, 'top': 5, 'east': 2}[states['torch_facing_direction']]
        return 2 if name == 'minecraft:chest' else 0

    def SetBlockStates(self, pos, states, dim):
        self.state_calls.append((tuple(pos), dict(states), dim))
        if self.refuse_state_restore:
            return False
        item = self.GetBlockNew(pos, dim)
        self.blocks[tuple(pos)] = {'name': item['name'],
                                  'aux': self.GetBlockAuxValueFromStates(item['name'], states)}
        return True

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
            ('CreateBlockInfo', 'CreateBlockState', 'CreateTime', 'CreateGame', 'CreateDimension', 'CreateWeather')})
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

    def test_bonus_chest_is_never_written_and_room_plan_binds_preserved_cell(self):
        position = (3,-60,3)
        self.sdk.blocks[position] = {'name': 'minecraft:chest', 'aux': 2}
        self.prepare()
        self.assertNotIn(position, self.sdk.changed)
        self.assertEqual(self.world.receipt['room']['preserved_containers'][0]['position'], list(position))
        self.assertEqual([row for row in self.world.expected_rows if row[0] == list(position)],
                         [[list(position), 'minecraft:chest', 2]])
        self.world.cleanup()
        self.assertNotIn(position, self.sdk.changed)
        self.assertIsNone(self.world.receipt['cleanup_failure'])

    def assert_canonical_torch_restored(self, aux, facing):
        position = (2,-60,3)
        self.sdk.blocks[position] = {'name': 'minecraft:torch', 'aux': aux}
        self.prepare()
        self.assertEqual(self.world.special_states[0]['legacy_aux'], aux)
        with patch.object(fixed.time, 'sleep'):
            self.world.cleanup()
        self.assertEqual(self.sdk.GetBlockNew(position,0), {'name': 'minecraft:torch', 'aux': aux})
        self.assertEqual(self.sdk.GetBlockStates(position,0), {'torch_facing_direction': facing})
        self.assertEqual(self.sdk.state_calls, [])
        self.assertIsNone(self.world.receipt['cleanup_failure'])

    def test_torch_restore_uses_canonical_aux_and_exact_states(self):
        self.assert_canonical_torch_restored(5, 'top')

    def test_east_torch_restore_preserves_raw_aux_and_exact_states(self):
        self.assert_canonical_torch_restored(2, 'east')

    def test_unknown_torch_auto_orientation_is_repaired_to_exact_raw_aux_and_state(self):
        position = (2,-60,3)
        self.sdk.blocks[position] = {'name': 'minecraft:torch', 'aux': 0}
        self.sdk.auto_orient_torch_zero = True
        self.prepare()
        self.assertEqual(self.world.special_states[0]['states'], {'torch_facing_direction': 'unknown'})
        self.assertEqual(self.world.special_states[0]['legacy_aux'], 0)
        with patch.object(fixed.time, 'sleep') as sleep:
            self.world.cleanup()
        self.assertEqual(self.sdk.GetBlockNew(position,0), {'name': 'minecraft:torch', 'aux': 0})
        self.assertEqual(self.sdk.GetBlockStates(position,0), {'torch_facing_direction': 'unknown'})
        self.assertEqual(self.sdk.state_calls, [(position, {'torch_facing_direction': 'unknown'}, 0)])
        repair = self.world.receipt['block_restore']['state_repairs'][0]
        self.assertEqual(repair['position'], list(position))
        self.assertIs(repair['accepted'], True)
        self.assertEqual(repair['before'], {'name': 'minecraft:torch', 'aux': 5})
        self.assertEqual(repair['states_before'], {'torch_facing_direction': 'top'})
        self.assertEqual(repair['after'], {'name': 'minecraft:torch', 'aux': 0})
        self.assertEqual(repair['states_after'], {'torch_facing_direction': 'unknown'})
        self.assertEqual(self.world.receipt['block_restore_delayed'], {'cells': 3757, 'mismatches': []})
        self.assertIn('fixed_world_blocks_restored_check', self.calls)
        sleep.assert_any_call(.25)
        self.assertTrue(all(update is False for _, _, update in self.sdk.block_calls))
        self.assertIsNone(self.world.receipt['cleanup_failure'])

    def test_refused_torch_state_repair_fails_cleanup_but_restores_environment(self):
        position = (2,-60,3)
        self.sdk.blocks[position] = {'name': 'minecraft:torch', 'aux': 0}
        self.sdk.auto_orient_torch_zero = True
        self.sdk.refuse_state_restore = True
        self.prepare()
        with patch.object(fixed.time, 'sleep'):
            self.world.cleanup()
        self.assertIn('blocks:', self.world.receipt['cleanup_failure'])
        self.assertEqual(self.sdk.GetBlockNew(position,0)['aux'], 5)
        self.assertEqual(len(self.sdk.state_calls), 1)
        self.assertIs(self.world.receipt['block_restore']['state_repairs'][0]['accepted'], False)
        self.assertEqual(self.sdk.ticks, 1000)
        self.assertTrue(self.sdk.rules['daylight_cycle'])

    def test_delayed_restore_readback_drift_fails_cleanup(self):
        position = (2,-60,3)
        self.sdk.blocks[position] = {'name': 'minecraft:torch', 'aux': 2}
        self.prepare()
        original = self.exp.server

        def server(label, code):
            if label == 'fixed_world_blocks_restored_check':
                self.sdk.blocks[position] = {'name': 'minecraft:torch', 'aux': 5}
            return original(label, code)

        self.exp.server = server
        with patch.object(fixed.time, 'sleep'):
            self.world.cleanup()
        self.assertIn('blocks:', self.world.receipt['cleanup_failure'])
        self.assertIn('delayed block restoration failed', self.world.receipt['cleanup_failure'])
        self.assertEqual(self.world.receipt['block_restore_delayed']['mismatches'][0]['position'], list(position))
        self.assertIn('fixed_world_blocks_restored_check', self.calls)
        self.assertEqual(self.sdk.ticks, 1000)

    def test_unknown_block_bails_before_any_room_mutation(self):
        self.sdk.blocks[(1,-60,3)] = {'name': 'minecraft:hopper', 'aux': 0}
        with self.assertRaisesRegex(RuntimeError, 'non-destructive'):
            self.prepare()
        self.assertEqual(self.sdk.changed, [])
        self.assertFalse(self.world.blocks_touched)

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


class ActorRebindTests(unittest.TestCase):
    """Run the actual nested guard and generated client code without transport."""

    def setUp(self):
        self.guard_module = fixed.module('fixed_world_fake_guard', fixed.GUARD)
        self.actors = {'ordinary': {'identifier': 'minecraft:item', 'dimensionId': 0}}
        self.flags = {'ordinary': False, 'fixture': False, 'effect': False, 'known': False}
        self.writes = []
        self.probe = SimpleNamespace(actors=[{'entity': 'fixture'}], effects=['effect'],
            known_fixture=SimpleNamespace(effect='known'), render_event=100,
            _dof_guard_saved=[], _dof_guard_expected={})
        self.fail_response = set()

        def render(entity):
            def setter(value):
                self.writes.append((entity, value))
                self.flags[entity] = value
                return True
            return SimpleNamespace(GetNotRenderAtAll=lambda: self.flags[entity],
                                   SetNotRenderAtAll=setter)
        factory = SimpleNamespace(CreateActorRender=render)
        api = SimpleNamespace(GetEngineActor=lambda: dict(self.actors),
            GetEngineCompFactory=lambda: factory, GetLocalPlayerId=lambda: 'player')
        self.scope = {'api': api, 'probe': self.probe}
        def call(label, code='', expression=''):
            exec(code, self.scope)
            result = eval(expression, self.scope)
            if label in self.fail_response:
                raise RuntimeError('lost response: ' + label)
            return result
        self.experiment = SimpleNamespace(call=call)
        dof = SimpleNamespace(native_module=lambda: None, run=lambda: None)
        self.guard_module.base_modules = lambda: (SimpleNamespace(), dof)

    def run_guard(self, operation):
        def main():
            instance = self.guard_module.SceneGuard(self.experiment, 'dof-identity')
            operation(instance)
        self.guard_module.main = main
        with patch.object(fixed, 'module', return_value=self.guard_module), patch.object(
                sys, 'argv', ['runner.py', '--initialize', '--case', 'dof-identity']):
            fixed.main()

    def test_new_actor_saves_hides_and_restores_prior_flags_but_never_owned_fixtures(self):
        for entity in ('fixture', 'effect', 'known'):
            self.actors[entity] = {'identifier': 'fixture', 'dimensionId': 0}
        self.actors['already_hidden'] = {'identifier': 'minecraft:chicken', 'dimensionId': 0}
        self.flags['already_hidden'] = True
        def operation(guard):
            guard.check_world()
            self.assertEqual(dict(self.probe._dof_guard_saved),
                             {'ordinary': False, 'already_hidden': True})
            self.assertTrue(self.flags['ordinary'])
            self.assertEqual(self.writes, [('ordinary', True)])
            guard.cleanup()
            self.assertIsNone(guard.receipt['cleanup_failure'])
            self.assertFalse(self.flags['ordinary'])
            self.assertTrue(self.flags['already_hidden'])
            self.assertFalse(set(entity for entity, _ in self.writes) & {'fixture', 'effect', 'known'})
        self.run_guard(operation)

    def test_identifier_or_dimension_collision_rejects_before_mutating_replacement(self):
        def operation(guard):
            guard.check_world()
            for key, value in (('identifier', 'minecraft:cow'), ('dimensionId', 1)):
                original = self.actors['ordinary'][key]
                self.actors['ordinary'][key] = value
                count = len(self.writes)
                with self.assertRaisesRegex(RuntimeError, 'identity|dimension'):
                    guard.check_world()
                self.assertEqual(len(self.writes), count)
                self.actors['ordinary'][key] = original
            guard.cleanup()
        self.run_guard(operation)

    def test_freeze_rejects_new_or_visible_actor_and_does_not_hide_it(self):
        def operation(guard):
            guard.freeze_world_actors()
            self.actors['late'] = {'identifier': 'minecraft:item', 'dimensionId': 0}
            self.flags['late'] = False
            count = len(self.writes)
            with self.assertRaisesRegex(RuntimeError, 'new or changed'):
                guard.check_world()
            self.assertEqual(len(self.writes), count)
            self.assertFalse(self.flags['late'])
            del self.actors['late']
            self.flags['ordinary'] = False
            with self.assertRaisesRegex(RuntimeError, 'was not hidden'):
                guard.check_world()
            self.assertEqual(len(self.writes), count)
            guard.cleanup()
        self.run_guard(operation)

    def test_persistent_saved_prefix_restores_even_when_both_setup_responses_are_lost(self):
        self.fail_response = {'fixed_world_rebind_actors', 'fixed_world_saved_actors'}
        def operation(guard):
            with self.assertRaisesRegex(RuntimeError, 'lost response'):
                guard.check_world()
            self.assertEqual(guard.hidden, [])
            self.assertEqual(self.probe._dof_guard_saved, [('ordinary', False)])
            self.assertTrue(self.flags['ordinary'])
            guard.cleanup()
            self.assertIsNone(guard.receipt['cleanup_failure'])
            self.assertFalse(self.flags['ordinary'])
        self.run_guard(operation)


if __name__ == '__main__': unittest.main()
