"""Raw-file regression controls for the geometry-atlas evidence replay audit."""
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
PROBE = ROOT / 'tools/geometry_atlas_probe'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROBE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = load('atlas_recheck_independent_pixels', 'verify_capture.py')
with patch.dict(sys.modules, {'verify_capture': VERIFY}):
    AUDIT = load('atlas_recheck_raw_files', 'recheck_evidence.py')


def save(path, data):
    path.write_text(json.dumps(data), encoding='utf-8')


def render(receipt, generation=None, hidden=False):
    image = Image.new('RGBA', (720, 1080), (255, 255, 255, 255))
    if hidden:
        return image
    generation = receipt['generation'] if generation is None else generation
    wrap = lambda value: ctypes.c_uint32(value).value
    values = []
    for index in range(receipt['slot_count']):
        value = receipt['seed'] ^ wrap(generation * 0x9e3779b9) ^ wrap(index * 0x85ebca6b)
        for shift, multiplier in ((16, 0x7feb352d), (15, 0x846ca68b)):
            value = wrap((value ^ (value >> shift)) * multiplier)
        values.append((value ^ (value >> 16)) % 256)
    start, count, mode, salt = receipt['query']
    draw, rows = ImageDraw.Draw(image), math.ceil(count / 64)
    for ordinal in range(count):
        index = start + ordinal
        if mode:
            index = (131 * index + salt) % receipt['slot_count']
            if mode == 2:
                index = (index + 257 * values[index] + receipt['dimensions'][3]) % receipt['slot_count']
        row, column = divmod(ordinal, 64)
        bounds = (math.ceil(column * 720 / 64 - .5), math.ceil(64 + row * 1000 / rows - .5),
                  math.ceil((column + 1) * 720 / 64 - .5) - 1,
                  math.ceil(64 + (row + 1) * 1000 / rows - .5) - 1)
        draw.rectangle(bounds, fill=(values[index],) * 3 + (255,))
    return image


def native_provenance(capture):
    background = {'background_safe': True, 'window_noactivate': True, 'foreground': {'pid': 9},
                  'windows': [{'pid': 7, 'hwnd': 11, 'minimized': False, 'noactivate': True}]}
    return {'ok': True, 'backend': 'Windows.Graphics.Capture', 'native_resolution': True,
            'width': 720, 'height': 1080, 'background_only': True,
            'request_qpc_100ns': 3, 'frame_qpc_100ns': 4, 'file': str(capture), 'pid': 7,
            'window': {'pid': 7, 'hwnd': 11, 'minimized': False},
            'background_before': background, 'background_after': copy.deepcopy(background)}


def fixture(folder, mismatch=False, split=False, modern=False):
    name, slots = 'atlas_evidence', 137
    history = [{'seed': 123456789, 'generation': 1, 'slot_count': slots, 'encoding': 'compact8',
                'name': 'geometry_1', 'serial': 1}]
    frozen = {'schema': 'geometry_atlas_probe_v1', 'seed': 123456789, 'generation': 1,
              'slot_count': slots, 'geometry_name': 'geometry_1', 'geometry_build_serial': 1,
              'encoding': 'compact8', 'ready': True, 'pipeline_ready': True, 'connection': True,
              'screen_size': [720, 1080], 'display_rect_norm': [0, 64. / 1080., 1, 1000. / 1080.],
              'layout': [slots, 16, 8, 64], 'dimensions': [4, 720, 1080, 0],
              'center': [.5, .5, .5], 'orientation': [1, 0, 0, 0], 'direct_source': False,
              'packed_mode': 4, 'query': [0, slots, 0, 0], 'writer_visible': True,
              'upload_history': history}
    if modern:
        frozen.update(update_policy='double', active_bank=0, publish_delay_ms=250.)
        if modern is True:
            frozen.update(pending_upload=None, updates_running=False)
    next_state = copy.deepcopy(frozen)
    next_state.update(generation=2, geometry_name='geometry_2', geometry_build_serial=2)
    if modern:
        next_state['active_bank'] = 1
    next_state['upload_history'].append(dict(history[0], generation=2, name='geometry_2', serial=2))
    save(folder / (name + '_frozen.state.json'), frozen)
    save(folder / (name + '_generation2_frozen.state.json'), next_state)
    commands = folder / 'commands'
    commands.mkdir()
    events, controls = [], {}
    for suffix, visible in (('hide_writer', False), ('restore_writer', True)):
        label = name + '_' + suffix
        state, command = folder / (label + '.state.json'), commands / (label + '.py')
        save(state, dict(frozen, writer_visible=visible))
        command.write_text('probe.set_writer_visible(%r)\n' % visible, encoding='utf-8')
        events.append({'label': label, 'action': 'call', 'status': 'completed',
                       'state_file': str(state), 'command_file': str(command)})
    for control in ('identity', 'permutation', 'dependent', 'hidden_writer', 'new_generation_identity'):
        is_hidden, is_next = control == 'hidden_writer', control == 'new_generation_identity'
        mode, salt, salt2 = (0, 0, 0) if is_hidden else AUDIT.SERIES[control]
        windows, pairs, old_pairs = [], [], []
        starts = ((0, slots),) if not split or is_hidden else ((0, 64), (64, 73))
        for ordinal, (start, count) in enumerate(starts):
            suffix = control if is_hidden else '%s_window_%04d' % (control, ordinal)
            label = name + '_' + suffix
            state = copy.deepcopy(next_state if is_next else frozen)
            state.update(query=[start, count, mode, salt], dimensions=[4, 720, 1080, salt2],
                         packed_mode=mode + 4, writer_visible=not is_hidden)
            paths = {'receipt': folder / (label + '.state.json'), 'capture': folder / (label + '.png'),
                     'verification_file': folder / (label + '.verify.json')}
            save(paths['receipt'], state)
            # Existing failed source frames may still be replay-consistent.
            image = render(state, generation=99 if mismatch and not is_hidden else None, hidden=is_hidden)
            image.save(paths['capture'])
            save(paths['capture'].with_suffix('.json'), native_provenance(paths['capture']))
            report = VERIFY.verify_image(state, image)
            pairs.append((state, report))
            report.update(receipt_sha256=hashlib.sha256(paths['receipt'].read_bytes()).hexdigest(),
                          capture_sha256=hashlib.sha256(paths['capture'].read_bytes()).hexdigest())
            save(paths['verification_file'], report)
            summary = dict(VERIFY.compact_report(report), **{key: str(path) for key, path in paths.items()})
            if is_next:
                old = dict(state)
                old.update({key: frozen[key] for key in VERIFY.IDENTITY_FIELDS})
                old_path, old_verify = folder / (label + '.previous-generation.state.json'), folder / (label + '.previous-generation.verify.json')
                save(old_path, old)
                old_report = VERIFY.verify_image(old, image)
                old_pairs.append((old, old_report))
                old_report.update(receipt_kind='previous_generation_oracle_control',
                                  receipt_sha256=hashlib.sha256(old_path.read_bytes()).hexdigest(),
                                  capture_sha256=report['capture_sha256'])
                save(old_verify, old_report)
                summary['previous_generation_control'] = dict(VERIFY.compact_report(old_report),
                    receipt=str(old_path), verification_file=str(old_verify), rejected=not old_report['passed'])
            windows.append(summary)
            events += [{'label': label, 'action': 'call', 'status': 'completed', 'state_file': str(paths['receipt'])},
                       {'label': label, 'action': 'capture', 'status': 'completed', 'capture_file': str(paths['capture'])}]
        if is_hidden:
            passed = not pairs[0][1]['passed']
            controls[control] = {'passed': passed, 'status': 'passed' if passed else 'failed',
                                 'expected_payload_match': False, 'windows': windows}
        else:
            series = VERIFY.verify_reports(pairs)
            passed = series['passed']
            entry = {'mode': mode, 'salt': salt, 'salt2': salt2, 'windows': windows,
                     'verification': VERIFY.compact_report(series)}
            if is_next:
                entry['previous_generation_rejected'] = not VERIFY.verify_reports(old_pairs)['passed']
                passed = passed and entry['previous_generation_rejected']
            entry.update(passed=passed, status='passed' if passed else 'failed')
            controls[control] = entry
    passed = all(control['passed'] for control in controls.values())
    case = {'schema': 'geometry_atlas_case_v1', 'name': name, 'status': 'completed' if passed else 'failed',
            'passed': passed, 'stage': 'completed', 'errors': [] if passed else [{'stage': 'identity', 'error': 'Pixel mismatch'}],
            'payload_bytes': slots, 'seed': 123456789, 'channel': 'alpha', 'direct_source': False,
            'flip_y': True, 'controls': controls, 'events': events,
            'final_snapshot': next_state, 'last_snapshot': next_state,
            'alpha_transport_verified': passed, 'shared_copy_texture_verified': passed,
            'gpu_to_python_readback': False, 'all_render_frames_verified': False, 'actual_mobile_hardware': False}
    path = folder / (name + '.atlas.json')
    save(path, case)
    return path, case


class GeometryAtlasRecheckTests(unittest.TestCase):
    def test_success_and_failed_payloads_replay_without_changing_sources(self):
        for mismatch, modern in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(mismatch=mismatch, modern=modern), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                path, _ = fixture(folder, mismatch=mismatch, modern=modern)
                before = {item.relative_to(folder).as_posix(): item.read_bytes() for item in folder.rglob('*') if item.is_file()}
                row = AUDIT.recheck_case(path, folder)
                self.assertTrue(row['audit_passed'], row)
                self.assertEqual(not mismatch, row['case_passed'])
                self.assertEqual(not mismatch, row['final_payload_passed'])
                self.assertEqual(mismatch, row['source_failure_preserved'])
                self.assertFalse(row['vertex_random_access_verified'])
                self.assertEqual(before, {item.relative_to(folder).as_posix(): item.read_bytes() for item in folder.rglob('*') if item.is_file()})
                self.assertEqual(len(before), len(row['artifact_sha256']))

    def test_pending_uploads_and_changed_bank_controls_are_rejected(self):
        for key, value in (('pending_upload', {'generation': 3}), ('updates_running', True),
                           ('active_bank', 1), ('update_policy', 'fresh'), ('publish_delay_ms', 500.),
                           ('updates_running', None)):
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                path, _ = fixture(folder, modern=True)
                artifact = folder / 'atlas_evidence_identity_window_0000.state.json'
                receipt = json.loads(artifact.read_text())
                if value is None:
                    del receipt[key]
                else:
                    receipt[key] = value
                save(artifact, receipt)
                self.assertFalse(AUDIT.recheck_case(path, folder)['audit_passed'])

    def test_partial_modern_controls_are_rejected_even_if_consistently_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path, _ = fixture(folder, modern='partial')
            row = AUDIT.recheck_case(path, folder)
            self.assertFalse(row['audit_passed'])
            self.assertTrue(any('incomplete update controls' in error for error in row['errors']))

    def test_frozen_bank_and_delay_must_describe_a_published_dataset(self):
        baseline = {'schema': 'geometry_atlas_probe_v1', 'seed': 1, 'generation': 1,
                    'slot_count': 137, 'geometry_name': 'geometry', 'geometry_build_serial': 1,
                    'encoding': 'compact8', 'ready': True, 'pipeline_ready': True,
                    'connection': True, 'writer_visible': True, 'update_policy': 'double',
                    'active_bank': 0, 'publish_delay_ms': 250., 'pending_upload': None,
                    'updates_running': False}
        for policy, bank in (('double', 0), ('double', 1), ('fresh', -1)):
            state = dict(baseline, update_policy=policy, active_bank=bank)
            AUDIT.frozen_state(state, state, 'valid')
        for controls in ({'active_bank': 3}, {'active_bank': -1}, {'active_bank': True},
                         {'update_policy': 'fresh'}, {'update_policy': 'unknown'},
                         {'publish_delay_ms': -1}, {'publish_delay_ms': 5001},
                         {'publish_delay_ms': float('nan')}, {'publish_delay_ms': float('inf')},
                         {'publish_delay_ms': True}):
            state = dict(baseline, **controls)
            with self.subTest(controls=controls), self.assertRaises(ValueError):
                AUDIT.frozen_state(state, state, 'invalid')

    def test_tampered_gather_mode_or_summary_counts_are_rejected(self):
        for mutation in ('mode', 'count', 'old_generation'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                path, case = fixture(folder)
                if mutation == 'mode':
                    case['controls']['dependent']['mode'] = 0
                    save(path, case)
                elif mutation == 'count':
                    artifact = folder / 'atlas_evidence_identity_window_0000.verify.json'
                    report = json.loads(artifact.read_text())
                    report['checked_channels'] = 1
                    save(artifact, report)
                else:
                    artifact = folder / 'atlas_evidence_new_generation_identity_window_0000.previous-generation.state.json'
                    receipt = json.loads(artifact.read_text())
                    receipt['generation'] = 2
                    save(artifact, receipt)
                self.assertFalse(AUDIT.recheck_case(path, folder)['audit_passed'])

    def test_hidden_writer_visible_and_native_activation_are_rejected(self):
        for mutation in ('writer', 'activation', 'history'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                path, _ = fixture(folder)
                suffix = '.json' if mutation == 'activation' else '.state.json'
                artifact = folder / ('atlas_evidence_hidden_writer' + suffix)
                receipt = json.loads(artifact.read_text())
                if mutation == 'writer':
                    receipt['writer_visible'] = True
                elif mutation == 'activation':
                    receipt['background_after']['window_noactivate'] = False
                else:
                    receipt['upload_history'][0]['generation'] = 7
                save(artifact, receipt)
                self.assertFalse(AUDIT.recheck_case(path, folder)['audit_passed'])

    def test_outside_paths_file_reuse_and_missing_coverage_are_rejected(self):
        for mutation in ('outside', 'reuse', 'coverage'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                path, case = fixture(folder)
                if mutation == 'outside':
                    case['controls']['identity']['windows'][0]['capture'] = str(folder.parent / 'outside.png')
                elif mutation == 'reuse':
                    case['controls']['dependent']['windows'] = case['controls']['identity']['windows']
                else:
                    case['controls']['identity']['windows'] = []
                save(path, case)
                self.assertFalse(AUDIT.recheck_case(path, folder)['audit_passed'])

    def test_operational_failure_without_pixels_is_preserved_as_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            name = 'failed_open'
            log = folder / (name + '_open.call.log')
            log.write_text('owned host timed out', encoding='utf-8')
            case = {'schema': 'geometry_atlas_case_v1', 'name': name, 'status': 'failed', 'passed': False,
                    'stage': 'open', 'errors': [{'stage': 'open', 'error': 'TimeoutError: timed out'}],
                    'payload_bytes': 256, 'seed': 54321, 'channel': 'alpha', 'direct_source': False, 'flip_y': True,
                    'controls': {}, 'events': [{'label': name + '_open', 'action': 'call', 'status': 'failed', 'log': str(log)}],
                    'final_snapshot': None, 'last_snapshot': {}, 'alpha_transport_verified': False,
                    'shared_copy_texture_verified': False, 'gpu_to_python_readback': False,
                    'all_render_frames_verified': False, 'actual_mobile_hardware': False}
            path = folder / (name + '.atlas.json')
            for slots in (256, 131072, 262144, 524288):
                with self.subTest(slots=slots):
                    case['payload_bytes'] = slots
                    save(path, case)
                    row = AUDIT.recheck_case(path, folder)
                    self.assertTrue(row['audit_passed'], row)
                    self.assertTrue(row['partial_source_failure'])
                    self.assertIsNone(row['final_payload_passed'])
                    self.assertTrue(row['source_failure_preserved'])
            case['payload_bytes'] = 524289
            save(path, case)
            self.assertFalse(AUDIT.recheck_case(path, folder)['audit_passed'])

    def test_cli_requires_new_output_and_retains_expected_failure_status(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path, _ = fixture(folder, mismatch=True)
            before = path.read_bytes()
            with patch.object(sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit):
                AUDIT.main(['--evidence', str(folder), '--output', str(path)])
            self.assertEqual(before, path.read_bytes())
            output = folder / 'audit.json'
            self.assertEqual(0, AUDIT.main(['--evidence', str(folder), '--output', str(output)]))
            report = json.loads(output.read_text())
            self.assertTrue(report['audit_passed'])
            self.assertFalse(report['final_payload_passed'])
            self.assertEqual(1, report['preserved_source_failures'])

    def test_malformed_controls_are_rejected_without_crashing_the_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path, case = fixture(folder)
            case['controls']['hidden_writer'] = []
            save(path, case)
            row = AUDIT.recheck_case(path, folder)
            self.assertFalse(row['audit_passed'])
            self.assertTrue(row['controls']['hidden_writer']['errors'])

    def test_failed_host_json_remains_raw_operational_failure_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path, case = fixture(folder)
            # Preserve a failed call with malformed JSON, and one missing its
            # output file. Neither is a successful snapshot used for pixels.
            malformed = folder / 'failed_call.state.json'
            malformed.write_text('{broken', encoding='utf-8')
            missing = folder / 'never_created.state.json'
            case.update(passed=False, status='failed', stage='open', controls={},
                        errors=[{'stage': 'open', 'error': 'ValueError: malformed JSON'}],
                        alpha_transport_verified=False, shared_copy_texture_verified=False)
            case['events'] = [{'label': 'failed_call', 'action': 'call', 'status': 'failed',
                               'state_file': str(malformed), 'error': 'ValueError: malformed JSON'},
                              {'label': 'missing_call', 'action': 'call', 'status': 'failed',
                               'state_file': str(missing), 'error': 'FileNotFoundError'}]
            # Remove successful frozen receipts so this represents a failure
            # before any frozen or capture evidence existed.
            (folder / 'atlas_evidence_frozen.state.json').unlink()
            (folder / 'atlas_evidence_generation2_frozen.state.json').unlink()
            case['final_snapshot'], case['last_snapshot'] = None, {}
            save(path, case)
            row = AUDIT.recheck_case(path, folder)
            self.assertTrue(row['audit_passed'], row)
            self.assertIn('failed_call.state.json', row['artifact_sha256'])
            self.assertEqual([{'label': 'missing_call', 'kind': 'state_file',
                               'path': 'never_created.state.json'}], row['missing_failed_event_artifacts'])

    def test_failed_terminal_readiness_is_preserved_without_a_payload_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path, case = fixture(folder)
            frozen_path = folder / 'atlas_evidence_frozen.state.json'
            terminal = json.loads(frozen_path.read_text())
            terminal['pipeline_ready'] = False
            save(frozen_path, terminal)
            (folder / 'atlas_evidence_generation2_frozen.state.json').unlink()
            case.update(passed=False, status='failed', stage='pipeline', controls={}, events=[],
                        errors=[{'stage': 'pipeline', 'error': 'ValueError: pipeline not ready'}],
                        final_snapshot=terminal, last_snapshot=terminal,
                        alpha_transport_verified=False, shared_copy_texture_verified=False)
            save(path, case)
            row = AUDIT.recheck_case(path, folder)
            self.assertTrue(row['audit_passed'], row)
            self.assertTrue(row['source_failure_preserved'])
            self.assertIsNone(row['final_payload_passed'])


if __name__ == '__main__':
    unittest.main()
