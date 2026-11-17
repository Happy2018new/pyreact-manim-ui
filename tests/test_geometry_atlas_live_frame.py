"""Live-frame generation classification still requires every exact 3x3 patch."""
import ctypes
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw


PROBE = Path(__file__).resolve().parents[1] / 'tools/geometry_atlas_probe'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROBE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = load('live_frame_pixel_oracle', 'verify_capture.py')
with patch.dict(sys.modules, {'verify_capture': VERIFY}):
    LIVE = load('live_frame_classifier', 'classify_live_frame.py')


def receipt(count=97):
    return dict(schema='geometry_atlas_probe_v1', seed=123456789, generation=99,
                slot_count=137, geometry_name='cpu_instant_name', geometry_build_serial=999,
                encoding='compact8', screen_size=[720, 1080],
                display_rect_norm=[0, 64. / 1080., 1, 1000. / 1080.], pipeline_ready=True,
                layout=[137, 16, 8, 64], dimensions=[4, 720, 1080, 91],
                orientation=[1, 0, 0, 0], direct_source=False, packed_mode=6,
                query=[17, count, 2, 37])


def upload(generation, name=None, serial=None):
    return dict(seed=123456789, generation=generation, slot_count=137, encoding='compact8',
                name=name or 'submitted_%d' % generation, serial=generation if serial is None else serial)


def render(state, generation):
    """Fixture bytes and dependent hops are computed without production helpers."""
    wrap = lambda value: ctypes.c_uint32(value).value
    values = []
    for index in range(state['slot_count']):
        value = state['seed'] ^ wrap(generation * 0x9e3779b9) ^ wrap(index * 0x85ebca6b)
        for shift, multiplier in ((16, 0x7feb352d), (15, 0x846ca68b)):
            value = wrap((value ^ (value >> shift)) * multiplier)
        values.append((value ^ (value >> 16)) % 256)
    image = Image.new('RGBA', (720, 1080), (255, 255, 255, 255))
    draw, rows = ImageDraw.Draw(image), math.ceil(state['query'][1] / 64)
    start, count, mode, salt = state['query']
    for local in range(count):
        index = start + local
        if mode:
            index = (131 * index + salt) % len(values)
            if mode == 2:
                index = (index + 257 * values[index] + state['dimensions'][3]) % len(values)
        row, column = divmod(local, 64)
        bounds = (math.ceil(column * 720 / 64 - .5), math.ceil(64 + row * 1000 / rows - .5),
                  math.ceil((column + 1) * 720 / 64 - .5) - 1,
                  math.ceil(64 + (row + 1) * 1000 / rows - .5) - 1)
        draw.rectangle(bounds, fill=(values[index],) * 3 + (255,))
    return image


class AtlasLiveFrameTests(unittest.TestCase):
    def test_old_dependent_generation_recomputes_hops_without_trusting_cpu_identity(self):
        state, history = receipt(), [upload(2), upload(3)]
        image = render(state, 2)
        with patch.object(LIVE, 'verify_image', wraps=VERIFY.verify_image) as verifier:
            result = LIVE.classify_frame(state, image, history)
        self.assertEqual('matched', result['classification'])
        self.assertTrue(result['passed'])
        self.assertTrue(result['full_patch_passed'])
        self.assertEqual([2], [item['generation'] for item in result['matching_candidates']])
        self.assertEqual(1, verifier.call_count)
        self.assertEqual(2, verifier.call_args.args[0]['generation'])
        self.assertEqual(17, result['fingerprint_samples'][0]['query_ordinal'])
        self.assertEqual(113, result['fingerprint_samples'][-1]['query_ordinal'])
        self.assertFalse(result['cpu_receipt_identity_used_as_expected'])
        self.assertFalse(result['every_generation_pixel_verified'])
        self.assertFalse(result['all_render_frames_verified'])

    def test_identical_centers_cannot_hide_corrupt_3x3_edge(self):
        for alpha_error in (False, True):
            with self.subTest(alpha_error=alpha_error):
                state = receipt()
                image = render(state, 2)
                center = LIVE.display_center(0, state['query'][1])
                original_center = image.getpixel(center)
                edge = (center[0] + 1, center[1])
                pixel = image.getpixel(edge)
                image.putpixel(edge, pixel[:3] + (254,) if alpha_error else ((pixel[0] + 1) % 256,) + pixel[1:])
                with patch.object(LIVE, 'verify_image', wraps=VERIFY.verify_image) as verifier:
                    result = LIVE.classify_frame(state, image, [upload(2)])
                self.assertEqual(original_center, image.getpixel(center))
                self.assertTrue(result['candidates'][0]['fingerprint_passed'])
                self.assertEqual(1, verifier.call_count)
                self.assertFalse(result['passed'])
                self.assertFalse(result['full_patch_passed'])
                self.assertEqual('unmatched', result['classification'])

    def test_center_fingerprint_requires_green_blue_and_alpha_too(self):
        for channel in (1, 2, 3):
            with self.subTest(channel=channel):
                state = receipt()
                image = render(state, 2)
                center = LIVE.display_center(0, state['query'][1])
                pixel = list(image.getpixel(center))
                pixel[channel] = (pixel[channel] + 1) % 256
                image.putpixel(center, tuple(pixel))
                with patch.object(LIVE, 'verify_image') as verifier:
                    result = LIVE.classify_frame(state, image, [upload(2)])
                verifier.assert_not_called()
                self.assertFalse(result['candidates'][0]['fingerprint_passed'])
                self.assertFalse(result['passed'])

    def test_same_payload_multiple_actual_resource_candidates_are_listed_but_verified_once(self):
        state = receipt()
        first, second = upload(2, 'bank_a', 10), upload(2, 'bank_b', 11)
        with patch.object(LIVE, 'verify_image', wraps=VERIFY.verify_image) as verifier:
            result = LIVE.classify_frame(state, render(state, 2), [first, second, first])
        self.assertEqual(1, verifier.call_count)
        self.assertEqual('matched', result['classification'])
        self.assertEqual(1, result['matching_payload_count'])
        self.assertEqual(2, result['matching_resource_candidates'])
        self.assertEqual({'bank_a', 'bank_b'}, {item['name'] for item in result['matching_candidates']})
        self.assertEqual([0, 2], result['matching_candidates'][0]['history_indices'])
        self.assertTrue(result['resource_identity_ambiguous'])
        self.assertFalse(result['resource_identity_verified'])

    def test_two_different_payloads_matching_a_tiny_query_are_ambiguous(self):
        state = receipt(count=1)
        state.update(query=[17, 1, 0, 0], packed_mode=4)
        seen = {}
        for generation in range(1, 258):
            _, value = VERIFY.expected_lookup(state['seed'], generation, 137, 17, 0)
            if value in seen:
                generations = (seen[value], generation)
                break
            seen[value] = generation
        state['generation'] = generations[0]  # CPU identity must not break the tie.
        history = [upload(generation) for generation in generations]
        result = LIVE.classify_frame(state, render(state, generations[0]), history)
        self.assertEqual('ambiguous', result['classification'])
        self.assertEqual(2, result['matching_payload_count'])
        self.assertTrue(result['full_patch_passed'])
        self.assertFalse(result['passed'])
        self.assertFalse(result['unique_submitted_payload_match'])
        self.assertEqual(1, result['fingerprint_sample_count'])

    def test_empty_history_or_no_actual_candidate_never_passes(self):
        state, image = receipt(), render(receipt(), 9)
        for history in ([], [upload(2), upload(3)]):
            with self.subTest(history=history), patch.object(LIVE, 'verify_image') as verifier:
                result = LIVE.classify_frame(state, image, history)
                verifier.assert_not_called()
                self.assertEqual('unmatched', result['classification'])
                self.assertFalse(result['passed'])
                self.assertFalse(result['full_patch_passed'])

    def test_small_and_large_fingerprints_are_distributed_unique_query_local_ordinals(self):
        for count in (1, 2, 7, 8, 9, 97, 4096):
            with self.subTest(count=count):
                ordinals = LIVE.fingerprint_ordinals(count)
                self.assertEqual(min(count, 8), len(ordinals))
                self.assertEqual(sorted(set(ordinals)), ordinals)
                self.assertEqual(0, ordinals[0])
                self.assertEqual(count - 1, ordinals[-1])

    def test_invalid_actual_history_is_rejected_instead_of_guessing_payload_metadata(self):
        for key, value in (('seed', True), ('generation', False), ('slot_count', 138),
                           ('encoding', 'other'), ('serial', None), ('name', '')):
            with self.subTest(key=key):
                item = upload(2)
                item[key] = value
                with self.assertRaises(ValueError):
                    LIVE.classify_frame(receipt(), render(receipt(), 2), [item])

    def test_cli_accepts_terminal_updates_history_hashes_sources_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            folder, state = Path(directory), receipt()
            receipt_path, history_path = folder / 'live.state.json', folder / 'end.updates.json'
            capture_path, output = folder / 'live.png', folder / 'classification.json'
            receipt_path.write_text(json.dumps(state), encoding='utf-8')
            history_path.write_text(json.dumps({'schema': 'geometry_atlas_updates_case_v1',
                'submitted_source_history': [upload(2), upload(3)]}), encoding='utf-8')
            render(state, 2).save(capture_path)
            originals = {path: path.read_bytes() for path in (receipt_path, history_path, capture_path)}
            argv = ['--receipt', str(receipt_path), '--capture', str(capture_path),
                    '--history', str(history_path), '--output', str(output)]
            with patch.object(sys, 'stdout', io.StringIO()):
                self.assertEqual(0, LIVE.main(argv))
            result = json.loads(output.read_text())
            self.assertEqual('matched', result['classification'])
            for artifact in result['source_artifacts'].values():
                self.assertEqual(hashlib.sha256(Path(artifact['path']).read_bytes()).hexdigest(), artifact['sha256'])
            saved = output.read_bytes()
            with patch.object(sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit):
                LIVE.main(argv)
            self.assertEqual(saved, output.read_bytes())
            self.assertEqual(originals, {path: path.read_bytes() for path in originals})

    def test_malformed_history_and_wrong_capture_size_save_failed_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            folder, state = Path(directory), receipt()
            receipt_path, history_path, capture_path = folder / 'receipt.json', folder / 'history.json', folder / 'live.png'
            receipt_path.write_text(json.dumps(state), encoding='utf-8')
            history_path.write_bytes(b'{broken raw history')
            render(state, 2).save(capture_path)
            for malformed in (True, False):
                if not malformed:
                    history_path.write_text(json.dumps([upload(2)]), encoding='utf-8')
                    Image.new('RGBA', (720, 1079)).save(capture_path)
                output = folder / ('failed_%r.json' % malformed)
                with patch.object(sys, 'stdout', io.StringIO()):
                    result = LIVE.main(['--receipt', str(receipt_path), '--capture', str(capture_path),
                                        '--history', str(history_path), '--output', str(output)])
                self.assertEqual(1, result)
                report = json.loads(output.read_text())
                self.assertEqual('error', report['classification'])
                self.assertFalse(report['passed'])
                self.assertTrue(report['error'])
                self.assertEqual(hashlib.sha256(history_path.read_bytes()).hexdigest(),
                                 report['source_artifacts']['history']['sha256'])

    def test_missing_capture_still_records_other_source_hashes_and_missing_path(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            receipt_path, history_path = folder / 'receipt.json', folder / 'history.json'
            receipt_path.write_text(json.dumps(receipt()), encoding='utf-8')
            history_path.write_text(json.dumps([upload(2)]), encoding='utf-8')
            output, capture_path = folder / 'failed.json', folder / 'missing.png'
            with patch.object(sys, 'stdout', io.StringIO()):
                self.assertEqual(1, LIVE.main(['--receipt', str(receipt_path), '--capture', str(capture_path),
                                               '--history', str(history_path), '--output', str(output)]))
            report = json.loads(output.read_text())
            self.assertFalse(report['passed'])
            self.assertTrue(report['source_artifacts']['capture']['error'])
            self.assertEqual(str(capture_path.resolve()), report['source_artifacts']['capture']['path'])
            self.assertEqual(hashlib.sha256(history_path.read_bytes()).hexdigest(),
                             report['source_artifacts']['history']['sha256'])


if __name__ == '__main__':
    unittest.main()
