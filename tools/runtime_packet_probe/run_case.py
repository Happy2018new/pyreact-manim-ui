"""Measure an owned probe case, then verify every declared payload byte."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--kind', choices=('ui', 'aggregate'), required=True)
    parser.add_argument('--count', type=int, default=8)
    parser.add_argument('--mode', type=int, choices=(0, 1), default=0)
    parser.add_argument('--seconds', type=float, default=12.)
    parser.add_argument('--static', action='store_true')
    parser.add_argument('--seed', type=int, default=54321)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9_]+', args.name):
        parser.error('name must use lowercase ASCII letters, digits and underscores')
    if not 2 <= args.seconds <= 30:
        parser.error('seconds must be between 2 and 30')
    project, evidence = args.project.resolve(), args.evidence.resolve()
    commands = evidence / 'commands'
    commands.mkdir(parents=True, exist_ok=True)
    result_path = evidence / (args.name + '.case.json')
    if result_path.exists() or (evidence / (args.name + '_start.state.json')).exists():
        raise ValueError('Preserve existing evidence; choose a new case name')

    def call(label, code):
        path = commands / (label + '.py')
        path.write_text(code, encoding='utf-8')
        subprocess.run([sys.executable, '-B', '-X', 'utf8', str(HERE / 'host.py'),
                        'call', '--project', str(project), '--evidence', str(evidence),
                        '--code', str(path), '--label', label], check=True,
                       stdout=subprocess.DEVNULL)
        return json.loads((evidence / (label + '.state.json')).read_text(encoding='utf-8'))

    if args.kind == 'ui':
        code = ('probe.open()\n_result=json.dumps(probe.start(%d,%d,%r,%r,%d))\n' %
                (args.count, args.mode, args.seconds, not args.static, args.seed))
    else:
        code = 'probe.aggregation.write(%d)\n' % args.seed
        code += '_result=json.dumps(probe.start_aggregate(%r,%r,%d))\n' % (
            args.seconds, not args.static, args.seed)
    call(args.name + '_start', code)
    deadline = time.monotonic() + args.seconds + 45.
    time.sleep(args.seconds + .5)
    iteration = 0
    while True:
        state = call(args.name + '_end_%d' % iteration, '_result=json.dumps(probe.snapshot())\n')
        if not state['running']:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError('Owned probe did not finish; inspect before retrying')
        iteration += 1
        time.sleep(1.)
    run = state['last_run']
    if not run or run.get('success') is not True:
        raise RuntimeError('Benchmark failed: ' + repr(run))
    receipt = call(args.name, '_result=json.dumps(probe.%s.snapshot())\n' % (
        'screen' if args.kind == 'ui' else 'aggregation'))
    capture_command = [sys.executable, '-B', '-X', 'utf8', str(HERE / 'host.py'),
                       'capture', '--project', str(project), '--evidence', str(evidence),
                       '--label', args.name]
    with (evidence / (args.name + '.capture.log')).open('w', encoding='utf-8') as output:
        subprocess.run(capture_command, check=True, stdout=output)
    from verify_capture import verify_image
    from PIL import Image
    # Import the same fixed-coordinate oracle used by the standalone CLI.
    with Image.open(evidence / (args.name + '.png')) as image:
        verification = verify_image(receipt, image)
    for label, path in (('receipt', evidence / (args.name + '.state.json')),
                        ('capture', evidence / (args.name + '.png'))):
        verification[label + '_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (evidence / (args.name + '.verify.json')).write_text(
        json.dumps(verification, indent=2), encoding='utf-8')
    payload_bytes = (receipt['count'] * 9 if args.kind == 'ui' else
                     receipt['aggregate']['pages'] * receipt['aggregate']['words_per_page'] * 3)
    result = {'name': args.name, 'kind': args.kind, 'payload_bytes': payload_bytes,
              'dynamic': not args.static, 'run': run,
              'final_capture_verified': verification['passed'],
              'verification_scope': 'one_frozen_final_payload',
              'all_frames_verified': False, 'exact_equal': verification['exact_equal'],
              'checked_cells': verification['checked_cells'],
              'failed_cells': verification['failed_cells'], 'max_error': verification['max_error']}
    result_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({key: result[key] for key in (
        'name', 'payload_bytes', 'final_capture_verified', 'exact_equal', 'failed_cells')}, ensure_ascii=False))
    return 0 if verification['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
