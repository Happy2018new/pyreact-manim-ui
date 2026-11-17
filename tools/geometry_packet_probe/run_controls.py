"""Native freeze/update controls: new CPU bytes cannot change retained geometry."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image
from verify_capture import verify_image, verify_reports, verify_transition

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    destination = evidence / 'freeze-update-controls.json'
    if destination.exists():
        raise ValueError('Preserve existing controls evidence')
    subprocess.run([sys.executable, '-B', '-X', 'utf8', str(HERE / 'run_case.py'),
                    '--project', str(args.project.resolve()), '--evidence', str(evidence),
                    '--name', 'control_initial', '--bytes', '3072', '--generation', '100',
                    '--verify-only'], check=True)
    commands = evidence / 'commands'

    def host(action, label, code=None):
        command = [sys.executable, '-B', '-X', 'utf8', str(HERE / 'host.py'), action,
                   '--project', str(args.project.resolve()), '--evidence', str(evidence),
                   '--label', label, '--timeout', '90']
        if code is not None:
            source = commands / (label + '.py')
            source.write_text("probe=api.GetSystem('pmanim_geometry_packet_probe','probe')\n" + code,
                              encoding='utf-8')
            command += ['--code', str(source)]
        with (evidence / (label + '.' + action + '.log')).open('w', encoding='utf-8') as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=105.)
        if action == 'call':
            return json.loads((evidence / (label + '.state.json')).read_text(encoding='utf-8'))

    def captured(label):
        host('capture', label)
        receipt = json.loads((evidence / (label + '.state.json')).read_text(encoding='utf-8'))
        with Image.open(evidence / (label + '.png')) as image:
            report = verify_image(receipt, image)
        (evidence / (label + '.verify.json')).write_text(json.dumps(report, separators=(',', ':')),
                                                      encoding='utf-8')
        return receipt, report

    initial = json.loads((evidence / 'control_initial.case.json').read_text(encoding='utf-8'))['verification']
    frozen = host('call', 'control_frozen',
                  "from geometry_packet_probe.runtime import byte_at\n"
                  "probe.pending_cpu_bytes=bytearray(byte_at(probe.seed,101,i) for i in range(3072))\n"
                  "probe.query(0,3072,64)\n_state=probe.snapshot()\n"
                  "_state['source_generation']=101\n"
                  "_state['pending_cpu_count']=len(probe.pending_cpu_bytes)\n"
                  "_state['pending_cpu_sum']=sum(probe.pending_cpu_bytes)\n_result=json.dumps(_state)\n")
    frozen_receipt, frozen_report = captured('control_frozen')
    frozen_full = verify_reports([(frozen_receipt, frozen_report)])
    freeze = verify_transition(initial, frozen_full, False)
    wrong_receipt = dict(frozen_receipt, generation=101)
    with Image.open(evidence / 'control_frozen.png') as image:
        wrong_generation = verify_image(wrong_receipt, image)
    host('call', 'control_updated_submit',
         "probe.load(3072,seed=54321,generation=101)\n_result=json.dumps(probe.snapshot())\n")
    time.sleep(2.)
    host('call', 'control_updated',
         'probe.query(0,3072,64)\n_result=json.dumps(probe.snapshot())\n')
    updated_receipt, updated_report = captured('control_updated')
    updated_full = verify_reports([(updated_receipt, updated_report)])
    update = verify_transition(frozen_full, updated_full, True)
    summary = {'passed': freeze['passed'] and update['passed'] and not wrong_generation['passed'],
               'payload_bytes': 3072, 'cpu_source_generation': frozen['source_generation'],
               'pending_cpu_count': frozen['pending_cpu_count'], 'freeze': freeze, 'update': update,
               'new_cpu_generation_on_old_geometry_rejected': not wrong_generation['passed'],
               'wrong_generation_failed_cells': wrong_generation['failed_cells'],
               'initial': initial, 'frozen': frozen_full, 'updated': updated_full,
               'all_render_frames_verified': False, 'gpu_to_python_readback': False}
    for key in ('frozen', 'updated'):
        summary[key] = {name: value for name, value in summary[key].items()
                        if name not in ('observed_bytes', 'expected_bytes')}
    destination.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({'passed': summary['passed'], 'evidence': str(destination)}))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
