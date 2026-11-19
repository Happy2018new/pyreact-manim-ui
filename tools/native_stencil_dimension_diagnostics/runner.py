"""Verify the unchanged static candidate at a shared positive camera/anchor altitude."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time
import traceback


HERE = Path(__file__).resolve().parent
COMPAT = HERE.parent/'native_stencil_compat_probe'
CANDIDATE = HERE.parent/'native_stencil_dimension_candidate'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


pose = module('positive_pose_helpers', HERE/'pose.py')
candidate = module('positive_pose_frozen_dimension_runner', CANDIDATE/'runner.py')


def nether_natural(experiment):
    return getattr(getattr(experiment, 'args', None), 'nether_natural', False) is True


def repeats_for(natural, repeats):
    selected = (1 if natural else 2) if repeats is None else repeats
    if selected not in (1, 2, 3) or (natural and selected != 1):
        raise ValueError('Natural Nether diagnostic requires one bounded round trip')
    return selected


def sources():
    paths = [p for folder in (HERE, CANDIDATE, COMPAT,
              HERE.parent/'weather_stencil_large_probe',
              HERE.parent/'weather_stencil_integrated_probe')
             for p in folder.iterdir() if p.is_file() and p.suffix in ('.py', '.md')]
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def wait_rooms(experiment):
    # Mark intent before dispatch, so a transport failure after server execution
    # still leaves the finally path responsible for checking room restoration.
    experiment.pose_receipt['rooms_request'] = {'dispatched': True}
    dimensions = (0,) if nether_natural(experiment) else (0, 1)
    experiment.pose_receipt['prepared_dimensions'] = list(dimensions)
    requested = experiment.server('positive_rooms_request', pose.room_request(dimensions))
    experiment.pose_receipt['rooms_request'] = requested
    if not all(row.get('accepted') is True for row in requested['requests']):
        raise RuntimeError('Positive pose chunk request rejected')
    for attempt in range(80):
        time.sleep(.25)
        value = experiment.server('positive_rooms_poll_%02d'%attempt, pose.room_status())
        experiment.pose_receipt['rooms_last'] = value
        rows = value['rooms']
        if any(row['phase'] == 'failed' for row in rows.values()):
            raise RuntimeError('Positive pose room preparation failed: '+repr(rows))
        if (set(rows) == {str(item) for item in dimensions} and all(row['phase'] == 'ready' and
                row['verified_blocks'] == pose.ROOM_BLOCKS for row in rows.values())):
            receipt = experiment.server('positive_rooms_backups', pose.room_status(True))
            experiment.pose_receipt['rooms'] = receipt
            return receipt
        advanced = experiment.server('positive_rooms_advance_%02d'%attempt, pose.room_advance())
        experiment.pose_receipt.setdefault('room_steps', []).append(advanced)
    raise RuntimeError('Positive pose room preparation timed out')


def restore(experiment):
    if not experiment.pose_receipt.get('rooms_request'):
        return {'requested': False, 'all_exact': True}
    requested = experiment.server('positive_rooms_restore_request', pose.restore_rooms())
    experiment.pose_receipt['restore_request'] = requested
    for attempt in range(80):
        time.sleep(.25)
        value = experiment.server('positive_rooms_restore_%02d'%attempt, pose.restore_status())
        experiment.pose_receipt['restore_last'] = value
        if value['all_exact']:
            return value
        if any(row['phase'] == 'failed' for row in value['rooms'].values()):
            raise RuntimeError('Positive room restoration failed: '+repr(value))
        advanced = experiment.server('positive_rooms_restore_advance_%02d'%attempt, pose.room_advance())
        experiment.pose_receipt.setdefault('restore_steps', []).append(advanced)
    raise RuntimeError('Positive room restoration timed out')


def create_experiment_type(original):
    class PositiveExperiment(original.Experiment):
        def __init__(self, args):
            super().__init__(args)
            self.pose_receipt = {}

        def prepare_camera(self):
            initial = self.call('positive_pose_initial', expression=
                "{'origin':probe.origin,'anchor':probe.anchor,'actors':len(probe.actors),"
                "'effects':len(probe.effects),'state':probe.state,'payload':probe.payload is not None,"
                "'dimension':probe.game.GetCurrentDimension(),'player':api.GetLocalPlayerId(),"
                "'frame':probe.render_event}")
            self.pose_receipt['initial'] = initial
            if (initial['origin'] is not None or initial['anchor'] is not None or
                    initial['actors'] or initial['effects'] or initial['state'] != 'empty' or
                    initial['payload'] or initial['dimension'] != 0):
                raise RuntimeError('Positive pose diagnostic requires a fresh empty Overworld candidate')
            wait_rooms(self)
            player = initial['player']
            moved = self.server('positive_player_request',
                "position=api.GetEngineCompFactory().CreatePos(%r)\n"
                "before=position.GetPos()\naccepted=position.SetPos(%r)\n"
                "_result=json.dumps({'before':before,'accepted':accepted,'after':position.GetPos()})"
                % (player, pose.PLAYER_FEET))
            self.pose_receipt['player_move'] = moved
            if moved['accepted'] is not True:
                raise RuntimeError('Positive pose player move rejected')
            requested = self.call('positive_camera_request',
                "probe.origin=(8,71,5)\nprobe.camera.DepartCamera()\n"
                "if not probe.camera.SetCameraPos(%r): raise RuntimeError('Positive camera position rejected')\n"
                "if not probe.camera.SetCameraRotation((8.,180.,0.)): raise RuntimeError('Positive camera rotation rejected')"
                % (pose.CAMERA,))
            for attempt in range(40):
                value = self.call('positive_camera_settle_%02d'%attempt, expression=
                    "{'position':probe.camera.GetPosition(),'forward':probe.camera.GetForward(),'frame':probe.render_event}")
                if (value['frame'] > requested['render_event'] and pose.vector(value['position']) and
                        pose.vector(value['forward']) and sum(v*v for v in value['forward']) > 0. and
                        all(abs(value['position'][i]-pose.CAMERA[i]) <= .01 for i in range(3))):
                    anchor = tuple(value['position'][i]+3.*value['forward'][i] for i in range(3))
                    if not pose.legal_pose(value['position'], anchor):
                        raise RuntimeError('Positive actor anchor is outside the controlled room')
                    location = self.server('positive_player_settled',
                        "position=api.GetEngineCompFactory().CreatePos(%r).GetPos()\n_result=json.dumps(position)" % player)
                    self.pose_receipt['player_settled'] = location
                    if (not pose.vector(location) or not 70. <= location[1] <= 73. or
                            abs(location[0]-pose.PLAYER_FEET[0]) > 1. or
                            abs(location[2]-pose.PLAYER_FEET[2]) > 1.):
                        raise RuntimeError('Positive player did not settle inside the loaded room')
                    self.pose_receipt.update(camera=value, anchor=anchor)
                    return self.call('positive_create_delayed_anchor',
                        "probe.anchor=%r\napi.HideHudGUI(True)\napi.HideCrossHairGUI(True)\n"
                        "probe.native_hud_hidden=True\nprobe.clear_actor=probe._new_actor('clear',0)" % (anchor,))
                time.sleep(.25)
            raise RuntimeError('Positive camera failed to settle before actor creation')

    return PositiveExperiment


def current(experiment, label):
    value = experiment.call(label, expression=
        "{'dimension':probe.game.GetCurrentDimension(),'probe':probe.snapshot(),"
        "'player_position':probe.factory.CreatePos(api.GetLocalPlayerId()).GetPos(),"
        "'camera':probe.camera.GetPosition(),'anchor':probe.anchor,"
        "'effect_positions':[probe.factory.CreateFrameAniTrans(effect).GetPos() for effect in probe.effects]}")
    experiment.state = value['probe']
    return value


def admission(client, server, target):
    client_position = client.get('player_position')
    server_position = server.get('position') if isinstance(server, dict) else None
    def local_positive(position):
        return (pose.vector(position) and 1. <= position[1] <= 126. and
                abs(position[0]-pose.DIMENSION_TARGET[0]) <= 4. and
                abs(position[2]-pose.DIMENSION_TARGET[2]) <= 4.)
    exact = (pose.vector(client_position) and pose.vector(server_position) and
             all(abs(position[i]-pose.DIMENSION_TARGET[i]) <= .05
                 for position in (client_position, server_position) for i in range(3)))
    return {'verified': client.get('dimension') == target and isinstance(server, dict) and
            server.get('dimension') == target and local_positive(client_position) and
            local_positive(server_position), 'target_dimension': target,
            'requested_head': list(pose.DIMENSION_TARGET),
            'client': {'dimension': client.get('dimension'), 'position': client_position}, 'server': server,
            'exact_requested_head': exact,
            'position_rule': 'finite head Y in [1,126], XZ within four blocks of request; natural terrain may adjust Y'}


def static_identity(state):
    return {key: state.get(key) for key in ('identity', 'generation', 'logical_bytes',
        'native_attempt_count', 'native_page_names', 'clear_page')}


def gate(value, frozen, serial=None, pair=None):
    state = value['probe']
    candidate.gate(state, frozen['identity'], frozen['native_page_names'], serial, pair)
    if static_identity(state) != frozen:
        raise RuntimeError('Static generation, bytes, cached geometry or native attempt count changed')
    if not pose.legal_pose(value['camera'], value['anchor']):
        raise RuntimeError('Recovered camera or geometry anchor left the positive diagnostic pose')
    positions = value['effect_positions']
    if (len(positions) != 3 or any(not pose.vector(position) or not 70. <= position[1] <= 77. or
            not 4.5 <= position[0] <= 11.5 or not 3.5 <= position[2] <= 12.5 for position in positions)):
        raise RuntimeError('Late effects left the positive diagnostic bounds')


def transit(experiment, label, target, player, frozen, original, record):
    try:
        before = current(experiment, label+'_before')
    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as error:
        record['before_failure'] = repr(error)
        if target != 0:
            raise
        # Invalid stale render entity IDs must not block the server return.
        record['request_intent'] = True
        record['request'] = experiment.server(label+'_request_without_client_preflight',
            "dimension=api.GetEngineCompFactory().CreateDimension(%r)\n"
            "accepted=dimension.ChangePlayerDimension(0,%r)\n_result=json.dumps({'accepted':accepted})"
            % (player, pose.DIMENSION_TARGET))
        raise RuntimeError('Owned Overworld return requested without usable client preflight; pixel verification unavailable')
    source = before['dimension']
    serial = before['probe']['dimension_recovery']['serial']+1
    record.update(before=before, expected_serial=serial, arm_failure=None,
                  requested_position=list(pose.DIMENSION_TARGET))
    try:
        candidate.arm(experiment, label+'_arm')
    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as error:
        record['arm_failure'] = repr(error)
        if target != 0:
            raise
    record['request_intent'] = True
    request = experiment.server(label+'_request',
        "dimension=api.GetEngineCompFactory().CreateDimension(%r)\n"
        "accepted=dimension.ChangePlayerDimension(%d,%r)\n_result=json.dumps({'accepted':accepted})"
        % (player, target, pose.DIMENSION_TARGET))
    record['request'] = request
    if request.get('accepted') is not True:
        raise RuntimeError('Positive pose dimension request rejected')
    for attempt in range(40):
        time.sleep(.6)
        value = current(experiment, label+'_poll_%02d'%attempt)
        record['last_state'] = value
        recovery = value['probe'].get('dimension_recovery', {})
        if value['probe'].get('error') or recovery.get('phase') == 'failed':
            if target == 0 and value['dimension'] != 0:
                continue
            raise RuntimeError('Automatic positive pose recovery failed: '+repr(recovery))
        if (value['dimension'] == target and recovery.get('phase') == 'ready' and
                recovery.get('serial') == serial and recovery.get('ready_serial') == serial):
            gate(value, frozen, serial, [source, target])
            # The next SDK command is passive host capture. No configure, inspect,
            # actor/effect recreation or post relink occurs after this ready receipt.
            if nether_natural(experiment):
                try:
                    record['automatic_readback'] = candidate.raw_readback(experiment, label+'_automatic_exact', original)
                finally:
                    server_position = None
                    try:
                        server_position = experiment.server(label+'_admitted_server_position',
                            "factory=api.GetEngineCompFactory()\n"
                            "dimension=factory.CreateDimension(%r).GetEntityDimensionId()\n"
                            "position=factory.CreatePos(%r).GetPos()\n"
                            "_result=json.dumps({'dimension':dimension,'position':position})" % (player, player))
                    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as error:
                        record['admission_read_failure'] = repr(error)
                    record['admitted_position'] = admission(value, server_position, target)
                if not record['admitted_position']['verified']:
                    raise RuntimeError('Automatic image captured, but actual natural-Nether player admission was not verified')
            else:
                record['automatic_readback'] = candidate.raw_readback(experiment, label+'_automatic_exact', original)
            controls = experiment.data_checks(label+'_checked')
            if not controls or not all(row.get('exact') is True for row in controls):
                raise RuntimeError('Positive pose mode1/mode3 exact verification failed')
            record.update(state=value, standard_exact_checks=controls, pixel_verified=True)
            return record
    raise RuntimeError('Matching positive pose recovery did not become ready before host deadline')


def run(experiment, original, repeats=None, progress=None):
    natural = nether_natural(experiment)
    repeats = repeats_for(natural, repeats)
    status = progress if progress is not None else {}
    status.update(trips=[], pixel_verified=False, fixture=experiment.pose_receipt,
                  nether_natural=natural, requested_round_trips=repeats,
                  nether_terrain_edits_allowed=not natural,
                  cleanup={}, cleanup_failure=None, end_tested=False,
                  end_limitation='End omitted; this diagnostic isolates the common positive Overworld/Nether pose')
    try:
        experiment.initialize()
        first = current(experiment, 'positive_initial')
        if (experiment.variant != 'carrier' or first['dimension'] != 0 or
                experiment.viewport != [720, 1080] or experiment.roi != [8, 128, 512, 512] or
                len(experiment.payload) != 65536 or 'dimension_recovery' not in first['probe']):
            raise RuntimeError('Positive pose requires the fresh 64 KiB Overworld candidate')
        frozen = static_identity(first['probe'])
        gate(first, frozen)
        status.update(initial=first, frozen_static_identity=frozen)
        player = experiment.call('positive_player', expression='api.GetLocalPlayerId()')
        candidate.arm(experiment, 'positive_initial_arm')
        status['initial_readback'] = candidate.raw_readback(experiment, 'positive_initial_exact', original)
        for index in range(repeats):
            row = {'index': index+1, 'outbound': {}, 'return': {},
                   'outbound_failure': None, 'return_failure': None}
            status['trips'].append(row)
            try:
                transit(experiment, 'positive_nether_%d'%index, 1, player, frozen, original, row['outbound'])
            except (RuntimeError, ValueError, OSError, KeyError, TypeError) as error:
                row['outbound_failure'] = repr(error)
            finally:
                try:
                    now = current(experiment, 'positive_return_decision_%d'%index)
                    needs_return = now['dimension'] != 0
                except (RuntimeError, ValueError, OSError, KeyError, TypeError) as error:
                    row['return_decision_failure'] = repr(error)
                    needs_return = row['outbound'].get('request_intent') is True
                if needs_return:
                    try:
                        transit(experiment, 'positive_overworld_%d'%index, 0, player, frozen, original, row['return'])
                    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as error:
                        row['return_failure'] = repr(error)
                else:
                    row['return_failure'] = 'Outbound did not leave Overworld; no return recovery was observed'
            if row['outbound_failure'] or row['return_failure']:
                raise RuntimeError('Positive pose dimension round trip failed: '+repr(row))
        status['pixel_verified'] = all(row['outbound']['pixel_verified'] and row['return']['pixel_verified']
                                       for row in status['trips'])
        return status
    finally:
        try:
            status['cleanup'] = restore(experiment)
        except (RuntimeError, ValueError, OSError, KeyError, TypeError) as error:
            status['cleanup_failure'] = repr(error)


def verify_install(project):
    installed = json.loads((project/'dimension_positive_pose_receipt.json').read_text(encoding='utf-8'))
    config = json.loads((project/'.mcdev.json').read_text(encoding='utf-8'))
    if config.get('world_source_path') != '' or (project/'level.dat').exists():
        raise RuntimeError('Positive pose requires the independent generated development world')
    runtime = project/'behavior_pack/stencil_large/dimension_candidate.py'
    for key, path in (('pose_source_sha256', HERE/'pose.py'), ('runner_source_sha256', HERE/'runner.py'),
                      ('candidate_runtime_sha256', runtime)):
        if installed[key] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise RuntimeError('Positive pose installation differs from reviewed source: '+key)
    if runtime.read_bytes() != (CANDIDATE/'runtime.py').read_bytes():
        raise RuntimeError('Positive pose must use the unchanged reviewed candidate runtime')
    frozen = json.loads((project/'dimension_candidate_receipt.json').read_text(encoding='utf-8'))
    if hashlib.sha256((project/'behavior_pack/stencil_large/modMain.py').read_bytes()).hexdigest() != frozen['entry_sha256']:
        raise RuntimeError('Dimension system registration changed')
    for name, sha in frozen['frozen_file_hashes'].items():
        if hashlib.sha256((project/name).read_bytes()).hexdigest() != sha:
            raise RuntimeError('Frozen carrier source or resource changed: '+name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path, required=True)
    parser.add_argument('--repeats', type=int, choices=(1, 2, 3),
                        help='Default 2 for controlled rooms; natural Nether permits only 1')
    parser.add_argument('--nether-natural', action='store_true',
                        help='One round trip; prepare only Overworld and use untouched natural Nether terrain')
    args = parser.parse_args()
    args.repeats = repeats_for(args.nether_natural, args.repeats)
    for key in ('project', 'evidence', 'previous_evidence'):
        setattr(args, key, getattr(args, key).resolve())
    if (args.evidence == args.previous_evidence or args.previous_evidence in args.evidence.parents or
            args.evidence in args.previous_evidence.parents):
        raise ValueError('Keep positive pose evidence outside preserved launch evidence')
    prior_path = args.previous_evidence/'launch.json'
    previous_files = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in args.previous_evidence.rglob('*') if p.is_file()}
    prior_bytes = prior_path.read_bytes()
    args.evidence.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(prior_path, args.evidence/'launch.json')
    before = sources()
    experiment, failure, trace, progress = None, None, None, {}
    try:
        verify_install(args.project)
        original = module('positive_pose_original_compat_runner', COMPAT/'runner.py')
        experiment = create_experiment_type(original)(args)
        run(experiment, original, args.repeats, progress)
        if progress.get('cleanup_failure'):
            raise RuntimeError('Positive pose cleanup failed: '+progress['cleanup_failure'])
    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as error:
        failure, trace = repr(error), traceback.format_exc()
    finally:
        if experiment is not None:
            experiment.save()
        after = sources()
        unchanged = previous_files == {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in args.previous_evidence.rglob('*') if p.is_file()}
        if not unchanged or before != after:
            failure = failure or 'Preserved evidence or reviewed sources changed'
        result = {'schema': 'positive_pose_dimension_run_v3', 'failure': failure,
            'nether_natural': args.nether_natural,
            'failure_traceback': trace, 'result': progress,
            'pixel_verified': failure is None and progress.get('pixel_verified') is True,
            'last_state': experiment.state if experiment is not None else None,
            'previous_evidence': str(args.previous_evidence),
            'previous_launch_sha256': hashlib.sha256(prior_bytes).hexdigest(),
            'previous_evidence_unchanged': unchanged, 'sources_before': before, 'sources_after': after,
            'sources_unchanged': before == after, 'launch_or_stop_performed': False,
            'owned_game_retained_for_parent_cleanup': True,
            'runtime_file_writes': False, 'continuous_update_tested': False}
        (args.evidence/'positive-pose-status.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({'failure': failure, 'pixel_verified': result['pixel_verified']}), flush=True)
    return 1 if failure or not progress.get('pixel_verified') else 0


if __name__ == '__main__':
    raise SystemExit(main())
