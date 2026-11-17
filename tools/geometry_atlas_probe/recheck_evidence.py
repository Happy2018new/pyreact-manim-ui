"""Replay raw geometry-atlas gathers and preserve consistent source failures.

The audit checks saved native WGC frames and independently regenerated integer
oracles. It establishes fragment-consumer texture indexing only, never vertex
random access, GPU readback into game Python, or verification of every frame.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re

from PIL import Image

from verify_capture import IDENTITY_FIELDS, compact_report, verify_image, verify_reports


HERE = Path(__file__).resolve().parent
ERRORS = (OSError, ValueError, KeyError, TypeError, OverflowError)
SERIES = {'identity': (0, 0, 0), 'permutation': (1, 17, 0),
          'dependent': (2, 97, 53), 'new_generation_identity': (0, 0, 0)}
REQUIRED = set(SERIES) | {'hidden_writer'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Evidence:
    def __init__(self, root):
        self.root = root.resolve()
        self.hashes = {}

    def path(self, value, base=None):
        require(isinstance(value, (str, Path)) and bool(str(value)), 'Evidence path must be nonempty')
        path = Path(value)
        path = (path if path.is_absolute() else (base or self.root) / path).resolve()
        require(path.is_relative_to(self.root), 'Evidence path escapes its directory: ' + str(path))
        return path

    def read(self, value):
        path = self.path(value)
        raw = path.read_bytes()
        key = path.relative_to(self.root).as_posix()
        digest = hashlib.sha256(raw).hexdigest()
        require(key not in self.hashes or self.hashes[key] == digest, 'Evidence changed during replay: ' + key)
        self.hashes[key] = digest
        return raw

    def json(self, value):
        data = json.loads(self.read(value).decode('utf-8-sig'))
        require(isinstance(data, dict), 'JSON evidence must be an object: ' + str(value))
        return data

    def digest(self, path):
        return self.hashes[self.path(path).relative_to(self.root).as_posix()]

    def unchanged(self):
        for key in list(self.hashes):
            self.read(self.root / key)


def compare(recorded, actual, keys, label):
    require(isinstance(recorded, dict), label + ' must be an object')
    for key in keys:
        require(key in recorded and recorded[key] == actual[key], label + ' mismatch: ' + key)


def frozen_state(state, frozen, label, visible=True):
    require(isinstance(state, dict) and isinstance(frozen, dict), label + ' lacks a frozen state')
    require(all(state.get(key) == frozen.get(key) for key in IDENTITY_FIELDS), label + ' changed uploaded geometry')
    require(state.get('ready') is True and state.get('pipeline_ready') is True and
            state.get('connection') is True, label + ' lacks a ready explicit texture connection')
    require(state.get('writer_visible') is visible, label + ' writer visibility is inconsistent')
    for key in ('layout', 'upload_history', 'center'):
        require(state.get(key) == frozen.get(key), label + ' changed frozen ' + key)
    require(state.get('dimensions', [])[:3] == frozen.get('dimensions', [])[:3],
            label + ' changed physical source dimensions')


def provenance(files, capture):
    path = capture.with_suffix('.json')
    data = files.json(path)
    for key, value in {'ok': True, 'backend': 'Windows.Graphics.Capture', 'native_resolution': True,
                       'width': 720, 'height': 1080, 'background_only': True}.items():
        require(data.get(key) == value and (not isinstance(value, bool) or data[key] is value),
                'Capture lacks native background WGC provenance: ' + key)
    requested, rendered = data.get('request_qpc_100ns'), data.get('frame_qpc_100ns')
    require(type(requested) is int and type(rendered) is int and 0 <= requested <= rendered,
            'WGC frame predates its request')
    require(files.path(data.get('file')) == capture, 'WGC provenance names a different PNG')
    window = data.get('window')
    require(isinstance(window, dict) and window.get('minimized') is False and
            type(window.get('pid')) is int and window['pid'] > 0 and
            type(window.get('hwnd')) is int and window['hwnd'] > 0 and
            data.get('pid') == window['pid'], 'Capture window identity is invalid')
    for phase in ('background_before', 'background_after'):
        background = data.get(phase)
        require(isinstance(background, dict) and background.get('background_safe') is True and
                background.get('window_noactivate') is True and isinstance(background.get('foreground'), dict) and
                background['foreground'].get('pid') != window['pid'], 'Capture activated the game: ' + phase)
        entries = background.get('windows')
        require(isinstance(entries, list) and all(isinstance(entry, dict) for entry in entries),
                'Background window list is malformed')
        matches = [entry for entry in entries if entry.get('pid') == window['pid'] and entry.get('hwnd') == window['hwnd']]
        require(len(matches) == 1 and matches[0].get('noactivate') is True and
                matches[0].get('minimized') is False, 'Background window identity is inconsistent')
    return window['pid'], window['hwnd']


def query_state(state, case, start, count, mode, salt, salt2):
    channel = int(case['channel'] == 'red')
    expected = {'query': [start, count, mode, salt],
                'orientation': [int(case['flip_y']), channel, 0, 0], 'direct_source': case['direct_source'],
                'packed_mode': mode + 4 * int(case['flip_y']) + 8 * channel + 16 * int(case['direct_source'])}
    compare(state, expected, expected.keys(), 'Raw query controls')
    require(len(state.get('dimensions', [])) == 4 and state['dimensions'][3] == salt2,
            'Raw query salt2 differs from the requested gather')


def event_match(events, files, folder, label, action, paths):
    matches = [event for event in events if event.get('label') == label and event.get('action') == action]
    require(len(matches) == 1 and matches[0].get('status') == 'completed',
            'Missing successful host event: ' + label + ':' + action)
    for key, expected in paths.items():
        require(files.path(matches[0].get(key), folder) == expected, 'Host event path mismatch: ' + label + ':' + key)


def replay_window(saved, case, frozen, previous, files, folder, label, settings, events, hidden=False):
    row = {'audit_passed': False, 'payload_match': None, 'errors': []}
    pair, old_pair = None, None
    try:
        require(isinstance(saved, dict), 'Window summary must be an object')
        expected_paths = {'receipt': folder / (label + '.state.json'), 'capture': folder / (label + '.png'),
                          'verification_file': folder / (label + '.verify.json')}
        paths = {key: files.path(saved.get(key), folder) for key in expected_paths}
        require(paths == expected_paths, 'Window artifacts do not belong to their declared control')
        # Hash every raw dependency before checking recorded claims.
        state = files.json(paths['receipt'])
        raw_capture = files.read(paths['capture'])
        recorded = files.json(paths['verification_file'])
        row['window_identity'] = list(provenance(files, paths['capture']))
        row.update(receipt=paths['receipt'].relative_to(files.root).as_posix(),
                   capture=paths['capture'].relative_to(files.root).as_posix())
        frozen_state(state, frozen, label, visible=not hidden)
        query_state(state, case, *settings)
        event_match(events, files, folder, label, 'call', {'state_file': paths['receipt']})
        event_match(events, files, folder, label, 'capture', {'capture_file': paths['capture']})
        with Image.open(io.BytesIO(raw_capture)) as source:
            image = source.convert('RGBA')
        report = verify_image(state, image)
        pair = state, report
        row.update(payload_match=report['passed'], verification=compact_report(report))
        compare(recorded, report, report.keys(), label + '.verify')
        hashes = {'receipt_sha256': files.digest(paths['receipt']), 'capture_sha256': files.digest(paths['capture'])}
        compare(recorded, hashes, hashes.keys(), label + '.verify')
        compare(saved, compact_report(report), compact_report(report).keys(), label + '.summary')
        compare(saved, hashes, hashes.keys(), label + '.summary')
        if previous is not None:
            old_saved = saved.get('previous_generation_control')
            require(isinstance(old_saved, dict), 'New-generation window lacks its old-oracle control')
            old_path = folder / (label + '.previous-generation.state.json')
            old_verify = folder / (label + '.previous-generation.verify.json')
            require(files.path(old_saved.get('receipt'), folder) == old_path and
                    files.path(old_saved.get('verification_file'), folder) == old_verify,
                    'Previous-generation control paths do not match the current PNG')
            old_state, old_recorded = files.json(old_path), files.json(old_verify)
            expected_old = dict(state)
            expected_old.update({key: previous[key] for key in IDENTITY_FIELDS})
            require(old_state == expected_old, 'Synthetic old-oracle receipt changes more than uploaded identity')
            old_report = verify_image(expected_old, image)
            old_pair = expected_old, old_report
            compare(old_recorded, old_report, old_report.keys(), label + '.old.verify')
            old_hashes = {'receipt_sha256': files.digest(old_path), 'capture_sha256': hashes['capture_sha256']}
            compare(old_recorded, old_hashes, old_hashes.keys(), label + '.old.verify')
            require(old_recorded.get('receipt_kind') == 'previous_generation_oracle_control',
                    'Old-oracle receipt is not identified as a synthetic control')
            compare(old_saved, compact_report(old_report), compact_report(old_report).keys(), label + '.old.summary')
            compare(old_saved, old_hashes, old_hashes.keys(), label + '.old.summary')
            require(old_saved.get('rejected') is (not old_report['passed']), 'Old-generation rejection flag differs from exact pixels')
            row['previous_generation_match'] = old_report['passed']
        row['audit_passed'] = True
    except ERRORS as error:
        row['errors'].append('%s: %s' % (type(error).__name__, error))
    return row, pair, old_pair


def recheck_case(case_path, evidence):
    files = Evidence(evidence)
    row = {'audit_passed': False, 'case_passed': False, 'final_payload_passed': None,
           'initial_payload_passed': None, 'controls': {}, 'errors': [], 'partial_source_failure': False,
           'missing_failed_event_artifacts': []}
    try:
        case_path = files.path(case_path)
        row['case'] = case_path.relative_to(files.root).as_posix()
        case, folder = files.json(case_path), case_path.parent
        name = case.get('name')
        require(case.get('schema') == 'geometry_atlas_case_v1' and isinstance(name, str) and
                re.fullmatch('[a-z0-9_]{1,64}', name) is not None and case_path.name == name + '.atlas.json',
                'Case schema/name does not match its safe filename')
        row.update(name=name, source_status=case.get('status'), source_passed=case.get('passed'),
                   payload_bytes=case.get('payload_bytes'), channel=case.get('channel'),
                   direct_source=case.get('direct_source'), flip_y=case.get('flip_y'), source_errors=case.get('errors'))
        require(isinstance(case.get('passed'), bool) and case.get('status') ==
                ('completed' if case['passed'] else 'failed'), 'Source status and passed flag disagree')
        require(isinstance(case.get('errors'), list) and (not case['passed'] or not case['errors']),
                'Source errors disagree with its passing claim')
        require(case['passed'] or bool(case['errors']), 'Failed source case must preserve its error')
        require(type(case.get('payload_bytes')) is int and 2 <= case['payload_bytes'] <= 65536 and
                type(case.get('seed')) is int and 0 <= case['seed'] <= 0xffffffff and
                case.get('channel') in ('alpha', 'red') and type(case.get('flip_y')) is bool and
                type(case.get('direct_source')) is bool, 'Case controls are malformed')
        for flag in ('gpu_to_python_readback', 'all_render_frames_verified', 'actual_mobile_hardware'):
            require(case.get(flag) is False, 'Unsupported evidence-boundary claim: ' + flag)
        controls, events = case.get('controls'), case.get('events')
        require(isinstance(controls, dict) and set(controls) <= REQUIRED, 'Case contains unknown controls')
        require(isinstance(events, list) and all(isinstance(event, dict) for event in events),
                'Host events must be a list of objects')
        # Hash all available event inputs, including failed-call logs/commands.
        for event in events:
            require(event.get('status') in ('completed', 'failed'), 'Host event did not reach a terminal state')
            for key in ('state_file', 'capture_file', 'command_file', 'log'):
                if key in event:
                    path = files.path(event[key], folder)
                    if event['status'] == 'failed':
                        if path.is_file():
                            files.read(path)
                        else:
                            row['missing_failed_event_artifacts'].append({
                                'label': event.get('label'), 'kind': key,
                                'path': path.relative_to(files.root).as_posix()})
                    else:
                        files.json(path) if path.suffix == '.json' else files.read(path)
        for filename in ('launch.json', 'launch.private.json'):
            if (folder / filename).is_file():
                files.json(folder / filename)
        complete = case.get('stage') == 'completed'
        if complete:
            require(set(controls) == REQUIRED, 'Completed diagnostic is missing a required control')
        else:
            require(not case['passed'], 'Incomplete source case claims success')
            row['partial_source_failure'] = True
        frozen_path, next_path = folder / (name + '_frozen.state.json'), folder / (name + '_generation2_frozen.state.json')
        frozen = files.json(frozen_path) if frozen_path.is_file() else None
        next_state = files.json(next_path) if next_path.is_file() else None
        captured_controls = {key for key, control in controls.items()
                             if isinstance(control, dict) and control.get('windows')}
        initial_required = complete or bool(captured_controls)
        next_required = complete or 'new_generation_identity' in captured_controls
        if controls or complete:
            require(frozen is not None, 'Captured controls lack the initial frozen receipt')
        if frozen is not None and initial_required:
            frozen_state(frozen, frozen, 'Initial frozen receipt')
            require(frozen.get('seed') == case['seed'] and frozen.get('slot_count') == case['payload_bytes'] and
                    frozen.get('generation') == 1 and frozen.get('encoding') == 'compact8',
                    'Initial frozen dataset differs from the requested case')
        if next_state is not None:
            require(frozen is not None, 'Generation2 evidence lacks the initial frozen receipt')
            if next_required:
                frozen_state(next_state, next_state, 'Generation2 frozen receipt')
                require(next_state.get('generation') == 2 and next_state.get('geometry_name') != frozen.get('geometry_name') and
                        next_state.get('geometry_build_serial', 0) > frozen.get('geometry_build_serial', 0),
                        'Generation2 did not produce a fresh geometry identity')
                for key in ('schema', 'seed', 'slot_count', 'encoding', 'layout', 'center'):
                    require(next_state.get(key) == frozen.get(key), 'Generation2 changed dataset property: ' + key)
        if complete:
            require(next_state is not None, 'Completed case lacks generation2 frozen evidence')
        window_identities = set()
        for control, saved in controls.items():
            entry = {'audit_passed': False, 'passed': False, 'payload_match': None, 'windows': [], 'errors': []}
            row['controls'][control] = entry
            try:
                require(isinstance(saved, dict), 'Control summary must be an object')
                windows = saved.get('windows', [])
                require(isinstance(windows, list), 'Control windows must be a list')
                if not windows:
                    require(saved.get('passed') is False and saved.get('status') == 'failed' and
                            isinstance(saved.get('error'), str), 'Empty control lacks an operational error')
                    entry.update(audit_passed=True, operational_failure=saved['error'])
                    continue
                is_hidden, is_next = control == 'hidden_writer', control == 'new_generation_identity'
                reference = next_state if is_next else frozen
                mode, salt, salt2 = (0, 0, 0) if is_hidden else SERIES[control]
                if not is_hidden:
                    compare(saved, {'mode': mode, 'salt': salt, 'salt2': salt2}, ('mode', 'salt', 'salt2'), control)
                pairs, old_pairs = [], []
                starts = (0,) if is_hidden else range(0, case['payload_bytes'], 4096)
                expected_windows = len(tuple(starts))
                partial = len(windows) < expected_windows
                require(len(windows) <= expected_windows and (not partial or
                        (saved.get('passed') is False and saved.get('status') == 'failed' and
                         isinstance(saved.get('error'), str) and 'verification' not in saved)),
                        'Control is missing query windows without preserving its operational failure')
                for ordinal, (start, window) in enumerate(zip(starts, windows)):
                    suffix = 'hidden_writer' if is_hidden else '%s_window_%04d' % (control, ordinal)
                    label = name + '_' + suffix
                    settings = start, min(4096, case['payload_bytes'] - start), mode, salt, salt2
                    replay, pair, old_pair = replay_window(window, case, reference, frozen if is_next else None,
                        files, folder, label, settings, events, hidden=is_hidden)
                    entry['windows'].append(replay)
                    if 'window_identity' in replay:
                        window_identities.add(tuple(replay['window_identity']))
                    if pair is not None:
                        pairs.append(pair)
                    if old_pair is not None:
                        old_pairs.append(old_pair)
                require(len(pairs) == len(windows), 'Some raw captures could not be replayed')
                if partial:
                    require(all(window['audit_passed'] for window in entry['windows']),
                            'Partial capture metadata differs from raw replay')
                    entry.update(audit_passed=True, partial_capture=True, operational_failure=saved['error'])
                    continue
                payload_match = all(report['passed'] for _, report in pairs)
                entry['payload_match'] = payload_match
                verified_values = ({value for _, report in pairs for value in report['expected_bytes']}
                                   if payload_match and not is_hidden else set())
                entry['verified_byte_value_count'] = len(verified_values)
                entry['verified_zero_and_255'] = {0, 255} <= verified_values
                if is_hidden:
                    require(saved.get('expected_payload_match') is False, 'Hidden-writer control lacks its negative expectation')
                    control_passed = not payload_match
                else:
                    series = verify_reports(pairs)  # Retain failed windows in the aggregate.
                    entry['verification'] = compact_report(series)
                    compare(saved.get('verification'), entry['verification'], entry['verification'].keys(), control + '.verification')
                    control_passed = series['passed']
                    if is_next:
                        require(len(old_pairs) == len(pairs), 'Some old-oracle controls could not be replayed')
                        old_series = verify_reports(old_pairs)
                        rejected = not old_series['passed']
                        entry['previous_generation_verification'] = compact_report(old_series)
                        entry['previous_generation_rejected'] = rejected
                        require(saved.get('previous_generation_rejected') is rejected,
                                'Previous-generation rejection differs from complete payload replay')
                        control_passed = control_passed and rejected
                entry['passed'] = control_passed
                require(saved.get('passed') is control_passed and saved.get('status') ==
                        ('passed' if control_passed else 'failed'), 'Recorded control status differs from exact pixels')
                require(all(window['audit_passed'] for window in entry['windows']), 'Window metadata differs from raw replay')
                entry['audit_passed'] = True
            except ERRORS as error:
                entry['errors'].append('%s: %s' % (type(error).__name__, error))
        require(len(window_identities) <= 1, 'Case captures changed native window identity')
        hidden_control = controls.get('hidden_writer')
        if isinstance(hidden_control, dict) and hidden_control.get('windows'):
            for suffix, visible in (('hide_writer', False), ('restore_writer', True)):
                label = name + '_' + suffix
                state_path, command_path = folder / (label + '.state.json'), folder / 'commands' / (label + '.py')
                state = files.json(state_path)
                frozen_state(state, frozen, suffix, visible=visible)
                command = files.read(command_path).decode('utf-8-sig')
                require('probe.set_writer_visible(%r)' % visible in command, 'Writer visibility command is missing: ' + suffix)
                event_match(events, files, folder, label, 'call', {'state_file': state_path, 'command_file': command_path})
        final_reference = next_state if next_state is not None else frozen
        if final_reference is not None:
            if complete:
                for key in ('final_snapshot', 'last_snapshot'):
                    frozen_state(case.get(key), final_reference, 'Case ' + key)
            else:
                # A failed terminal readiness/identity postcondition is itself
                # evidence. Preserve that state without claiming valid pixels.
                require(case.get('final_snapshot') == final_reference,
                        'Failed case final snapshot differs from its terminal raw frozen state')
        row['initial_payload_passed'] = row['controls'].get('identity', {}).get('payload_match')
        row['final_payload_passed'] = row['controls'].get('new_generation_identity', {}).get('payload_match')
        row['case_passed'] = bool(complete and set(row['controls']) == REQUIRED and not case['errors'] and
                                  all(control['passed'] for control in row['controls'].values()))
        require(case['passed'] is row['case_passed'], 'Overall case result differs from replayed controls')
        require(case.get('alpha_transport_verified') is bool(row['case_passed'] and case['channel'] == 'alpha'),
                'Alpha-transport claim differs from replayed controls')
        require(case.get('shared_copy_texture_verified') is bool(row['case_passed'] and not case['direct_source']),
                'Shared-copy claim differs from replayed controls')
        files.unchanged()
        require(all(control['audit_passed'] for control in row['controls'].values()), 'One or more control evidence audits failed')
        row['audit_passed'] = True
    except ERRORS as error:
        row['errors'].append('%s: %s' % (type(error).__name__, error))
    row['source_failure_preserved'] = bool(row['audit_passed'] and not row['case_passed'])
    row['artifact_sha256'] = dict(sorted(files.hashes.items()))
    row['indexing_stage'] = 'fragment_consumer'
    row['vertex_random_access_verified'] = False
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    evidence, output = args.evidence.resolve(), args.output.resolve()
    if not evidence.is_dir():
        parser.error('--evidence must be an existing directory')
    if output.exists() or output.name.endswith('.atlas.json'):
        parser.error('--output must be a new audit path and cannot replace source evidence')
    cases = [recheck_case(path, evidence) for path in sorted(evidence.rglob('*.atlas.json'))]
    artifacts = {}
    for case in cases:
        for path, digest in case['artifact_sha256'].items():
            if path in artifacts and artifacts[path] != digest:
                case.update(audit_passed=False, source_failure_preserved=False)
                case['errors'].append('Shared evidence changed between case audits: ' + path)
            artifacts[path] = digest
    report = {'schema': 'geometry_atlas_evidence_recheck_v1', 'generated_at_utc': datetime.now(timezone.utc).isoformat(),
              'evidence': str(evidence), 'audit_passed': bool(cases) and all(case['audit_passed'] for case in cases),
              'case_count': len(cases), 'consistent_cases': sum(case['audit_passed'] for case in cases),
              'passing_cases': sum(case['case_passed'] and case['audit_passed'] for case in cases),
              'preserved_source_failures': sum(case['source_failure_preserved'] for case in cases),
              'final_payload_passed': bool(cases) and all(case['final_payload_passed'] is True for case in cases),
              'artifact_sha256': dict(sorted(artifacts.items())), 'cases': cases,
              'tool_sha256': {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in
                              ('recheck_evidence.py', 'verify_capture.py', 'run_case.py', 'consumer.fragment', 'copy.fragment', 'poison.fragment')},
              'indexing_stage': 'fragment_consumer', 'vertex_random_access_verified': False,
              'gpu_to_python_readback': False, 'all_render_frames_verified': False, 'actual_mobile_hardware': False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('audit_passed', 'case_count', 'consistent_cases',
        'passing_cases', 'preserved_source_failures', 'final_payload_passed')}, separators=(',', ':')))
    return 0 if report['audit_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
