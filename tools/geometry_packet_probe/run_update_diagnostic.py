"""Capture bounded geometry updates and distinguish submitted stale generations.

Run against an existing owner-bound background instance launched by host.py.
The final upload remains the only passing payload. Earlier-generation matches
are diagnostic evidence, and never turn a failed final upload into a pass.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

from PIL import Image

from verify_capture import verify_image, verify_reports


HERE = Path(__file__).resolve().parent
SYSTEM = 'pmanim_geometry_packet_probe'
MAX_PAYLOAD_BYTES = 1 << 20
LARGE_REPORT_FIELDS = frozenset(('results', 'observed_bytes', 'expected_bytes',
                                 'indices', 'verified_indices', 'verified_slot_indices',
                                 'centers', 'failures', 'reports'))
IDENTITY_FIELDS = ('schema', 'seed', 'generation', 'slot_count', 'geometry_name',
                   'geometry_build_serial', 'encoding')


def compact_report(report):
    return {key: value for key, value in report.items() if key not in LARGE_REPORT_FIELDS}


def classify_observed(receipt, image, history):
    """Compare one fixed query with every actually submitted upload.

    Each candidate changes only the uploaded seed/generation/name/serial in the
    receipt. The original slot offset, screen rectangle and payload mode remain
    fixed, and verify_image checks every RGBA pixel in each 3x3 patch. History
    is upload metadata, never a source of expected bytes or a guessed offset.
    Constant queries retain exact pixel results for a full-coverage tail, but
    cannot identify a delivered generation from a standalone uniform control.
    """
    final = verify_image(receipt, image)
    final_informative = len(set(final['expected_bytes'])) > 1
    if not isinstance(history, list) or not history:
        raise ValueError('Submitted upload_history must be a nonempty list')
    candidates, matches = [], []
    final_submitted = False
    for ordinal, upload in enumerate(history):
        if not isinstance(upload, dict) or any(key not in upload for key in ('generation', 'name', 'serial')):
            raise ValueError('Each submitted upload needs generation, name and serial')
        if (('slot_count' in upload and upload['slot_count'] != receipt['slot_count']) or
                ('encoding' in upload and upload['encoding'] != receipt.get('encoding'))):
            raise ValueError('Submitted uploads must preserve the slot count and encoding')
        candidate = dict(receipt, seed=upload.get('seed', receipt['seed']), generation=upload['generation'],
                         geometry_name=upload['name'], geometry_build_serial=upload['serial'])
        report = verify_image(candidate, image)
        informative = len(set(report['expected_bytes'])) > 1
        identity = {'history_index': ordinal, 'seed': candidate['seed'], 'generation': upload['generation'],
                    'name': upload['name'], 'serial': upload['serial']}
        is_final = all(candidate[key] == receipt[key] for key in
                       ('seed', 'generation', 'geometry_name', 'geometry_build_serial'))
        final_submitted = final_submitted or is_final
        candidates.append(dict(identity, is_final_upload=is_final, informative_query=informative,
                               verification=compact_report(report)))
        if report['passed'] and informative:
            matches.append(identity)
    if not final_submitted:
        raise ValueError('Final geometry identity is missing from submitted upload_history')
    matched_generations = sorted({match['generation'] for match in matches})
    matched_payloads = {(match['seed'], match['generation']) for match in matches}
    if final['passed'] and final_informative:
        classification = 'current_generation'
    elif len(matched_payloads) == 1:
        classification = 'stale_generation'
    elif matched_payloads:
        classification = 'ambiguous_submitted_generations'
    elif any(candidate['informative_query'] for candidate in candidates):
        classification = 'unmatched'
    else:
        classification = 'insufficient_query_variation'
    return {'classification': classification, 'final_generation_match': final['passed'],
            'final_verification': final, 'matched_generations': matched_generations,
            'matched_candidates': matches, 'candidates': candidates,
            'query': list(final['query']),
            'final_query_has_payload_variation': final_informative,
            'observed_query_sha256': final['observed_payload_sha256'],
            'offset_search_used': False, 'full_3x3_patch_required': True,
            'uniform_controls_used_as_payload': False}


class DiagnosticRunner:
    def __init__(self, args):
        self.args = args
        self.evidence = args.evidence.resolve()
        self.commands = self.evidence / 'commands'
        self.result_path = self.evidence / (args.name + '.update.json')
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.commands.mkdir(exist_ok=True)
        if self.result_path.exists() or (self.commands / (args.name + '_open.py')).exists():
            raise ValueError('Keep previous evidence; choose a new diagnostic name')
        self.started = time.monotonic()
        self.state = {}
        self.frozen = None
        self.stage = 'open'
        self.errors = []
        self.events = []
        self.controls = {}
        self.benchmark = None

    def host(self, action, suffix, code=None, timeout=120.):
        label = self.args.name + '_' + suffix
        event = {'stage': self.stage, 'action': action, 'label': label, 'status': 'running',
                 'elapsed_host_seconds': time.monotonic() - self.started}
        self.events.append(event)
        command = [sys.executable, '-B', '-X', 'utf8', str(HERE / 'host.py'), action,
                   '--project', str(self.args.project.resolve()), '--evidence', str(self.evidence),
                   '--label', label, '--timeout', str(timeout)]
        if code is not None:
            path = self.commands / (label + '.py')
            path.write_text("probe=api.GetSystem(%r,'probe')\n" % SYSTEM + code, encoding='utf-8')
            command += ['--code', str(path)]
            event['command_file'] = str(path)
        log_path = self.evidence / (label + '.' + action + '.log')
        event['log'] = str(log_path)
        try:
            with log_path.open('w', encoding='utf-8') as log:
                subprocess.run(command, check=True, stdin=subprocess.DEVNULL,
                               stdout=log, stderr=subprocess.STDOUT, timeout=timeout + 15.)
            if action == 'call':
                state_path = self.evidence / (label + '.state.json')
                event['state_file'] = str(state_path)
                self.state = json.loads(state_path.read_text(encoding='utf-8-sig'))
                if not isinstance(self.state, dict):
                    raise ValueError('Runtime snapshot must be a JSON object')
                event['status'] = 'completed'
                return self.state
            event['capture_file'] = str(self.evidence / (label + '.png'))
            event['status'] = 'completed'
            return None
        except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
            event.update(status='failed', error='%s: %s' % (type(error).__name__, error))
            raise
        finally:
            event['finished_host_seconds'] = time.monotonic() - self.started

    def snapshot(self, suffix):
        return self.host('call', suffix, '_result=json.dumps(probe.snapshot())\n')

    def ready(self, suffix):
        deadline = time.monotonic() + 30.
        attempt = 0
        while not self.state.get('ready'):
            if time.monotonic() >= deadline:
                raise TimeoutError('Geometry screen never reached Create')
            time.sleep(.2)
            self.snapshot('%s_ready_%d' % (suffix, attempt))
            attempt += 1

    def assert_frozen(self, state):
        if state.get('benchmark_running') or state.get('slot_count') != self.args.byte_count:
            raise ValueError('Dataset is still changing or has the wrong size')
        if self.frozen is not None:
            if any(state.get(key) != self.frozen.get(key) for key in IDENTITY_FIELDS):
                raise ValueError('Frozen geometry identity changed during the diagnostic controls')
            if state.get('upload_history') != self.frozen.get('upload_history'):
                raise ValueError('Submitted uploads changed during the diagnostic controls')

    def capture_window(self, control, index, start, count):
        suffix = '%s_window_%04d' % (control, index)
        self.stage = control + ':query:' + str(start)
        state = self.host('call', suffix,
                          "if probe.snapshot().get('benchmark_running'):\n"
                          "    raise RuntimeError('Payload must be frozen')\n"
                          "probe.query(%d,%d,64)\n_result=json.dumps(probe.snapshot())\n" % (start, count))
        self.assert_frozen(state)
        self.stage = control + ':capture:' + str(start)
        self.host('capture', suffix)
        label = self.args.name + '_' + suffix
        capture_path = self.evidence / (label + '.png')
        state_path = self.evidence / (label + '.state.json')
        self.stage = control + ':verify:' + str(start)
        with Image.open(capture_path) as source:
            image = source.convert('RGBA')
        report = verify_image(state, image)
        report.update(receipt_sha256=hashlib.sha256(state_path.read_bytes()).hexdigest(),
                      capture_sha256=hashlib.sha256(capture_path.read_bytes()).hexdigest())
        verify_path = self.evidence / (label + '.verify.json')
        classify_path = self.evidence / (label + '.classification.json')
        verify_path.write_text(json.dumps(report, separators=(',', ':')), encoding='utf-8')
        try:
            diagnostic = classify_observed(state, image, state.get('upload_history'))
            diagnostic.pop('final_verification')
        except (ValueError, KeyError, TypeError) as error:
            classify_path.write_text(json.dumps({'classification': 'invalid_evidence',
                'final_generation_match': report['passed'],
                'error': '%s: %s' % (type(error).__name__, error)}, indent=2), encoding='utf-8')
            raise
        classify_path.write_text(json.dumps(diagnostic, indent=2), encoding='utf-8')
        summary = dict(compact_report(report), classification=diagnostic['classification'],
                       matched_generations=diagnostic['matched_generations'],
                       matched_candidates=diagnostic['matched_candidates'],
                       receipt=str(state_path), capture=str(capture_path),
                       verification_file=str(verify_path), classification_file=str(classify_path))
        return state, report, summary

    def capture_control(self, control):
        entry = {'stage': control, 'status': 'running', 'windows': []}
        self.controls[control] = entry
        pairs = []
        try:
            starts = range(0, self.args.byte_count, 4096) if self.args.full else (0,)
            for index, start in enumerate(starts):
                state, report, summary = self.capture_window(
                    control, index, start, min(4096, self.args.byte_count - start))
                pairs.append((state, report))
                entry['windows'].append(summary)
            entry['passed'] = all(report['passed'] for _, report in pairs)
            entry['full_slot_coverage'] = self.args.full or self.args.byte_count <= 4096
            if entry['full_slot_coverage']:
                entry['verification'] = compact_report(verify_reports(pairs))
            entry['status'] = 'passed' if entry['passed'] else 'failed'
            if not entry['passed']:
                self.errors.append({'stage': control, 'error': 'Final uploaded generation did not match exact native pixels'})
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            entry.update(status='failed', passed=False, error='%s: %s' % (type(error).__name__, error))
            self.record_error(error)

    def record_error(self, error):
        self.errors.append({'stage': self.stage, 'error': '%s: %s' % (type(error).__name__, error)})

    def run(self):
        try:
            self.host('call', 'open',
                      "if probe is None:\n    raise RuntimeError('Geometry probe is not registered')\n"
                      "if api.HideCrossHairGUI(True) is not True:\n"
                      "    raise RuntimeError('Native crosshair hide rejected')\n"
                      "probe.open()\n_result=json.dumps(probe.snapshot())\n")
            self.ready('open')
            self.stage = 'load'
            self.host('call', 'load',
                      "if probe.snapshot().get('benchmark_running'):\n"
                      "    raise RuntimeError('Finish the current benchmark before a new dataset')\n"
                      "probe.begin_dataset(encoding=%r)\n"
                      "probe.configure_updates(name_policy=%r,interval_frames=%d,max_updates=%d)\n"
                      "probe.load(%d,seed=54321,generation=1)\n_result=json.dumps(probe.snapshot())\n" %
                      (self.args.encoding, self.args.policy, self.args.interval_frames,
                       self.args.updates, self.args.byte_count))
            time.sleep(self.args.settle)
            self.stage = 'updates'
            self.host('call', 'start',
                      "probe.start(seconds=%r,dynamic=True,seed=54321)\n_result=json.dumps(probe.snapshot())\n" %
                      self.args.seconds)
            deadline = time.monotonic() + self.args.seconds + 45.
            attempt = 0
            while True:
                self.snapshot('end_%d' % attempt)
                if not self.state.get('benchmark_running'):
                    self.benchmark = self.state.get('last_run')
                    if not isinstance(self.benchmark, dict) or self.benchmark.get('error'):
                        raise RuntimeError('Update run failed: ' + repr(self.benchmark))
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Geometry update run did not finish')
                time.sleep(.5)
                attempt += 1
            self.stage = 'freeze'
            time.sleep(self.args.settle)
            self.frozen = self.snapshot('frozen')
            self.assert_frozen(self.frozen)
            history = self.frozen.get('upload_history')
            if not isinstance(history, list) or not 2 <= len(history) <= self.args.updates + 1:
                raise ValueError('Bounded update run must retain initial upload and 1..max_updates submissions')
            self.capture_control('final')
            try:
                self.stage = 'same_name_redraw'
                self.host('call', 'same_name_redraw',
                          'probe.redraw()\n_result=json.dumps(probe.snapshot())\n')
                self.assert_frozen(self.state)
                time.sleep(self.args.settle)
                self.capture_control('same_name_redraw')
            except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
                self.controls['same_name_redraw'] = {'status': 'failed', 'passed': False,
                                                    'error': '%s: %s' % (type(error).__name__, error)}
                self.record_error(error)
            if self.args.recreate:
                try:
                    self.stage = 'recreated_screen'
                    self.host('call', 'recreate',
                              'probe.recreate_screen()\n_result=json.dumps(probe.snapshot())\n')
                    self.ready('recreate')
                    self.host('call', 'recreated_redraw',
                              'probe.redraw()\n_result=json.dumps(probe.snapshot())\n')
                    self.assert_frozen(self.state)
                    time.sleep(self.args.settle)
                    self.capture_control('recreated_screen')
                except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
                    self.controls['recreated_screen'] = {'status': 'failed', 'passed': False,
                                                        'error': '%s: %s' % (type(error).__name__, error)}
                    self.record_error(error)
            self.stage = 'completed'
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            self.record_error(error)
        passed = not self.errors and self.controls.get('final', {}).get('passed', False)
        final_passed = self.controls.get('final', {}).get('passed', False)
        final_pixel_mismatch = any(window.get('passed') is False
                                   for window in self.controls.get('final', {}).get('windows', []))
        result = {'name': self.args.name, 'status': 'completed' if passed else 'failed',
                  'passed': passed, 'stage': self.stage, 'errors': self.errors,
                  'payload_bytes': self.args.byte_count, 'encoding': self.args.encoding,
                  'name_policy': self.args.policy, 'max_updates': self.args.updates,
                  'interval_frames': self.args.interval_frames, 'seconds': self.args.seconds,
                  'settle_seconds': self.args.settle, 'full_requested': self.args.full,
                  'recreate_requested': self.args.recreate, 'benchmark': self.benchmark,
                  'final_snapshot': self.frozen, 'last_snapshot': self.state,
                  'controls': self.controls, 'events': self.events,
                  'elapsed_host_seconds': time.monotonic() - self.started,
                  'same_name_redraw_recovers': (final_pixel_mismatch and
                                               self.controls.get('same_name_redraw', {}).get('passed', False)),
                  'recreated_screen_recovers': (final_pixel_mismatch and
                                               self.controls.get('recreated_screen', {}).get('passed', False)),
                  'whole_payload_simultaneously_resident': bool(final_passed and
                      self.controls.get('final', {}).get('full_slot_coverage')),
                  'all_render_frames_verified': False, 'gpu_to_python_readback': False,
                  'actual_mobile_hardware': False}
        self.result_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({'name': self.args.name, 'status': result['status'], 'stage': self.stage,
                          'errors': self.errors, 'report': str(self.result_path)}, separators=(',', ':')))
        return 0 if passed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--bytes', type=int, default=12288, dest='byte_count')
    parser.add_argument('--encoding', choices=('legacy8', 'compact8'), default='compact8')
    parser.add_argument('--policy', choices=('single', 'double', 'fresh'), default='fresh')
    parser.add_argument('--updates', type=int, default=32)
    parser.add_argument('--interval-frames', type=int, default=1)
    parser.add_argument('--seconds', type=float, default=8.)
    parser.add_argument('--recreate', action='store_true')
    parser.add_argument('--settle', type=float, default=2.)
    parser.add_argument('--full', action='store_true', help='verify every resident slot in each control')
    args = parser.parse_args(argv)
    if (not re.fullmatch('[a-z0-9_]{1,64}', args.name) or not 2 <= args.byte_count <= MAX_PAYLOAD_BYTES or
            not 1 <= args.updates <= 128 or not 1 <= args.interval_frames <= 120 or
            not math.isfinite(args.seconds) or not 2 <= args.seconds <= 30 or
            not math.isfinite(args.settle) or not 0 <= args.settle <= 60):
        parser.error('Use a safe name, 2..1,048,576 bytes, 1..128 updates, 1..120 frame interval, '
                     '2..30 seconds, and 0..60 seconds settle')
    return DiagnosticRunner(args).run()


if __name__ == '__main__':
    raise SystemExit(main())
