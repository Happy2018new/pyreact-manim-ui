"""Offline image criteria and emitted-command tests; never connects to a game."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np


SPEC = importlib.util.spec_from_file_location('candidate_bloom_under_test', Path(__file__).with_name('bloom.py'))
bloom = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bloom)

LAYOUT = {'viewport': [160, 144], 'patch': [72, 64, 16, 16],
          'halo_gap': 3, 'halo_radius': 12, 'guard_gap': 12}
CORE = ('stencil_integrated_copy', 'stencil_integrated_restore', 'stencil_integrated_consumer')


def rectangle(padding=0):
    width, height = LAYOUT['viewport']
    x, y, w, h = LAYOUT['patch']
    value = np.zeros((height, width), dtype=bool)
    value[y-padding:y+h+padding, x-padding:x+w+padding] = True
    return value


def source_images():
    rgb = np.repeat((rectangle().astype(np.uint8) * 255)[:, :, None], 3, axis=2)
    alpha_a = np.full(rgb.shape, 255, dtype=np.uint8)
    alpha_b = alpha_a.copy()
    alpha_b[rectangle()] = 0
    return [rgb.copy() for _ in range(3)], [alpha_a, alpha_b, alpha_a.copy()]


def native_images(direction='alpha_zero_gain'):
    a = np.full((LAYOUT['viewport'][1], LAYOUT['viewport'][0], 3), 31, dtype=np.uint8)
    b = a.copy()
    ring = rectangle(10) & ~rectangle(4)
    if direction == 'alpha_zero_gain':
        b[ring] += 48
    elif direction == 'alpha_one_gain':
        a[ring] += 48
    return [a, b, a.copy()]


class FakePost:
    """Execute emitted public calls, rather than returning canned runner states."""
    def __init__(self):
        self.order = list(CORE) + list(bloom.NATIVE)
        self.enabled = {name: name in CORE or name == 'bloom' for name in self.order}
        self.parameters = {}
        self.links = []
        self.native_mutations = []

    def GetPostProcessOrder(self):
        return self.order[:]

    def CheckEnabledByName(self, name):
        return self.enabled[name]

    def AddPostProcess(self, definition, index=-1):
        name = definition['name']
        if name in self.order:
            return False
        if index < 0:
            self.order.append(name)
        else:
            self.order.insert(index, name)
        self.enabled[name] = definition['enable']
        self.parameters[name] = {row['name']: copy.deepcopy(row['value']) for row in definition['paras']}
        return True

    def SetEnableByName(self, name, enabled):
        if name in bloom.NATIVE:
            self.native_mutations.append((name, enabled))
            raise AssertionError('Candidate must never set native enable flags')
        self.enabled[name] = enabled
        return True

    def SetParameter(self, name, key, value):
        if name in bloom.NATIVE:
            raise AssertionError('Candidate must never set native parameters')
        self.parameters[name][key] = copy.deepcopy(value)
        return True

    def GetParameter(self, name, key):
        return copy.deepcopy(self.parameters[name][key])

    def PostPassResultToOtherPass(self, *link):
        if not 3 <= link[4] <= 7:
            raise AssertionError('Public destination must be T3..T7')
        if self.order.index(link[0]) >= self.order.index(link[2]):
            raise AssertionError('Source must precede diagnostic')
        if not self.enabled[link[0]] or not self.enabled[link[2]]:
            raise AssertionError('Prime custom passes before linking their attachment')
        self.links.append(link)
        return True


class FakeProbe:
    def __init__(self):
        self.post = FakePost()
        self.render_event = 0
        self.mode = 'all'
        self.fixture = {'visible': True, 'varying_alpha': True}

    def configure(self, mode):
        self.mode = mode
        for name in CORE:
            self.post.enabled[name] = mode == 'all'

    def configure_known_fixture(self, enabled, varying_alpha=True):
        self.fixture = {'visible': enabled, 'varying_alpha': varying_alpha}

    def snapshot(self):
        return {'render_event': self.render_event, 'mode': self.mode,
                'payload_visible': self.mode == 'all', 'clear_visible': self.mode == 'all',
                'known_fixture': copy.deepcopy(self.fixture),
                'native_post_flags': [(name, self.post.enabled[name]) for name in bloom.NATIVE]}


class FakeExperiment:
    def __init__(self, evidence, direction='alpha_zero_gain', bad_source=False):
        self.evidence = Path(evidence)
        self.viewport = LAYOUT['viewport'][:]
        self.probe = FakeProbe()
        self.labels, self.capture_labels = [], []
        self.direction, self.bad_source = direction, bad_source
        self.saved = 0
        self.initial_flags = self.probe.post.enabled.copy()
        self.intrude_after_capture = False

    def call(self, label, code='', expression='probe.snapshot()'):
        self.labels.append(label)
        self.probe.render_event += 1
        environment = {'probe': self.probe}
        exec(code, environment)
        return json.loads(json.dumps(eval(expression, environment)))

    def invoke(self, *args):
        raise AssertionError('Offline tests must never invoke a host/runtime tool')

    def save(self):
        self.saved += 1

    def settle(self):
        self.probe.render_event += 1

    def capture(self, experiment, label):
        self.capture_labels.append(label)
        post = self.probe.post
        alpha = post.parameters[bloom.SOURCE]['control'][2]
        if post.enabled[bloom.INPUT]:
            rgb, alpha_frames = source_images()
            index = 0 if alpha == 1. else 1
            mode = post.parameters[bloom.INPUT]['control'][0]
            pixels = (alpha_frames if mode else rgb)[index].copy()
            if self.bad_source and mode and alpha == 0.:
                pixels[:] = 255
        else:
            index = 0 if alpha == 1. else 1
            pixels = native_images(self.direction)[index].copy()
        if self.intrude_after_capture:
            post.enabled[CORE[0]] = True
        return {'label': label, 'offline_synthetic': True}, pixels


class ImageCriteriaTests(unittest.TestCase):
    def test_source_requires_identical_rgb_and_declared_alpha(self):
        rgb, alpha = source_images()
        self.assertTrue(bloom.evaluate_source_control(rgb, alpha, LAYOUT)['passed'])
        alpha[1][64, 72] = 255
        report = bloom.evaluate_source_control(rgb, alpha, LAYOUT)
        self.assertFalse(report['passed'])
        self.assertEqual(report['source_alpha_expected_error_pixels'], [0, 1, 0])

    def test_rgb_alpha_confusion_is_rejected(self):
        rgb, _ = source_images()
        self.assertFalse(bloom.evaluate_source_control(rgb, rgb, LAYOUT)['passed'])

    def test_native_accepts_both_signed_directions_without_authenticating_backend(self):
        for direction in ('alpha_zero_gain', 'alpha_one_gain'):
            with self.subTest(direction=direction):
                report = bloom.evaluate_bloom_response(native_images(direction), LAYOUT)
                self.assertTrue(report['passed'])
                self.assertEqual(report['response_direction'], direction)
                self.assertFalse(report['renderer_branch_authenticated'])

    def test_source_body_or_filter_edge_changes_are_not_a_halo(self):
        for mask in (rectangle(), rectangle(3)):
            frames = native_images(None)
            frames[1][mask] += 48
            report = bloom.evaluate_bloom_response(frames, LAYOUT)
            self.assertFalse(report['passed'])
            self.assertEqual(report['outside_patch_halo_pixels'], 0)

    def test_guard_drift_and_failed_return_reject_apparent_halo(self):
        frames = native_images()
        frames[1][0, 0] += 10
        report = bloom.evaluate_bloom_response(frames, LAYOUT)
        self.assertFalse(report['passed'])
        self.assertEqual(report['guard_changed_pixels'], 1)
        frames = native_images()
        frames[2][65, 73] += 10
        report = bloom.evaluate_bloom_response(frames, LAYOUT)
        self.assertFalse(report['passed'])
        self.assertEqual(report['a_return_changed_pixels'], 1)

    def test_mixed_motion_and_isolated_noise_do_not_establish_native_response(self):
        frames = native_images()
        frames[1][54:60, 62:68] = 0
        self.assertFalse(bloom.evaluate_bloom_response(frames, LAYOUT)['passed'])
        frames = native_images(None)
        frames[1][54, 62] = 255
        self.assertFalse(bloom.evaluate_bloom_response(frames, LAYOUT)['passed'])

    def test_local_b_only_object_and_colored_side_motion_are_not_a_halo(self):
        frames = native_images(None)
        frames[1][54:58, 72:76] = 255  # Sixteen pixels, top side only, with stable A-return.
        report = bloom.evaluate_bloom_response(frames, LAYOUT)
        self.assertEqual(report['outside_patch_halo_pixels'], 16)
        self.assertFalse(report['passed'])
        self.assertFalse(report['halo_distributed_on_four_sides'])
        frames = native_images(None)
        ring = rectangle(10) & ~rectangle(4)
        frames[1][ring] = [230, 31, 31]  # Red-only changes cover every side.
        self.assertFalse(bloom.evaluate_bloom_response(frames, LAYOUT)['passed'])

    def test_malformed_frames_and_vacuous_thresholds_are_rejected(self):
        frames = native_images()
        for kwargs in ({'min_halo_pixels': 0}, {'tolerance': -1}, {'tolerance': 255}):
            with self.assertRaises(ValueError):
                bloom.evaluate_bloom_response(frames, LAYOUT, **kwargs)
        with self.assertRaises(ValueError):
            bloom.evaluate_bloom_response([frame[:-1] for frame in frames], LAYOUT)
        with self.assertRaises(ValueError):
            bloom.source_config(dict(LAYOUT, patch=[0, 0, 16, 16]))


class RunnerTests(unittest.TestCase):
    def run_fake(self, evidence, **kwargs):
        experiment = FakeExperiment(evidence, **kwargs)
        report = bloom.run_bloom_candidate(experiment, capture=experiment.capture,
                                          settle=experiment.settle, layout=LAYOUT)
        return experiment, report

    def assert_restored(self, experiment):
        for name, enabled in experiment.initial_flags.items():
            self.assertIs(experiment.probe.post.enabled[name], enabled)
        self.assertFalse(experiment.probe.post.enabled[bloom.SOURCE])
        self.assertFalse(experiment.probe.post.enabled[bloom.INPUT])
        self.assertEqual(experiment.probe.mode, 'all')
        self.assertTrue(experiment.probe.fixture['visible'])
        self.assertEqual(experiment.probe.post.native_mutations, [])

    def test_runner_executes_legal_control_gate_then_native_and_restores(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment, report = self.run_fake(evidence)
            self.assertEqual(report['status'], 'native_positive_control_observed')
            self.assertTrue(report['source_input_gate_passed'])
            self.assertTrue(report['native_stage_executed_observed'])
            self.assertIsNone(report['compatibility'])
            self.assertEqual(len(experiment.capture_labels), 9)
            self.assertTrue(all('_source_' in label for label in experiment.capture_labels[:6]))
            self.assertTrue(all('_native_' in label for label in experiment.capture_labels[6:]))
            self.assertEqual(experiment.probe.post.links, [(bloom.SOURCE, 0, bloom.INPUT, 0, 3)])
            self.assert_restored(experiment)
            stored = json.loads((Path(evidence) / 'bloom_candidate_status.json').read_text())
            self.assertEqual(stored['status'], report['status'])
            self.assertEqual(experiment.saved, 1)

    def test_source_gate_failure_skips_native_and_does_not_claim_incompatibility(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment, report = self.run_fake(evidence, bad_source=True)
            self.assertEqual(report['status'], 'source_control_unproven')
            self.assertFalse(report['native_positive_response_observed'])
            self.assertIsNone(report['compatibility'])
            self.assertEqual(len(experiment.capture_labels), 6)
            self.assertNotIn('native_response', report)
            self.assert_restored(experiment)

    def test_no_native_response_stays_unproven(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment, report = self.run_fake(evidence, direction=None)
            self.assertEqual(report['status'], 'native_stage_unproven')
            self.assertFalse(report['native_positive_response_observed'])
            self.assertIsNone(report['compatibility'])
            self.assertIsNone(report['failure'])
            self.assert_restored(experiment)

    def test_state_changed_during_capture_is_rejected(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment = FakeExperiment(evidence)
            experiment.intrude_after_capture = True
            report = bloom.run_bloom_candidate(experiment, capture=experiment.capture,
                                              settle=experiment.settle, layout=LAYOUT)
            self.assertEqual(report['status'], 'helper_failed')
            self.assertIn('Exactly procedural source', report['failure'])
            self.assertFalse(report['native_positive_response_observed'])
            self.assert_restored(experiment)

    def test_rejected_attachment_link_skips_captures_and_restores(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment = FakeExperiment(evidence)
            experiment.probe.post.PostPassResultToOtherPass = lambda *args: False
            report = bloom.run_bloom_candidate(experiment, capture=experiment.capture,
                                              settle=experiment.settle, layout=LAYOUT)
            self.assertEqual(report['status'], 'helper_failed')
            self.assertIsNone(report['compatibility'])
            self.assertEqual(experiment.capture_labels, [])
            self.assert_restored(experiment)

    def test_capture_exception_still_restores_original_controls(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment = FakeExperiment(evidence)

            def failed_capture(*args):
                raise OSError('synthetic passive capture failure')

            report = bloom.run_bloom_candidate(experiment, capture=failed_capture,
                                              settle=experiment.settle, layout=LAYOUT)
            self.assertEqual(report['status'], 'helper_failed')
            self.assertIn('synthetic passive capture failure', report['failure'])
            self.assertIsNone(report['compatibility'])
            self.assert_restored(experiment)

    def test_rejected_initial_isolation_performs_no_mutations(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment = FakeExperiment(evidence)
            experiment.probe.post.enabled['depthoffield'] = True
            original = experiment.probe.post.enabled.copy()
            report = bloom.run_bloom_candidate(experiment, capture=experiment.capture,
                                              settle=experiment.settle, layout=LAYOUT)
            self.assertEqual(report['status'], 'helper_failed')
            self.assertEqual(experiment.probe.post.enabled, original)
            self.assertEqual(experiment.probe.post.links, [])
            self.assertEqual(experiment.capture_labels, [])

    def test_unsettled_render_turn_skips_capture(self):
        with tempfile.TemporaryDirectory() as evidence:
            experiment = FakeExperiment(evidence)
            original_call = experiment.call

            def frozen_turn(label, code='', expression='probe.snapshot()'):
                row = original_call(label, code, expression)
                row['render_event'] = 1
                return row

            experiment.call = frozen_turn
            report = bloom.run_bloom_candidate(experiment, capture=experiment.capture,
                                              settle=lambda: None, layout=LAYOUT)
            self.assertEqual(report['status'], 'helper_failed')
            self.assertEqual(experiment.capture_labels, [])
            self.assertIn('render turn', report['failure'])
            self.assert_restored(experiment)

    def test_owned_resources_do_not_override_native_materials_or_slots(self):
        bundle = bloom.resources()
        self.assertEqual(set(bundle['materials']), {bloom.SOURCE, bloom.INPUT})
        for material in bundle['materials'].values():
            self.assertIn('Blending', material['-states'])
            self.assertIn('DisableAlphaWrite', material['-states'])
        self.assertNotIn('TEXTURE_0', bloom.SOURCE_FRAGMENT)
        self.assertIn('TEXTURE_3', bloom.INPUT_FRAGMENT)
        self.assertFalse(bloom.source_config(LAYOUT)['enable'])
        tree = ast.parse(Path(bloom.__file__).read_text(encoding='utf-8'))
        imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertFalse(any('runner' in ast.unparse(node) or 'lifecycle' in ast.unparse(node) for node in imports))


if __name__ == '__main__':
    unittest.main()
