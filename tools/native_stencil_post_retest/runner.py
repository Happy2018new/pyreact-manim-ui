"""Invoke one prebuilt candidate on an already owned session; no launch/stop.

All runtime transport is delegated to the supplied compatibility Experiment.
No operation occurs on import. This CLI is for the sole lifecycle owner.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import build_retest as build
import dof_retest as dof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path, required=True)
    parser.add_argument('--case', choices=build.CASES, required=True)
    parser.add_argument('--identity-gate', type=Path)
    parser.add_argument('--initialize', action='store_true',
                        help='Fresh owner-launched project; implied when prior evidence has no loads')
    args = parser.parse_args()
    args.project, args.evidence = args.project.resolve(), args.evidence.resolve()
    previous = args.previous_evidence.resolve()
    build.validate(args.project, args.case)
    # Active gate validation precedes even Experiment construction or resize.
    if args.case == 'dof-active':
        if args.identity_gate is None:
            parser.error('dof-active requires --identity-gate <dof-identity-status.json>')
        dof.verify_identity_gate(args.identity_gate, dof.native_module().verify_module.payload_bytes(65536))
    launch = previous / 'launch.json'
    if not launch.is_file():
        parser.error('--previous-evidence must contain the current owner launch.json')
    prior_path = previous / 'results.json'
    prior = build.read_json(prior_path) if prior_path.is_file() else None
    initialize = args.initialize or not (prior and prior.get('loads'))
    args.evidence.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(launch, args.evidence / 'launch.json')
    runner = build.module('candidate_compat_experiment', HERE.parent / 'native_stencil_compat_probe/runner.py')
    experiment = runner.Experiment(args)
    session = build.read_json(experiment.session)
    if (session.get('owner') != 'manim-native-stencil-compat'
            or Path(session['project']).resolve() != args.project
            or session['game_pid'] != experiment.game_pid):
        raise RuntimeError('Candidate owner/session/project/PID mismatch')
    result, failure, emergency_cleanup = None, None, None
    try:
        if initialize:
            dof.initialize(experiment, args.case, args.identity_gate)
        else:
            load = prior['loads'][-1]
            experiment.payload = Path(load['input_file']).read_bytes()
            if hashlib.sha256(experiment.payload).hexdigest() != load['input_sha256']:
                raise ValueError('Prior actual upload bytes changed')
            experiment.loads.append(dict(load))
            experiment.viewport, experiment.roi, experiment.output_y = build.VIEWPORT, build.ROI, 650
        if args.case == 'bloom-control':
            bloom = build.module('bloom_retest_runner', HERE / 'bloom_retest.py')
            result = bloom.run_bloom_retest(experiment)
        elif args.case in ('dof-sentinel', 'dof-raw-t1'):
            result = dof.run_control(experiment, args.case)
        else:
            result = dof.run(experiment, args.case, args.identity_gate)
        print(json.dumps({'case': args.case, 'result': result}, ensure_ascii=False))
    except Exception as error:
        failure = repr(error)
        if args.case.startswith('dof-') and result is None:
            emergency_cleanup = {'cleanup_failure': None}
            dof._cleanup(experiment, emergency_cleanup)
        raise
    finally:
        experiment.save()
        (args.evidence / 'retest-run-status.json').write_bytes(build.json_bytes({
            'case': args.case, 'result': result, 'failure': failure,
            'emergency_cleanup': emergency_cleanup,
            'initialized': initialize, 'previous_evidence': str(previous),
            'launch_receipt_sha256': build.sha(launch),
            'runtime_file_writes': False, 'launch_or_stop_performed': False,
            'lifecycle_owner_must_cleanup_instance': True}))


if __name__ == '__main__':
    main()
