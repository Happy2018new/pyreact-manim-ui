"""Explicit same-instance continuation after preserved offscreen-guard failure."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

from runner import Experiment, HERE, LAYOUTS
from verify import payload_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path, required=True)
    args = parser.parse_args()
    original_path = args.previous_evidence/'results.json'
    original_bytes = original_path.read_bytes()
    original = json.loads(original_bytes)
    failed = original['reports'][-1]
    if (failed['label'] != 'n262144_clear_t0_m1' or failed['data_error_pixels'] != 0
            or failed['guard_error_pixels'] != 81000 or failed['exact']):
        raise RuntimeError('Expected the preserved offscreen guard failure')
    args.evidence.mkdir(exist_ok=False)
    shutil.copyfile(args.previous_evidence/'launch.json', args.evidence/'launch.json')
    experiment = Experiment(args)
    failure = None
    try:
        size = 262144
        experiment.viewport, experiment.roi = LAYOUTS[size]
        experiment.payload = payload_bytes(size)
        state = experiment.call('same_instance_initial')
        if state['identity'] != failed['state']['identity'] or state['active_pages'] != failed['state']['active_pages']:
            raise RuntimeError('Frozen input or resident pages differ from original instance')
        experiment.loads.append(original['loads'][-1])
        experiment.invoke([sys.executable, '-B', '-X', 'utf8', str(HERE/'center.py'),
                           '--project', str(args.project.resolve()), '--evidence', str(args.evidence.resolve())], 'center_owned')
        for slot in (0, 1):
            for mode in (1, 2, 3):
                experiment.capture('n262144_clear_t%d_m%d' % (slot, mode), mode, slot)
        experiment.capture('n262144_hidden_negative', 1, hide=True, expected=False)
        experiment.capture('n262144_return_positive', 1)
        experiment.restoration('n262144')
        experiment.weather('n262144_rain_on', True)
        wet = []
        for slot in (0, 1):
            for mode in (1, 2, 3):
                report = experiment.capture('n262144_wet_t%d_m%d' % (slot, mode), mode, slot)
                if mode == 3:
                    wet.append(report)
        if not any(report['alpha_not255_pixels'] for report in wet):
            raise RuntimeError('Wet same-fetch alpha witness missing')
        experiment.weather('n262144_rain_off', False)
        experiment.capture('n262144_clear_return', 1)
        for mode in ('baseline', 'restore', 'dependent'):
            experiment.measure('n262144', mode)
        for mode in (1, 2, 3):
            experiment.capture('n262144_posttiming_m%d' % mode, mode)
            if (experiment.state['identity'] != state['identity']
                    or experiment.state['active_pages'] != state['active_pages']):
                raise RuntimeError('Post-timing input or pages changed')
        experiment.call('n262144_timing_off', "probe.configure('off')\nprobe.inspect(0,0,True)")
        experiment.suite(524288)
        experiment.call('final_hidden', "probe.configure('off')\nprobe.inspect(0,0,False)")
    except Exception as error:
        failure = repr(error)
        raise
    finally:
        experiment.save()
        (args.evidence/'continuation-status.json').write_text(json.dumps({
            'reason': 'Full payload exact; bottom75guardrows offscreen. Center owned normal window without activation, then full recheck.',
            'previous_results_file': str(original_path.resolve()),
            'previous_results_sha256': hashlib.sha256(original_bytes).hexdigest(),
            'previous_results_unchanged': original_path.read_bytes() == original_bytes,
            'failure': failure, 'rain_reversion_required': experiment.weather_is_raining,
            'last_state': experiment.state,
            'source_hashes': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in HERE.iterdir() if path.is_file()}}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
