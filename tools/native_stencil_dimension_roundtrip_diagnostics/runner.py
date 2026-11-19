"""One owned static resident payload across repeated natural Nether and End trips."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import traceback


HERE = Path(__file__).resolve().parent
POSITIVE = HERE.parent/'native_stencil_dimension_diagnostics'
ERRORS = (RuntimeError, ValueError, OSError, KeyError, TypeError)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


positive = module('repeated_dimension_reviewed_positive_runner', POSITIVE/'runner.py')


def plan(nether_repeats=2, include_end=True):
    if isinstance(nether_repeats, bool) or nether_repeats not in (1, 2):
        raise ValueError('Choose one or two bounded Nether round trips')
    if not isinstance(include_end, bool):
        raise ValueError('End plan flag must be a bool')
    rows = [{'name': 'nether_%d'%(index+1), 'dimension': 1} for index in range(nether_repeats)]
    if include_end:
        rows.append({'name': 'end_1', 'dimension': 2})
    return rows


def sources():
    result = positive.sources()
    result.update({str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in HERE.iterdir() if path.is_file() and path.suffix in ('.py', '.md')})
    return result


def return_to_overworld(experiment, original, player, frozen, row):
    try:
        now = positive.current(experiment, row['name']+'_return_decision')
        needs_return = now['dimension'] != 0
        row['return_decision'] = now
    except ERRORS as error:
        row['return_decision_failure'] = repr(error)
        needs_return = row['outbound'].get('request_intent') is True
    if not needs_return:
        row['return_failure'] = 'No departure from Overworld was observed; return recovery is unverified'
        return
    try:
        positive.transit(experiment, 'roundtrip_'+row['name']+'_overworld', 0, player,
                         frozen, original, row['return'])
    except ERRORS as error:
        row['return_failure'] = repr(error)


def run(experiment, original, nether_repeats=2, include_end=True, progress=None):
    schedule = plan(nether_repeats, include_end)
    if not positive.nether_natural(experiment):
        raise ValueError('Repeated dimension runner requires natural targets and an Overworld-only foothold')
    status = progress if progress is not None else {}
    status.update(schema='static_repeated_dimension_progress_v1', planned_trips=schedule,
        planned_transitions=2*len(schedule), trips=[], pixel_verified=False, cleanup={}, cleanup_failure=None,
        fixture=experiment.pose_receipt, resident_payload_uploads=0,
        target_terrain_edits_allowed=False, continuous_updates_tested=False,
        end_attempted=False, end_pixel_verified=False,
        automatic_capture_qualification='First host capture after matching ready; not claimed to be the first GPU frame')
    try:
        experiment.initialize()
        status['resident_payload_uploads'] = 1
        first = positive.current(experiment, 'roundtrip_initial')
        if (experiment.variant != 'carrier' or first['dimension'] != 0 or
                experiment.viewport != [720, 1080] or experiment.roi != [8, 128, 512, 512] or
                len(experiment.payload) != 65536 or
                first['probe'].get('dimension_recovery', {}).get('serial') != 0):
            raise RuntimeError('Repeated dimension diagnostic requires the fresh 64 KiB Overworld candidate')
        frozen = positive.static_identity(first['probe'])
        positive.gate(first, frozen)
        status.update(initial=first, frozen_static_identity=frozen)
        player = experiment.call('roundtrip_player', expression='api.GetLocalPlayerId()')
        positive.candidate.arm(experiment, 'roundtrip_initial_arm')
        status['initial_readback'] = positive.candidate.raw_readback(experiment, 'roundtrip_initial_exact', original)
        for item in schedule:
            row = {'name': item['name'], 'target': item['dimension'], 'outbound': {}, 'return': {},
                   'outbound_failure': None, 'return_failure': None}
            status['trips'].append(row)
            if item['dimension'] == 2:
                status['end_attempted'] = True
            try:
                positive.transit(experiment, 'roundtrip_'+item['name'], item['dimension'], player,
                                 frozen, original, row['outbound'])
            except ERRORS as error:
                row['outbound_failure'] = repr(error)
            finally:
                return_to_overworld(experiment, original, player, frozen, row)
            row['pixel_verified'] = (row['outbound_failure'] is None and row['return_failure'] is None and
                row['outbound'].get('pixel_verified') is True and row['return'].get('pixel_verified') is True)
            if item['dimension'] == 2:
                status['end_pixel_verified'] = row['pixel_verified']
            if not row['pixel_verified']:
                raise RuntimeError('Bounded repeated dimension trip failed: '+repr(row))
        status['pixel_verified'] = len(status['trips']) == len(schedule) and all(
            row['pixel_verified'] for row in status['trips'])
        return status
    finally:
        try:
            status['cleanup'] = positive.restore(experiment)
        except ERRORS as error:
            status['cleanup_failure'] = repr(error)


def verify_install(project):
    positive.verify_install(project)
    receipt = json.loads((project/'dimension_roundtrip_receipt.json').read_text(encoding='utf-8'))
    for name, sha in receipt['source_sha256'].items():
        if hashlib.sha256((HERE/name).read_bytes()).hexdigest() != sha:
            raise RuntimeError('Repeated dimension diagnostic differs from reviewed source: '+name)
    if receipt.get('room_dimensions') != [0] or receipt.get('maximum_planned_transitions') != 6:
        raise RuntimeError('Repeated dimension diagnostic receipt plan is invalid')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path, required=True)
    parser.add_argument('--nether-repeats', type=int, choices=(1, 2), default=2)
    parser.add_argument('--skip-end', action='store_true', help='Default includes one direct SDK End round trip')
    args = parser.parse_args()
    args.nether_natural = True
    for key in ('project', 'evidence', 'previous_evidence'):
        setattr(args, key, getattr(args, key).resolve())
    if (args.evidence == args.previous_evidence or args.previous_evidence in args.evidence.parents or
            args.evidence in args.previous_evidence.parents):
        raise ValueError('Preserve launch evidence in a separate directory')
    prior_path = args.previous_evidence/'launch.json'
    prior_bytes = prior_path.read_bytes()
    previous_files = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in args.previous_evidence.rglob('*') if path.is_file()}
    args.evidence.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(prior_path, args.evidence/'launch.json')
    before = sources()
    experiment, failure, trace, progress = None, None, None, {}
    try:
        verify_install(args.project)
        original = module('roundtrip_original_compat_runner', positive.COMPAT/'runner.py')
        experiment = positive.create_experiment_type(original)(args)
        run(experiment, original, args.nether_repeats, not args.skip_end, progress)
        if progress.get('cleanup_failure'):
            raise RuntimeError('Repeated dimension room cleanup failed: '+progress['cleanup_failure'])
    except ERRORS as error:
        failure, trace = repr(error), traceback.format_exc()
    finally:
        if experiment is not None:
            experiment.save()
        after = sources()
        unchanged = previous_files == {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                      for path in args.previous_evidence.rglob('*') if path.is_file()}
        if before != after or not unchanged:
            failure = failure or 'Reviewed sources or preserved launch evidence changed'
        result = {'schema': 'static_repeated_dimension_run_v1', 'failure': failure,
            'failure_traceback': trace, 'result': progress,
            'pixel_verified': failure is None and progress.get('pixel_verified') is True,
            'last_state': experiment.state if experiment is not None else None,
            'previous_evidence': str(args.previous_evidence),
            'previous_launch_sha256': hashlib.sha256(prior_bytes).hexdigest(),
            'previous_evidence_unchanged': unchanged, 'sources_before': before, 'sources_after': after,
            'sources_unchanged': before == after, 'launch_or_stop_performed': False,
            'owned_game_retained_for_parent_cleanup': True, 'runtime_file_writes': False,
            'continuous_updates_tested': False}
        (args.evidence/'roundtrip-status.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({'failure': failure, 'pixel_verified': result['pixel_verified'],
                          'end_pixel_verified': progress.get('end_pixel_verified', False)}), flush=True)
    return 1 if failure or not progress.get('pixel_verified') else 0


if __name__ == '__main__':
    raise SystemExit(main())
