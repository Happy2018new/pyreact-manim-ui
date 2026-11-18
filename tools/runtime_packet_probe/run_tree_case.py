"""Owner-bound native tree benchmark and independently replayed byte oracle.

Initialization is a single full upload. Subsequent dynamic writes touch only
bounded circular leaf ranges. Frozen scans validate the final resident state,
not every render frame or atomic visibility of uploads.
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
import uuid

from PIL import Image
from run_isolated_case import (DISPLAY_RECT, FAILURES, HOST_TIMEOUT, WINDOW_BYTES,
                               _sha256, _snapshot_code, _write_json, verify_window)
from tree_assets import tree_config

HERE = Path(__file__).resolve().parent


def words_for_seed(seed, leaves):
    """Independent integer reference; never import the game's generator."""
    value = int(seed) & 0xffffff
    words = []
    for unused in range(leaves):
        page = []
        for unused_word in range(12):
            value = (value * 1664525 + 1013904223) & 0xffffff
            page.append(value)
        words.append(page)
    return words


def replay(state, config):
    if (state.get('initialized') is not True or state.get('payload_consistent') is not True or
            state.get('history_complete') is not True):
        raise ValueError('Tree oracle needs a consistent payload and complete update journal')
    words = words_for_seed(state['initial_seed'], config['pages'])
    cursor = 0
    history = state['update_history']
    if len(history) != state['update_count']:
        raise ValueError('Missing incremental update receipts')
    for record in history:
        first, count = record['first_leaf'], record['leaf_count']
        budget = record['budget_bytes']
        if (first != cursor or type(count) is not int or not 1 <= count <= config['pages'] or
                type(budget) is not int or not 36 <= budget <= 3072 or
                record['actual_storage_bytes'] != count * 36 or
                record['actual_storage_bytes'] > budget):
            raise ValueError('Incremental upload exceeded its budget or lost its circular range')
        replacement = words_for_seed(record['seed'], count)
        valid = 0
        for offset, page in enumerate(replacement):
            index = (first + offset) % config['pages']
            words[index] = page
            valid += max(0, min(36, config['payload_bytes'] - index * 36))
        if valid != record['valid_payload_bytes']:
            raise ValueError('Incremental valid byte count disagrees with its leaf range')
        cursor = (first + count) % config['pages']
    if state['cursor'] != cursor or state['aggregate']['words'] != words:
        raise ValueError('Runtime words disagree with independently replayed uploads')
    source = bytes(channel for page in words for word in page
                   for channel in (word >> 16, (word >> 8) & 255, word & 255))
    return words, source[:config['payload_bytes']]


def validate(state, config, words=None, query=None):
    aggregate = state['aggregate']
    if (state.get('transport') != 'tree_atlas' or state.get('ready') is not True or
            state.get('enabled') is not True or state.get('error') is not None or
            state.get('runner_running') is not False or
            state.get('case_namespace') != config['namespace']):
        raise ValueError('Tree is not a ready, frozen, owned payload')
    if (state['screen_size'] != config['screen_size'] or
            state['payload_bytes'] != config['payload_bytes'] or
            aggregate['pages'] != config['pages'] or aggregate['words_per_page'] != 12 or
            aggregate['layout'] != config['layout'] or
            aggregate['display_rect_norm'] != DISPLAY_RECT or
            state.get('native_crosshair_hidden') is not True):
        raise ValueError('Tree receipt differs from the native configuration')
    if state['process_names'] != [process['name'] for process in config['processes']]:
        raise ValueError('Tree process identities or order changed')
    if words is not None and aggregate['words'] != words:
        raise ValueError('Frozen payload changed during the native scan')
    if query is not None and aggregate['query'] != query:
        raise ValueError('Native consumer query differs from the requested window')


def validate_benchmark(before, after, run, seed, dynamic, budget):
    prefix = before['update_history']
    history = after['update_history']
    if history[:len(prefix)] != prefix or after['initial_seed'] != before['initial_seed']:
        raise ValueError('Benchmark changed prior upload receipts or initial seed')
    records = history[len(prefix):]
    expected = run['frames'] if dynamic else 0
    if len(records) != expected or after['update_count']-before['update_count'] != expected:
        raise ValueError('Benchmark render frames do not match incremental upload receipts')
    for frame, record in enumerate(records, 1):
        if record['seed'] != seed+frame*97 or record['budget_bytes'] != budget:
            raise ValueError('Benchmark upload seed or budget differs from its owned render frame')


class NativeHost:
    def __init__(self, project, evidence):
        self.project, self.evidence = project.resolve(), evidence.resolve()
        self.commands = self.evidence / 'commands'
        self.commands.mkdir(parents=True, exist_ok=True)

    def call(self, label, code):
        return self.run('call', label, code)

    def run(self, action, label, code=None):
        command = [sys.executable, '-B', '-X', 'utf8', str(HERE / 'host.py'), action,
                   '--project', str(self.project), '--evidence', str(self.evidence),
                   '--label', label, '--timeout', str(HOST_TIMEOUT)]
        if code is not None:
            path = self.commands / (label + '.py')
            if path.exists():
                raise ValueError('Refusing to replay a saved mutation or query: ' + label)
            path.write_text(code, encoding='utf-8')
            command += ['--code', str(path)]
        with (self.evidence / (label + '.' + action + '.log')).open('w', encoding='utf-8') as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT,
                           timeout=HOST_TIMEOUT + 10)
        suffix = '.state.json' if action == 'call' else '.json'
        result = json.loads((self.evidence / (label + suffix)).read_text(encoding='utf-8'))
        if action == 'capture':
            allowed = (result.get('background_only') is True or
                       (result.get('user_foreground_allowed') is True and
                        result.get('agent_activation_allowed') is False))
            if (result.get('ok') is not True or not allowed or
                    result['frame_qpc_100ns'] < result['request_qpc_100ns']):
                raise ValueError('Capture is not fresh and owner protected')
        return result


def scan(host, name, config, receipt, scope):
    words, source = replay(receipt, config)
    validate(receipt, config, words)
    size = len(source)
    starts = (list(range(0, size, WINDOW_BYTES)) if scope == 'full' else
              sorted(set((0, size//2//36*36, max(0, size-WINDOW_BYTES)))))
    reports = []
    for mode in (1, 2):
        observed_hash, expected_hash = hashlib.sha256(), hashlib.sha256()
        report = {'mode': mode, 'windows': [], 'query_count': 0, 'cross_leaf_queries': 0}
        reports.append(report)
        for window, start in enumerate(starts):
            count = min(WINDOW_BYTES, size-start)
            label = name + '_m%d_w%03d' % (mode, window)
            query = [mode, start, count, 7]
            state = host.call(label, _snapshot_code(
                'probe.aggregation.select(%d,%d,%d,7)\n' % (mode, start, count)))
            validate(state, config, words, query)
            host.run('capture', label)
            with Image.open(host.evidence / (label + '.png')) as image:
                result, observed, expected, unused = verify_window(
                    state, image, source, mode, start, count)
            # The shared pixel verifier predates 36-byte leaves. Recompute its
            # diagnostic cross-page statistic without changing its pixel oracle.
            result['cross_page_queries'] = sum(
                (index+source[index]+7) % size // 36 != index // 36
                for index in range(start, start+count)) if mode == 2 else 0
            result['bytes_per_page'] = 36
            result.update(capture_sha256=_sha256(host.evidence / (label+'.png')),
                          receipt_sha256=_sha256(host.evidence / (label+'.state.json')),
                          provenance_sha256=_sha256(host.evidence / (label+'.json')))
            verification = host.evidence / (label+'.verify.json')
            _write_json(verification, result)
            summary = {key: value for key, value in result.items() if key != 'results'}
            summary['verification_sha256'] = _sha256(verification)
            report['windows'].append(summary)
            if not result['passed']:
                raise ValueError('Native tree byte comparison failed: ' + label)
            observed_hash.update(observed)
            expected_hash.update(expected)
            report['query_count'] += count
            report['cross_leaf_queries'] += result['cross_page_queries']
            print(json.dumps({'case': name, 'mode': mode, 'window': window+1,
                              'query_count': report['query_count'], 'bytes': size}), flush=True)
        report.update(passed=observed_hash.digest() == expected_hash.digest(),
                      full_query_coverage=scope == 'full',
                      observed_sha256=observed_hash.hexdigest(), expected_sha256=expected_hash.hexdigest())
        if scope == 'full' and (report['query_count'] != size or
                (mode == 1 and observed_hash.hexdigest() != hashlib.sha256(source).hexdigest())):
            raise ValueError('Tree full scan did not cover the exact payload')
    terminal = host.call(name+'_terminal', _snapshot_code())
    validate(terminal, config, words)
    return {'scope': scope, 'passed': all(report['passed'] for report in reports),
            'source_sha256': hashlib.sha256(source).hexdigest(), 'modes': reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--bytes', type=int, default=65536)
    parser.add_argument('--seed', type=int, default=54321)
    parser.add_argument('--reuse-config', type=Path)
    parser.add_argument('--seconds', type=float, default=8)
    parser.add_argument('--dynamic', action='store_true')
    parser.add_argument('--budget', type=int, default=3072)
    parser.add_argument('--scan', choices=('full', 'samples', 'none'), default='full')
    args = parser.parse_args()
    if (not re.fullmatch('[a-z0-9_]+', args.name) or args.bytes < 1 or
            not 36 <= args.budget <= 3072 or not math.isfinite(args.seconds) or
            (args.seconds != 0 and not 2 <= args.seconds <= 8)):
        parser.error('Use a simple name, positive bytes, budget 36..3072 and seconds 0 or 2..8')
    host = NativeHost(args.project, args.evidence)
    if list(host.evidence.glob(args.name+'.*')):
        raise ValueError('Preserve existing evidence; choose a fresh name')
    config = (json.loads(args.reuse_config.read_text(encoding='utf-8')) if args.reuse_config else
              tree_config(payload_bytes=args.bytes))
    if config['payload_bytes'] != args.bytes:
        raise ValueError('Reused config differs from requested byte length')
    _write_json(host.evidence / (args.name+'.config.json'), config)
    token, stage, error = uuid.uuid4().hex, 'register', None
    benchmark, verification, receipt, failure, cleanup = None, None, {}, None, None
    try:
        if args.reuse_config:
            receipt = host.call(args.name+'_reuse', _snapshot_code(hide_crosshair=True))
        else:
            code = ('from packet_probe.tree_runtime import TreeProbe\n'
                    'probe.close()\n_config=json.loads(%r)\n'
                    'try:\n    probe.aggregation=TreeProbe(probe.post,_config,%d)\n'
                    'except Exception as _error:\n'
                    '    probe.aggregation=getattr(_error,"aggregate_probe",None)\n    raise\n' %
                    (json.dumps(config), args.seed))
            host.call(args.name+'_register', code+_snapshot_code(require_ready=False))
            stage = 'finish'
            receipt = host.call(args.name+'_finish', _snapshot_code(
                'probe.aggregation.finish()\n', require_ready=False, hide_crosshair=True))
        validate(receipt, config)
        replay(receipt, config)
        stage = 'benchmark'
        if args.seconds:
            before_benchmark = host.call(args.name+'_benchmark', _snapshot_code(
                'probe.aggregation.set_update_budget(%d)\n'
                'probe.aggregation.select(0,0,%d,7)\n' % (args.budget, min(args.bytes, WINDOW_BYTES))))
            host.call(args.name+'_start',
                'if probe.run is not None:\n    raise RuntimeError("Another run is active")\n'
                '_result=json.dumps(probe.start_aggregate(%r,%r,%d))\n'
                'probe.run["tree_case_token"]=%r\n' %
                (args.seconds, args.dynamic, args.seed, token))
            time.sleep(args.seconds+0.25)
            deadline, attempt = time.monotonic()+HOST_TIMEOUT, 0
            while True:
                end = host.call(args.name+'_end_%d' % attempt,
                                '_result=json.dumps(probe.snapshot())\n')
                if not end['running']:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Owned tree benchmark exceeded its deadline')
                attempt += 1
                time.sleep(0.5)
            benchmark = end['last_run']
            if (end['running'] or not benchmark or not benchmark.get('success') or
                    benchmark.get('tree_case_token') != token):
                raise ValueError('Tree benchmark failed or is still active')
        receipt = host.call(args.name+'_frozen', _snapshot_code())
        validate(receipt, config)
        replay(receipt, config)
        if benchmark:
            validate_benchmark(before_benchmark, receipt, benchmark,
                               args.seed, args.dynamic, args.budget)
        stage = 'scan'
        if args.scan != 'none':
            verification = scan(host, args.name, config, receipt, args.scan)
        stage = 'hide'
        host.call(args.name+'_hidden', _snapshot_code(
            'probe.aggregation.select(0,0,%d,7)\n' % min(args.bytes, WINDOW_BYTES)))
        host.run('capture', args.name+'_hidden')
        stage = 'completed'
    except FAILURES as problem:
        error = '%s: %s' % (type(problem).__name__, problem)
        try:
            failure = host.call(args.name+'_failure', '_result=json.dumps(probe.snapshot())\n')
            cleanup = host.call(args.name+'_abort',
                'if probe.run is not None and probe.run.get("tree_case_token")==%r:\n'
                '    probe._finish_run("aborted","Tree case failed")\n'
                '_result=json.dumps(probe.snapshot())\n' % token)
        except FAILURES as inspection:
            cleanup = {'error': str(inspection)}
    passed = error is None and stage == 'completed'
    result = {'name': args.name, 'status': 'completed' if passed else 'failed',
              'stage': stage, 'error': error, 'payload_bytes': args.bytes,
              'config': args.name+'.config.json', 'config_sha256': _sha256(
                  host.evidence / (args.name+'.config.json')),
              'stats': config['stats'], 'benchmark': benchmark, 'verification': verification,
              'incremental': bool(args.dynamic and benchmark), 'budget_bytes': args.budget,
              'update_count': receipt.get('update_count'), 'history_complete': receipt.get('history_complete'),
              'initialization_timing': receipt.get('initialization_timing'),
              'initialization_is_budgeted': False, 'failure_state': failure, 'cleanup': cleanup,
              'all_resident_bytes_verified': bool(passed and verification and args.scan == 'full'),
              'all_render_frames_verified': False, 'atomic_upload_verified': False,
              'automatic_mutation_replays': 0, 'gpu_to_python_readback': False}
    _write_json(host.evidence / (args.name+'.case.json'), result)
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ('verification', 'failure_state', 'cleanup', 'stats')}), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
