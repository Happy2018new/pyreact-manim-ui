"""Raw-file controls for the update diagnostic replay auditor; no Minecraft."""
import copy
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


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'tools/geometry_packet_probe'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROBE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


with patch.dict(sys.modules), patch.object(sys, 'path', [str(PROBE)] + sys.path):
    sys.modules['verify_capture'] = load('update_recheck_pixel_oracle', 'verify_capture.py')
    sys.modules['recheck_evidence'] = load('update_recheck_wgc', 'recheck_evidence.py')
    sys.modules['run_update_diagnostic'] = load('update_recheck_classifier', 'run_update_diagnostic.py')
    AUDIT = load('update_recheck_test', 'recheck_updates.py')


def write_json(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


def render(receipt, generation):
    seed, count = receipt['seed'], receipt['query'][1]
    image = Image.new('RGBA', (720, 1080), (17, 53, 97, 255))
    draw, rows = ImageDraw.Draw(image), math.ceil(count / 64)
    wrap = lambda value: ctypes.c_uint32(value).value
    for ordinal in range(count):
        index = receipt['query'][0] + ordinal
        value = seed ^ wrap(generation * 0x9e3779b9) ^ wrap(index * 0x85ebca6b)
        for shift, multiplier in ((16, 0x7feb352d), (15, 0x846ca68b)):
            value = wrap((value ^ (value >> shift)) * multiplier)
        level = (value ^ (value >> 16)) % 256
        row, column = divmod(ordinal, 64)
        bounds = (math.ceil(column * 720 / 64 - .5), math.ceil(row * 1080 / rows - .5),
                  math.ceil((column + 1) * 720 / 64 - .5) - 1,
                  math.ceil((row + 1) * 1080 / rows - .5) - 1)
        draw.rectangle(bounds, fill=(level, level, level, 255))
    return image


def provenance(path):
    background = {'background_safe': True, 'window_noactivate': True, 'foreground': {'pid': 42},
                  'windows': [{'pid': 7, 'hwnd': 11, 'noactivate': True, 'minimized': False}]}
    return {'ok': True, 'backend': 'Windows.Graphics.Capture', 'native_resolution': True,
            'width': 720, 'height': 1080, 'background_only': True,
            'request_qpc_100ns': 3, 'frame_qpc_100ns': 4, 'file': str(path), 'pid': 7,
            'window': {'pid': 7, 'hwnd': 11, 'minimized': False},
            'background_before': copy.deepcopy(background), 'background_after': copy.deepcopy(background)}


def fixture(folder, stale=False, legacy=False, split=False):
    name = 'recorded_updates'
    history = [{'generation': generation, 'name': 'geometry_%d' % generation, 'serial': generation,
                'timings': {'combine_ms': 1.}}
               for generation in range(1, 10)]
    benchmark = {'updates': 8, 'error': None, 'success': True, 'name_policy': 'fresh',
                 'max_updates': 8, 'interval_frames': 1, 'initial_generation': 1,
                 'initial_build_serial': 1, 'start': 10., 'until': 18.}
    frozen = {'schema': 'geometry_packet_probe_v1', 'seed': 123456789, 'generation': 9,
              'slot_count': 137, 'geometry_name': 'geometry_9', 'geometry_build_serial': 9,
              'encoding': 'compact8', 'screen_size': [720, 1080], 'query': [0, 137, 64],
              'display_rect_norm': [0, 0, 1, 1], 'query_mode': 0, 'ready': True,
              'benchmark_running': False, 'upload_history': history, 'screen_revision': 0,
              'name_policy': 'fresh', 'max_updates': 8, 'interval_frames': 1,
              'last_run': benchmark}
    write_json(folder / (name + '_frozen.state.json'), frozen)
    controls, events = {}, []
    (folder / 'commands').mkdir()
    for suffix, method, revision in (('same_name_redraw', 'probe.redraw()', 0),
                                     ('recreate', 'probe.recreate_screen()', 1),
                                     ('recreated_redraw', 'probe.redraw()', 1)):
        label = name + '_' + suffix
        state_path = folder / (label + '.state.json')
        command_path = folder / 'commands' / (label + '.py')
        write_json(state_path, dict(frozen, screen_revision=revision))
        command_path.write_text(method + '\n', encoding='utf-8')
        events.append({'label': label, 'action': 'call', 'status': 'completed',
                       'state_file': str(state_path), 'command_file': str(command_path)})
    for control in ('final', 'same_name_redraw', 'recreated_screen'):
        windows, pairs = [], []
        queries = ((0, 64), (64, 73)) if split else ((0, 137),)
        for ordinal, (start, count) in enumerate(queries):
            label = '%s_%s_window_%04d' % (name, control, ordinal)
            paths = {key: folder / (label + suffix) for key, suffix in
                     (('receipt', '.state.json'), ('capture', '.png'),
                      ('verification_file', '.verify.json'), ('classification_file', '.classification.json'))}
            receipt = dict(frozen, query=[start, count, 64],
                           screen_revision=int(control == 'recreated_screen'))
            write_json(paths['receipt'], receipt)
            image = render(receipt, 5 if stale else 9)
            image.save(paths['capture'])
            write_json(folder / (label + '.json'), provenance(paths['capture']))
            diagnostic = AUDIT.classify_observed(receipt, image, history)
            report = diagnostic.pop('final_verification')
            pairs.append((receipt, report))
            report.update(receipt_sha256=hashlib.sha256(paths['receipt'].read_bytes()).hexdigest(),
                          capture_sha256=hashlib.sha256(paths['capture'].read_bytes()).hexdigest())
            if legacy:
                diagnostic.pop('final_query_has_payload_variation', None)
                for entry in diagnostic['matched_candidates'] + diagnostic['candidates']:
                    entry.pop('seed', None)
                    entry.pop('informative_query', None)
            write_json(paths['verification_file'], report)
            write_json(paths['classification_file'], diagnostic)
            windows.append(dict(AUDIT.compact_report(report), classification=diagnostic['classification'],
                                matched_generations=diagnostic['matched_generations'],
                                matched_candidates=diagnostic['matched_candidates'],
                                **{key: str(path) for key, path in paths.items()}))
        controls[control] = {'stage': control, 'status': 'failed' if stale else 'passed',
                             'passed': not stale, 'full_slot_coverage': True, 'windows': windows,
                             'verification': AUDIT.compact_report(AUDIT.verify_reports(pairs))}
    case = {'name': name, 'status': 'failed' if stale else 'completed', 'passed': not stale,
            'stage': 'completed', 'errors': [{'stage': 'final', 'error': 'Pixel mismatch'}] if stale else [],
            'payload_bytes': 137, 'encoding': 'compact8', 'name_policy': 'fresh',
            'max_updates': 8, 'interval_frames': 1, 'seconds': 8.,
            'benchmark': frozen['last_run'], 'final_snapshot': frozen, 'last_snapshot': frozen,
            'controls': controls, 'events': events, 'full_requested': True, 'recreate_requested': True,
            'whole_payload_simultaneously_resident': not stale,
            'same_name_redraw_recovers': False, 'recreated_screen_recovers': False,
            'gpu_to_python_readback': False, 'all_render_frames_verified': False,
            'actual_mobile_hardware': False}
    path = folder / (name + '.update.json')
    write_json(path, case)
    return path, case


class GeometryUpdateRecheckTests(unittest.TestCase):
    def test_current_and_legacy_stale_evidence_audit_separately_from_payload(self):
        for stale in (False, True):
            with self.subTest(stale=stale), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                path, _ = fixture(folder, stale=stale, legacy=True)
                before = {item.relative_to(folder).as_posix(): item.read_bytes()
                          for item in folder.rglob('*') if item.is_file()}
                row = AUDIT.recheck_case(path, folder)
                self.assertTrue(row['audit_passed'], row)
                self.assertEqual(not stale, row['final_payload_passed'])
                self.assertEqual(stale, row['expected_payload_failure_preserved'])
                self.assertEqual(before, {item.relative_to(folder).as_posix(): item.read_bytes()
                                          for item in folder.rglob('*') if item.is_file()})
                self.assertEqual(len(before), len(row['artifact_sha256']))
                self.assertTrue(all(control['audit_passed'] for control in row['controls'].values()))
                if stale:
                    self.assertEqual([5], row['controls']['final']['windows'][0]['matched_generations'])
                    self.assertEqual(123456789, row['controls']['final']['windows'][0]['matched_candidates'][0]['seed'])

    def test_tampered_saved_verifier_or_classifier_is_rejected(self):
        for suffix, field, value in (('.verify.json', 'checked_pixels', 1),
                                      ('.classification.json', 'matched_generations', [7])):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                path, _ = fixture(folder, stale=True)
                artifact = folder / ('recorded_updates_final_window_0000' + suffix)
                data = json.loads(artifact.read_text())
                data[field] = value
                write_json(artifact, data)
                row = AUDIT.recheck_case(path, folder)
                self.assertFalse(row['audit_passed'])
                self.assertIn(field, str(row['controls']['final']['windows'][0]['errors']))

    def test_full_coverage_missing_failed_window_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path, case = fixture(folder, stale=True, split=True)
            case['controls']['final']['windows'].pop()
            write_json(path, case)
            row = AUDIT.recheck_case(path, folder)
            self.assertFalse(row['audit_passed'])
            self.assertIn('missing', str(row['controls']['final']['errors']))

    def test_changed_frozen_upload_history_and_background_activation_are_rejected(self):
        for mutation in ('history', 'provenance'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                path, _ = fixture(folder)
                suffix = '.state.json' if mutation == 'history' else '.json'
                artifact = folder / ('recorded_updates_same_name_redraw_window_0000' + suffix)
                data = json.loads(artifact.read_text())
                if mutation == 'history':
                    data['upload_history'][0]['generation'] = 2
                else:
                    data['background_after']['window_noactivate'] = False
                write_json(artifact, data)
                row = AUDIT.recheck_case(path, folder)
                self.assertFalse(row['audit_passed'])
                self.assertFalse(row['controls']['same_name_redraw']['audit_passed'])

    def test_declared_source_path_outside_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as other:
            folder = Path(directory)
            path, case = fixture(folder)
            outside = Path(other) / 'outside.png'
            outside.write_bytes(b'do not open')
            case['controls']['final']['windows'][0]['capture'] = str(outside)
            write_json(path, case)
            row = AUDIT.recheck_case(path, folder)
            self.assertFalse(row['audit_passed'])
            self.assertIn('escapes', str(row['controls']['final']['windows'][0]['errors']))
            self.assertNotIn('outside.png', row['artifact_sha256'])

    def test_policy_control_file_reuse_and_recreation_revision_are_rejected(self):
        for mutation in ('policy', 'reuse', 'revision'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                path, case = fixture(folder)
                if mutation == 'policy':
                    case['name_policy'] = 'single'
                    write_json(path, case)
                elif mutation == 'reuse':
                    case['controls']['same_name_redraw']['windows'] = case['controls']['final']['windows']
                    write_json(path, case)
                else:
                    operation = folder / 'recorded_updates_recreated_redraw.state.json'
                    state = json.loads(operation.read_text())
                    state['screen_revision'] = 0
                    write_json(operation, state)
                row = AUDIT.recheck_case(path, folder)
                self.assertFalse(row['audit_passed'])
                self.assertTrue(row['errors'])

    def test_cli_preserves_payload_failure_and_refuses_existing_source_output(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path, _ = fixture(folder, stale=True)
            before = path.read_bytes()
            with patch.object(sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit) as stopped:
                AUDIT.main(['--evidence', str(folder), '--output', str(path)])
            self.assertEqual(2, stopped.exception.code)
            self.assertEqual(before, path.read_bytes())
            raw_receipt = folder / 'recorded_updates_final_window_0000.state.json'
            with patch.object(sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit):
                AUDIT.main(['--evidence', str(folder), '--output', str(raw_receipt)])
            output = folder / 'replayed.json'
            self.assertEqual(0, AUDIT.main(['--evidence', str(folder), '--output', str(output)]))
            report = json.loads(output.read_text())
            self.assertTrue(report['audit_passed'])
            self.assertFalse(report['final_payload_passed'])
            self.assertEqual(1, report['expected_payload_failures'])


if __name__ == '__main__':
    unittest.main()
