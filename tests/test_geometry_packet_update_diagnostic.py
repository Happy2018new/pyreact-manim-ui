"""CPU controls for exact submitted-generation classification and runner stages."""
import argparse
import copy
import ctypes
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'tools/geometry_packet_probe'
VERIFY_SPEC = importlib.util.spec_from_file_location('geometry_update_verifier',
                                                    PROBE / 'verify_capture.py')
VERIFY = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFY)
with patch.dict(sys.modules, {'verify_capture': VERIFY}), \
        patch.object(sys, 'path', [str(PROBE)] + sys.path):
    SPEC = importlib.util.spec_from_file_location('geometry_update_diagnostic',
                                                 PROBE / 'run_update_diagnostic.py')
    DIAGNOSTIC = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(DIAGNOSTIC)


def fixture_bytes(seed, generation, count):
    values = []
    wrap = lambda value: ctypes.c_uint32(value).value
    for index in range(count):
        value = seed ^ wrap(generation * 0x9e3779b9) ^ wrap(index * 0x85ebca6b)
        for shift, multiplier in ((16, 0x7feb352d), (15, 0x846ca68b)):
            value = wrap((value ^ (value >> shift)) * multiplier)
        values.append((value ^ (value >> 16)) % 256)
    return bytes(values)


def fixture(generation=9, captured_generation=None, start=0, count=137, slot_count=137,
            captured_seed=None):
    receipt = {'schema': 'geometry_packet_probe_v1', 'seed': 123456789,
               'generation': generation, 'slot_count': slot_count,
               'geometry_name': 'geometry_%d' % generation, 'geometry_build_serial': generation,
               'screen_size': [720, 1080], 'query': [start, count, 64],
               'display_rect_norm': [0, 0, 1, 1], 'encoding': 'compact8', 'query_mode': 0}
    captured_generation = generation if captured_generation is None else captured_generation
    payload = fixture_bytes(receipt['seed'] if captured_seed is None else captured_seed,
                            captured_generation, slot_count)
    image = Image.new('RGBA', (720, 1080), (17, 53, 97, 255))
    draw = ImageDraw.Draw(image)
    rows = math.ceil(count / 64)
    for ordinal, value in enumerate(payload[start:start + count]):
        row, column = divmod(ordinal, 64)
        left = math.ceil(column * 720 / 64 - .5)
        right = math.ceil((column + 1) * 720 / 64 - .5) - 1
        top = math.ceil(row * 1080 / rows - .5)
        bottom = math.ceil((row + 1) * 1080 / rows - .5) - 1
        draw.rectangle((left, top, right, bottom), fill=(value, value, value, 255))
    return receipt, image


def history(*generations):
    return [{'generation': generation, 'name': 'geometry_%d' % generation,
             'serial': generation, 'timings': {'combine_ms': 1.25}}
            for generation in generations]


def runner_args(directory, **overrides):
    values = dict(project=Path(directory) / 'project', evidence=Path(directory),
                  name='update_case', byte_count=137, encoding='compact8', policy='fresh',
                  updates=8, interval_frames=1, seconds=8., settle=0., full=False,
                  recreate=True)
    values.update(overrides)
    return argparse.Namespace(**values)


class GeometryUpdateClassificationTests(unittest.TestCase):
    def test_exact_submitted_stale_generation_preserves_final_failure(self):
        receipt, image = fixture(captured_generation=5)
        result = DIAGNOSTIC.classify_observed(receipt, image, history(1, 4, 5, 9))
        self.assertEqual('stale_generation', result['classification'])
        self.assertFalse(result['final_generation_match'])
        self.assertFalse(result['final_verification']['passed'])
        self.assertEqual([5], result['matched_generations'])
        self.assertEqual([{'history_index': 2, 'seed': 123456789, 'generation': 5, 'name': 'geometry_5',
                           'serial': 5}], result['matched_candidates'])
        self.assertEqual(4, len(result['candidates']))
        for candidate in result['candidates']:
            verified = candidate['verification']
            self.assertEqual(137 * 9, verified['checked_pixels'])
            self.assertEqual(137 * 36, verified['checked_channels'])
            self.assertEqual(64, len(verified['expected_payload_sha256']))
            self.assertEqual(result['observed_query_sha256'], verified['observed_payload_sha256'])
        self.assertFalse(result['offset_search_used'])

    def test_each_submitted_upload_uses_its_recorded_seed(self):
        receipt, image = fixture(captured_generation=5, captured_seed=987654321)
        uploads = history(1, 5, 9)
        for upload in uploads:
            upload.update(seed=123456789, slot_count=137, encoding='compact8')
        uploads[1]['seed'] = 987654321
        result = DIAGNOSTIC.classify_observed(receipt, image, uploads)
        self.assertEqual('stale_generation', result['classification'])
        self.assertFalse(result['final_generation_match'])
        self.assertEqual([{'history_index': 1, 'seed': 987654321, 'generation': 5,
                           'name': 'geometry_5', 'serial': 5}], result['matched_candidates'])
        for field, value in (('slot_count', 138), ('encoding', 'legacy8')):
            bad = copy.deepcopy(uploads)
            bad[1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                DIAGNOSTIC.classify_observed(receipt, image, bad)

    def test_final_generation_pass_and_nonzero_query_offset_use_exact_indices(self):
        receipt, image = fixture(start=137, count=137, slot_count=300)
        result = DIAGNOSTIC.classify_observed(receipt, image, history(1, 5, 9))
        self.assertEqual('current_generation', result['classification'])
        self.assertTrue(result['final_generation_match'])
        self.assertEqual([9], result['matched_generations'])
        self.assertEqual([137, 137, 64], result['query'])
        wrong_offset = copy.deepcopy(receipt)
        wrong_offset['query'][0] = 0
        wrong = DIAGNOSTIC.classify_observed(wrong_offset, image, history(1, 5, 9))
        self.assertEqual('unmatched', wrong['classification'])
        self.assertEqual([], wrong['matched_generations'])

    def test_off_center_single_channel_or_alpha_corruption_rejects_stale_match(self):
        receipt, image = fixture(captured_generation=5)
        stale_receipt = dict(receipt, generation=5)
        exact = DIAGNOSTIC.verify_image(stale_receipt, image)
        x, y = exact['centers'][136]
        for channel in (0, 1, 2, 3):
            corrupt = image.copy()
            pixel = list(corrupt.getpixel((x + 1, y - 1)))
            pixel[channel] ^= 1
            corrupt.putpixel((x + 1, y - 1), tuple(pixel))
            with self.subTest(channel=channel):
                result = DIAGNOSTIC.classify_observed(receipt, corrupt, history(1, 5, 9))
                self.assertEqual('unmatched', result['classification'])
                self.assertEqual([], result['matched_candidates'])
                self.assertFalse(any(candidate['verification']['passed'] for candidate in result['candidates']))

    def test_only_submitted_generations_can_be_matched(self):
        receipt, image = fixture(captured_generation=5)
        result = DIAGNOSTIC.classify_observed(receipt, image, history(1, 4, 9))
        self.assertEqual('unmatched', result['classification'])
        self.assertEqual([], result['matched_generations'])
        for entries in ([], history(1, 5), [{'generation': 9}],
                        history(1, 9) + [{'generation': True, 'name': 'bad', 'serial': 10}]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                DIAGNOSTIC.classify_observed(receipt, image, entries)

    def test_diagnostic_modes_and_uniform_controls_are_not_payload_evidence(self):
        receipt, image = fixture()
        for mode in (1, 2, 3, True):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                DIAGNOSTIC.classify_observed(dict(receipt, query_mode=mode), image, history(1, 9))
        for color in ((0, 0, 0, 255), (127, 127, 127, 255), (255, 255, 255, 255),
                      (17, 53, 97, 255)):
            result = DIAGNOSTIC.classify_observed(receipt, Image.new('RGBA', image.size, color), history(1, 9))
            with self.subTest(color=color):
                self.assertEqual('unmatched', result['classification'])
                self.assertFalse(result['uniform_controls_used_as_payload'])
        singleton, singleton_image = fixture(count=1, slot_count=1)
        singleton_result = DIAGNOSTIC.classify_observed(singleton, singleton_image, history(1, 9))
        self.assertEqual('insufficient_query_variation', singleton_result['classification'])
        self.assertEqual([], singleton_result['matched_candidates'])
        self.assertFalse(singleton_result['final_query_has_payload_variation'])


class GeometryUpdateRunnerTests(unittest.TestCase):
    def test_full_coverage_keeps_exact_singleton_tail_without_uniform_delivery_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = DIAGNOSTIC.DiagnosticRunner(runner_args(directory, byte_count=4097, full=True))

            def capture(control, index, start, count):
                receipt, image = fixture(start=start, count=count, slot_count=4097)
                diagnostic = DIAGNOSTIC.classify_observed(receipt, image, history(1, 9))
                report = diagnostic['final_verification']
                return receipt, report, {'classification': diagnostic['classification']}

            with patch.object(runner, 'capture_window', side_effect=capture):
                runner.capture_control('final')
            control = runner.controls['final']
            self.assertTrue(control['passed'])
            self.assertTrue(control['verification']['passed'])
            self.assertEqual(4097, control['verification']['checked_cells'])
            self.assertEqual('insufficient_query_variation', control['windows'][-1]['classification'])
            self.assertEqual([], runner.errors)

    def test_final_mismatch_still_runs_both_controls_and_stays_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = DIAGNOSTIC.DiagnosticRunner(runner_args(directory))
            frozen, _ = fixture()
            frozen.update(ready=True, benchmark_running=False, upload_history=history(1, 5, 9),
                          last_run={'updates': 2})
            calls = []

            def host(action, suffix, code=None, timeout=120.):
                calls.append((action, suffix, code))
                runner.state = copy.deepcopy(frozen)
                return runner.state

            def capture(control):
                runner.controls[control] = {'status': 'failed' if control == 'final' else 'passed',
                                            'passed': control != 'final', 'full_slot_coverage': True,
                                            'windows': [{'passed': control != 'final'}]}
                if control == 'final':
                    runner.errors.append({'stage': 'final', 'error': 'Pixel mismatch'})

            with patch.object(runner, 'host', side_effect=host), \
                    patch.object(runner, 'capture_control', side_effect=capture), \
                    patch.object(DIAGNOSTIC.time, 'sleep'):
                self.assertEqual(1, runner.run())
            result = json.loads(runner.result_path.read_text(encoding='utf-8'))
            self.assertFalse(result['passed'])
            self.assertEqual('failed', result['status'])
            self.assertTrue(result['same_name_redraw_recovers'])
            self.assertTrue(result['recreated_screen_recovers'])
            self.assertEqual({'final', 'same_name_redraw', 'recreated_screen'}, set(result['controls']))
            self.assertTrue(any(suffix == 'same_name_redraw' and 'probe.redraw()' in code
                                for _, suffix, code in calls))
            self.assertTrue(any(suffix == 'recreate' and 'probe.recreate_screen()' in code
                                for _, suffix, code in calls))
            self.assertTrue(runner.result_path.name.endswith('.update.json'))

    def test_open_timeout_is_persisted_with_stage_and_error(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = DIAGNOSTIC.DiagnosticRunner(runner_args(directory))
            with patch.object(runner, 'host', side_effect=TimeoutError('probe timed out')):
                self.assertEqual(1, runner.run())
            result = json.loads(runner.result_path.read_text(encoding='utf-8'))
            self.assertEqual('failed', result['status'])
            self.assertEqual('open', result['stage'])
            self.assertEqual('open', result['errors'][0]['stage'])
            self.assertIn('TimeoutError: probe timed out', result['errors'][0]['error'])


if __name__ == '__main__':
    unittest.main()
