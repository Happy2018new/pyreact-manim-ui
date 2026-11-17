"""Measure a prepared spatial chain and verify every resident byte on native WGC."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from PIL import Image
from verify_spatial import expected_words, verify_spatial


HERE = Path(__file__).resolve().parent


def _frozen_code(body='', hide_crosshair=False):
    """Keep the guard and snapshot in one client callback, before any mutation."""
    crosshair = ("_crosshair_hidden=api.HideCrossHairGUI(True)\n"
                 "if _crosshair_hidden is not True:\n"
                 "    raise RuntimeError('Native crosshair hide was rejected')\n"
                 if hide_crosshair else '')
    annotation = "_state['native_crosshair_hidden']=_crosshair_hidden\n" if hide_crosshair else ''
    return ("if probe.run is not None:\n"
            "    raise RuntimeError('Finish the active benchmark before spatial verification')\n"
            "if (probe.aggregation is None or not probe.aggregation.ready or\n"
            "        probe.aggregation.enabled is not True or probe.aggregation.error is not None):\n"
            "    raise RuntimeError('Spatial payload is not ready and enabled')\n" + crosshair + body +
            "_state=probe.aggregation.snapshot()\n"
            "_state['runner_running']=probe.run is not None\n" + annotation +
            "_result=json.dumps(_state)\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--seconds', type=float, default=12.)
    parser.add_argument('--static', action='store_true')
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--word-shift', type=int, default=0)
    args = parser.parse_args()
    if not re.fullmatch('[a-z0-9_]+', args.name) or not 2 <= args.seconds <= 30:
        parser.error('Use a simple ASCII name and duration from 2 to 30 seconds')
    evidence = args.evidence.resolve()
    commands = evidence / 'commands'
    commands.mkdir(parents=True, exist_ok=True)
    if (evidence / (args.name + '.case.json')).exists() or (commands / (args.name + '_start.py')).exists():
        raise ValueError('Preserve previous evidence; choose a new name')

    def host(action, label, code=None, timeout=120.):
        command = [sys.executable, '-B', '-X', 'utf8', str(HERE / 'host.py'), action,
                   '--project', str(args.project.resolve()), '--evidence', str(evidence),
                   '--label', label, '--timeout', str(timeout)]
        if code is not None:
            path = commands / (label + '.py')
            path.write_text(code, encoding='utf-8')
            command += ['--code', str(path)]
        with (evidence / (label + '.' + action + '.log')).open('w', encoding='utf-8') as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT,
                           timeout=timeout + 10.)
        if action == 'call':
            return json.loads((evidence / (label + '.state.json')).read_text(encoding='utf-8'))

    seed, run, receipt, pages = 54321, None, {}, 0
    reports, verified, observed_digest, expected_digest = [], set(), hashlib.sha256(), hashlib.sha256()
    stage, error, cleanup = 'initialization', None, None
    native_crosshair_hidden = False
    token, benchmark_attempted = uuid.uuid4().hex, False
    try:
        receipt = host('call', args.name + '_start',
                       _frozen_code('probe.aggregation.write(%d)\n' % seed, hide_crosshair=True))
        native_crosshair_hidden = receipt.get('native_crosshair_hidden') is True
        if not native_crosshair_hidden:
            raise RuntimeError('Native crosshair hide was not confirmed')
        pages = receipt['aggregate']['pages']
        if not args.verify_only:
            stage = 'benchmark_start'
            benchmark_attempted = True
            host('call', args.name + '_benchmark',
                 "if probe.run is not None:\n"
                 "    raise RuntimeError('Benchmark already running')\n"
                 "_started=probe.start_aggregate(%r,%r,%d)\n"
                 "probe.run['spatial_case_token']=%r\n"
                 "_result=json.dumps(_started)\n" % (args.seconds, not args.static, seed, token))
            stage = 'benchmark_wait'
            deadline = time.monotonic() + args.seconds + 45.
            time.sleep(args.seconds + .5)
            attempt = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Owned spatial benchmark did not finish before its deadline')
                state = host('call', args.name + '_end_%d' % attempt,
                             '_result=json.dumps(probe.snapshot())\n', timeout=min(remaining, 120.))
                if not state['running']:
                    run = state['last_run']
                    break
                attempt += 1
                time.sleep(min(1., max(0., deadline - time.monotonic())))
            if run is None or not run.get('success'):
                raise RuntimeError('Benchmark did not complete successfully: ' + repr(run))
            if run.get('spatial_case_token') != token:
                raise RuntimeError('Completed benchmark does not belong to this spatial case')
            if not args.static:
                seed += run['frames'] * 97
        stage = 'frozen_payload'
        receipt = host('call', args.name + '_frozen', _frozen_code())
        if receipt['aggregate']['pages'] != pages or receipt['aggregate']['words'] != expected_words(seed, pages):
            raise ValueError('Frozen runtime payload disagrees with final frame generation')
        starts = range(0, pages, int(receipt['aggregate']['query'][2])) if receipt['transport'] == 'atlas2d' else [0]
        for index, start in enumerate(starts):
            label = args.name + '_window_%03d' % index
            stage = 'window_snapshot:' + label
            code = ''
            if receipt['transport'] == 'atlas2d':
                code += 'probe.aggregation.select(%d,%d,%d)\n' % (start, receipt['aggregate']['query'][2], args.word_shift)
            state = host('call', label, _frozen_code(code))
            if (state['transport'] != receipt['transport'] or state['aggregate']['pages'] != pages or
                    state['aggregate']['words'] != receipt['aggregate']['words']):
                raise ValueError('Resident payload changed between spatial windows')
            state['expected_seed'] = seed
            state_path = evidence / (label + '.state.json')
            state_path.write_text(json.dumps(state, indent=2), encoding='utf-8')
            stage = 'window_capture:' + label
            host('capture', label)
            stage = 'window_verification:' + label
            with Image.open(evidence / (label + '.png')) as image:
                result = verify_spatial(state, image)
            for kind, path in [('receipt', state_path), ('capture', evidence / (label + '.png'))]:
                result[kind + '_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            (evidence / (label + '.verify.json')).write_text(json.dumps(result, separators=(',', ':')), encoding='utf-8')
            summary = {key: value for key, value in result.items() if key != 'results'}
            summary['label'] = label
            reports.append(summary)
            if not result['passed']:
                raise ValueError('Spatial byte comparison failed: ' + label)
            for row in result['results']:
                if not row['payload']:
                    continue
                page = row['index']
                if page in verified:
                    raise ValueError('Duplicate page in spatial capture coverage')
                verified.add(page)
                observed_digest.update(bytes(rgb[0] for rgb in row['observed']))
                words = state['aggregate']['words'][page]
                shift = args.word_shift % 8 if receipt['transport'] == 'atlas2d' else 0
                words = words[shift:] + words[:shift]
                expected_digest.update(bytes(byte for word in words for byte in (word >> 16, (word >> 8) & 255, word & 255)))
            print(json.dumps({'name': args.name, 'window': index + 1, 'verified_pages': len(verified), 'total_pages': pages}), flush=True)
        stage = 'coverage'
        if verified != set(range(pages)) or observed_digest.hexdigest() != expected_digest.hexdigest():
            raise ValueError('Spatial page coverage or combined payload digest is incomplete')
        stage = 'completed'
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as failure:
        error = '%s: %s' % (type(failure).__name__, failure)
        if benchmark_attempted:
            try:
                cleanup = host('call', args.name + '_abort',
                               "_aborted=False\n"
                               "if probe.run is not None and probe.run.get('spatial_case_token')==%r:\n"
                               "    probe._finish_run('aborted','Spatial case failed or timed out')\n"
                               "    _aborted=True\n"
                               "_result=json.dumps({'aborted_owned_run':_aborted,'running':probe.run is not None,"
                               "'last_run':probe.last_run})\n" % token,
                               timeout=15.)
            except (OSError, RuntimeError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as failure:
                cleanup = {'error': '%s: %s' % (type(failure).__name__, failure)}
    complete = error is None and pages > 0 and verified == set(range(pages))
    result = {'name': args.name, 'transport': receipt.get('transport'), 'shader_mode': receipt.get('shader_mode'),
              'pages': pages, 'payload_bytes': pages * 24, 'payload_scalar_uniforms': pages * 8,
              'screen_size': receipt.get('screen_size'), 'target_pixels': receipt.get('target_pixels'),
              'dynamic': not args.static and not args.verify_only, 'run': run,
              'final_seed': seed, 'verified_pages': len(verified), 'all_resident_bytes_verified': complete,
              'exact_equal': complete, 'observed_payload_sha256': observed_digest.hexdigest(),
              'expected_payload_sha256': expected_digest.hexdigest(), 'windows': reports,
              'verification_scope': 'all_pages_of_one_frozen_resident_payload',
              'whole_payload_simultaneously_resident': complete, 'all_render_frames_verified': False,
              'gpu_to_python_readback': False, 'actual_mobile_hardware': False,
              'native_crosshair_hidden': native_crosshair_hidden,
              'status': 'completed' if complete else 'failed', 'stage': stage,
              'error': error, 'cleanup': cleanup}
    (evidence / (args.name + '.case.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key not in ('run', 'windows')}))
    return 0 if complete else 1


if __name__ == '__main__':
    raise SystemExit(main())
