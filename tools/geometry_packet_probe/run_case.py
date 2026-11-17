"""Measure geometry-packet transport and audit one frozen resident dataset."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from PIL import Image

from verify_capture import verify_image, verify_reports


HERE = Path(__file__).resolve().parent
SYSTEM = 'pmanim_geometry_packet_probe'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--bytes', type=int, required=True, dest='byte_count')
    parser.add_argument('--seed', type=int, default=54321)
    parser.add_argument('--generation', type=int, default=1)
    parser.add_argument('--seconds', type=float, default=8.)
    parser.add_argument('--dynamic', action='store_true')
    parser.add_argument('--encoding', choices=('legacy8','compact8'), default='compact8')
    parser.add_argument('--policy', choices=('single','double','fresh'), default='fresh')
    parser.add_argument('--updates',type=int,default=64)
    parser.add_argument('--interval-frames',type=int,default=1)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--window', type=int, default=4096)
    parser.add_argument('--settle', type=float, default=2.)
    args = parser.parse_args()
    if (not re.fullmatch('[a-z0-9_]+', args.name) or args.byte_count < 1 or
            not 1 <= args.window <= 4096 or not 2 <= args.seconds <= 30 or
            not 1<=args.updates<=256 or not 1<=args.interval_frames<=120):
        parser.error('Invalid case name, payload length, window or duration')
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    commands = evidence / 'commands'
    commands.mkdir(exist_ok=True)
    case_path = evidence / (args.name + '.case.json')
    if case_path.exists() or (commands / (args.name + '_load.py')).exists():
        raise ValueError('Keep previous evidence; choose a new case name')

    def host(action, label, code=None, timeout=120.):
        command = [sys.executable, '-B', '-X', 'utf8', str(HERE / 'host.py'), action,
                   '--project', str(args.project.resolve()), '--evidence', str(evidence),
                   '--label', label, '--timeout', str(timeout)]
        if code is not None:
            path = commands / (label + '.py')
            path.write_text("probe=api.GetSystem(%r,'probe')\n" % SYSTEM + code,
                            encoding='utf-8')
            command += ['--code', str(path)]
        with (evidence / (label + '.' + action + '.log')).open('w', encoding='utf-8') as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT,
                           timeout=timeout + 15.)
        if action == 'call':
            return json.loads((evidence / (label + '.state.json')).read_text(encoding='utf-8'))

    stage, failure, state, benchmark, reports, pairs = 'open', None, {}, None, [], []
    started = time.monotonic()
    try:
        state = host('call', args.name + '_open',
                     "if probe is None:\n    raise RuntimeError('Geometry probe is not registered')\n"
                     "if api.HideCrossHairGUI(True) is not True:\n"
                     "    raise RuntimeError('Native crosshair hide rejected')\n"
                     "probe.open()\n_result=json.dumps(probe.snapshot())\n")
        for attempt in range(15):
            if state.get('ready'):
                break
            time.sleep(.2)
            state = host('call', args.name + '_ready_%d' % attempt,
                         '_result=json.dumps(probe.snapshot())\n')
        if not state.get('ready'):
            raise RuntimeError('Geometry screen never reached Create')
        stage = 'load'
        state = host('call', args.name + '_load',
                     "if probe.snapshot().get('benchmark_running'):\n"
                     "    raise RuntimeError('Finish the current benchmark before a new dataset')\n"
                     "probe.begin_dataset(encoding=%r)\n"
                     "probe.configure_updates(name_policy=%r,interval_frames=%d,max_updates=%d)\n"
                     "probe.load(%d,seed=%d,generation=%d)\n_result=json.dumps(probe.snapshot())\n" %
                     (args.encoding,args.policy,args.interval_frames,args.updates,
                      args.byte_count, args.seed, args.generation))
        time.sleep(args.settle)
        if not args.verify_only:
            stage = 'benchmark'
            state = host('call', args.name + '_start',
                         "probe.start(seconds=%r,dynamic=%r,seed=%d)\n_result=json.dumps(probe.snapshot())\n" %
                         (args.seconds, args.dynamic, args.seed))
            time.sleep(args.seconds + .5)
            deadline = time.monotonic() + 45.
            poll = 0
            while True:
                state = host('call', args.name + '_end_%d' % poll,
                             '_result=json.dumps(probe.snapshot())\n')
                if not state.get('benchmark_running'):
                    benchmark = state.get('last_run')
                    if benchmark is None or benchmark.get('error'):
                        raise RuntimeError('Benchmark failed: ' + repr(benchmark))
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Geometry benchmark did not finish')
                time.sleep(1.)
                poll += 1
        stage = 'freeze'
        time.sleep(args.settle)
        frozen = host('call', args.name + '_frozen', '_result=json.dumps(probe.snapshot())\n')
        if frozen.get('benchmark_running') or frozen['slot_count'] != args.byte_count:
            raise ValueError('Dataset is still changing or has the wrong size')
        frozen_keys = ('schema', 'seed', 'generation', 'slot_count', 'geometry_name', 'geometry_build_serial')
        for window_index, start in enumerate(range(0, args.byte_count, args.window)):
            count = min(args.window, args.byte_count - start)
            label = args.name + '_window_%04d' % window_index
            stage = 'query:' + str(start)
            state = host('call', label,
                         "if probe.snapshot().get('benchmark_running'):\n"
                         "    raise RuntimeError('Payload must be frozen')\n"
                         "probe.query(%d,%d,64)\n_result=json.dumps(probe.snapshot())\n" % (start, count))
            if any(state[key] != frozen[key] for key in frozen_keys):
                raise ValueError('Resident geometry changed while only query parameters were updated')
            stage = 'capture:' + str(start)
            host('capture', label)
            with Image.open(evidence / (label + '.png')) as source:
                image = source.convert('RGBA')
            stage = 'verify:' + str(start)
            report = verify_image(state, image)
            (evidence / (label + '.verify.json')).write_text(json.dumps(report, separators=(',', ':')),
                                                          encoding='utf-8')
            reports.append({key: value for key, value in report.items()
                            if key not in ('results', 'observed_bytes', 'expected_bytes', 'indices',
                                           'verified_indices', 'verified_slot_indices', 'centers')})
            pairs.append((state, report))
            if not report['passed']:
                raise ValueError('Geometry bytes did not match the independent oracle: ' + label)
            print(json.dumps({'name': args.name, 'verified_bytes': start + count,
                              'resident_bytes': args.byte_count}), flush=True)
        stage = 'complete_coverage'
        series = verify_reports(pairs)
        series = {key: value for key, value in series.items()
                  if key not in ('observed_bytes', 'expected_bytes', 'reports', 'verified_slot_indices')}
        if not series['passed']:
            raise ValueError('Complete resident-dataset audit failed')
        stage = 'completed'
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        failure = '%s: %s' % (type(error).__name__, error)
        series = None
    result = {'name': args.name, 'payload_bytes': args.byte_count, 'dynamic': args.dynamic,
              'encoding':args.encoding,'name_policy':args.policy,
              'verify_only': args.verify_only, 'status': 'completed' if failure is None else 'failed',
              'stage': stage, 'error': failure, 'elapsed_host_seconds': time.monotonic() - started,
              'final_snapshot': state, 'benchmark': benchmark, 'windows': reports,
              'verification': series, 'whole_payload_simultaneously_resident': failure is None,
              'all_render_frames_verified': False, 'gpu_to_python_readback': False,
              'actual_mobile_hardware': False}
    case_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'name': args.name, 'status': result['status'], 'stage': stage, 'error': failure,
                      'payload_bytes': args.byte_count, 'case': str(case_path)}))
    return 0 if failure is None else 1


if __name__ == '__main__':
    raise SystemExit(main())
