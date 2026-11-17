"""Replay raw update diagnostics, preserving expected stale-payload failures.

audit_passed describes consistency of the saved evidence and its WGC provenance.
final_payload_passed separately describes the exact pixels of the final upload.
No source evidence is modified and no running game is contacted.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re

from PIL import Image

from recheck_evidence import _capture_provenance
from run_update_diagnostic import classify_observed, compact_report
from verify_capture import verify_reports


HERE = Path(__file__).resolve().parent
IDENTITY = ('schema', 'seed', 'generation', 'slot_count', 'geometry_name',
            'geometry_build_serial', 'encoding')
ERRORS = (OSError, ValueError, KeyError, TypeError, OverflowError)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


class EvidenceFiles:
    def __init__(self, evidence):
        self.evidence = evidence.resolve()
        self.hashes = {}

    def path(self, value, base=None):
        _require(isinstance(value, (str, Path)) and bool(str(value)), 'Evidence path must be nonempty')
        path = Path(value)
        path = (path if path.is_absolute() else (base or self.evidence) / path).resolve()
        _require(path.is_relative_to(self.evidence), 'Evidence path escapes the evidence directory: ' + str(path))
        return path

    def read(self, path):
        path = self.path(path)
        raw = path.read_bytes()
        relative = path.relative_to(self.evidence).as_posix()
        digest = hashlib.sha256(raw).hexdigest()
        previous = self.hashes.get(relative)
        _require(previous is None or previous == digest, 'Evidence changed during replay: ' + relative)
        self.hashes[relative] = digest
        return raw

    def json(self, path):
        data = json.loads(self.read(path).decode('utf-8-sig'))
        _require(isinstance(data, dict), 'JSON evidence must be an object: ' + str(path))
        return data

    def digest(self, path):
        return self.hashes[self.path(path).relative_to(self.evidence).as_posix()]

    def check_unchanged(self):
        for relative in list(self.hashes):
            self.read(self.evidence / relative)


def _compare_fields(recorded, actual, fields, label):
    _require(isinstance(recorded, dict), label + ' must be an object')
    for key in fields:
        _require(key in recorded and recorded[key] == actual[key], label + ' mismatch: ' + key)


def _compare_candidates(recorded, actual, label):
    _require(isinstance(recorded, list) and len(recorded) == len(actual), label + ' count mismatch')
    for ordinal, (saved, replayed) in enumerate(zip(recorded, actual)):
        _compare_fields(saved, replayed, ('history_index', 'generation', 'name', 'serial'),
                        '%s[%d]' % (label, ordinal))
        # The earliest v6 captures predate explicit seed and informative-query
        # fields. Their raw uploaded receipts still determine those values.
        for key in ('seed', 'is_final_upload', 'informative_query'):
            if key in saved:
                _compare_fields(saved, replayed, (key,), '%s[%d]' % (label, ordinal))
        if 'verification' in replayed:
            _compare_fields(saved.get('verification'), replayed['verification'],
                            replayed['verification'].keys(), '%s[%d].verification' % (label, ordinal))


def _compare_classification(recorded, replayed, label, complete=True):
    fields = ['classification', 'matched_generations']
    if complete:
        fields += ['final_generation_match', 'query', 'observed_query_sha256',
                   'offset_search_used', 'full_3x3_patch_required', 'uniform_controls_used_as_payload']
    _compare_fields(recorded, replayed, fields, label)
    _compare_candidates(recorded.get('matched_candidates'), replayed['matched_candidates'],
                        label + '.matched_candidates')
    if complete:
        _compare_candidates(recorded.get('candidates'), replayed['candidates'], label + '.candidates')
        if 'final_query_has_payload_variation' in recorded:
            _compare_fields(recorded, replayed, ('final_query_has_payload_variation',), label)


def _frozen_state(state, frozen, label, require_ready=True):
    _require(all(state.get(key) == frozen.get(key) for key in IDENTITY), label + ' changed frozen geometry identity')
    _require(state.get('benchmark_running') is False and
             (not require_ready or state.get('ready') is True),
             label + ' is updating or has no ready screen')
    _require(state.get('upload_history') == frozen.get('upload_history'), label + ' changed submitted upload history')


def _replay_window(saved, frozen, folder, files, label, artifact_label, revision):
    row = {'audit_passed': False, 'final_payload_passed': False, 'errors': []}
    pair = None
    try:
        _require(isinstance(saved, dict), 'Window summary must be an object')
        paths = {key: files.path(saved.get(key), folder) for key in
                 ('receipt', 'capture', 'verification_file', 'classification_file')}
        for key, suffix in (('receipt', '.state.json'), ('capture', '.png'),
                            ('verification_file', '.verify.json'), ('classification_file', '.classification.json')):
            _require(paths[key] == folder / (artifact_label + suffix),
                     'Window artifact does not belong to its declared control: ' + key)
        for path in paths.values():
            files.read(path)
        row.update(receipt=paths['receipt'].relative_to(files.evidence).as_posix(),
                   capture=paths['capture'].relative_to(files.evidence).as_posix())
        state = files.json(paths['receipt'])
        _frozen_state(state, frozen, label)
        _require(state.get('screen_revision') == revision, label + ' has an unexpected screen revision')
        raw_capture = files.read(paths['capture'])
        provenance_value = saved.get('capture_provenance', saved.get('provenance'))
        provenance_path = (files.path(provenance_value, folder) if provenance_value is not None
                           else paths['capture'].with_suffix('.json'))
        _require(provenance_path == paths['capture'].with_suffix('.json'),
                 'Capture provenance must be the matching control-specific sibling')
        files.json(provenance_path)
        digest = _capture_provenance(provenance_path, paths['capture'])
        _require(digest == files.digest(provenance_path), 'Capture provenance changed during replay')
        with Image.open(io.BytesIO(raw_capture)) as source:
            replayed = classify_observed(state, source.convert('RGBA'), state.get('upload_history'))
        report = replayed['final_verification']
        pair = (state, report)
        row.update(final_payload_passed=report['passed'], query=report['query'],
                   classification=replayed['classification'],
                   matched_generations=replayed['matched_generations'],
                   matched_candidates=replayed['matched_candidates'],
                   verification=compact_report(report))
        verification = files.json(paths['verification_file'])
        classification = files.json(paths['classification_file'])
        _compare_fields(verification, report, report.keys(), label + '.verify')
        hashes = {'receipt_sha256': files.digest(paths['receipt']),
                  'capture_sha256': files.digest(paths['capture'])}
        _compare_fields(verification, hashes, hashes.keys(), label + '.verify')
        _compare_fields(saved, compact_report(report), compact_report(report).keys(), label + '.summary')
        _compare_fields(saved, hashes, hashes.keys(), label + '.summary')
        _compare_classification(classification, replayed, label + '.classification')
        _compare_classification(saved, replayed, label + '.summary', complete=False)
        row['audit_passed'] = True
    except ERRORS as error:
        row['errors'].append('%s: %s' % (type(error).__name__, error))
    return row, pair


def recheck_case(case_path, evidence):
    """Audit one .update.json without treating a reproduced stale frame as bad evidence."""
    files = EvidenceFiles(evidence)
    row = {'audit_passed': False, 'final_payload_passed': False, 'errors': [], 'controls': {}}
    try:
        case_path = files.path(case_path)
        row['case'] = case_path.relative_to(files.evidence).as_posix()
        case = files.json(case_path)
        row.update(name=case.get('name'), source_status=case.get('status'),
                   source_passed=case.get('passed'), payload_bytes=case.get('payload_bytes'),
                   encoding=case.get('encoding'), name_policy=case.get('name_policy'))
        name = case.get('name')
        _require(isinstance(name, str) and re.fullmatch('[a-z0-9_]{1,64}', name) is not None and
                 case_path.name == name + '.update.json', 'Case name does not match its safe filename')
        _require(isinstance(case.get('passed'), bool) and case.get('status') ==
                 ('completed' if case['passed'] else 'failed'), 'Case status and passed flag disagree')
        _require(case.get('stage') == 'completed', 'Diagnostic did not reach all requested controls')
        _require(isinstance(case.get('errors'), list), 'Diagnostic errors must be a list')
        for key in ('gpu_to_python_readback', 'all_render_frames_verified', 'actual_mobile_hardware'):
            _require(case.get(key) is False, 'Unsupported evidence-boundary flag: ' + key)
        folder = case_path.parent
        frozen = files.json(folder / (name + '_frozen.state.json'))
        _frozen_state(frozen, frozen, 'Frozen snapshot')
        _require(frozen.get('slot_count') == case.get('payload_bytes') and
                 frozen.get('encoding') == case.get('encoding'), 'Case payload size or encoding differs from frozen state')
        _require(isinstance(case.get('final_snapshot'), dict), 'Missing final snapshot')
        _frozen_state(case['final_snapshot'], frozen, 'Case final snapshot')
        _require(isinstance(case.get('last_snapshot'), dict), 'Missing last snapshot')
        _frozen_state(case['last_snapshot'], frozen, 'Case last snapshot')
        benchmark = case.get('benchmark')
        _require(isinstance(benchmark, dict) and benchmark == frozen.get('last_run') and
                 benchmark.get('error') is None and benchmark.get('success') is True,
                 'Benchmark metadata does not describe the completed frozen run')
        for key in ('name_policy', 'max_updates', 'interval_frames'):
            _require(key in case and case[key] == frozen.get(key) == benchmark.get(key),
                     'Case settings differ from frozen benchmark: ' + key)
        _require(case['name_policy'] in ('single', 'double', 'fresh'), 'Unknown name policy')
        updates, bound = benchmark.get('updates'), case['max_updates']
        _require(type(updates) is int and type(bound) is int and 1 <= updates <= bound <= 128,
                 'Benchmark updates exceed the declared bounded diagnostic')
        _require(isinstance(frozen.get('upload_history'), list) and
                 len(frozen['upload_history']) == updates + 1, 'Upload history length disagrees with update count')
        _require(benchmark.get('initial_generation') == 1 and frozen['generation'] == 1 + updates and
                 frozen['geometry_build_serial'] == benchmark.get('initial_build_serial', -1) + updates,
                 'Uploaded identity disagrees with the initial upload and update count')
        seconds = case.get('seconds')
        _require(isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and
                 math.isfinite(seconds) and math.isclose(seconds, benchmark.get('until', 0) -
                                                        benchmark.get('start', 0), abs_tol=1e-6),
                 'Requested duration differs from the raw benchmark interval')
        revision = frozen.get('screen_revision')
        _require(type(revision) is int and revision >= 0, 'Frozen screen revision is invalid')
        events = case.get('events')
        _require(isinstance(events, list) and all(isinstance(event, dict) for event in events),
                 'Diagnostic events must be a list of objects')

        def operation(suffix, method, expected_revision, ready=True):
            label = name + '_' + suffix
            state_path = folder / (label + '.state.json')
            command_path = folder / 'commands' / (label + '.py')
            state = files.json(state_path)
            _frozen_state(state, frozen, suffix, require_ready=ready)
            _require(state.get('screen_revision') == expected_revision,
                     suffix + ' did not preserve the expected screen lifecycle')
            code = files.read(command_path).decode('utf-8-sig')
            _require(method in code, suffix + ' command does not invoke the recorded control')
            matches = [event for event in events if event.get('label') == label and event.get('action') == 'call']
            _require(len(matches) == 1 and matches[0].get('status') == 'completed' and
                     files.path(matches[0].get('state_file'), folder) == state_path and
                     files.path(matches[0].get('command_file'), folder) == command_path,
                     suffix + ' is not substantiated by the recorded host call')

        operation('same_name_redraw', 'probe.redraw()', revision)
        if case.get('recreate_requested'):
            operation('recreate', 'probe.recreate_screen()', revision + 1, ready=False)
            operation('recreated_redraw', 'probe.redraw()', revision + 1)
        controls = case.get('controls')
        expected = {'final', 'same_name_redraw'} | ({'recreated_screen'} if case.get('recreate_requested') else set())
        _require(isinstance(controls, dict) and set(controls) == expected, 'Requested diagnostic controls are missing or unexpected')
        for control in ('final', 'same_name_redraw', 'recreated_screen'):
            if control not in controls:
                continue
            saved = controls[control]
            entry = {'audit_passed': False, 'final_payload_passed': False, 'windows': [], 'errors': []}
            row['controls'][control] = entry
            try:
                _require(isinstance(saved, dict) and saved.get('stage') == control,
                         'Control stage label is missing or inconsistent')
                windows = saved.get('windows')
                _require(isinstance(windows, list) and bool(windows), 'Control has no raw windows')
                pairs = []
                for ordinal, window in enumerate(windows):
                    artifact_label = '%s_%s_window_%04d' % (name, control, ordinal)
                    replay, pair = _replay_window(window, frozen, folder, files,
                                                  '%s.window[%d]' % (control, ordinal), artifact_label,
                                                  revision + int(control == 'recreated_screen'))
                    entry['windows'].append(replay)
                    if pair is not None:
                        pairs.append(pair)
                _require(len(pairs) == len(windows), 'Some raw windows could not be replayed')
                payload_passed = all(report['passed'] for _, report in pairs)
                entry['final_payload_passed'] = payload_passed
                _require(saved.get('passed') is payload_passed and saved.get('status') ==
                         ('passed' if payload_passed else 'failed'), 'Recorded control status differs from exact pixels')
                full = saved.get('full_slot_coverage')
                _require(isinstance(full, bool), 'Control coverage declaration must be boolean')
                _require(not case.get('full_requested') or full, 'Full coverage was requested but not declared')
                if full:
                    # Failed reports are deliberately retained in this aggregate.
                    series = verify_reports(pairs)
                    entry['verification'] = compact_report(series)
                    _compare_fields(saved.get('verification'), entry['verification'],
                                    entry['verification'].keys(), control + '.verification')
                else:
                    indices = [index for _, report in pairs for index in report['verified_slot_indices']]
                    _require(len(indices) == len(set(indices)), 'Partial queries contain duplicated slots')
                    _require(len(indices) < frozen['slot_count'], 'Full slot coverage was incorrectly marked partial')
                entry['full_slot_coverage'] = full
                _require(all(window['audit_passed'] for window in entry['windows']), 'Raw window summaries disagree with replay')
                entry['audit_passed'] = True
            except ERRORS as error:
                entry['errors'].append('%s: %s' % (type(error).__name__, error))
        row['final_payload_passed'] = row['controls'].get('final', {}).get('final_payload_passed', False)
        complete_pass = all(control.get('final_payload_passed') for control in row['controls'].values()) and not case['errors']
        _require(case['passed'] is complete_pass, 'Overall diagnostic status differs from replayed controls and recorded errors')
        final_full = row['controls'].get('final', {}).get('full_slot_coverage', False)
        _require(case.get('whole_payload_simultaneously_resident') is bool(row['final_payload_passed'] and final_full),
                 'Whole-payload result differs from final full-coverage pixels')
        for control, flag in (('same_name_redraw', 'same_name_redraw_recovers'),
                              ('recreated_screen', 'recreated_screen_recovers')):
            recovered = not row['final_payload_passed'] and row['controls'].get(control, {}).get('final_payload_passed', False)
            _require(case.get(flag) is recovered, 'Recovery flag differs from replayed pixels: ' + flag)
        # Hash all declared host states as well as the raw image/oracle dependencies.
        for event in events:
            _require(isinstance(event, dict), 'Diagnostic event must be an object')
            for key in ('state_file', 'capture_file', 'command_file', 'log'):
                if key in event:
                    path = files.path(event[key], folder)
                    files.json(path) if path.suffix == '.json' else files.read(path)
        for launch in ('launch.json', 'launch.private.json'):
            if (folder / launch).is_file():
                files.json(folder / launch)
        files.check_unchanged()
        _require(all(control['audit_passed'] for control in row['controls'].values()),
                 'One or more control evidence audits failed')
        row['audit_passed'] = True
    except ERRORS as error:
        row['errors'].append('%s: %s' % (type(error).__name__, error))
    row['artifact_sha256'] = dict(sorted(files.hashes.items()))
    row['expected_payload_failure_preserved'] = bool(row['audit_passed'] and not row['final_payload_passed'])
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    evidence, output = args.evidence.resolve(), args.output.resolve()
    if not evidence.is_dir():
        parser.error('--evidence must be an existing directory')
    paths = sorted(evidence.rglob('*.update.json'))
    if output in paths or output.name.endswith('.update.json'):
        parser.error('--output must be a new audit artifact, not source .update.json evidence')
    if output.exists():
        parser.error('--output must be a new path so existing evidence cannot be overwritten')
    cases = [recheck_case(path, evidence) for path in paths]
    artifacts = {}
    for case in cases:
        for relative, digest in case['artifact_sha256'].items():
            if relative in artifacts and artifacts[relative] != digest:
                case['audit_passed'] = False
                case['expected_payload_failure_preserved'] = False
                case['errors'].append('Shared evidence changed between case audits: ' + relative)
            artifacts[relative] = digest
    report = {'schema': 'geometry_packet_update_recheck_v1',
              'generated_at_utc': datetime.now(timezone.utc).isoformat(),
              'evidence': str(evidence), 'audit_passed': bool(cases) and all(case['audit_passed'] for case in cases),
              'final_payload_passed': bool(cases) and all(case['final_payload_passed'] for case in cases),
              'case_count': len(cases), 'consistent_cases': sum(case['audit_passed'] for case in cases),
              'expected_payload_failures': sum(case['expected_payload_failure_preserved'] for case in cases),
              'artifact_sha256': dict(sorted(artifacts.items())), 'cases': cases,
              'tool_sha256': {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in
                              ('recheck_updates.py', 'recheck_evidence.py', 'run_update_diagnostic.py', 'verify_capture.py')},
              'gpu_to_python_readback': False, 'all_render_frames_verified': False,
              'actual_mobile_hardware': False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('audit_passed', 'final_payload_passed', 'case_count',
                                                  'consistent_cases', 'expected_payload_failures')}, separators=(',', ':')))
    return 0 if report['audit_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
