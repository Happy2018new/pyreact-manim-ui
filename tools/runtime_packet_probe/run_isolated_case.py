"""Verify a frozen private-RT payload through an existing owner-bound game.

This runner never launches Minecraft. Identity covers the exact requested byte
count; dependent queries use A[(i + A[i] + salt) % len(A)]. Screenshots retain
native coordinates and every diagnostic cell must match a complete 3x3 RGBA
patch with zero tolerance. A successful frozen scan does not verify every
render frame or establish lossless preservation of the saved scene image.
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
from verify_capture import _sample
from verify_spatial import expected_words


HERE = Path(__file__).resolve().parent
WINDOW_BYTES = 3072
COLUMNS = 24
DISPLAY_RECT = [0.05, 0.05, 0.90, 0.90]
HOST_TIMEOUT = 120.0
FAILURES = (OSError, RuntimeError, ValueError, TypeError, KeyError,
            IndexError, subprocess.SubprocessError)


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payload(seed, pages, size):
    """Generate the host oracle without trusting words returned by the game."""
    words = expected_words(seed, pages)
    data = bytes(channel for row in words for word in row
                 for channel in (word >> 16, (word >> 8) & 255, word & 255))
    return words, data[:size]


def _snapshot_code(body='', require_ready=True, hide_crosshair=False):
    guard = ("if probe.run is not None:\n"
             "    raise RuntimeError('Finish the active benchmark before isolated verification')\n")
    if require_ready:
        guard += ("if (probe.aggregation is None or not probe.aggregation.ready or\n"
                  "        probe.aggregation.enabled is not True or probe.aggregation.error is not None):\n"
                  "    raise RuntimeError('Isolated payload is not ready and enabled')\n")
    crosshair = ''
    if hide_crosshair:
        crosshair = ("probe._isolated_case_crosshair_hidden=api.HideCrossHairGUI(True)\n"
                     "if probe._isolated_case_crosshair_hidden is not True:\n"
                     "    raise RuntimeError('Native crosshair hide was rejected')\n")
    return (guard + body + crosshair +
            "_state=probe.aggregation.snapshot() if probe.aggregation is not None else {}\n"
            "_state['runner_running']=probe.run is not None\n"
            "_state['case_namespace']=(probe.aggregation.config.get('namespace')\n"
            "    if probe.aggregation is not None else None)\n"
            "_state['native_crosshair_hidden']=getattr(probe,'_isolated_case_crosshair_hidden',False)\n"
            "_result=json.dumps(_state)\n")


def _layout_dimensions(layout):
    if not isinstance(layout, dict):
        raise ValueError('Missing atlas layout receipt')
    columns = layout.get('columns', layout.get('cols'))
    rows = layout.get('rows')
    if (isinstance(columns, bool) or isinstance(rows, bool) or
            not isinstance(columns, int) or not isinstance(rows, int) or
            columns < 1 or rows < 1):
        raise ValueError('Atlas layout needs positive integer columns and rows')
    return columns, rows


def _validate_snapshot(state, config, words, namespace, query=None):
    if (state.get('ready') is not True or state.get('enabled') is not True or
            state.get('error') is not None or state.get('runner_running') is not False):
        raise ValueError('Payload snapshot is not ready, enabled and frozen')
    if state.get('case_namespace') != namespace:
        raise ValueError('Payload belongs to another isolated case')
    aggregate = state['aggregate']
    if (aggregate['pages'] != config['pages'] or aggregate['words'] != words or
            aggregate.get('words_per_page', 8) != 8 or
            aggregate.get('payload_bytes', state.get('payload_bytes')) != config['payload_bytes']):
        raise ValueError('Frozen runtime words or exact payload size differ from the host oracle')
    if list(state['screen_size']) != list(config['screen_size']):
        raise ValueError('Runtime viewport differs from the generated native profile')
    layout = aggregate.get('layout', state.get('atlas_layout', state.get('layout')))
    expected_layout = config.get('atlas_layout', config.get('layout'))
    if _layout_dimensions(layout) != _layout_dimensions(expected_layout):
        raise ValueError('Frozen atlas layout differs from its configuration')
    if list(aggregate['display_rect_norm']) != DISPLAY_RECT:
        raise ValueError('Diagnostic rectangle differs from the fixed acceptance profile')
    if state.get('native_crosshair_hidden') is not True:
        raise ValueError('Native crosshair hide was not confirmed')
    if query is not None:
        current = aggregate['query']
        if (len(current) != 4 or any(isinstance(value, bool) or
                not isinstance(value, (int, float)) or not math.isfinite(value) or
                int(value) != value for value in current) or
                [int(value) for value in current] != list(query)):
            raise ValueError('Consumer query differs from its requested fixed window')
    return aggregate


def verify_window(state, image, source, mode, start, count, salt=7):
    """Check the whole fixed diagnostic grid, including final-row zero padding."""
    if list(image.size) != list(state['screen_size']):
        raise ValueError('WGC image dimensions differ from the declared native viewport')
    if mode not in (1, 2) or not 1 <= count <= WINDOW_BYTES or not 0 <= start < len(source):
        raise ValueError('Invalid isolated diagnostic window')
    image = image.convert('RGBA')
    rows = (count + COLUMNS - 1) // COLUMNS
    left, top, width, height = DISPLAY_RECT
    observed, expected, results = bytearray(), bytearray(), []
    failures, maximum, padding, cross_page = 0, 0, 0, 0
    targets = set()
    for offset in range(rows * COLUMNS):
        row, column = divmod(offset, COLUMNS)
        rect = (left * image.width, (top + row * height / rows) * image.height,
                width * image.width, height * image.height / rows)
        center, pixels, patch_width = _sample(image, rect, column, COLUMNS, False)
        if patch_width != 3:
            raise ValueError('Native viewport cannot fit a complete 3x3 patch in every cell')
        index = start + offset
        valid = offset < count and index < len(source)
        address = index if valid else None
        if valid and mode == 2:
            address = (index + source[index] + salt) % len(source)
            cross_page += address // 24 != index // 24
        value = source[address] if valid else 0
        rgba = (value, value, value, 255)
        error = max(abs(pixel[channel] - rgba[channel]) for pixel in pixels for channel in range(4))
        failures += error != 0
        maximum = max(maximum, error)
        center_rgba = list(image.getpixel(tuple(center)))
        if valid:
            targets.add(address)
            observed.append(center_rgba[0])
            expected.append(value)
        else:
            padding += 1
        results.append({'index': index, 'payload': valid, 'address': address,
                        'expected': value, 'observed_rgba': center_rgba,
                        'center': center, 'patch_width': patch_width, 'max_error': error})
    return {'passed': failures == 0, 'exact_equal': failures == 0,
            'mode': mode, 'start': start, 'count': count, 'salt': salt,
            'columns': COLUMNS, 'rows': rows, 'capture_size': list(image.size),
            'checked_cells': len(results), 'checked_pixels': len(results) * 9,
            'failed_cells': failures, 'max_error': maximum, 'padding_cells': padding,
            'verified_query_count': len(observed), 'unique_target_count': len(targets),
            'cross_page_queries': cross_page,
            'observed_query_sha256': hashlib.sha256(observed).hexdigest(),
            'expected_query_sha256': hashlib.sha256(expected).hexdigest(),
            'results': results}, bytes(observed), bytes(expected), targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--bytes', type=int, default=96)
    parser.add_argument('--seed', type=int, default=54321)
    parser.add_argument('--reuse-config', type=Path,
                        help='Reuse this resident configuration without registration, finish or an initial write')
    parser.add_argument('--seconds', type=float, default=8.0,
                        help='0 skips the benchmark; otherwise 2 to 30 seconds')
    parser.add_argument('--static', action='store_true')
    parser.add_argument('--frozen-only', action='store_true',
                        help='Keep the existing generation; do not write additional full datasets')
    args = parser.parse_args()
    if (not re.fullmatch('[a-z0-9_]+', args.name) or args.bytes < 1 or
            not math.isfinite(args.seconds) or
            (args.seconds != 0 and not 2 <= args.seconds <= 30)):
        parser.error('Use a simple ASCII name, a positive byte count and duration 0 or 2..30')
    if args.reuse_config is not None and args.seconds != 0:
        parser.error('--reuse-config requires --seconds 0 to preserve the resident generation')
    evidence = args.evidence.resolve()
    commands = evidence / 'commands'
    commands.mkdir(parents=True, exist_ok=True)
    if list(evidence.glob(args.name + '.*')) or list(commands.glob(args.name + '_*.py')):
        raise ValueError('Preserve previous evidence; choose a new case name')
    namespace = 'isolated_' + uuid.uuid4().hex[:16]
    token = uuid.uuid4().hex
    config, receipt, run = {}, {}, None
    generations, recoveries, failure_state, cleanup = [], [], None, None
    stage, error = 'configuration', None
    final_seed, benchmark_attempted = args.seed, False
    diagnostic_hidden = False

    def host(action, label, code=None):
        command = [sys.executable, '-B', '-X', 'utf8', str(HERE / 'host.py'), action,
                   '--project', str(args.project.resolve()), '--evidence', str(evidence),
                   '--label', label, '--timeout', str(HOST_TIMEOUT)]
        if code is not None:
            path = commands / (label + '.py')
            if path.exists():
                raise ValueError('Refusing to replay a saved host command: ' + label)
            path.write_text(code, encoding='utf-8')
            command += ['--code', str(path)]
        with (evidence / (label + '.' + action + '.log')).open('w', encoding='utf-8') as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT,
                           timeout=HOST_TIMEOUT + 10.0)
        if action == 'call':
            return json.loads((evidence / (label + '.state.json')).read_text(encoding='utf-8'))
        capture = json.loads((evidence / (label + '.json')).read_text(encoding='utf-8'))
        allowed_capture = (capture.get('background_only') is True or
                           (capture.get('user_foreground_allowed') is True and
                            capture.get('agent_activation_allowed') is False))
        if (capture.get('ok') is not True or not allowed_capture or
                capture['frame_qpc_100ns'] < capture['request_qpc_100ns']):
            raise ValueError('Capture lacks fresh, owner-protected background WGC provenance')
        return capture

    def initial_call(label, code, must_be_ready):
        """On a lost response only inspect state; never replay the mutation."""
        try:
            return host('call', label, code)
        except FAILURES as failure:
            recovery = {'operation': label, 'error': '%s: %s' % (type(failure).__name__, failure)}
            recoveries.append(recovery)
            state = host('call', label + '_inspect', _snapshot_code(require_ready=False))
            recovery['state'] = state
            if (state.get('case_namespace') != namespace or state.get('error') is not None or
                    (must_be_ready and state.get('ready') is not True)):
                raise RuntimeError('Initial host operation failed; retained its inspected state') from failure
            return state

    try:
        if args.reuse_config is not None:
            config = json.loads(args.reuse_config.resolve().read_text(encoding='utf-8'))
            namespace = config['namespace']
            if not isinstance(namespace, str) or re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', namespace) is None:
                raise ValueError('Reused configuration has an invalid namespace')
        else:
            from isolated_assets import isolated_config
            config = isolated_config(payload_bytes=args.bytes, namespace=namespace)
        if config['payload_bytes'] != args.bytes or config['pages'] != (args.bytes + 23) // 24:
            raise ValueError('Generated atlas must retain the exact requested byte length')
        _write_json(evidence / (args.name + '.config.json'), config)
        if args.reuse_config is not None:
            stage = 'reuse_resident_snapshot'
            receipt = host('call', args.name + '_reuse', _snapshot_code())
        else:
            stage = 'register'
            registration = ("from packet_probe.isolated_runtime import IsolatedProbe\n"
                            "probe.close()\n"
                            "_config=json.loads(%r)\n"
                            "try:\n"
                            "    probe.aggregation=IsolatedProbe(probe.post,_config,%d)\n"
                            "except Exception as _error:\n"
                            "    probe.aggregation=getattr(_error,'aggregate_probe',None)\n"
                            "    raise\n" % (json.dumps(config), args.seed))
            receipt = initial_call(args.name + '_register',
                                   registration + _snapshot_code(require_ready=False), False)
            stage = 'finish'
            receipt = initial_call(args.name + '_finish',
                                   _snapshot_code('probe.aggregation.finish()\n',
                                                  require_ready=False, hide_crosshair=True), True)
        words, source = _payload(args.seed, config['pages'], args.bytes)
        _validate_snapshot(receipt, config, words, namespace)
        if args.seconds:
            stage = 'benchmark_start'
            benchmark_attempted = True
            host('call', args.name + '_benchmark',
                 "if probe.run is not None:\n"
                 "    raise RuntimeError('Benchmark already running')\n"
                 "probe.aggregation.select(0,0,%d,7)\n"
                 "_started=probe.start_aggregate(%r,%r,%d)\n"
                 "probe.run['isolated_case_token']=%r\n"
                 "_result=json.dumps(_started)\n" %
                 (min(WINDOW_BYTES, args.bytes), args.seconds, not args.static, args.seed, token))
            stage = 'benchmark_wait'
            deadline = time.monotonic() + args.seconds + HOST_TIMEOUT
            time.sleep(args.seconds + 0.25)
            attempt = 0
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Owned isolated benchmark did not finish before its deadline')
                state = host('call', args.name + '_benchmark_end_%d' % attempt,
                             '_result=json.dumps(probe.snapshot())\n')
                if not state['running']:
                    run = state['last_run']
                    break
                attempt += 1
                time.sleep(1.0)
            if (not run or not run.get('success') or
                    run.get('isolated_case_token') != token):
                raise RuntimeError('Benchmark failed or belongs to another case: ' + repr(run))
            if not args.static:
                final_seed += run['frames'] * 97

        generation_count = 1 if args.frozen_only else (3 if args.bytes <= WINDOW_BYTES else 2)
        for generation_index in range(generation_count):
            seed = final_seed + generation_index * 1000003
            words, source = _payload(seed, config['pages'], args.bytes)
            full = generation_index == 0 or args.bytes <= WINDOW_BYTES
            generation = {'index': generation_index, 'seed': seed,
                          'scope': 'full_frozen_payload' if full else 'first_middle_last_samples',
                          'requested_payload_bytes': args.bytes,
                          'source_sha256': hashlib.sha256(source).hexdigest(),
                          'modes': [], 'passed': False}
            generations.append(generation)
            stage = 'generation_%d_freeze' % generation_index
            body = '' if generation_index == 0 else 'probe.aggregation.write(%d)\n' % seed
            receipt = host('call', args.name + '_g%d_frozen' % generation_index, _snapshot_code(body))
            _validate_snapshot(receipt, config, words, namespace)
            names = receipt.get('process_names')
            if not names:
                raise ValueError('Frozen payload receipt omitted its producer/consumer identities')
            if full:
                starts = list(range(0, args.bytes, WINDOW_BYTES))
            else:
                starts = sorted(set((0, (args.bytes // 2 // 24) * 24,
                                     max(0, args.bytes - WINDOW_BYTES))))
            for mode in (1, 2):
                seen, targets = set(), set()
                observed_hash, expected_hash = hashlib.sha256(), hashlib.sha256()
                mode_report = {'mode': mode, 'windows': [], 'passed': False}
                generation['modes'].append(mode_report)
                cross_page = 0
                for window_index, start in enumerate(starts):
                    count = min(WINDOW_BYTES, args.bytes - start)
                    label = args.name + '_g%d_m%d_w%03d' % (generation_index, mode, window_index)
                    stage = 'window_snapshot:' + label
                    query = [mode, start, count, 7]
                    state = host('call', label, _snapshot_code(
                        'probe.aggregation.select(%d,%d,%d,7)\n' % (mode, start, count)))
                    _validate_snapshot(state, config, words, namespace, query)
                    if state.get('process_names') != names:
                        raise ValueError('Consumer or producer identity changed during the frozen scan')
                    state.update(expected_seed=seed, generation_index=generation_index)
                    state_path = evidence / (label + '.state.json')
                    _write_json(state_path, state)
                    stage = 'window_capture:' + label
                    host('capture', label)
                    stage = 'window_verification:' + label
                    with Image.open(evidence / (label + '.png')) as image:
                        result, observed, expected, addresses = verify_window(
                            state, image, source, mode, start, count)
                    result.update(label=label, expected_seed=seed,
                                  receipt_sha256=_sha256(state_path),
                                  capture_sha256=_sha256(evidence / (label + '.png')),
                                  provenance_sha256=_sha256(evidence / (label + '.json')))
                    _write_json(evidence / (label + '.verify.json'), result)
                    summary = {key: value for key, value in result.items() if key != 'results'}
                    summary['verification_sha256'] = _sha256(evidence / (label + '.verify.json'))
                    mode_report['windows'].append(summary)
                    if not result['passed']:
                        raise ValueError('Exact 3x3 RGBA comparison failed: ' + label)
                    if full and seen.intersection(range(start, start + count)):
                        raise ValueError('Full-scan windows overlap')
                    seen.update(range(start, start + count))
                    targets.update(addresses)
                    cross_page += result['cross_page_queries']
                    observed_hash.update(observed)
                    expected_hash.update(expected)
                    print(json.dumps({'name': args.name, 'generation': generation_index,
                                      'mode': mode, 'window': window_index + 1,
                                      'verified_query_addresses': len(seen),
                                      'payload_bytes': args.bytes}), flush=True)
                hashes_equal = observed_hash.hexdigest() == expected_hash.hexdigest()
                complete = len(seen) == args.bytes and min(seen) == 0 and max(seen) == args.bytes - 1
                mode_report.update(passed=hashes_equal and (complete or not full),
                                   verified_query_addresses=len(seen), unique_target_addresses=len(targets),
                                   cross_page_queries=cross_page, full_query_coverage=complete,
                                   observed_query_sha256=observed_hash.hexdigest(),
                                   expected_query_sha256=expected_hash.hexdigest(),
                                   full_payload_identity_verified=full and mode == 1 and complete and hashes_equal)
                if (not mode_report['passed'] or (mode == 2 and args.bytes > 24 and cross_page == 0)):
                    raise ValueError('Frozen scan lacks complete coverage, matching hashes or cross-page reads')
                if full and mode == 1 and expected_hash.hexdigest() != generation['source_sha256']:
                    raise ValueError('Identity digest differs from the exact unpadded payload')
            terminal = host('call', args.name + '_g%d_terminal' % generation_index, _snapshot_code())
            _validate_snapshot(terminal, config, words, namespace)
            if terminal.get('process_names') != names:
                raise ValueError('Payload identities changed before the terminal frozen-state check')
            generation['passed'] = all(mode['passed'] for mode in generation['modes'])
            _write_json(evidence / (args.name + '.progress.json'), {'generations': generations})

        stage = 'hide_diagnostic'
        receipt = host('call', args.name + '_hidden', _snapshot_code(
            'probe.aggregation.select(0,0,%d,7)\n' % min(WINDOW_BYTES, args.bytes)))
        _validate_snapshot(receipt, config, words, namespace, [0, 0, min(WINDOW_BYTES, args.bytes), 7])
        host('capture', args.name + '_hidden')
        diagnostic_hidden = True
        stage = 'completed'
    except FAILURES as failure:
        error = '%s: %s' % (type(failure).__name__, failure)
        try:
            failure_state = host('call', args.name + '_failure',
                                 '_result=json.dumps(probe.snapshot())\n')
        except FAILURES as inspection_error:
            failure_state = {'error': '%s: %s' % (type(inspection_error).__name__, inspection_error)}
        if benchmark_attempted:
            try:
                cleanup = host('call', args.name + '_abort',
                               "_aborted=False\n"
                               "if probe.run is not None and probe.run.get('isolated_case_token')==%r:\n"
                               "    probe._finish_run('aborted','Isolated case failed or timed out')\n"
                               "    _aborted=True\n"
                               "_result=json.dumps({'aborted_owned_run':_aborted,'state':probe.snapshot()})\n" % token)
            except FAILURES as cleanup_error:
                cleanup = {'error': '%s: %s' % (type(cleanup_error).__name__, cleanup_error)}

    passed = bool(error is None and generations and all(item['passed'] for item in generations))
    result = {'name': args.name, 'namespace': namespace, 'status': 'completed' if passed else 'failed',
              'stage': stage, 'error': error, 'payload_bytes': args.bytes,
              'pages': config.get('pages'), 'screen_size': config.get('screen_size'),
              'target_pixels': config.get('target_pixels'), 'config': args.name + '.config.json',
              'benchmark_seconds': args.seconds, 'benchmark_run': run,
              'dynamic': bool(args.seconds and not args.static),
              'continuous_updates_exercised': bool(run and run.get('success') and not args.static),
              'continuous_generation_correctness_verified': False,
              'initial_frozen_seed': final_seed, 'generations': generations,
              'all_resident_bytes_verified': bool(passed and generations[0]['modes'][0].get(
                  'full_payload_identity_verified')), 'exact_equal': passed,
              'whole_payload_simultaneously_resident': passed,
              'additional_generation_scope': ('none_frozen_only' if args.frozen_only else
                  ('two_full_generations' if args.bytes <= WINDOW_BYTES
                   else 'second_generation_first_middle_last_samples_only')),
              'diagnostic_hidden': diagnostic_hidden,
              'native_crosshair_hidden': receipt.get('native_crosshair_hidden') is True,
              'saved_scene_color_preservation_verified': False,
              'all_render_frames_verified': False, 'gpu_to_python_readback': False,
              'actual_mobile_hardware': False, 'automatic_mutation_replays': 0,
              'reused_resident_payload': args.reuse_config is not None,
              'reuse_config': str(args.reuse_config.resolve()) if args.reuse_config is not None else None,
              'initial_response_recoveries': recoveries, 'failure_state': failure_state, 'cleanup': cleanup}
    config_path = evidence / (args.name + '.config.json')
    if config_path.exists():
        result['config_sha256'] = _sha256(config_path)
    _write_json(evidence / (args.name + '.case.json'), result)
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ('benchmark_run', 'generations', 'failure_state', 'cleanup',
                                     'initial_response_recoveries')}), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
