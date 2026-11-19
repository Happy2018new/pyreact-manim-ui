"""Offline regression checks for loaded materials and strict retest gates."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import build_retest as build
import dof_retest as dof
import numpy as np
from PIL import Image


FROZEN = Path(__file__).resolve().parent.parent / 'native_stencil_post_candidate'
if str(FROZEN) not in sys.path:
    sys.path.append(str(FROZEN))
fixtures = build.module('frozen_candidate_test_fixtures_for_retest', FROZEN / 'test_candidate.py')


class RetestBuildTests(unittest.TestCase):
    def setUp(self):
        fixtures.CandidateAssetsTests.setUp(self)
        fixtures.write_json(self.native / 'materials/common.json', [
            {'path': 'materials/sfx.material'}, {'path': 'materials/postprocess.material'}])
        self.source = fixtures.NATIVE_SOURCE.replace(
            'gl_FragColor = depth_sample_auto(clearColor) + texture(TEXTURE_0, uv);',
            'gl_FragColor = depth_sample2(color);')
        for root in (self.native, self.game.parent / 'data'):
            (root / 'shaders/glsl/depth_sample.fragment').write_text(self.source, encoding='utf-8')

    def test_identity_uses_loaded_map_exact_material_name_and_native_templates(self):
        receipt = build.install(self.project, self.game, 'dof-identity')
        self.assertEqual(build.validate(self.project), receipt)
        materials = build.read_json(self.project / build.MATERIAL_PATH)
        self.assertEqual(materials['carrier_custom'], {'unchanged': True})
        self.assertEqual(set(materials), {'carrier_custom', 'depth_sample_with_blur'})
        expected = copy.deepcopy(receipt['native_detail']['native_material'])
        expected['fragmentShader'] = 'shaders/pmanim_dof_retest_identity.fragment'
        self.assertEqual(materials['depth_sample_with_blur'], expected)
        self.assertFalse((self.project / 'resource_pack/materials/native_post_candidate.material').exists())
        self.assertEqual((self.project / receipt['native_detail']['fragment_file']).read_text(), self.source)
        for name in ('post_process.json', 'post_process_rngl.json'):
            actual = build.read_json(self.project / 'resource_pack/graphics_settings' / name)
            expected_config = copy.deepcopy(self.config)
            for process in expected_config['process_array']:
                process['enable'] = process['name'] == 'depthoffield'
            self.assertEqual(actual, expected_config)

    def test_active_is_disabled_and_only_one_raw_t1_sample_is_wrapped(self):
        receipt = build.install(self.project, self.game, 'dof-active')
        self.assertTrue(receipt['active_requires_identity_gate'])
        shader = (self.project / receipt['native_detail']['fragment_file']).read_text()
        self.assertIn('mod(encoded, 64.0)', shader)
        self.assertIn('texture(TEXTURE_2, vec2(.5))', shader)
        self.assertNotIn('clearScene.a =', shader)
        for name in ('post_process.json', 'post_process_rngl.json'):
            actual = build.read_json(self.project / 'resource_pack/graphics_settings' / name)
            self.assertTrue(all(row['enable'] is False for row in actual['process_array']))
            self.assertEqual(actual['process_array'][1]['pass_array'], self.config['process_array'][1]['pass_array'])

    def test_sentinel_and_raw_t1_change_only_native_final_assignment(self):
        for case, expected in [('dof-sentinel', 'gl_FragColor = vec4(0.2, 0.8, 0.4, 1.0);'),
                               ('dof-raw-t1', 'gl_FragColor = texture(TEXTURE_1, uv);')]:
            shader = build.fragment_source(self.source, case)
            self.assertEqual(shader.replace(expected, 'gl_FragColor = depth_sample2(color);'), self.source)

    def test_bloom_materials_are_merged_in_loaded_file_without_native_overrides(self):
        receipt = build.install(self.project, self.game, 'bloom-control')
        materials = build.read_json(self.project / build.MATERIAL_PATH)
        self.assertEqual(set(materials), {'carrier_custom', 'pmanim_bloom_candidate_source',
                                         'pmanim_bloom_candidate_input'})
        self.assertEqual(materials['carrier_custom'], {'unchanged': True})
        self.assertEqual(build.validate(self.project), receipt)
        self.assertEqual(build.read_json(self.project / 'resource_pack/graphics_settings/post_process.json'), self.config)

    def test_registration_omission_is_rejected_before_any_startup_output(self):
        fixtures.write_json(self.native / 'materials/common.json', [{'path': 'materials/sfx.material'}])
        with self.assertRaisesRegex(ValueError, 'does not register'):
            build.install(self.project, self.game, 'dof-identity')
        self.assertFalse((self.project / 'native_post_startup.json').exists())

    def test_identity_copies_native_crlf_bytes_exactly(self):
        source = self.source.replace('\n', '\r\n').encode('utf-8')
        for root in (self.native, self.game.parent / 'data'):
            (root / 'shaders/glsl/depth_sample.fragment').write_bytes(source)
        receipt = build.install(self.project, self.game, 'dof-identity')
        self.assertEqual((self.project / receipt['native_detail']['fragment_file']).read_bytes(), source)

    def test_added_pack_file_is_rejected(self):
        build.install(self.project, self.game, 'dof-identity')
        (self.project / 'resource_pack/shaders/glsl/rogue.fragment').write_bytes(b'rogue')
        with self.assertRaisesRegex(ValueError, 'inventory changed'):
            build.validate(self.project)

    def test_changed_bloom_dependency_is_rejected_before_startup_write(self):
        bloom = build.module('pinned_bloom_test_dependency', build.HERE / 'bloom_retest.py')
        original_module = build.module
        with patch.object(build, 'module', side_effect=lambda name, path: (
                bloom if Path(path).name == 'bloom_retest.py' else original_module(name, path))):
            with patch.object(bloom, 'FROZEN_BLOOM_SHA256', 'changed'):
                with self.assertRaisesRegex(RuntimeError, 'source changed'):
                    build.install(self.project, self.game, 'bloom-control')
        self.assertFalse((self.project / 'native_post_startup.json').exists())

    def test_installed_registration_tampering_is_rejected(self):
        build.install(self.project, self.game, 'dof-identity')
        fixtures.write_json(self.native / 'materials/common.json', [])
        with self.assertRaisesRegex(ValueError, 'registration changed'):
            build.validate(self.project)

    def test_reinstall_or_project_registration_override_is_rejected(self):
        build.install(self.project, self.game, 'dof-identity')
        with self.assertRaisesRegex(ValueError, 'fresh carrier'):
            build.install(self.project, self.game, 'dof-active')
        fixtures.write_json(self.project / 'resource_pack/materials/common.json', [])
        with self.assertRaisesRegex(ValueError, 'inventory changed|overrides installed'):
            build.validate(self.project)


class RetestGateTests(unittest.TestCase):
    def test_old_candidate_schema_never_passes_retest_gate(self):
        native = Mock()
        with patch.object(build, 'read_json', return_value={
            'schema': 'native_dof_candidate_run_v1', 'case': 'dof-identity',
            'failure': None, 'cleanup_failure': None}):
            with self.assertRaisesRegex(ValueError, 'did not finish'):
                dof.verify_identity_gate('old-status.json', b'0'*65536, native)
        native.assert_not_called()

    def test_cleanup_failed_disable_keeps_carrier_visible(self):
        experiment = Mock()
        experiment.call.return_value = {'accepted': False, 'enabled': True}
        receipt = {'cleanup_failure': None}
        dof._cleanup(experiment, receipt)
        self.assertEqual(experiment.call.call_count, 1)
        self.assertIn('preserve active carrier', receipt['cleanup_failure'])

    def test_cleanup_hides_carrier_and_fixture_after_confirmed_disable(self):
        experiment = Mock()
        experiment.call.side_effect = [{'accepted': True, 'enabled': False}, {}, {}]
        receipt = {'cleanup_failure': None}
        dof._cleanup(experiment, receipt)
        self.assertIsNone(receipt['cleanup_failure'])
        self.assertEqual(experiment.call.call_count, 3)
        self.assertIn('pipeline_ready=False', experiment.call.call_args_list[1].args[1])
        self.assertIn('configure_known_fixture(False)', experiment.call.call_args_list[2].args[1])


class RetestIdentityReplayTests(unittest.TestCase):
    """Real PNG fixtures exercise replay rather than trusting stored exact flags."""
    @classmethod
    def setUpClass(cls):
        cls.native = dof.native_module()
        cls.payload = cls.native.verify_module.payload_bytes(65536)

    save_image = fixtures.DofGateTests.save_image
    persist = fixtures.DofGateTests.persist

    def setUp(self):
        fixtures.DofGateTests.setUp(self)
        (self.project / build.RECEIPT).write_bytes(b'immutable fake retest receipt')
        self.gate.update(schema='native_dof_retest_run_v1', game_pid=123,
            cleanup_disable={'accepted': True, 'enabled': False},
            candidate_receipt_sha256=build.sha(self.project / build.RECEIPT),
            profile_setters=[{'requested': dict(profile), 'enabled': True,
                'accepted': [[name, True] for name in
                             ('center_reset', 'focus', 'near', 'far', 'radius', 'center', 'enable')]}
                for profile in [*dof.PROFILES, dof.PROFILES[0]]])
        for row in [*self.gate['profiles'], *self.gate['diagnostics']]:
            row['capture_receipt'].update(file=row['capture_file'], pid=123,
                                         window={'pid': 123, 'minimized': False})
        self.persist()

    def verify(self):
        with patch.object(build, 'validate', return_value=self.validated):
            return dof.verify_identity_gate(self.path, self.payload, self.native)

    test_actual_profiles_and_full_late_data_pass = fixtures.DofGateTests.test_gate_reopens_profiles_and_fully_redecodes_actual_bytes
    test_claimed_exact_does_not_hide_corrupt_data_or_guard = fixtures.DofGateTests.test_claimed_exact_does_not_hide_corrupted_data_or_guard
    test_guard_motion_is_not_a_native_blur_positive = fixtures.DofGateTests.test_guard_motion_is_not_a_native_blur_positive
    test_zero_return_and_fixed_camera_are_required = fixtures.DofGateTests.test_final_native_zero_return_and_camera_are_required

    def test_rejected_setter_and_wrong_request_are_rejected(self):
        self.gate['profile_setters'][1]['accepted'][0][1] = False
        self.persist()
        with self.assertRaisesRegex(ValueError, 'setter receipt rejected'):
            self.verify()
        self.gate['profile_setters'][1]['accepted'][0][1] = True
        self.gate['profile_setters'][1]['requested']['scale'] = 0.
        self.persist()
        with self.assertRaisesRegex(ValueError, 'setter receipt rejected'):
            self.verify()

    def test_capture_wrong_pid_path_or_minimized_is_rejected(self):
        receipt = self.gate['profiles'][0]['capture_receipt']
        for updates in ({'pid': 124}, {'file': 'wrong.png'}, {'window': {'pid': 123, 'minimized': True}}):
            original = copy.deepcopy(receipt)
            receipt.update(updates)
            self.persist()
            with self.assertRaisesRegex(ValueError, 'provenance rejected'):
                self.verify()
            receipt.clear()
            receipt.update(original)

    def test_unconfirmed_native_disable_is_rejected(self):
        self.gate['cleanup_disable']['enabled'] = True
        self.persist()
        with self.assertRaisesRegex(ValueError, 'confirmed dedicated native disable'):
            self.verify()


if __name__ == '__main__':
    unittest.main()
