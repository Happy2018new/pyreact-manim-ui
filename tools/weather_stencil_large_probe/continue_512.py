"""Reuse the frozen512KiB allocation with diagnostic output below native debug text."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from runner import Experiment, HERE, LAYOUTS
from verify import payload_bytes


class Resident512(Experiment):
    def load(self, size):
        if size != 524288:
            raise ValueError('Only the existing512KiB allocation is accepted')
        self.viewport, self.roi = LAYOUTS[size]
        self.payload = payload_bytes(size)
        state = self.call('same_instance_initial')
        if (state['identity'] != self.previous['state']['identity']
                or state['active_pages'] != self.previous['state']['active_pages']
                or state['logical_bytes'] != size or state['state'] != 'resident'):
            raise RuntimeError('Frozen512KiB input or resident pages changed')
        self.memory('resident512_continuation', True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path, required=True)
    args = parser.parse_args()
    prior_path = args.previous_evidence/'results.json'
    prior_bytes = prior_path.read_bytes()
    prior = json.loads(prior_bytes)
    failed = prior['reports'][-1]
    if (failed['label'] != 'n524288_clear_t0_m1' or failed['data_error_pixels'] != 3787
            or failed['guard_error_pixels'] != 0 or failed['exact']):
        raise RuntimeError('Expected the preserved native debug overlay failure')
    args.evidence.mkdir(exist_ok=False)
    shutil.copyfile(args.previous_evidence/'launch.json', args.evidence/'launch.json')
    experiment = Resident512(args)
    experiment.previous = failed
    experiment.output_y = 128
    experiment.loads.append(prior['loads'][-1])
    failure = None
    try:
        experiment.suite(524288)
        experiment.call('final_hidden', "probe.configure('off')\nprobe.inspect(0,0,False)")
    except Exception as error:
        failure = repr(error)
        raise
    finally:
        experiment.save()
        (args.evidence/'continuation-status.json').write_text(json.dumps({
            'reason': 'Native debug worldname text overlays outputY76..91 after post. New output origin[0,128] verifies every payload address and all new guards.',
            'previous_results_file': str(prior_path.resolve()),
            'previous_results_sha256': hashlib.sha256(prior_bytes).hexdigest(),
            'previous_results_unchanged': prior_path.read_bytes() == prior_bytes,
            'packaged_shader_and_runtime_unchanged': True,
            'diagnostic_output_origin': [0, 128], 'timing_dependent_output_origin': [0, 64],
            'failure': failure, 'rain_reversion_required': experiment.weather_is_raining,
            'last_state': experiment.state,
            'source_hashes': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in HERE.iterdir() if path.is_file()}}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
