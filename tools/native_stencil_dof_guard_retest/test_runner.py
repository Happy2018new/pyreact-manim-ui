"""Host-only matched-scene preparation, restore and pretransport gate tests."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location('guard_runner_under_test', Path(__file__).with_name('runner.py'))
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.experiment = Mock(evidence=Path(self.tmp.name))
        self.scene = guard.SceneGuard(self.experiment, 'dof-identity')

    def test_prepares_before_fixtures_and_hides_only_current_dimension_nonplayers(self):
        self.experiment.server.side_effect = [
            {'before': True}, {'accepted': True, 'after': False, 'actors': {
                'cow': {'dimensionId': 0, 'identifier': 'minecraft:cow'},
                'far': {'dimensionId': 1, 'identifier': 'minecraft:pig'}}, 'players': ['local']}]
        self.experiment.call.side_effect = [
            {'saved': [['cow', False]], 'frame': 10}, {'saved': [['cow', False]]},
            {'flags': [['cow', True]], 'frame': 20}]
        self.scene.before_prepare()
        self.assertEqual(self.scene.hidden, [['cow', False]])
        self.assertEqual(self.scene.receipt['world_actor_ids'], ['cow'])
        self.assertTrue(self.scene.receipt['world_actor_check']['all_hidden'])
        code = self.experiment.call.call_args_list[0].args[1]
        self.assertIn("['cow']", code)
        self.assertNotIn("'far'", code)
        self.assertNotIn('DestroyEntity', code)
        self.assertNotIn('kill', code)
        self.assertEqual(self.experiment.server.call_args_list[0].args[0], 'dof_guard_read_world_rule')

    def test_rule_prior_is_saved_for_cleanup_even_after_mutation_transport_error(self):
        self.experiment.server.side_effect = [{'before': False}, RuntimeError('transport'),
                                               {'accepted': True, 'after': False}]
        with self.assertRaisesRegex(RuntimeError, 'transport'):
            self.scene.before_prepare()
        self.scene.cleanup()
        self.assertFalse(self.scene.receipt['world_rule']['before'])
        self.assertIsNone(self.scene.receipt['cleanup_failure'])
        self.assertIn("'mob_spawn':False", self.experiment.server.call_args.args[1])

    def test_partial_actor_prefix_is_retained_for_independent_restore(self):
        self.experiment.server.side_effect = [{'before': True},
            {'accepted': True, 'after': False, 'actors': {'cow': {'dimensionId': 0}}, 'players': []},
            {'accepted': True, 'after': True}]
        self.experiment.call.side_effect = [RuntimeError('hide second actor failed'),
            {'saved': [['cow', False]]},
            {'restored': [['cow', False, True]], 'readbacks': [['cow', False]]}]
        with self.assertRaisesRegex(RuntimeError, 'second actor'):
            self.scene.before_prepare()
        self.scene.cleanup()
        self.assertEqual(self.scene.hidden, [['cow', False]])
        self.assertIsNone(self.scene.receipt['cleanup_failure'])

    def test_explicit_local_hide_requires_true_setter(self):
        self.experiment.call.return_value = {'accepted': False}
        with self.assertRaisesRegex(RuntimeError, 'local-player'):
            self.scene.after_prepare()
        self.assertTrue(self.scene.local_changed)
        self.assertFalse(self.scene.receipt['prepared'])

    def test_lost_hide_and_prefix_responses_restore_remote_prefix_independently(self):
        self.experiment.server.side_effect = [{'before': True},
            {'accepted': True, 'after': False, 'actors': {'cow': {'dimensionId': 0}}, 'players': []},
            {'accepted': True, 'after': True}]
        self.experiment.call.side_effect = [RuntimeError('lost hide response'),
            RuntimeError('lost prefix response'),
            {'restored': [['cow', False, True]], 'readbacks': [['cow', False]]}]
        with self.assertRaisesRegex(RuntimeError, 'lost prefix'):
            self.scene.before_prepare()
        self.assertEqual(self.scene.hidden, [])
        self.scene.cleanup()
        self.assertIsNone(self.scene.receipt['cleanup_failure'])
        self.assertEqual(self.experiment.call.call_args.args[0], 'dof_guard_restore_world')
        self.assertIn("getattr(probe,'_dof_guard_saved'", self.experiment.call.call_args.args[1])
        self.assertEqual(self.scene.receipt['world_actor_restore']['restored'], [['cow', False, True]])

    def test_cleanup_restores_other_actors_and_rule_after_local_restore_failure(self):
        self.scene.rule_changed = self.scene.local_changed = True
        self.scene.hidden = [['cow', True], ['pig', False]]
        self.scene.receipt['world_rule'] = {'before': True}
        self.experiment.call.side_effect = [{'accepted': False},
            {'restored': [['cow', True, True], ['pig', False, True]],
             'readbacks': [['cow', True], ['pig', False]]}]
        self.experiment.server.return_value = {'accepted': True, 'after': True}
        self.scene.cleanup()
        self.assertIn('Local player render restore rejected', self.scene.receipt['cleanup_failure'])
        self.assertEqual(self.experiment.server.call_count, 1)
        self.assertEqual(self.experiment.call.call_count, 2)
        self.scene.cleanup()
        self.assertEqual(self.experiment.call.call_count, 2)

    def test_changed_actor_flag_readback_blocks_prepared_scene(self):
        self.scene.hidden = [['cow', False]]
        self.experiment.call.return_value = {'flags': [['cow', False]], 'frame': 2}
        with self.assertRaisesRegex(RuntimeError, 'not hidden'):
            self.scene.check_world()

    def test_matching_fixture_gate_binds_status_wrapper_and_source_policy(self):
        status = self.experiment.evidence / 'dof-identity-status.json'
        status.write_bytes(b'actual image-replay status')
        fixture = {'schema': 'native_dof_guard_v1', 'policy': guard.POLICY,
            'wrapper_sha256': guard.sha(guard.__file__), 'case': 'dof-identity',
            'failure': None, 'cleanup_failure': None, 'complete': True,
            'identity_status_sha256': guard.sha(status),
            'local_player_hidden': {'accepted': True}, 'world_rule': {'after': False},
            'world_actor_check': {'all_hidden': True}}
        (self.experiment.evidence / guard.STATUS).write_text(json.dumps(fixture))
        dof = Mock()
        dof.native_module.return_value.verify_module.payload_bytes.return_value = b'fixed'
        dof.verify_identity_gate.return_value = {'accepted': True}
        self.assertEqual(guard.verify_matched_identity(status, dof), {'accepted': True})
        dof.verify_identity_gate.assert_called_once_with(status.resolve(), b'fixed')
        fixture['cleanup_failure'] = 'restore failed'
        (self.experiment.evidence / guard.STATUS).write_text(json.dumps(fixture))
        with self.assertRaisesRegex(ValueError, 'matching static-scene'):
            guard.verify_matched_identity(status, dof)
        self.assertEqual(dof.verify_identity_gate.call_count, 1)

    def test_complete_requires_strict_original_gate_and_clean_scene_restore(self):
        (self.experiment.evidence / 'dof-identity-status.json').write_bytes(b'status')
        self.scene.receipt['prepared'] = True
        self.scene.receipt['cleanup_failure'] = 'failed'
        self.scene.save({'status': 'identity_phase_accepted', 'gate': {'accepted': True},
                         'failure': None, 'cleanup_failure': None})
        self.assertFalse(self.scene.receipt['complete'])

    def engine_calls(self, loaded, flags, owned=()):
        probe = SimpleNamespace(actors=[{'entity': entity} for entity in owned], effects=[],
            known_fixture=SimpleNamespace(effect=None), _dof_guard_saved=[['cow', False]],
            _dof_guard_expected={'cow': {'dimensionId': 0, 'identifier': 'minecraft:cow'}}, render_event=42)
        changed = []
        def render(entity):
            def set_flag(value):
                changed.append((entity, value)); flags[entity] = value
                return True
            return SimpleNamespace(GetNotRenderAtAll=lambda: flags[entity], SetNotRenderAtAll=set_flag)
        api = SimpleNamespace(GetEngineActor=lambda: loaded,
                              GetEngineCompFactory=lambda: SimpleNamespace(CreateActorRender=render))
        def call(label, code='', expression='probe.snapshot()'):
            scope = {'api': api, 'probe': probe}
            exec(code, scope)
            return eval(expression, scope)
        self.experiment.call.side_effect = call
        self.scene.hidden = [['cow', False]]
        self.scene.actor_touched = True
        return changed

    def test_actual_inventory_code_allows_absent_actor_and_skips_its_restore(self):
        changed = self.engine_calls({}, {})
        row = self.scene.check_world()
        self.assertEqual(row['absent'], ['cow'])
        self.assertEqual(row['flags'], [])
        self.scene.cleanup()
        self.assertEqual(changed, [])
        self.assertIsNone(self.scene.receipt['cleanup_failure'])
        self.assertEqual(self.scene.receipt['world_actor_restore']['absent_or_replaced'], ['cow'])

    def test_actual_inventory_code_rejects_new_ordinary_or_wrong_dimension_actor(self):
        self.engine_calls({'cow': {'dimensionId': 0, 'identifier': 'minecraft:cow'},
                           'sheep': {'dimensionId': 0, 'identifier': 'minecraft:sheep'}},
                          {'cow': True, 'sheep': False})
        with self.assertRaisesRegex(RuntimeError, 'new or changed'):
            self.scene.check_world()
        self.engine_calls({'cow': {'dimensionId': 1, 'identifier': 'minecraft:cow'}}, {'cow': True})
        with self.assertRaisesRegex(RuntimeError, 'new or changed'):
            self.scene.check_world()

    def test_actual_inventory_code_never_hides_or_restores_an_owned_reused_id(self):
        changed = self.engine_calls({'cow': {'dimensionId': 0, 'identifier': 'pmanim_geometry_atlas:anchor'}},
                                   {'cow': False}, owned=['cow'])
        row = self.scene.check_world()
        self.assertEqual(row['owned_replacements'], ['cow'])
        self.assertEqual(row['absent'], [])
        self.scene.cleanup()
        self.assertEqual(changed, [])
        self.assertIsNone(self.scene.receipt['cleanup_failure'])

    def test_actual_inventory_code_restores_live_original_actor(self):
        changed = self.engine_calls({'cow': {'dimensionId': 0, 'identifier': 'minecraft:cow'}}, {'cow': True})
        self.scene.check_world()
        self.scene.cleanup()
        self.assertEqual(changed, [('cow', False)])
        self.assertIsNone(self.scene.receipt['cleanup_failure'])


if __name__ == '__main__':
    unittest.main()
