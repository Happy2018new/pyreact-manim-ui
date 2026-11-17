"""Measure autonomous atlas updates, then audit the frozen final generation.

The host dispatches one benchmark start, waits without IPC or screenshots, and
reads one terminal receipt. Default verification covers all bytes through 12
KiB; larger payloads use three separated 4096-byte windows unless --full is
given. A sampled case never establishes the full resident payload capacity.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import time

from PIL import Image

from run_case import AtlasCase, ERRORS
from verify_capture import IDENTITY_FIELDS, MAX_SLOTS, compact_report, verify_image, verify_reports


MAX_QUERY = 4096
FULL_DEFAULT_BYTES = 12288
PAYLOAD_IDENTITY = ('seed', 'generation', 'geometry_name', 'geometry_build_serial')


def write_json(path, value):
    """Evidence files are immutable, including reports from failed attempts."""
    with path.open('x', encoding='utf-8') as output:
        json.dump(value, output, indent=2)


def planned_windows(byte_count, full=False):
    if full or byte_count <= FULL_DEFAULT_BYTES:
        return [(start, min(MAX_QUERY, byte_count - start))
                for start in range(0, byte_count, MAX_QUERY)]
    starts = (0, (byte_count - MAX_QUERY) // 2, byte_count - MAX_QUERY)
    return [(start, MAX_QUERY) for start in dict.fromkeys(starts)]


def source_history(snapshot):
    """Collect submitted metadata, including candidates not yet published."""
    records = snapshot.get('upload_history')
    if not isinstance(records, list):
        raise ValueError('upload_history must be a list of submitted upload metadata')
    updates = snapshot.get('last_updates') or {}
    if not isinstance(updates, dict):
        raise ValueError('last_updates must be an object or null')
    submitted = updates.get('uploads', [])
    if not isinstance(submitted, list):
        raise ValueError('last_updates.uploads must be a list')
    result, identities = [], set()
    for item in records + submitted:
        if not isinstance(item, dict):
            raise ValueError('Each submitted upload must be an object')
        # Scheduler records may wrap the runtime upload receipt.
        item = item.get('upload', item)
        if not isinstance(item, dict):
            raise ValueError('Submitted upload metadata must be an object')
        name = item.get('name', item.get('geometry_name'))
        serial = item.get('serial', item.get('geometry_build_serial'))
        candidate = dict(item, name=name, serial=serial)
        for key in ('seed', 'generation', 'slot_count', 'serial'):
            value = candidate.get(key)
            minimum = 1 if key == 'serial' else (2 if key == 'slot_count' else 0)
            maximum = MAX_SLOTS if key == 'slot_count' else 0xffffffff
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError('Submitted upload has an invalid ' + key)
        if not isinstance(name, str) or not name or candidate.get('encoding') != 'compact8':
            raise ValueError('Submitted uploads need a name and compact8 encoding')
        if (candidate['slot_count'] != snapshot.get('slot_count') or
                candidate['encoding'] != snapshot.get('encoding')):
            raise ValueError('Submitted upload history changed the dataset layout or encoding')
        identity = (candidate['seed'], candidate['generation'], name, serial)
        if identity not in identities:
            result.append(candidate)
            identities.add(identity)
    final = tuple(snapshot.get(key) for key in PAYLOAD_IDENTITY)
    if final not in identities:
        raise ValueError('Final geometry identity is missing from submitted upload history')
    return result


def candidate_receipt(receipt, upload):
    return dict(receipt, seed=upload['seed'], generation=upload['generation'],
                geometry_name=upload['name'], geometry_build_serial=upload['serial'])


def classify_observed(receipt, image, history):
    """Recompute both dependent-gather hops for every submitted generation."""
    history = source_history(dict(receipt, upload_history=history, last_updates=None))
    final = verify_image(receipt, image)
    candidates, matches = [], []
    for ordinal, upload in enumerate(history):
        candidate = candidate_receipt(receipt, upload)
        report = verify_image(candidate, image)
        identity = dict(history_index=ordinal, seed=upload['seed'], generation=upload['generation'],
                        name=upload['name'], serial=upload['serial'])
        informative = len(set(report['expected_bytes'])) > 1
        is_final = all(candidate[key] == receipt[key] for key in PAYLOAD_IDENTITY)
        candidates.append(dict(identity, is_final_upload=is_final, informative_query=informative,
                               verification=compact_report(report)))
        if report['passed'] and informative:
            matches.append(identity)
    if not any(candidate['is_final_upload'] for candidate in candidates):
        raise ValueError('Final geometry identity is missing from submitted upload history')
    payloads = {(item['seed'], item['generation']) for item in matches}
    if final['passed'] and len(set(final['expected_bytes'])) > 1:
        classification = 'current_generation'
    elif len(payloads) == 1:
        classification = 'stale_generation'
    elif payloads:
        classification = 'ambiguous_submitted_generations'
    else:
        classification = 'unmatched'
    return {'classification': classification, 'final_generation_match': final['passed'],
            'matched_generations': sorted({item['generation'] for item in matches}),
            'matched_candidates': matches, 'candidates': candidates,
            'query': list(receipt['query']), 'offset_search_used': False,
            'dependent_addresses_recomputed_per_generation': True,
            'full_3x3_patch_required': True, 'final_verification': compact_report(final)}


def summarize_windows(pairs):
    if not pairs:
        raise ValueError('At least one final-generation query window is required')
    slots = pairs[0][0]['slot_count']
    ordinals = [index for _, report in pairs for index in report['verified_slot_indices']]
    if len(set(ordinals)) != len(ordinals):
        raise ValueError('Final-generation query windows must not overlap')
    if len(ordinals) == slots:
        return compact_report(verify_reports(pairs))
    sources = {index for _, report in pairs for index in report['source_indices']}
    return {'passed': all(report['passed'] for _, report in pairs),
            'exact_equal': all(report['passed'] for _, report in pairs),
            'full_query_coverage': False, 'full_source_coverage': len(sources) == slots,
            'query_ordinal_coverage': len(ordinals), 'source_index_coverage': len(sources),
            'capture_count': len(pairs), 'payload_bytes': slots,
            'checked_cells': sum(report['checked_cells'] for _, report in pairs),
            'checked_pixels': sum(report['checked_pixels'] for _, report in pairs),
            'failed_cells': sum(report['failed_cells'] for _, report in pairs),
            'max_error': max(report['max_error'] for _, report in pairs),
            'sampled_verification_only': True}


class UpdateCase(AtlasCase):
    def __init__(self, args):
        evidence = args.evidence.resolve()
        for folder in (evidence, evidence / 'commands'):
            if folder.exists() and any(self.owns(item.name, args.name) for item in folder.iterdir()):
                raise ValueError('Preserve previous evidence; choose a new case name')
        super().__init__(args)
        self.output = self.evidence / (args.name + '.updates.json')
        self.initial = None
        self.performance = None
        self.history = []
        self.native_crosshair_hidden = False
        self.terminal_request_while_running = False

    @staticmethod
    def owns(filename, name):
        return filename == name or filename.startswith(name + '_') or filename.startswith(name + '.')

    def host(self, action, suffix, code=None):
        label = self.args.name + '_' + suffix
        expected = {'log': self.evidence / (label + '.' + action + '.log')}
        if code is not None:
            expected['command_file'] = self.commands / (label + '.py')
        if action == 'call':
            expected['state_file'] = self.evidence / (label + '.state.json')
        elif action == 'capture':
            expected.update(capture_file=self.evidence / (label + '.png'),
                            capture_metadata_file=self.evidence / (label + '.json'))
        if any(path.exists() for path in expected.values()):
            raise ValueError('Refusing to overwrite a command, receipt, log or capture: ' + label)
        before = len(self.events)
        try:
            result = super().host(action, suffix, code)
            missing = [key for key, path in expected.items() if not path.is_file()]
            if missing:
                raise ValueError('Completed host action is missing expected artifacts: ' + ','.join(missing))
            return result
        except ERRORS as error:
            if len(self.events) > before:
                self.events[-1].update(status='failed', error='%s: %s' % (type(error).__name__, error))
            raise
        finally:
            if len(self.events) > before:
                self.events[-1].update({key: str(path) for key, path in expected.items()})

    def assert_frozen(self, state):
        if any(state.get(key) is not False for key in ('updates_running', 'measurement_running')):
            raise ValueError('Updates and measurement must have stopped before final verification')
        if state.get('pending_upload') is not None:
            raise ValueError('A pending upload cannot be declared frozen')
        if state.get('connection') is not True or state.get('writer_visible') is not True:
            raise ValueError('A visible writer and explicit shared texture connection are required')
        super().assert_frozen(state)
        if self.frozen is not None:
            for key in ('epoch', 'center', 'writer_visible', 'update_policy', 'publish_delay_ms', 'update_run_serial'):
                if state.get(key) != self.frozen.get(key):
                    raise ValueError('A query changed frozen ' + key)

    def prepare(self):
        code = ("if probe is None:\n    raise RuntimeError('Geometry atlas probe is not registered')\n"
                "_before=probe.snapshot()\n"
                "if _before.get('updates_running') or _before.get('measurement_running'):\n"
                "    raise RuntimeError('Finish the active benchmark before opening a new case')\n"
                "_hidden=api.HideCrossHairGUI(True)\n"
                "if _hidden is not True:\n    raise RuntimeError('Native crosshair hide rejected')\n"
                "probe.open()\n_result=json.dumps(dict(probe.snapshot(),native_crosshair_hidden=_hidden))\n")
        self.host('call', 'open', code)
        self.native_crosshair_hidden = self.state.get('native_crosshair_hidden') is True
        self.wait_ready('ready', 'open')
        self.stage = 'load'
        if self.args.reuse_dataset:
            if (self.state.get('slot_count') != self.args.byte_count or self.state.get('seed') != self.args.seed or
                    self.state.get('encoding') != 'compact8' or self.state.get('update_policy') != self.args.policy or
                    self.state.get('publish_delay_ms') != self.args.publish_delay_ms or
                    not self.state.get('geometry_name')):
                raise ValueError('Reusable dataset does not match payload, seed, encoding, policy and delay')
        else:
            self.call('load', "probe.begin_dataset(encoding='compact8')\n"
                      "probe.configure_updates(policy=%r,publish_delay_ms=%r)\n"
                      "probe.load(%d,seed=%d,generation=1)" %
                      (self.args.policy, self.args.publish_delay_ms, self.args.byte_count, self.args.seed))
            time.sleep(self.args.publish_delay_ms / 1000. + .25)
            settled = self.call('load_settled', '')
            if settled.get('pending_upload') is not None or settled.get('slot_count') != self.args.byte_count:
                raise ValueError('Initial upload did not publish before pipeline preparation')
        self.stage = 'pipeline'
        if self.state.get('pipeline_ready') is not True:
            if self.state.get('connection'):
                raise ValueError('An already-connected failed pipeline requires a fresh owned instance')
            if self.state.get('pipeline_installed') is not True:
                self.call('install', 'probe.install_pipeline()')
                time.sleep(.2)
            self.call('finish', 'probe.finish_pipeline()')
        self.wait_ready('pipeline_ready', 'pipeline')
        self.initial = self.call('initial', '')
        self.assert_frozen(self.initial)
        if (self.initial.get('slot_count') != self.args.byte_count or self.initial.get('seed') != self.args.seed or
                self.initial.get('encoding') != 'compact8' or
                (not self.args.reuse_dataset and self.initial.get('generation') != 1)):
            raise ValueError('Initial dataset identity differs from the requested case')
        self.query('measurement_query', 0, min(MAX_QUERY, self.args.byte_count), 2, 37, 91)
        self.initial = self.state

    def measure(self):
        self.stage = 'benchmark_start'
        guard = ("_before=probe.snapshot()\n"
                 "if _before.get('updates_running') or _before.get('measurement_running'):\n"
                 "    raise RuntimeError('Benchmark already running')\n")
        if self.args.static:
            state = self.call('benchmark_start', guard + 'probe.start_measurement(seconds=%r)' % self.args.seconds)
            if state.get('measurement_running') is not True or state.get('last_measurement') is not None:
                raise ValueError('Static measurement did not start cleanly')
            serial = None
        else:
            state = self.call('benchmark_start', guard +
                'probe.start_updates(duration_seconds=%r,interval_ms=%r,max_updates=%d)' %
                (self.args.seconds, self.args.interval_ms, self.args.max_updates))
            serial = state.get('update_run_serial')
            if (state.get('updates_running') is not True or state.get('last_updates') is not None or
                    type(serial) is not int or serial <= self.initial.get('update_run_serial', 0)):
                raise ValueError('Autonomous update measurement did not start with a fresh run identity')
        self.stage = 'benchmark_wait'
        # No IPC, capture, GetFps or query calls occur during this interval.
        remaining = self.args.seconds + self.args.publish_delay_ms / 1000. + 3.
        while remaining > 0:
            delay = min(30., remaining)
            time.sleep(delay)
            remaining -= delay
        self.stage = 'benchmark_end'
        state = self.call('benchmark_end', '')
        self.terminal_request_while_running = bool(state.get('updates_running') or state.get('measurement_running'))
        self.assert_frozen(state)
        key = 'last_measurement' if self.args.static else 'last_updates'
        self.performance = state.get(key)
        if not isinstance(self.performance, dict):
            raise ValueError('Terminal receipt is missing ' + key)
        for key in ('schema', 'seed', 'slot_count', 'encoding', 'epoch', 'layout', 'center',
                    'update_policy', 'publish_delay_ms', 'screen_size', 'display_rect_norm', 'writer_visible'):
            if state.get(key) != self.initial.get(key):
                raise ValueError('Measurement changed the requested dataset or layout: ' + key)
        if state.get('dimensions', [])[:3] != self.initial.get('dimensions', [])[:3]:
            raise ValueError('Measurement changed the physical source atlas dimensions')
        fixed = {'query': [0, min(MAX_QUERY, self.args.byte_count), 2, 37],
                 'orientation': [1, 0, 0, 0], 'direct_source': False, 'packed_mode': 6}
        if any(state.get(key) != value for key, value in fixed.items()) or state['dimensions'][3] != 91:
            raise ValueError('Terminal measurement did not preserve the fixed shared alpha dependent query')
        for key in ('generation', 'geometry_name', 'geometry_build_serial', 'query'):
            if self.performance.get(key) != state.get(key):
                raise ValueError('Measurement result differs from terminal payload or query: ' + key)
        if not self.args.static:
            if self.performance.get('run_serial') != serial:
                raise ValueError('Completed update measurement belongs to a different run')
            requested = {'duration_seconds': self.args.seconds, 'interval_ms_requested': self.args.interval_ms,
                         'requested_max_updates': self.args.max_updates}
            if any(isinstance(self.performance.get(key), bool) or
                   not isinstance(self.performance.get(key), (int, float)) or
                   not math.isclose(self.performance[key], value, rel_tol=1e-12, abs_tol=1e-9)
                   for key, value in requested.items()):
                raise ValueError('Completed update measurement differs from the requested configuration')
            if any(self.performance.get(key) != state.get(key) for key in ('seed', 'publish_delay_ms')) or \
                    self.performance.get('policy') != self.args.policy or self.performance.get('salt2') != 91:
                raise ValueError('Completed update measurement differs from terminal dataset controls')
            if self.performance.get('duration_completed') is not True:
                raise ValueError('Update measurement did not complete the requested duration')
            if self.performance.get('success') is not True:
                raise RuntimeError('Autonomous updates failed: ' + repr(self.performance.get('error')))
            if self.performance.get('published', 0) < 1:
                raise ValueError('Dynamic measurement did not publish a new generation')
            if state.get('generation') == self.initial.get('generation'):
                raise ValueError('Dynamic measurement did not change the frozen generation')
        elif any(state.get(key) != self.initial.get(key) for key in IDENTITY_FIELDS):
            raise ValueError('Static measurement changed the uploaded payload identity')
        elapsed = self.performance.get('elapsed')
        if (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or
                not math.isfinite(elapsed) or elapsed < self.args.seconds):
            raise ValueError('Measurement ended before the requested duration')
        self.frozen = state
        self.assert_frozen(state)
        history_state = dict(state, upload_history=self.initial['upload_history'] + state['upload_history'])
        if self.args.static:
            # A static baseline may retain last_updates from an earlier epoch.
            history_state['last_updates'] = None
        self.history = source_history(history_state)

    def capture_final(self, suffix, state, previous):
        label = self.args.name + '_' + suffix
        receipt_path = self.evidence / (label + '.state.json')
        capture_path = self.evidence / (label + '.png')
        verify_path = self.evidence / (label + '.verify.json')
        self.host('capture', suffix)
        try:
            with Image.open(capture_path) as source:
                image = source.convert('RGBA')
            report = verify_image(state, image)
            report.update(receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                          capture_sha256=hashlib.sha256(capture_path.read_bytes()).hexdigest())
            write_json(verify_path, report)
            summary = dict(compact_report(report), receipt=str(receipt_path), capture=str(capture_path),
                           verification_file=str(verify_path))
            if previous is not None:
                old = candidate_receipt(state, previous)
                old_path = self.evidence / (label + '.previous-generation.state.json')
                old_verify = self.evidence / (label + '.previous-generation.verify.json')
                write_json(old_path, old)
                rejection = verify_image(old, image)
                rejection.update(receipt_kind='previous_generation_oracle_control',
                    receipt_sha256=hashlib.sha256(old_path.read_bytes()).hexdigest(),
                    capture_sha256=report['capture_sha256'])
                write_json(old_verify, rejection)
                summary['previous_generation_control'] = dict(compact_report(rejection),
                    receipt=str(old_path), verification_file=str(old_verify), rejected=not rejection['passed'])
            if not report['passed']:
                classification = classify_observed(state, image, self.history)
                classification_path = self.evidence / (label + '.classification.json')
                write_json(classification_path, classification)
                summary.update(classification=classification['classification'],
                    matched_generations=classification['matched_generations'],
                    classification_file=str(classification_path))
            return report, summary
        except ERRORS as error:
            if not verify_path.exists():
                write_json(verify_path, {'passed': False, 'exact_equal': False,
                    'error': '%s: %s' % (type(error).__name__, error)})
            raise

    def verify_series(self, label, mode, salt, salt2, previous):
        entry = {'mode': mode, 'salt': salt, 'salt2': salt2, 'status': 'running', 'windows': []}
        self.controls[label] = entry
        pairs = []
        try:
            for ordinal, (start, count) in enumerate(planned_windows(self.args.byte_count, self.args.full)):
                suffix = '%s_window_%04d' % (label, ordinal)
                self.stage = label + ':query:' + str(start)
                state = self.query(suffix, start, count, mode, salt, salt2)
                time.sleep(self.args.settle)
                self.stage = label + ':capture:' + str(start)
                report, summary = self.capture_final(suffix, state, previous)
                pairs.append((state, report))
                entry['windows'].append(summary)
            entry['verification'] = summarize_windows(pairs)
            entry['passed'] = entry['verification']['passed']
            if previous is not None:
                entry['previous_generation_rejected'] = any(
                    window['previous_generation_control']['rejected'] for window in entry['windows'])
                entry['passed'] = entry['passed'] and entry['previous_generation_rejected']
            entry['status'] = 'passed' if entry['passed'] else 'failed'
            if not entry['passed']:
                self.errors.append({'stage': label, 'error': 'Final gather or previous-generation rejection failed'})
        except ERRORS as error:
            entry.update(passed=False, status='failed', error='%s: %s' % (type(error).__name__, error))
            self.record(error)

    def artifacts(self):
        hashes, missing = {}, []
        for folder in (self.evidence, self.commands):
            for path in folder.iterdir():
                if path.is_file() and self.owns(path.name, self.args.name) and path != self.output:
                    hashes[path.relative_to(self.evidence).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        for event in self.events:
            for key in ('log', 'command_file', 'state_file', 'capture_file', 'capture_metadata_file'):
                if key in event and not Path(event[key]).exists():
                    missing.append({'label': event['label'], 'kind': key,
                                    'path': Path(event[key]).relative_to(self.evidence).as_posix()})
        return hashes, missing

    def run(self):
        try:
            self.prepare()
            self.measure()
            final_payload = (self.frozen['seed'], self.frozen['generation'])
            older = [item for item in self.history if (item['seed'], item['generation']) != final_payload]
            previous = max(older, key=lambda item: item['serial']) if older else None
            if not self.args.static and previous is None:
                raise ValueError('Dynamic final verification needs an earlier submitted generation')
            self.verify_series('final_identity', 0, 0, 0, previous)
            self.verify_series('final_dependent', 2, 37, 91, previous)
            self.stage = 'completed'
        except ERRORS as error:
            self.record(error)
        passed = not self.errors and all(self.controls.get(key, {}).get('passed') for key in
                                        ('final_identity', 'final_dependent'))
        identity = self.controls.get('final_identity', {}).get('verification', {})
        complete = bool(passed and identity.get('full_query_coverage') and identity.get('full_source_coverage'))
        hashes, missing = self.artifacts()
        result = {'schema': 'geometry_atlas_updates_case_v1', 'name': self.args.name,
                  'status': 'completed' if passed else 'failed', 'passed': passed, 'stage': self.stage,
                  'errors': self.errors, 'payload_bytes': self.args.byte_count, 'seed': self.args.seed,
                  'static': self.args.static, 'policy': self.args.policy,
                  'publish_delay_ms': self.args.publish_delay_ms, 'requested_seconds': self.args.seconds,
                  'requested_interval_ms': self.args.interval_ms, 'max_updates': self.args.max_updates,
                  'reuse_dataset': self.args.reuse_dataset, 'full_verification_requested': self.args.full,
                  'channel': self.args.channel, 'direct_source': self.args.direct_source, 'flip_y': self.args.flip_y,
                  'native_crosshair_hidden': self.native_crosshair_hidden,
                  'performance': self.performance, 'initial_snapshot': self.initial,
                  'final_snapshot': self.frozen, 'last_snapshot': self.state,
                  'submitted_source_history': self.history, 'controls': self.controls, 'events': self.events,
                  'artifact_sha256': hashes, 'missing_event_artifacts': missing,
                  'complete_payload_verified': complete,
                  'verified_payload_capacity_bytes': self.args.byte_count if complete else None,
                  'sampled_verification_only': bool(identity and not identity.get('full_query_coverage')),
                  'alpha_transport_verified': bool(passed and self.args.channel == 'alpha'),
                  'shared_copy_texture_verified': bool(passed and not self.args.direct_source),
                  'host_requests_between_start_and_terminal': 0,
                  'terminal_request_while_running': self.terminal_request_while_running,
                  'gpu_completion_fence': False,
                  'gpu_to_python_readback': False, 'all_render_frames_verified': False,
                  'actual_mobile_hardware': False, 'elapsed_host_seconds': time.monotonic() - self.started}
        write_json(self.output, result)
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
    parser.add_argument('--seconds', type=float, default=8.)
    parser.add_argument('--interval-ms', type=float, default=100.)
    parser.add_argument('--max-updates', type=int, default=4096)
    parser.add_argument('--policy', choices=('fresh', 'double'), default='double')
    parser.add_argument('--publish-delay-ms', type=float, default=0.)
    parser.add_argument('--static', action='store_true')
    parser.add_argument('--reuse-dataset', action='store_true')
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--settle', type=float, default=2.)
    parser.set_defaults(channel='alpha', direct_source=False, flip_y=True)
    args = parser.parse_args(argv)
    bounded = ((args.seconds, 2., 30.), (args.interval_ms, 0., 30000.),
               (args.publish_delay_ms, 0., 5000.), (args.settle, 0., 30.))
    if (not re.fullmatch('[a-z0-9_]{1,64}', args.name) or not 2 <= args.byte_count <= MAX_SLOTS or
            not 0 <= args.seed <= 0xffffffff or not 1 <= args.max_updates <= 4096 or
            any(not math.isfinite(value) or not low <= value <= high for value, low, high in bounded)):
        parser.error('Use a safe name, supported byte count, uint32 seed, 1..4096 updates, '
                     '2..30 seconds, 0..30000 ms interval, 0..5000 ms delay and 0..30 seconds settle')
    return UpdateCase(args).run()


if __name__ == '__main__':
    raise SystemExit(main())
