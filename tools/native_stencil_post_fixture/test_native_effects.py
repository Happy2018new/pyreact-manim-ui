"""Offline guards against misclassifying native bypasses or inactive writers."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import native_effects as native


def state():
    payload = native.verify_module.payload_bytes(65536)
    value = {'state': 'resident', 'ready': True, 'logical_bytes': 65536,
             'viewport': native.VIEWPORT, 'source_roi': native.ROI,
             'identity': {'host_sha256': native.hashlib.sha256(payload).hexdigest(), 'byte_count': 65536},
             'generation': 1, 'active_pages': ['low', 'high'],
             'native_page_names': ['clear', 'low', 'high'],
             'native_attempt_count': 3, 'native_records_reserved': 131073}
    return payload, value


class NativeEffectTests(unittest.TestCase):
    def test_camera_requires_finite_vectors_and_nonzero_forward(self):
        valid = {'position': [0., -4., 9.], 'forward': [0., 0., -1.], 'render_event': 3}
        self.assertTrue(native._camera_sample_valid(valid))
        for key, value in (('position', None), ('position', [0., 1.]),
                           ('position', [0., float('inf'), 0.]),
                           ('forward', [0., float('nan'), 1.]),
                           ('forward', [0., 0., 0.]), ('forward', [False, 0., 1.]),
                           ('render_event', True)):
            invalid = dict(valid)
            invalid[key] = value
            self.assertFalse(native._camera_sample_valid(invalid), (key, value))

    def test_camera_waits_for_later_render_turn_and_persists_receipt(self):
        observations = iter([
            {'position': [1., 2., 3.], 'forward': None, 'render_event': 0},
            {'position': [1., 2., 3.], 'forward': [0., 0., 1.], 'render_event': 1},
            {'position': [1., 2., 3.], 'forward': [0., 0., 1.], 'render_event': 1},
            {'position': [1., 2., 3.], 'forward': [0., 0., 1.], 'render_event': 2}])
        with tempfile.TemporaryDirectory() as directory:
            experiment = SimpleNamespace(evidence=Path(directory), call=lambda *args, **kwargs: next(observations))
            with patch.object(native.time, 'sleep') as sleep:
                receipt = native.wait_camera(experiment, 'bloom')
            self.assertTrue(receipt['ready'])
            self.assertEqual(receipt['calls_attempted'], 4)
            self.assertEqual(receipt['first_ready_render_event'], 1)
            self.assertEqual(receipt['later_ready_render_event'], 2)
            self.assertEqual(sleep.call_args_list, [unittest.mock.call(.25)]*3)
            saved = json.loads((Path(directory)/'native_bloom_camera_preflight.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt, saved)

    def test_camera_stalled_render_turn_exhausts_exact_bounded_calls(self):
        calls = []
        def stalled(*args, **kwargs):
            calls.append(args)
            return {'position': [0., 0., 0.], 'forward': [1., 0., 0.], 'render_event': 1}
        with tempfile.TemporaryDirectory() as directory:
            experiment = SimpleNamespace(evidence=Path(directory), call=stalled)
            with patch.object(native.time, 'sleep') as sleep:
                with self.assertRaisesRegex(RuntimeError, '20 bounded reads'):
                    native.wait_camera(experiment, 'dof')
            self.assertEqual(len(calls), 20)
            self.assertEqual(sleep.call_args_list, [unittest.mock.call(.25)]*19)
            receipt = json.loads((Path(directory)/'native_depthoffield_camera_preflight.json').read_text(encoding='utf-8'))
            self.assertFalse(receipt['ready'])
            self.assertEqual(receipt['calls_attempted'], 20)
            self.assertIsNotNone(receipt['failure'])

    def test_camera_sdk_failure_persists_failed_preflight(self):
        def rejected(*args, **kwargs):
            raise RuntimeError('SDK read rejected')
        with tempfile.TemporaryDirectory() as directory:
            experiment = SimpleNamespace(evidence=Path(directory), call=rejected)
            with self.assertRaisesRegex(RuntimeError, 'SDK read rejected'):
                native.wait_camera(experiment, 'bloom')
            receipt = json.loads((Path(directory)/'native_bloom_camera_preflight.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['calls_attempted'], 1)
            self.assertFalse(receipt['ready'])
            self.assertEqual(receipt['observations'], [])

    def test_detached_camera_samples_must_follow_detach_render_event(self):
        events = iter((9, 10, 11, 11, 12))
        def observe(*args, **kwargs):
            return {'position': [0., 1., 2.], 'forward': [0., 1., 0.], 'render_event': next(events)}
        with tempfile.TemporaryDirectory() as directory:
            experiment = SimpleNamespace(evidence=Path(directory), call=observe)
            with patch.object(native.time, 'sleep'):
                receipt = native.wait_camera(experiment, 'bloom', phase='detached', after_render_event=10)
            self.assertEqual(receipt['calls_attempted'], 5)
            self.assertEqual([row['valid'] for row in receipt['observations']], [False, False, True, True, True])
            self.assertEqual(receipt['first_ready_render_event'], 11)
            self.assertEqual(receipt['later_ready_render_event'], 12)
            self.assertTrue((Path(directory)/'native_bloom_camera_preflight_detached.json').is_file())

    def test_split_prepare_uses_validated_literals_after_camera_transition(self):
        initial = {'observations': [{'position': [1.5, 2.5, 3.5], 'forward': [0., 0., 1.], 'render_event': 4}]}
        detached = {'observations': [{'position': [1., 2., 3.], 'forward': [0., 0., 1.], 'render_event': 7}]}
        calls = []
        def invoke(label, code='', expression=''):
            calls.append((label, code, expression))
            compile(code, '<host-generated>', 'exec')
            compile(expression, '<host-expression>', 'eval')
            if label.endswith('request_fixed_camera'):
                return {'origin': [1, 1, 3], 'accepted': [True, True], 'detach_result': None, 'render_event': 5}
            return {'origin': [1, 1, 3], 'anchor': [1., 2., 6.], 'clear_created': True, 'hud_hidden': True, 'render_event': 8}
        with tempfile.TemporaryDirectory() as directory:
            experiment = SimpleNamespace(evidence=Path(directory), call=invoke)
            with patch.object(native, 'wait_camera', side_effect=[initial, detached]) as wait:
                receipt = native.prepare_camera(experiment, 'bloom')
            self.assertEqual(wait.call_args_list, [unittest.mock.call(experiment, 'bloom'),
                unittest.mock.call(experiment, 'bloom', phase='detached', after_render_event=5)])
            self.assertEqual(len(calls), 2)
            self.assertIn('DepartCamera()', calls[0][1])
            self.assertNotIn('GetPosition()', calls[0][1] + calls[1][1])
            self.assertNotIn('GetForward()', calls[0][1] + calls[1][1])
            self.assertIn("probe._new_actor('clear',0)", calls[1][1])
            self.assertIn('probe.prepare()', calls[1][1])
            self.assertTrue(receipt['ready'])
            saved = json.loads((Path(directory)/'native_bloom_camera_setup.json').read_text(encoding='utf-8'))
            self.assertEqual(saved, receipt)

    def test_split_prepare_failure_never_creates_anchor_and_preserves_stage(self):
        initial = {'observations': [{'position': [1., 2., 3.], 'forward': [0., 0., 1.], 'render_event': 4}]}
        calls = []
        def invoke(label, code='', expression=''):
            calls.append(label)
            return {'origin': [1, 1, 3], 'accepted': [True, True], 'detach_result': None, 'render_event': 5}
        with tempfile.TemporaryDirectory() as directory:
            experiment = SimpleNamespace(evidence=Path(directory), call=invoke)
            with patch.object(native, 'wait_camera', side_effect=[initial, RuntimeError('Detached forward unavailable')]):
                with self.assertRaisesRegex(RuntimeError, 'Detached forward unavailable'):
                    native.prepare_camera(experiment, 'depthoffield')
            self.assertEqual(calls, ['native_depthoffield_request_fixed_camera'])
            receipt = json.loads((Path(directory)/'native_depthoffield_camera_setup.json').read_text(encoding='utf-8'))
            self.assertFalse(receipt['ready'])
            self.assertEqual(receipt['stage'], 'wait_detached')
            self.assertNotIn('completion', receipt)

    def test_independent_full_fixture_original_and_encoded(self):
        payload = native.verify_module.payload_bytes(65536)
        image = np.zeros((1080, 720, 3), dtype=np.uint8)
        y, x = np.indices((512, 512), dtype=np.int64)
        original = np.stack(((33*x+17*y+13) % 256, (73*x+19*y+41) % 256,
                             (151*x+47*y+97) % 256), axis=2).astype(np.uint8)
        image[128:640, 8:520] = original
        observed = native.fixture_statistics(Image.fromarray(image), payload)
        self.assertEqual(observed['original_exact_pixels'], 262144)
        self.assertEqual(observed['original_error_gt2_pixels'], 0)
        encoded = np.floor(original.astype(np.float64)*63./255.+.5).astype(np.uint8)
        symbols = np.array([(value >> shift) & 3 for value in payload for shift in (0, 2, 4, 6)], dtype=np.uint8)
        encoded[:, :, 0] += (symbols.reshape(512, 512)*64).astype(np.uint8)
        image[128:640, 8:520] = encoded
        observed = native.fixture_statistics(Image.fromarray(image), payload)
        self.assertEqual(observed['encoded_exact_pixels'], 262144)
        self.assertGreater(observed['original_error_gt2_pixels'], 260000)
        image[128, 8, 0] ^= 1
        corrupted = native.fixture_statistics(Image.fromarray(image), payload)
        self.assertEqual(corrupted['encoded_error_pixels'], 1)

    def test_bypass_requires_proven_restored_reference_and_full_payload(self):
        off = {'original_error_gt2_pixels': 0}
        active = {'original_error_gt2_pixels': 262000, 'encoded_error_pixels': 0}
        data = [{'mode': mode, 'exact': True} for mode in (1, 2, 6)]
        result = native.classify(off, active, off, data, False)
        self.assertEqual(result['status'], 'original_raw_t1_bypass_detected')
        self.assertFalse(result['compatibility'])
        self.assertTrue(result['native_stage_executed_observed'])
        data[-1]['exact'] = False
        result = native.classify(off, active, off, data, False)
        self.assertFalse(result['original_raw_t1_bypass_detected'])
        self.assertEqual(result['status'], 'late_payload_or_restored_reference_failed')

    def test_restored_output_without_native_witness_is_inconclusive(self):
        off = {'original_error_gt2_pixels': 0}
        active = dict(off, encoded_error_pixels=262144)
        data = [{'mode': mode, 'exact': True} for mode in (1, 2, 6)]
        result = native.classify(off, active, off, data, False)
        self.assertEqual(result['status'], 'native_stage_unproven')
        self.assertIsNone(result['compatibility'])
        self.assertEqual(native.classify(off, active, off, data, True)['compatibility'], True)
        self.assertFalse(native.classify(off, active, off, data[:2], True)['compatibility'])

    def test_resident_evidence_rejects_missing_duplicate_or_changed_pages(self):
        payload, value = state()
        native._resident(value, payload)
        for key in native.RESIDENT:
            invalid = copy.deepcopy(value)
            del invalid[key]
            with self.assertRaises(RuntimeError):
                native._resident(invalid, payload)
        duplicate = copy.deepcopy(value)
        duplicate['active_pages'] = ['low', 'low']
        with self.assertRaises(RuntimeError):
            native._resident(duplicate, payload)
        changed = copy.deepcopy(value)
        changed['generation'] += 1
        with self.assertRaises(RuntimeError):
            native._resident(changed, payload, value)

    def test_isolation_rejects_extra_enabled_custom_effect(self):
        late = 'stencil_integrated_after_bloom'
        order = [*native.CORE, *native.NATIVE, late]
        required = [*native.CORE, 'bloom', late]
        value = {'actual_post_order': order,
                 'native_post_flags': [(name, name == 'bloom') for name in native.NATIVE],
                 'native_test_all_flags': [(name, name in required) for name in order]}
        native._isolation(value, 'bloom', late)
        extra = copy.deepcopy(value)
        extra['actual_post_order'].insert(-1, 'unrelated_custom_alpha_effect')
        extra['native_test_all_flags'].insert(-1, ('unrelated_custom_alpha_effect', True))
        with self.assertRaises(RuntimeError):
            native._isolation(extra, 'bloom', late)
        wrong = copy.deepcopy(value)
        wrong['native_test_all_flags'][0] = (native.CORE[0], False)
        with self.assertRaises(RuntimeError):
            native._isolation(wrong, 'bloom', late)


if __name__ == '__main__':
    unittest.main()
