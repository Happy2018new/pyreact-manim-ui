"""One isolated natural End (default) or Nether trip with passive failure diagnostics."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import time
import traceback


HERE = Path(__file__).resolve().parent
ROUNDTRIP = HERE.parent/'native_stencil_dimension_roundtrip_diagnostics'
ERRORS = (RuntimeError, ValueError, OSError, KeyError, TypeError)
FOLLOWUP_DELAYS = (.6, 1.2, 2.4)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


roundtrip = module('target_dimension_reviewed_roundtrip', ROUNDTRIP/'runner.py')
positive = roundtrip.positive


def sources():
    result = roundtrip.sources()
    result.update({str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in HERE.iterdir() if path.is_file() and path.suffix in ('.py', '.md')})
    return result


def validate_plan(target, followups):
    if isinstance(target, bool) or target not in (1, 2):
        raise ValueError('Choose one isolated target: Nether 1 or End 2')
    if isinstance(followups, bool) or followups not in (0, 3):
        raise ValueError('Choose zero or three bounded passive followups')


def saved_report(experiment, label):
    return next((row for row in reversed(experiment.reports) if row.get('label') == label), None)


def terrain_source():
    # Client-only loaded-terrain reads. GetBlock has no dimension argument and
    # does not request chunks or mutate terrain. Preserve None/unknown returns.
    return """import math
block=probe.factory.CreateBlockInfo(api.GetLevelId())
dimension_before=probe.game.GetCurrentDimension()
frame_before=probe.render_event
origins=[('camera',probe.camera.GetPosition()),('anchor',probe.anchor)]
origins.extend(('effect_%d'%index,probe.factory.CreateFrameAniTrans(effect).GetPos()) for index,effect in enumerate(probe.effects))
centers=[]
samples=[]
seen=set()
for name,position in origins:
    center=tuple(int(math.floor(value)) for value in position)
    centers.append({'name':name,'position':position,'floor':center})
    for dx in (-1,0,1):
        for dy in (-1,0,1):
            for dz in (-1,0,1):
                coordinate=(center[0]+dx,center[1]+dy,center[2]+dz)
                if coordinate in seen: continue
                seen.add(coordinate)
                value=block.GetBlock(coordinate)
                samples.append({'position':coordinate,'block':list(value) if isinstance(value,(tuple,list)) else value})
terrain_result={'dimension_before':dimension_before,'dimension_after':probe.game.GetCurrentDimension(),
    'frame_before':frame_before,'frame_after':probe.render_event,'centers':centers,'samples':samples,
    'read_only':True,'loaded_terrain_only':True,'neighborhood_radius':1}
"""


def terrain_after_capture(experiment, label, record):
    try:
        record['terrain_after_first_capture'] = experiment.call(label+'_terrain', terrain_source(),
                                                               expression='terrain_result')
    except ERRORS as error:
        # Supplemental terrain evidence must not replace an automatic pixel error.
        record['terrain_read_failure'] = repr(error)


def transit(experiment, label, target, player, frozen, original, record):
    """Reviewed positive transit ordering, plus terrain reads after first image."""
    before = positive.current(experiment, label+'_before')
    source = before['dimension']
    serial = before['probe']['dimension_recovery']['serial']+1
    record.update(before=before, expected_serial=serial, arm_failure=None,
                  requested_position=list(positive.pose.DIMENSION_TARGET))
    positive.candidate.arm(experiment, label+'_arm')
    record['request_intent'] = True
    record['request'] = experiment.server(label+'_request',
        "dimension=api.GetEngineCompFactory().CreateDimension(%r)\n"
        "accepted=dimension.ChangePlayerDimension(%d,%r)\n_result=json.dumps({'accepted':accepted})"
        % (player, target, positive.pose.DIMENSION_TARGET))
    if record['request'].get('accepted') is not True:
        raise RuntimeError('Isolated target dimension request rejected')
    for attempt in range(40):
        time.sleep(.6)
        value = positive.current(experiment, label+'_poll_%02d'%attempt)
        record['last_state'] = value
        recovery = value['probe'].get('dimension_recovery', {})
        if value['probe'].get('error') or recovery.get('phase') == 'failed':
            raise RuntimeError('Automatic isolated-target recovery failed: '+repr(recovery))
        if (value['dimension'] == target and recovery.get('phase') == 'ready' and
                recovery.get('serial') == serial and recovery.get('ready_serial') == serial):
            positive.gate(value, frozen, serial, [source, target])
            capture_label = label+'_automatic_exact'
            try:
                # Absolutely no SDK command between matching ready and capture.
                record['automatic_readback'] = positive.candidate.raw_readback(experiment, capture_label, original)
            finally:
                report = saved_report(experiment, capture_label)
                if report is not None:
                    record['automatic_readback'] = report
                    terrain_after_capture(experiment, label, record)
                server_position = None
                try:
                    server_position = experiment.server(label+'_admitted_server_position',
                        "factory=api.GetEngineCompFactory()\n"
                        "dimension=factory.CreateDimension(%r).GetEntityDimensionId()\n"
                        "position=factory.CreatePos(%r).GetPos()\n"
                        "_result=json.dumps({'dimension':dimension,'position':position})" % (player, player))
                except ERRORS as error:
                    record['admission_read_failure'] = repr(error)
                record['admitted_position'] = positive.admission(value, server_position, target)
            if not record['admitted_position']['verified']:
                raise RuntimeError('Automatic target image captured but actual player admission was not verified')
            controls = experiment.data_checks(label+'_checked')
            if not controls or not all(row.get('exact') is True for row in controls):
                raise RuntimeError('Isolated target standard mode1/mode3 exact checks failed')
            record.update(state=value, standard_exact_checks=controls, pixel_verified=True)
            return record
    raise RuntimeError('Matching isolated-target recovery did not become ready before host deadline')


def passive_gate(value, frozen, serial, pair):
    positive.gate(value, frozen, serial, pair)
    state = value['probe']
    if (value['dimension'] != pair[1] or state.get('mode') != 'all' or
            state.get('consumer_mode') != 1 or state.get('diagnostic_output_y') != 128 or
            state.get('pipeline_enabled') is not True or state.get('shape_enabled') is not False):
        raise RuntimeError('Passive followup requires the unchanged automatic mode1 output state')


def observe_failure(experiment, original, label, target, frozen, record, followups):
    report = record.get('automatic_readback')
    if (not followups or not isinstance(report, dict) or report.get('exact') is not False):
        return []
    last = record.get('last_state', {})
    serial = record.get('expected_serial')
    source = record.get('before', {}).get('dimension')
    if serial is None or source is None:
        return []
    passive_gate(last, frozen, serial, [source, target])
    rows = record.setdefault('passive_followups', [])
    for index, delay in enumerate(FOLLOWUP_DELAYS):
        row = {'index': index+1, 'host_wait_seconds': delay, 'failure': None, 'readback': None,
               'runtime_mutation_performed': False}
        rows.append(row)
        time.sleep(delay)
        try:
            value = positive.current(experiment, label+'_passive_%d_state'%(index+1))
            row['state'] = value
            passive_gate(value, frozen, serial, [source, target])
            capture_label = label+'_passive_%d_exact'%(index+1)
            try:
                row['readback'] = positive.candidate.raw_readback(experiment, capture_label, original)
            finally:
                report = saved_report(experiment, capture_label)
                if report is not None:
                    row['readback'] = report
        except ERRORS as error:
            row['failure'] = repr(error)
            if row['readback'] is None:
                # Stop on stale identity/state or invalid capture; never rearm.
                break
    return rows


def run(experiment, original, target=2, followups=3, progress=None):
    validate_plan(target, followups)
    if not positive.nether_natural(experiment):
        raise ValueError('Isolated target runner requires natural targets and an Overworld-only foothold')
    name = 'end_1' if target == 2 else 'nether_1'
    status = progress if progress is not None else {}
    status.update(schema='static_target_dimension_progress_v1', target=target,
        planned_dimensions=[0, target, 0], planned_transitions=2, passive_followup_count=followups,
        trips=[], pixel_verified=False, cleanup={}, cleanup_failure=None, fixture=experiment.pose_receipt,
        resident_payload_uploads=0, target_terrain_edits_allowed=False, continuous_updates_tested=False,
        end_attempted=False, end_pixel_verified=False,
        automatic_capture_qualification='First host capture after matching ready; not claimed to be the first GPU frame')
    try:
        experiment.initialize()
        status['resident_payload_uploads'] = 1
        first = positive.current(experiment, 'target_initial')
        if (experiment.variant != 'carrier' or first['dimension'] != 0 or
                experiment.viewport != [720, 1080] or experiment.roi != [8, 128, 512, 512] or
                len(experiment.payload) != 65536 or
                first['probe'].get('dimension_recovery', {}).get('serial') != 0):
            raise RuntimeError('Isolated target requires the fresh 64 KiB Overworld candidate')
        frozen = positive.static_identity(first['probe'])
        positive.gate(first, frozen)
        status.update(initial=first, frozen_static_identity=frozen)
        player = experiment.call('target_player', expression='api.GetLocalPlayerId()')
        positive.candidate.arm(experiment, 'target_initial_arm')
        status['initial_readback'] = positive.candidate.raw_readback(experiment, 'target_initial_exact', original)
        row = {'name': name, 'target': target, 'outbound': {}, 'return': {},
               'outbound_failure': None, 'return_failure': None}
        status['trips'].append(row)
        status['end_attempted'] = target == 2
        try:
            transit(experiment, 'target_'+name, target, player, frozen, original, row['outbound'])
        except ERRORS as error:
            row['outbound_failure'] = repr(error)
            try:
                observe_failure(experiment, original, 'target_'+name, target, frozen, row['outbound'], followups)
            except ERRORS as diagnostic_error:
                row['passive_diagnostic_failure'] = repr(diagnostic_error)
        finally:
            roundtrip.return_to_overworld(experiment, original, player, frozen, row)
        row['pixel_verified'] = (row['outbound_failure'] is None and row['return_failure'] is None and
            row['outbound'].get('pixel_verified') is True and row['return'].get('pixel_verified') is True)
        status['end_pixel_verified'] = target == 2 and row['pixel_verified']
        status['pixel_verified'] = row['pixel_verified']
        if not row['pixel_verified']:
            raise RuntimeError('Isolated dimension trip failed: '+repr(row))
        return status
    finally:
        try:
            status['cleanup'] = positive.restore(experiment)
        except ERRORS as error:
            status['cleanup_failure'] = repr(error)


def verify_install(project):
    roundtrip.verify_install(project)
    receipt = json.loads((project/'dimension_target_receipt.json').read_text(encoding='utf-8'))
    if set(receipt['source_sha256']) != {'runner.py', 'build_candidate.py'}:
        raise RuntimeError('Isolated target receipt must bind both reviewed host sources')
    for name, sha in receipt['source_sha256'].items():
        if hashlib.sha256((HERE/name).read_bytes()).hexdigest() != sha:
            raise RuntimeError('Isolated target diagnostic differs from reviewed source: '+name)
    if (receipt.get('room_dimensions') != [0] or receipt.get('default_dimension_sequence') != [0, 2, 0] or
            receipt.get('maximum_planned_transitions') != 2 or receipt.get('maximum_passive_followups') != 3):
        raise RuntimeError('Isolated target diagnostic receipt plan is invalid')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path, required=True)
    parser.add_argument('--target', choices=('end', 'nether'), default='end')
    parser.add_argument('--passive-followups', type=int, choices=(0, 3), default=3,
                        help='Three bounded passive images only after an actual failed automatic image')
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
    experiment, failure, trace, progress, save_failure = None, None, None, {}, None
    try:
        verify_install(args.project)
        original = module('target_original_compat_runner', positive.COMPAT/'runner.py')
        experiment = positive.create_experiment_type(original)(args)
        run(experiment, original, 2 if args.target == 'end' else 1, args.passive_followups, progress)
        if progress.get('cleanup_failure'):
            raise RuntimeError('Isolated target room cleanup failed: '+progress['cleanup_failure'])
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
        result = {'schema': 'static_target_dimension_run_v1', 'failure': failure,
            'failure_traceback': trace, 'save_failure': save_failure, 'result': progress,
            'pixel_verified': failure is None and progress.get('pixel_verified') is True,
            'last_state': experiment.state if experiment is not None else None,
            'previous_evidence': str(args.previous_evidence),
            'previous_launch_sha256': hashlib.sha256(prior_bytes).hexdigest(),
            'previous_evidence_unchanged': unchanged, 'sources_before': before, 'sources_after': after,
            'sources_unchanged': before == after, 'launch_or_stop_performed': False,
            'owned_game_retained_for_parent_cleanup': True, 'runtime_file_writes': False,
            'continuous_updates_tested': False}
        (args.evidence/'target-status.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({'failure': failure, 'pixel_verified': result['pixel_verified'],
                          'end_pixel_verified': progress.get('end_pixel_verified', False)}), flush=True)
    return 1 if failure or not progress.get('pixel_verified') else 0


if __name__ == '__main__':
    raise SystemExit(main())
