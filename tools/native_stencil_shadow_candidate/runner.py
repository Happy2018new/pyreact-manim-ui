"""Explicit owner-run shadow candidate capture; never launches or stops games."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


build = module('shadow_candidate_build_api', HERE / 'build_candidate.py')
verify = module('shadow_candidate_comparative_oracle', HERE / 'verify.py')
compat = module('shadow_candidate_frozen_compat_runner', HERE.parent / 'native_stencil_compat_probe/runner.py')
predecessor_path = HERE.parent / 'native_stencil_compat_probe/shadow_runner_recovery.py'
predecessor = module('shadow_candidate_frozen_hover_fixture', predecessor_path)


class Experiment(compat.Experiment):
    def data_checks(self, prefix):
        # Preserve complete negative data as evidence; expected native shadow
        # conflicts must not prevent the second exhaustive diagnostic capture.
        return [self.capture(prefix + '_m%d' % mode, mode, output_y=650, expected=False)
                for mode in (1, 3)]


def run(args):
    project = args.project.resolve(strict=True)
    candidate = build.validate(project, args.mask)
    evidence, previous = args.evidence.resolve(), args.previous_evidence.resolve(strict=True)
    launch = json.loads((previous / 'launch.json').read_text(encoding='utf-8'))
    session_path = Path(launch['session_file'])
    session_bytes = session_path.read_bytes()
    session = json.loads(session_bytes.decode('utf-8-sig'))
    if session.get('owner') != compat.OWNER or Path(session['project']).resolve() != project or not session.get('ready'):
        raise ValueError('Use this fresh ready owner-bound candidate session')
    evidence.mkdir(exist_ok=False)
    shutil.copyfile(previous / 'launch.json', evidence / 'launch.json')
    (evidence / 'assigned-session-snapshot.json').write_bytes(session_bytes)
    args.project, args.evidence = project, evidence
    experiment = Experiment(args)
    source_hash = hashlib.sha256(predecessor_path.read_bytes()).hexdigest()
    status = {'schema': 'native_shadow_mask_candidate_run_v1', 'mask': args.mask,
              'candidate': candidate, 'failure': None, 'compatibility': None,
              'classification': 'not_started', 'operational_complete': False,
              'diagnostic_only': True, 'launch_or_stop_performed': False,
              'assigned_session_sha256': hashlib.sha256(session_bytes).hexdigest(),
              'host_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'verifier_sha256': hashlib.sha256((HERE / 'verify.py').read_bytes()).hexdigest(),
              'frozen_hover_helper_sha256': source_hash}
    try:
        status['installed_original_shadow_source'] = verify.shadow.native_material_receipt(Path(candidate['game_executable']).parent)
        experiment.initialize()
        status['initialized_resident_state'] = experiment.state
        try:
            predecessor.run(experiment)
        except RuntimeError as error:
            # This exact bounded negative is an experimental observation, not
            # a host failure. Every other error remains operational failure.
            if str(error) != 'Native shadow/64KiB coexistence failed; preserve actual conflict':
                raise
            status['preserved_compatibility_exception'] = repr(error)
        source = json.loads((evidence / 'shadow-recovery-status.json').read_text(encoding='utf-8'))
        status['frozen_predecessor_result'] = source
        attempts = [row for row in source.get('attempts', []) if row.get('coexistence') is not None]
        if len(attempts) != 1:
            raise RuntimeError('One complete native shadow/carrier comparison is required')
        attempt = attempts[0]
        for key in ('plan', 'native_snapshots', 'active_snapshots', 'native_captures', 'payload_captures'):
            status[key] = attempt[key]
        active_paths = [str(evidence / ('shadow_%s_active_%s.png' % (attempt['kind'], suffix)))
                        for suffix in ('off_before', 'on', 'off_after')]
        status['active_captures'] = active_paths
        reports = [row for row in experiment.reports if row.get('mode') in (1, 3)]
        result = verify.compare(verify.images(attempt['native_captures']), verify.images(active_paths),
                                attempt['plan'], reports, experiment.payload)
        status['symbol_comparison'] = result
        status['actual_payload_sha256'] = hashlib.sha256(experiment.payload).hexdigest()
        status['actual_input_file'] = experiment.loads[-1]['input_file']
        status['payload_reports'] = reports
        capture_paths = attempt['native_captures'] + active_paths + attempt['payload_captures']
        status['capture_sha256'] = {str(Path(path).resolve()): hashlib.sha256(Path(path).read_bytes()).hexdigest()
                                    for path in capture_paths}
        status['compatibility'] = result['pass']
        status['classification'] = ('all_four_symbol_shadow_and_data_preserved' if result['pass']
            else 'four_symbol_shadow_or_data_difference_observed')
        floor = source.get('cleanup', {}).get('floor', {})
        if (attempt.get('native_state_gate', {}).get('pass') is not True
                or attempt.get('active_state_gate', {}).get('pass') is not True
                or attempt.get('native_visual', {}).get('pass') is not True
                or not result['all_four_symbol_groups_covered'] or floor.get('all_exact') is not True):
            raise RuntimeError('Native positive control, four-symbol coverage or exact floor cleanup failed')
        if attempt['kind'] == 'pig' and source.get('cleanup', {}).get('pig', {}).get('accepted') is not True:
            raise RuntimeError('Native fallback pig destruction was not accepted')
        cleanup = experiment.call('candidate_cleanup_readback')
        status['final_runtime_state'] = cleanup
        if cleanup.get('outline', {}).get('entity') is not None:
            raise RuntimeError('Native caster remains after predecessor cleanup')
        status['operational_complete'] = True
    except Exception as error:
        status['failure'] = repr(error)
        status['classification'] = 'operational_or_positive_control_failure'
        raise
    finally:
        status['frozen_hover_helper_unchanged'] = hashlib.sha256(predecessor_path.read_bytes()).hexdigest() == source_hash
        try:
            build.validate(project, args.mask)
            status['candidate_package_unchanged'] = True
        except Exception as error:
            status['candidate_package_unchanged'] = False
            status['failure'] = status['failure'] or repr(error)
            status['operational_complete'] = False
            status['compatibility'] = None
        if not status['frozen_hover_helper_unchanged']:
            status['failure'] = status['failure'] or 'Frozen predecessor source changed'
            status['operational_complete'] = False
            status['compatibility'] = None
        experiment.save()
        (evidence / 'shadow-candidate-status.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path, required=True)
    parser.add_argument('--mask', type=int, choices=build.MASKS, required=True)
    args = parser.parse_args()
    status = run(args)
    print(json.dumps({key: status[key] for key in ('mask', 'classification', 'compatibility', 'operational_complete', 'failure')}))
    if not status['operational_complete']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
