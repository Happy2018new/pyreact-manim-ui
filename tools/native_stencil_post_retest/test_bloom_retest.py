"""Offline recovery schedule and frozen visual-gate regressions; no game IO."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('bloom_retest_under_test', HERE / 'bloom_retest.py')
retest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retest)
FAKE_SPEC = importlib.util.spec_from_file_location(
    'frozen_bloom_fakes_for_retest', HERE.parent / 'native_stencil_post_candidate/test_bloom.py')
fakes = importlib.util.module_from_spec(FAKE_SPEC)
FAKE_SPEC.loader.exec_module(fakes)
base = fakes.bloom


class ScheduledPost(fakes.FakePost):
    """Model delayed attachment availability; not an assertion of engine internals."""
    def __init__(self, probe):
        super().__init__()
        self.probe = probe
        self.operations = []
        self.created = {}
        self.primed = {}
        self.link_result = True
        self.reject_add = None
        self.hide_parameter_until_settle = False

    def AddPostProcess(self, definition, index=-1):
        name = definition['name']
        self.operations.append(('add', name, definition['enable'], self.probe.render_event))
        if name == self.reject_add:
            return False
        result = super().AddPostProcess(definition, index)
        self.created[name] = self.probe.render_event
        return result

    def SetEnableByName(self, name, enabled):
        self.operations.append(('enable', name, enabled, self.probe.render_event))
        if name in self.created and enabled:
            self.primed[name] = self.probe.render_event
        return super().SetEnableByName(name, enabled)

    def GetParameter(self, name, key):
        if self.hide_parameter_until_settle and self.probe.render_event == self.created.get(name):
            return None
        return super().GetParameter(name, key)

    def PostPassResultToOtherPass(self, *link):
        self.operations.append(('link', link, self.probe.render_event))
        for name in (link[0], link[2]):
            if name not in self.created or name not in self.primed:
                raise AssertionError('Register and explicitly prime each attachment first')
            if not self.created[name] < self.primed[name] < self.probe.render_event:
                raise AssertionError('Registration, prime and link require separate turns')
        if not self.link_result:
            return False
        return super().PostPassResultToOtherPass(*link)


class RetestExperiment(fakes.FakeExperiment):
    def __init__(self, evidence, **kwargs):
        super().__init__(evidence, **kwargs)
        self.probe.post = ScheduledPost(self.probe)
        self.initial_flags = self.probe.post.enabled.copy()
        self.command_text = {}
        self.invalid_ready_stage = None
        self.native_capture_drift = None

    def call(self, label, code='', expression='probe.snapshot()'):
        self.command_text[label] = code
        row = super().call(label, code, expression)
        if label == self.invalid_ready_stage:
            row['candidate_source_control'] = [0., 0., 0., 0.]
        return row

    def capture(self, experiment, label):
        row, pixels = super().capture(experiment, label)
        if '_native_b' in label and self.native_capture_drift == 'guard':
            pixels[0, 0] = 255
        if '_native_a_return' in label and self.native_capture_drift == 'return':
            pixels[65, 73] = 255
        return row, pixels


class BloomRetestTests(unittest.TestCase):
    def execute(self, experiment):
        return retest.run_bloom_retest(experiment, capture=experiment.capture,
                                      settle=experiment.settle, layout=fakes.LAYOUT)

    def assert_restored(self, experiment):
        for name, enabled in experiment.initial_flags.items():
            self.assertIs(experiment.probe.post.enabled[name], enabled)
        for name in (base.SOURCE, base.INPUT):
            if name in experiment.probe.post.enabled:
                self.assertFalse(experiment.probe.post.enabled[name])
        self.assertEqual(experiment.probe.post.native_mutations, [])
        self.assertEqual(experiment.probe.mode, 'all')
        self.assertTrue(experiment.probe.fixture['visible'])

    def test_separate_enabled_registration_prime_link_then_unchanged_image_gates(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment = RetestExperiment(evidence)
            report = self.execute(experiment)
            self.assertEqual(report['status'], 'native_positive_control_observed')
            self.assertIsNone(report['compatibility'])
            self.assertEqual([stage['phase'] for stage in report['setup_stages']],
                             ['isolate', 'add_source', 'add_input', 'prime'])
            self.assertEqual(len(report['captures']), 9)
            stages = report['setup_stages']
            for stage in stages:
                self.assertGreater(stage['ready_state']['render_event'], stage['request']['state']['render_event'])
            for left, right in zip(stages, stages[1:]):
                self.assertGreater(right['request']['state']['render_event'], left['ready_state']['render_event'])
            adds = [operation for operation in experiment.probe.post.operations if operation[0] == 'add']
            self.assertEqual([(row[1], row[2]) for row in adds], [(base.SOURCE, True), (base.INPUT, True)])
            self.assertLess(adds[0][3], adds[1][3])
            self.assertEqual(experiment.probe.post.links, [(base.SOURCE, 0, base.INPUT, 0, 3)])
            self.assertGreater(report['link_state_before']['render_event'], stages[-1]['ready_state']['render_event'])
            for phase in ['bloom_retest_add_source', 'bloom_retest_add_input']:
                self.assertNotIn('SetEnableByName', experiment.command_text[phase])
            self.assert_restored(experiment)
            stored = json.loads((Path(evidence) / retest.STATUS_FILE).read_text())
            self.assertEqual(stored['status'], report['status'])
            self.assertEqual(experiment.saved, 1)

    def test_new_attachment_parameters_can_be_unready_until_later_turn(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment = RetestExperiment(evidence)
            experiment.probe.post.hide_parameter_until_settle = True
            report = self.execute(experiment)
            self.assertEqual(report['status'], 'native_positive_control_observed')
            source = report['setup_stages'][1]
            self.assertIsNone(source['request']['state']['candidate_source_control'])
            self.assertEqual(source['ready_state']['candidate_source_control'], [160., 144., 1., 0.])
            self.assert_restored(experiment)

    def test_rejected_link_is_attempted_once_preserved_and_skips_all_images(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment = RetestExperiment(evidence)
            experiment.probe.post.link_result = False
            report = self.execute(experiment)
            self.assertEqual(report['status'], 'helper_failed')
            self.assertEqual(report['source_attachment']['accepted'], [['source_to_diagnostic_T3', False]])
            self.assertEqual(sum(row[0] == 'link' for row in experiment.probe.post.operations), 1)
            self.assertEqual(report['captures'], [])
            self.assertFalse(report['source_input_gate_passed'])
            self.assertIsNone(report['compatibility'])
            self.assert_restored(experiment)

    def test_partial_registration_failure_restores_without_linking(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment = RetestExperiment(evidence)
            experiment.probe.post.reject_add = base.INPUT
            report = self.execute(experiment)
            self.assertEqual(report['status'], 'helper_failed')
            self.assertEqual(report['setup_stages'][-1]['phase'], 'add_input')
            self.assertEqual(report['setup_stages'][-1]['request']['accepted'], [['add_input_enabled', False]])
            self.assertEqual(experiment.capture_labels, [])
            self.assertFalse(any(row[0] == 'link' for row in experiment.probe.post.operations))
            self.assert_restored(experiment)

    def test_bad_ready_readback_aborts_before_link(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment = RetestExperiment(evidence)
            experiment.invalid_ready_stage = 'bloom_retest_prime_ready'
            report = self.execute(experiment)
            self.assertEqual(report['status'], 'helper_failed')
            self.assertIn('source parameters', report['failure'])
            self.assertEqual(experiment.probe.post.links, [])
            self.assertEqual(experiment.capture_labels, [])
            self.assert_restored(experiment)

    def test_missing_render_fence_aborts_before_registration(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment = RetestExperiment(evidence)
            original = experiment.call

            def frozen_turn(label, code='', expression='probe.snapshot()'):
                row = original(label, code, expression)
                if label.endswith('_ready'):
                    row['render_event'] -= 2
                return row

            experiment.call = frozen_turn
            report = self.execute(experiment)
            self.assertEqual(report['status'], 'helper_failed')
            self.assertIn('later render turn', report['failure'])
            self.assertFalse(any(row[0] == 'add' for row in experiment.probe.post.operations))
            self.assertEqual(experiment.capture_labels, [])
            self.assert_restored(experiment)

    def test_failed_source_gate_skips_native_even_after_successful_recovery_link(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment = RetestExperiment(evidence, bad_source=True)
            report = self.execute(experiment)
            self.assertEqual(report['status'], 'source_control_unproven')
            self.assertEqual(len(report['captures']), 6)
            self.assertFalse(any('_native_' in label for label in experiment.capture_labels))
            self.assertIsNone(report['compatibility'])
            self.assertFalse(report['native_stage_executed_observed'])
            self.assert_restored(experiment)

    def test_no_halo_and_drift_preserve_unknown_compatibility(self):
        for direction, drift in [(None, None), ('alpha_zero_gain', 'guard'), ('alpha_one_gain', 'return')]:
            with self.subTest(direction=direction, drift=drift), tempfile.TemporaryDirectory() as evidence:
                experiment = RetestExperiment(evidence, direction=direction)
                experiment.native_capture_drift = drift
                report = self.execute(experiment)
                self.assertEqual(report['status'], 'native_stage_unproven')
                self.assertIsNone(report['compatibility'])
                self.assertFalse(report['native_positive_response_observed'])
                self.assert_restored(experiment)

    def test_alpha_one_gain_keeps_frozen_halo_direction_semantics(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment = RetestExperiment(evidence, direction='alpha_one_gain')
            report = self.execute(experiment)
            self.assertTrue(report['native_response']['passed'])
            self.assertEqual(report['native_response']['response_direction'], 'alpha_one_gain')
            self.assertFalse(report['native_response']['renderer_branch_authenticated'])
            self.assertIsNone(report['compatibility'])
            self.assert_restored(experiment)

    def test_capture_exception_restores_and_records_failure(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment = RetestExperiment(evidence)

            def failed_capture(*args):
                raise OSError('offline synthetic capture failure')

            report = retest.run_bloom_retest(experiment, capture=failed_capture,
                                           settle=experiment.settle, layout=fakes.LAYOUT)
            self.assertEqual(report['status'], 'helper_failed')
            self.assertIn('offline synthetic capture failure', report['failure'])
            self.assertIsNone(report['compatibility'])
            self.assert_restored(experiment)

    def test_invalid_initial_isolation_has_no_setup_mutation(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment = RetestExperiment(evidence)
            experiment.probe.post.enabled['depthoffield'] = True
            original = copy.deepcopy(experiment.probe.post.enabled)
            report = self.execute(experiment)
            self.assertEqual(report['status'], 'helper_failed')
            self.assertEqual(report['setup_stages'], [])
            self.assertEqual(experiment.probe.post.enabled, original)
            self.assertEqual(experiment.probe.post.operations, [])

    def test_changed_frozen_dependency_rejected_before_experiment_transport(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as evidence:
            experiment = RetestExperiment(evidence)
            with patch.object(Path, 'read_bytes', return_value=b'changed dependency'):
                with self.assertRaisesRegex(RuntimeError, 'Frozen Bloom candidate source changed'):
                    retest.resources()
                report = self.execute(experiment)
            self.assertEqual(report['status'], 'helper_failed')
            self.assertIn('Frozen Bloom candidate source changed', report['failure'])
            self.assertEqual(experiment.labels, [])
            self.assertEqual(experiment.probe.post.operations, [])
            self.assertEqual(report['captures'], [])
            self.assertIsNone(report['compatibility'])

    def test_resources_and_frozen_dependency_are_unchanged_and_import_is_inert(self):
        before = hashlib.sha256(retest.FROZEN_BLOOM.read_bytes()).hexdigest()
        self.assertEqual(before, retest.FROZEN_BLOOM_SHA256)
        self.assertEqual(retest.resources(), base.resources())
        self.assertEqual(hashlib.sha256(retest.FROZEN_BLOOM.read_bytes()).hexdigest(), before)
        tree = ast.parse((HERE / 'bloom_retest.py').read_text(encoding='utf-8'))
        import_nodes = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertFalse(any('runner' in ast.unparse(node) or 'lifecycle' in ast.unparse(node) for node in import_nodes))
        # An import with all external file reads and transport functions denied
        # proves loading the retest itself does not eagerly load its dependency.
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('inert_bloom_retest', HERE / 'bloom_retest.py')
        module = importlib.util.module_from_spec(spec)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('eager file read')):
            spec.loader.exec_module(module)


if __name__ == '__main__':
    unittest.main()
