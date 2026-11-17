"""Audit frozen geometry-to-texture identity, permutation and dependent gathers.

Uses only owner-bound host calls and passive captures. Query changes must keep
the geometry identity fixed. Hiding the writer must break the payload, and a new
uploaded generation must pass its own oracle and fail the previous generation.
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

from verify_capture import IDENTITY_FIELDS, MAX_SLOTS, compact_report, verify_image, verify_reports


HERE = Path(__file__).resolve().parent
SYSTEM = 'pmanim_geometry_atlas_probe'
ERRORS = (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError)


class AtlasCase:
    def __init__(self, args):
        self.args = args
        self.evidence = args.evidence.resolve()
        self.commands = self.evidence / 'commands'
        self.output = self.evidence / (args.name + '.atlas.json')
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.commands.mkdir(exist_ok=True)
        if self.output.exists() or (self.commands / (args.name + '_open.py')).exists():
            raise ValueError('Preserve previous evidence; choose a new case name')
        self.started = time.monotonic()
        self.stage, self.state, self.frozen = 'open', {}, None
        self.events, self.errors, self.controls = [], [], {}

    def host(self, action, suffix, code=None):
        label = self.args.name + '_' + suffix
        event = {'stage': self.stage, 'label': label, 'action': action, 'status': 'running'}
        self.events.append(event)
        command = [sys.executable, '-B', '-X', 'utf8', str(HERE / 'host.py'), action,
                   '--project', str(self.args.project.resolve()), '--evidence', str(self.evidence),
                   '--label', label, '--timeout', '120']
        log_path = self.evidence / (label + '.' + action + '.log')
        event['log'] = str(log_path)
        try:
            if code is not None:
                path = self.commands / (label + '.py')
                path.write_text("probe=api.GetSystem(%r,'probe')\n" % SYSTEM + code, encoding='utf-8')
                command += ['--code', str(path)]
                event['command_file'] = str(path)
            with log_path.open('w', encoding='utf-8') as log:
                subprocess.run(command, check=True, stdin=subprocess.DEVNULL, stdout=log,
                               stderr=subprocess.STDOUT, timeout=135.)
            if action == 'call':
                path = self.evidence / (label + '.state.json')
                event['state_file'] = str(path)
                self.state = json.loads(path.read_text(encoding='utf-8-sig'))
                if not isinstance(self.state, dict):
                    raise ValueError('Runtime snapshot must be a JSON object')
                return self.state
            event['capture_file'] = str(self.evidence / (label + '.png'))
            return None
        except ERRORS as error:
            event.update(status='failed', error='%s: %s' % (type(error).__name__, error))
            raise
        finally:
            if event['status'] == 'running':
                event['status'] = 'completed'
            event['elapsed_host_seconds'] = time.monotonic() - self.started

    def call(self, suffix, code):
        return self.host('call', suffix, code + '\n_result=json.dumps(probe.snapshot())\n')

    def wait_ready(self, key, suffix):
        deadline, attempt = time.monotonic() + 30., 0
        while self.state.get(key) is not True:
            if time.monotonic() >= deadline:
                raise TimeoutError('Runtime never reached ' + key)
            time.sleep(.2)
            self.call('%s_ready_%d' % (suffix, attempt), '')
            attempt += 1

    def assert_frozen(self, state):
        if state.get('pipeline_ready') is not True or state.get('ready') is not True:
            raise ValueError('Geometry and explicit texture pipeline must both be ready')
        if self.frozen is not None:
            if any(state.get(key) != self.frozen.get(key) for key in IDENTITY_FIELDS):
                raise ValueError('A query control rebuilt or changed the uploaded geometry')
            for key in ('layout', 'upload_history'):
                if state.get(key) != self.frozen.get(key):
                    raise ValueError('A query control changed frozen ' + key)
            if state.get('dimensions', [])[:3] != self.frozen.get('dimensions', [])[:3]:
                raise ValueError('A query control changed the frozen physical atlas dimensions')

    def query(self, suffix, start, count, mode, salt, salt2):
        state = self.call(suffix,
            'probe.query(%d,%d,mode=%d,salt=%d,salt2=%d,flip_y=%r,channel_mode=%d,direct_source=%r)' %
            (start, count, mode, salt, salt2, self.args.flip_y,
             int(self.args.channel == 'red'), self.args.direct_source))
        self.assert_frozen(state)
        channel = int(self.args.channel == 'red')
        expected = {'query': [start, count, mode, salt],
                    'orientation': [int(self.args.flip_y), channel, 0, 0],
                    'direct_source': self.args.direct_source,
                    'packed_mode': mode + 4 * int(self.args.flip_y) + 8 * channel +
                                   16 * int(self.args.direct_source)}
        if any(state.get(key) != value for key, value in expected.items()):
            raise ValueError('Runtime query receipt does not reflect the requested gather controls')
        if len(state.get('dimensions', [])) != 4 or state['dimensions'][3] != salt2:
            raise ValueError('Runtime query receipt does not reflect the requested dependent-gather salt')
        return state

    def capture(self, suffix, state, previous=None):
        label = self.args.name + '_' + suffix
        capture_path = self.evidence / (label + '.png')
        receipt_path = self.evidence / (label + '.state.json')
        verify_path = self.evidence / (label + '.verify.json')
        self.host('capture', suffix)
        try:
            with Image.open(capture_path) as source:
                image = source.convert('RGBA')
            report = verify_image(state, image)
            report.update(receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                          capture_sha256=hashlib.sha256(capture_path.read_bytes()).hexdigest())
            verify_path.write_text(json.dumps(report, separators=(',', ':')), encoding='utf-8')
            summary = dict(compact_report(report), receipt=str(receipt_path), capture=str(capture_path),
                           verification_file=str(verify_path))
            if previous is not None:
                old = dict(state)
                old.update({key: previous[key] for key in IDENTITY_FIELDS})
                old_path = self.evidence / (label + '.previous-generation.state.json')
                old_verify = self.evidence / (label + '.previous-generation.verify.json')
                old_path.write_text(json.dumps(old, indent=2), encoding='utf-8')
                rejection = verify_image(old, image)
                rejection.update(receipt_kind='previous_generation_oracle_control',
                                 receipt_sha256=hashlib.sha256(old_path.read_bytes()).hexdigest(),
                                 capture_sha256=report['capture_sha256'])
                old_verify.write_text(json.dumps(rejection, separators=(',', ':')), encoding='utf-8')
                summary['previous_generation_control'] = dict(compact_report(rejection),
                    receipt=str(old_path), verification_file=str(old_verify),
                    rejected=not rejection['passed'])
            return report, summary
        except (OSError, ValueError, KeyError, TypeError) as error:
            verify_path.write_text(json.dumps({'passed': False, 'exact_equal': False,
                'error': '%s: %s' % (type(error).__name__, error)}), encoding='utf-8')
            raise

    def series(self, label, mode, salt, salt2, previous=None):
        entry = {'mode': mode, 'salt': salt, 'salt2': salt2, 'status': 'running', 'windows': []}
        self.controls[label] = entry
        pairs = []
        try:
            for ordinal, start in enumerate(range(0, self.args.byte_count, 4096)):
                suffix = '%s_window_%04d' % (label, ordinal)
                self.stage = label + ':query:' + str(start)
                state = self.query(suffix, start, min(4096, self.args.byte_count - start), mode, salt, salt2)
                time.sleep(self.args.settle)
                self.stage = label + ':capture:' + str(start)
                report, summary = self.capture(suffix, state, previous=previous)
                entry['windows'].append(summary)
                pairs.append((state, report))
            entry['verification'] = compact_report(verify_reports(pairs))
            entry['passed'] = entry['verification']['passed']
            if previous is not None:
                entry['previous_generation_rejected'] = any(
                    window['previous_generation_control']['rejected'] for window in entry['windows'])
                entry['passed'] = entry['passed'] and entry['previous_generation_rejected']
            entry['status'] = 'passed' if entry['passed'] else 'failed'
            if not entry['passed']:
                self.errors.append({'stage': label, 'error': 'Exact gather or previous-generation rejection failed'})
        except ERRORS as error:
            entry.update(passed=False, status='failed', error='%s: %s' % (type(error).__name__, error))
            self.record(error)

    def record(self, error):
        self.errors.append({'stage': self.stage, 'error': '%s: %s' % (type(error).__name__, error)})

    def run(self):
        try:
            self.call('open', "if probe is None:\n    raise RuntimeError('Geometry atlas probe is not registered')\n"
                      "if api.HideCrossHairGUI(True) is not True:\n"
                      "    raise RuntimeError('Native crosshair hide rejected')\nprobe.open()")
            self.wait_ready('ready', 'open')
            self.stage = 'load'
            self.call('load', "probe.begin_dataset(encoding='compact8')\nprobe.load(%d,seed=%d,generation=1)" %
                      (self.args.byte_count, self.args.seed))
            self.stage = 'pipeline'
            if self.state.get('pipeline_ready') is not True:
                if self.state.get('connection'):
                    raise ValueError('An already-connected failed pipeline requires a fresh owned instance')
                if self.state.get('pipeline_installed') is not True:
                    self.call('install', 'probe.install_pipeline()')
                    time.sleep(.2)
                self.call('finish', 'probe.finish_pipeline()')
            self.wait_ready('pipeline_ready', 'pipeline')
            self.frozen = self.call('frozen', '')
            self.assert_frozen(self.frozen)
            if (self.frozen.get('slot_count') != self.args.byte_count or self.frozen.get('generation') != 1 or
                    self.frozen.get('seed') != self.args.seed or self.frozen.get('encoding') != 'compact8'):
                raise ValueError('Initial uploaded dataset identity differs from the requested case')
            self.series('identity', 0, 0, 0)
            self.series('permutation', 1, 17, 0)
            self.series('dependent', 2, 97, 53)
            self.stage = 'hide_writer'
            try:
                self.call('hide_writer', 'probe.set_writer_visible(False)')
                self.assert_frozen(self.state)
                state = self.query('hidden_writer', 0, min(4096, self.args.byte_count), 0, 0, 0)
                if state.get('writer_visible') is not False:
                    raise ValueError('Writer hide was not reflected in the raw receipt')
                time.sleep(self.args.settle)
                report, summary = self.capture('hidden_writer', state)
                self.controls['hidden_writer'] = {'passed': not report['passed'],
                    'status': 'passed' if not report['passed'] else 'failed',
                    'expected_payload_match': False, 'windows': [summary]}
                if report['passed']:
                    self.errors.append({'stage': self.stage, 'error': 'Hidden writer still delivered the current payload'})
            except ERRORS as error:
                self.record(error)
                self.controls['hidden_writer'] = {'passed': False, 'status': 'failed',
                                                  'error': '%s: %s' % (type(error).__name__, error)}
            finally:
                self.stage = 'restore_writer'
                self.call('restore_writer', 'probe.set_writer_visible(True)')
            previous = self.frozen
            self.stage = 'new_generation'
            self.call('generation2_load', 'probe.load(%d,seed=%d,generation=2)' %
                      (self.args.byte_count, self.args.seed))
            self.frozen = self.call('generation2_frozen', '')
            if (self.frozen.get('generation') != 2 or
                    self.frozen.get('geometry_build_serial', 0) <= previous['geometry_build_serial'] or
                    self.frozen.get('geometry_name') == previous['geometry_name']):
                raise ValueError('New generation did not produce a fresh uploaded geometry identity')
            if any(self.frozen.get(key) != previous.get(key) for key in
                   ('schema', 'seed', 'slot_count', 'encoding', 'layout')):
                raise ValueError('New generation changed the requested dataset or atlas layout')
            self.assert_frozen(self.frozen)
            self.series('new_generation_identity', 0, 0, 0, previous=previous)
            self.stage = 'completed'
        except ERRORS as error:
            self.record(error)
        required = ('identity', 'permutation', 'dependent', 'hidden_writer', 'new_generation_identity')
        passed = not self.errors and all(self.controls.get(label, {}).get('passed') for label in required)
        result = {'schema': 'geometry_atlas_case_v1', 'name': self.args.name,
                  'status': 'completed' if passed else 'failed', 'passed': passed, 'stage': self.stage,
                  'errors': self.errors, 'payload_bytes': self.args.byte_count, 'seed': self.args.seed,
                  'channel': self.args.channel, 'direct_source': self.args.direct_source,
                  'flip_y': self.args.flip_y, 'controls': self.controls,
                  'final_snapshot': self.frozen, 'last_snapshot': self.state, 'events': self.events,
                  'elapsed_host_seconds': time.monotonic() - self.started,
                  'alpha_transport_verified': bool(passed and self.args.channel == 'alpha'),
                  'shared_copy_texture_verified': bool(passed and not self.args.direct_source),
                  'gpu_to_python_readback': False, 'all_render_frames_verified': False,
                  'actual_mobile_hardware': False}
        self.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({'name': self.args.name, 'status': result['status'], 'stage': self.stage,
                          'errors': self.errors, 'report': str(self.output)}, separators=(',', ':')))
        return 0 if passed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--bytes', type=int, default=3072, dest='byte_count')
    parser.add_argument('--seed', type=int, default=54321)
    parser.add_argument('--settle', type=float, default=2.)
    parser.add_argument('--channel', choices=('alpha', 'red'), default='alpha')
    parser.add_argument('--direct-source', action='store_true')
    parser.add_argument('--no-flip-y', action='store_false', dest='flip_y', default=True)
    args = parser.parse_args(argv)
    if (not re.fullmatch('[a-z0-9_]{1,64}', args.name) or not 2 <= args.byte_count <= MAX_SLOTS or
            math.gcd(131, args.byte_count) != 1 or not 0 <= args.seed <= 0xffffffff or
            not math.isfinite(args.settle) or not 0 <= args.settle <= 30):
        parser.error('Use a safe name,2..65536 bytes coprime with131,uint32 seed,and0..30 seconds settle')
    return AtlasCase(args).run()


if __name__ == '__main__':
    raise SystemExit(main())
