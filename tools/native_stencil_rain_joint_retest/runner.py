"""Finite sheltered-rain joint retest on an already owned native session."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


joint = module('sheltered_rain_unchanged_joint', HERE.parent / 'native_stencil_joint_compat_candidate/runner.py')
scene = module('sheltered_rain_native_geometry', HERE / 'shelter_scene.py')


class Experiment(joint.Experiment):
    def __init__(self, args):
        super().__init__(args)
        self.shelter = scene.ShelterScene(self, joint)

    def call(self, label, code='', expression='probe.snapshot()'):
        if label == 'joint_ui_open':
            self.shelter.install()
        return super().call(label, code, expression)


def exposed_rain(report, roi):
    if report['mode'] != 3 or report['exact'] is not True:
        raise ValueError('Exposed rain witness requires the complete exact mode3 data PNG')
    x, y, width, height = scene.EXPOSED_RECT
    rx, ry, rw, rh = roi
    if not (rx <= x and ry <= y and x + width <= rx + rw and y + height <= ry + rh):
        raise ValueError('Exposed weather witness must be wholly within the source ROI')
    pixels = np.asarray(Image.open(report['capture_file']).convert('RGB'))
    indices = np.array([(py - ry) * rw + px - rx
                        for py in range(y, y + height) for px in range(x, x + width)])
    alpha = pixels[650 + indices // 720, indices % 720, 1]
    count = int(np.count_nonzero(alpha != 255))
    return {'source_rectangle': scene.EXPOSED_RECT, 'pixels': int(alpha.size),
            'alpha_non255': count, 'minimum_observed_alpha': int(alpha.min()),
            'minimum_required_non255': 24, 'pass': count >= 24,
            'same_png': report['capture_file'], 'pixel_selection_from_geometry_only': True}


def run(exp):
    result = None
    status = {'schema': 'sheltered_native_rain_joint_retest_v1', 'failure': None,
              'compatibility_verified': False, 'scope': 'sheltered native role geometry in an otherwise visibly rainy world',
              'original_strict_standard_unchanged': True, 'production_fix_claimed': False,
              'runner_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'scene_source_sha256': hashlib.sha256((HERE / 'shelter_scene.py').read_bytes()).hexdigest()}
    try:
        result = joint.run(exp)
        rain = next(row for row in result['weather'] if row['weather'] == 'rain')
        mode3 = next(row for row in rain['same_frame_reports'] if row['mode'] == 3)
        status['exposed_rain_same_frame'] = exposed_rain(mode3, exp.roi)
        status['original_joint_pass'] = result['pass']
        status['weather_pass'] = {row['weather']: row['pass'] for row in result['weather']}
        status['compatibility_verified'] = result['pass'] and status['exposed_rain_same_frame']['pass']
    except Exception as error:
        status['failure'] = repr(error)
        raise
    finally:
        status['shelter'] = exp.shelter.cleanup()
        if status['shelter']['cleanup_failure'] is not None:
            status['compatibility_verified'] = False
        (exp.evidence / 'rain-shelter-status.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path, required=True)
    args = parser.parse_args()
    args.project, args.evidence = args.project.resolve(), args.evidence.resolve()
    args.evidence.mkdir(exist_ok=False)
    shutil.copyfile(args.previous_evidence / 'launch.json', args.evidence / 'launch.json')
    launch = json.loads((args.evidence / 'launch.json').read_text(encoding='utf-8'))
    (args.evidence / 'assigned-session-snapshot.json').write_bytes(Path(launch['session_file']).read_bytes())
    status = run(Experiment(args))
    print(json.dumps({key: status[key] for key in ('compatibility_verified', 'failure', 'weather_pass')}))
    raise SystemExit(0 if status['compatibility_verified'] else 1)


if __name__ == '__main__':
    main()
