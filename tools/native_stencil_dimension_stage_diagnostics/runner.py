"""Bounded End-first stage isolation after preserving the actual automatic result."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import time
import traceback

from PIL import Image


HERE = Path(__file__).resolve().parent
TARGET = HERE.parent/'native_stencil_dimension_target_diagnostics'
ERRORS = (RuntimeError, ValueError, OSError, KeyError, TypeError)
BOUND_SOURCES = ('runner.py', 'observations.py', 'routing.py', 'build_candidate.py')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


target_runner = module('stage_reviewed_target_runner', TARGET/'runner.py')
positive = target_runner.positive
observations = module('stage_host_observations', HERE/'observations.py')
routing = module('stage_sfx_routing', HERE/'routing.py')


def sources():
    result = target_runner.sources()
    result.update({str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in HERE.iterdir() if path.is_file() and path.suffix in ('.py', '.md')})
    return result


def current_gate(experiment, label, frozen, serial, pair):
    value = positive.current(experiment, label)
    positive.gate(value, frozen, serial, pair)
    if value['dimension'] != pair[1]:
        raise RuntimeError('Stage observation left the admitted target dimension')
    return value


def stage_matrix(experiment, original, frozen, serial, pair, rows):
    for stage in observations.STAGES:
        for mode in observations.MODES:
            label = 'stage_%s_m%d'%(stage, mode)
            row = {'stage': stage, 'mode': mode, 'failure': None, 'readback': None}
            rows.append(row)
            current_gate(experiment, label+'_before', frozen, serial, pair)
            row['control'] = experiment.call(label+'_controls', observations.stage_source(stage, mode),
                expression="{'receipts':stage_receipts,'spec':stage_spec,'frame':probe.render_event,'probe':probe.snapshot()}")
            time.sleep(.6)
            row['state'] = current_gate(experiment, label+'_settled', frozen, serial, pair)
            if row['state']['probe'].get('consumer_mode') != mode:
                raise RuntimeError('Stage consumer mode did not apply')
            row['readback'] = observations.capture(experiment, label, mode, original, positive)
            expected = observations.predicted_payload(stage, experiment.payload)
            if mode in (1, 3) and expected is not None:
                with Image.open(row['readback']['capture_file']) as frame:
                    row['stage_prediction_comparison'] = original.integrated.verify_module.verify(
                        frame.convert('RGB'), mode, expected, experiment.viewport, experiment.roi,
                        output_y=128, fixture=False)
                row['stage_prediction_exact_asserted'] = False


def fixture_controls(experiment, original, frozen, serial, pair, rows):
    try:
        for stage in ('off', 'base', 'all'):
            label = 'known_fixture_'+stage+'_m7'
            row = {'stage': stage, 'mode': 7, 'failure': None}
            rows.append(row)
            current_gate(experiment, label+'_before', frozen, serial, pair)
            row['control'] = experiment.call(label+'_controls', observations.stage_source(stage, 7)+
                '\nprobe.configure_known_fixture(True,False)',
                expression="{'receipts':stage_receipts,'spec':stage_spec,'frame':probe.render_event,'probe':probe.snapshot()}")
            time.sleep(.6)
            row['state'] = current_gate(experiment, label+'_settled', frozen, serial, pair)
            row['readback'] = observations.capture(experiment, label, 7, original, positive)
            with Image.open(row['readback']['capture_file']) as frame:
                row['fixture_comparison'] = observations.fixture_comparison(frame, stage, experiment.payload,
                    experiment.viewport, experiment.roi, original.integrated.verify_module)
    finally:
        experiment.call('known_fixture_finally_off', 'probe.configure_known_fixture(False)')


def manual_control(experiment, original, frozen, serial, pair, record):
    record.update(attempted=True, automatic_recovery_reclassified=False, checkpoints=[],
                  pixel_verified=False, recovered_at=None, failure=None)
    before = current_gate(experiment, 'manual_before', frozen, serial, pair)
    record['before'] = before
    plans = (('A_relink', observations.relink_source(), 'manual_link_result'),
             ('B_effects', observations.effects_source(), 'manual_result'),
             ('C_holders', observations.holders_source(), 'manual_result'))
    for name, source, expression in plans:
        row = {'name': name, 'captures': [], 'failure': None, 'pixel_verified': False}
        record['checkpoints'].append(row)
        row['before'] = current_gate(experiment, name+'_before', frozen, serial, pair)
        row['intervention'] = experiment.call(name+'_explicit', source, expression=expression)
        frame = row['intervention']['frame']
        for attempt in range(8):
            time.sleep(.25)
            value = positive.current(experiment, name+'_later_frame_%d'%attempt)
            row['last_wait_state'] = value
            recovery = value['probe'].get('dimension_recovery', {})
            if (value['dimension'] != pair[1] or positive.static_identity(value['probe']) != frozen or
                    recovery.get('serial') != serial or recovery.get('pair') != pair or
                    value['probe'].get('error')):
                raise RuntimeError('Manual checkpoint lost static identity or target transition')
            if value['probe']['render_event'] > frame and value['probe'].get('ready') is True:
                positive.gate(value, frozen, serial, pair)
                break
        else:
            raise RuntimeError('Manual checkpoint never reached a later render frame')
        for mode in (1, 3):
            experiment.call(name+'_m%d_controls'%mode,
                'probe.configure(\'all\')\nprobe.inspect(%d,shape_enabled=False,enabled=True,restore_enabled=True)'%mode)
            time.sleep(.6)
            current_gate(experiment, name+'_m%d_settled'%mode, frozen, serial, pair)
            row['captures'].append(observations.capture(experiment, name+'_m%d'%mode, mode, original, positive))
        row['pixel_verified'] = all(item['full_payload_comparison'].get('exact') is True for item in row['captures'])
        if row['pixel_verified']:
            record.update(pixel_verified=True, recovered_at=name)
            break
    record['completed'] = bool(record['recovered_at']) or len(record['checkpoints']) == 3


def run(experiment, original, target=2, progress=None, sfx_routing=False):
    target_runner.validate_plan(target, 0)
    if not isinstance(sfx_routing, bool):
        raise ValueError('SFX routing selector must be bool')
    if not positive.nether_natural(experiment):
        raise ValueError('Stage diagnostic requires natural targets and Overworld-only foothold')
    status = progress if progress is not None else {}
    status.update(schema='static_dimension_stage_progress_v1', planned_dimensions=[0, target, 0],
        resident_payload_uploads=0, target=target, trips=[], stages=[], known_fixture_controls=[],
        manual_control={}, pixel_verified=False, diagnostics_completed=False, cleanup={}, cleanup_failure=None,
        fixture=experiment.pose_receipt, target_terrain_edits_allowed=False, runtime_file_writes=False)
    status['sfx_routing'] = sfx_routing
    try:
        experiment.initialize()
        status['resident_payload_uploads'] = 1
        first = positive.current(experiment, 'stage_initial')
        if (experiment.variant != 'carrier' or first['dimension'] != 0 or
                experiment.viewport != [720, 1080] or experiment.roi != [8, 128, 512, 512] or
                len(experiment.payload) != 65536 or first['probe']['dimension_recovery'].get('serial') != 0):
            raise RuntimeError('Stage diagnostic requires fresh resident 64 KiB Overworld candidate')
        frozen = positive.static_identity(first['probe'])
        positive.gate(first, frozen)
        status.update(initial=first, frozen_static_identity=frozen)
        player = experiment.call('stage_player', expression='api.GetLocalPlayerId()')
        if sfx_routing:
            routing.preflight(experiment, original, positive, observations, frozen,
                              status.setdefault('routing_overworld_positive', {}))
        positive.candidate.arm(experiment, 'stage_initial_arm')
        status['initial_readback'] = positive.candidate.raw_readback(experiment, 'stage_initial_exact', original)
        row = {'name': 'stage_end' if target == 2 else 'stage_nether', 'target': target,
               'outbound': {}, 'return': {}, 'outbound_failure': None, 'return_failure': None}
        status['trips'].append(row)
        try:
            try:
                target_runner.transit(experiment, row['name'], target, player, frozen, original, row['outbound'])
            except ERRORS as error:
                row['outbound_failure'] = repr(error)
            first_image = row['outbound'].get('automatic_readback')
            if not isinstance(first_image, dict):
                raise RuntimeError('No actual automatic image; stage observations are not a substitute')
            serial = row['outbound']['expected_serial']
            pair = [row['outbound']['before']['dimension'], target]
            current_gate(experiment, 'stage_diagnostics_admission', frozen, serial, pair)
            if sfx_routing:
                try:
                    routing.run(experiment, original, positive, observations,
                        lambda label: current_gate(experiment, label, frozen, serial, pair),
                        status.setdefault('routing', {}))
                except ERRORS as error:
                    status['routing_failure'] = repr(error)
                status['diagnostics_completed'] = (status.get('routing', {}).get('completed') is True and
                                                    status.get('routing_failure') is None)
            else:
                try:
                    stage_matrix(experiment, original, frozen, serial, pair, status['stages'])
                except ERRORS as error:
                    status['stage_failure'] = repr(error)
                try:
                    fixture_controls(experiment, original, frozen, serial, pair, status['known_fixture_controls'])
                except ERRORS as error:
                    status['known_fixture_failure'] = repr(error)
                try:
                    manual_control(experiment, original, frozen, serial, pair, status['manual_control'])
                except ERRORS as error:
                    status['manual_control']['failure'] = repr(error)
                status['diagnostics_completed'] = (len(status['stages']) == 21 and
                    all(row.get('readback') is not None for row in status['stages']) and
                    len(status['known_fixture_controls']) == 3 and
                    all(row.get('readback') is not None for row in status['known_fixture_controls']) and
                    status['manual_control'].get('completed') is True and
                    not any(status.get(key) for key in ('stage_failure', 'known_fixture_failure')) and
                    status['manual_control'].get('failure') is None)
        finally:
            # Never allow an optional layer-12 fixture to block the dimension start.
            try:
                if sfx_routing:
                    status['routing_fixture_destroy_reset'] = experiment.call('routing_finally_fixture_destroy_reset',
                        routing.destroy_fixture_source(), expression="{'receipts':routing_destroy,'fixture':probe.known_fixture.snapshot()}")
                else:
                    experiment.call('stage_finally_fixture_off', 'probe.configure_known_fixture(False)')
            except ERRORS as error:
                status['fixture_disable_failure'] = repr(error)
            target_runner.roundtrip.return_to_overworld(experiment, original, player, frozen, row)
        row['pixel_verified'] = (row['outbound_failure'] is None and row['return_failure'] is None and
            row['outbound'].get('pixel_verified') is True and row['return'].get('pixel_verified') is True)
        status['pixel_verified'] = row['pixel_verified']
        if not status['pixel_verified'] or not status['diagnostics_completed']:
            raise RuntimeError('Stage diagnostic retains automatic failure or incomplete observations: '+
                               repr({'outbound_failure': row['outbound_failure'], 'return_failure': row['return_failure'],
                                     'diagnostics_completed': status['diagnostics_completed']}))
        return status
    finally:
        try:
            status['cleanup'] = positive.restore(experiment)
        except ERRORS as error:
            status['cleanup_failure'] = repr(error)


def verify_install(project):
    target_runner.verify_install(project)
    receipt = json.loads((project/'dimension_stage_receipt.json').read_text(encoding='utf-8'))
    if set(receipt['source_sha256']) != set(BOUND_SOURCES):
        raise RuntimeError('Stage receipt must bind all reviewed host sources')
    for name, sha in receipt['source_sha256'].items():
        if hashlib.sha256((HERE/name).read_bytes()).hexdigest() != sha:
            raise RuntimeError('Stage diagnostic source differs from reviewed build: '+name)
    if (receipt.get('room_dimensions') != [0] or receipt.get('default_dimension_sequence') != [0, 2, 0] or
            receipt.get('maximum_transitions') != 2 or receipt.get('maximum_stage_captures') != 21 or
            receipt.get('manual_control_captures') != 6 or receipt.get('resident_payload_uploads') != 1 or
            receipt.get('maximum_routing_captures') != 13):
        raise RuntimeError('Stage receipt plan is invalid')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path, required=True)
    parser.add_argument('--target', choices=('end', 'nether'), default='end')
    parser.add_argument('--sfx-routing', action='store_true', help='Replace the stage matrix with bounded SetGlobal and metadata routing controls')
    args = parser.parse_args()
    args.nether_natural = True
    for key in ('project', 'evidence', 'previous_evidence'):
        setattr(args, key, getattr(args, key).resolve())
    if (args.evidence == args.previous_evidence or args.previous_evidence in args.evidence.parents or
            args.evidence in args.previous_evidence.parents):
        raise ValueError('Preserve launch evidence in a separate directory')
    prior = args.previous_evidence/'launch.json'
    prior_bytes = prior.read_bytes()
    previous_files = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in args.previous_evidence.rglob('*') if path.is_file()}
    args.evidence.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(prior, args.evidence/'launch.json')
    before = sources()
    experiment, failure, trace, save_failure, progress = None, None, None, None, {}
    try:
        verify_install(args.project)
        original = module('stage_original_compat_runner', positive.COMPAT/'runner.py')
        experiment = positive.create_experiment_type(original)(args)
        run(experiment, original, 2 if args.target == 'end' else 1, progress, sfx_routing=args.sfx_routing)
        if progress.get('cleanup_failure'):
            raise RuntimeError('Stage room cleanup failed: '+progress['cleanup_failure'])
    except ERRORS as error:
        failure, trace = repr(error), traceback.format_exc()
    finally:
        if experiment is not None:
            try:
                experiment.save()
            except ERRORS as error:
                save_failure = repr(error)
                failure = failure or 'Host evidence save failed: '+save_failure
        after = sources()
        unchanged = previous_files == {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                      for path in args.previous_evidence.rglob('*') if path.is_file()}
        if before != after or not unchanged:
            failure = failure or 'Reviewed sources or preserved launch evidence changed'
        result = {'schema': 'static_dimension_stage_run_v1', 'failure': failure, 'failure_traceback': trace,
            'save_failure': save_failure, 'result': progress,
            'pixel_verified': failure is None and progress.get('pixel_verified') is True,
            'diagnostics_completed': progress.get('diagnostics_completed') is True,
            'last_state': experiment.state if experiment is not None else None,
            'previous_evidence': str(args.previous_evidence), 'previous_evidence_unchanged': unchanged,
            'previous_launch_sha256': hashlib.sha256(prior_bytes).hexdigest(),
            'sources_before': before, 'sources_after': after, 'sources_unchanged': before == after,
            'launch_or_stop_performed': False, 'owned_game_retained_for_parent_cleanup': True,
            'runtime_file_writes': False, 'continuous_updates_tested': False}
        (args.evidence/'stage-status.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({'failure': failure, 'pixel_verified': result['pixel_verified'],
                          'diagnostics_completed': result['diagnostics_completed']}), flush=True)
    return 1 if failure or not progress.get('pixel_verified') else 0


if __name__ == '__main__':
    raise SystemExit(main())
