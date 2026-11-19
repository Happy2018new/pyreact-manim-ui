"""Bounded attached-player recovery for native target highlighting; owner calls run."""
import importlib.util
import json
import math
from pathlib import Path
import time


HERE=Path(__file__).resolve().parent
_SPEC=importlib.util.spec_from_file_location('attached_highlight_previous_host_helpers',HERE/'highlight_runner.py')
previous=importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(previous)
verify=previous.verify


def _backup(experiment,label,positions):
    return experiment.server(label,
        "blocks=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\n"
        "rows=[{'pos':pos,'before':blocks.GetBlockNew(pos,0)} for pos in %r]\n"
        "if any(row['before'] is None for row in rows): raise RuntimeError('Attached target fixture needs loaded terrain')\n"
        "_result=json.dumps(rows)"%(positions,))


def _place(experiment,label,plan):
    result=experiment.server(label,
        "blocks=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\nrows=[]\n"
        "for pos,name in %r:\n"
        "    blocks.SetBlockNew(tuple(pos),{'name':name,'aux':0},0,0,True,False)\n"
        "    after=blocks.GetBlockNew(tuple(pos),0)\n"
        "    rows.append({'pos':pos,'after':after,'exact':after is not None and after.get('name')==name and after.get('aux',0)==0})\n"
        "_result=json.dumps({'all_exact':all(row['exact'] for row in rows),'rows':rows})"%(plan,))
    if not result['all_exact']:
        raise RuntimeError('Attached target block placement readback failed')
    return result


def _restore_blocks(experiment,label,backup):
    return experiment.server(label,
        "blocks=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\nrows=[]\n"
        "for row in %r:\n"
        "    pos=tuple(row['pos']); block=row['before']\n"
        "    blocks.SetBlockNew(pos,block,0,0,False,False)\n"
        "    after=blocks.GetBlockNew(pos,0)\n"
        "    rows.append({'pos':pos,'exact':after is not None and after.get('name')==block.get('name') and after.get('aux',0)==block.get('aux',0)})\n"
        "_result=json.dumps({'all_exact':all(row['exact'] for row in rows),'rows':rows})"%(backup,))


def _player(experiment,label,entity,position=None,rotation=None):
    code="factory=api.GetEngineCompFactory()\npos=factory.CreatePos(%r)\nrot=factory.CreateRot(%r)\naccepted=[]\n"%(entity,entity)
    if position is not None:
        code+="accepted.append(pos.SetFootPos(%r))\n"%(tuple(position),)
    if rotation is not None:
        code+="accepted.append(rot.SetRot(%r))\n"%(tuple(rotation),)
    code+="_result=json.dumps({'accepted':accepted,'foot':pos.GetFootPos(),'rotation':rot.GetRot()})"
    result=experiment.server(label,code)
    if not all(result['accepted']):
        raise RuntimeError('Owned player public position/rotation setter rejected')
    return result


def _face_world(target,eye):
    """Camera is aimed along actual cardinal forward; expose its nearest Z face."""
    x,y,z=target
    face_z=float(z) if eye[2]<z else float(z+1)
    epsilon=-.001 if eye[2]<z else .001
    return [(x,y,face_z+epsilon),(x+1,y,face_z+epsilon),
            (x+1,y+1,face_z+epsilon),(x,y+1,face_z+epsilon)]


def _snapshot(experiment,label,enabled,target):
    return experiment.call(label,
        'probe.factory.CreatePlayerView(probe.level).HighlightBoxSelection(%r)'%enabled,
        expression="{'highlight_requested':%r,'pick':probe.camera.PickFacing(),"
        "'camera':{'position':probe.camera.GetPosition(),'forward':probe.camera.GetForward()},"
        "'block_readback':probe.factory.CreateBlockInfo(probe.level).GetBlock(%r)}"%(enabled,tuple(target)))


def _triplet(experiment,prefix,configuration,target):
    reports,states=[],[]
    for suffix,enabled in (('off_before',False),('on',True),('off_after',False)):
        states.append(_snapshot(experiment,prefix+'_'+suffix+'_toggle',enabled,target))
        reports.append(experiment.raw_capture(prefix+'_'+suffix,configuration=configuration))
    return reports,states


def run(experiment):
    """Back up player/camera and <=47 blocks; never starts/stops/activates a game."""
    path=experiment.evidence/'attached-highlight-status.json'
    if path.exists():
        raise RuntimeError('Attached highlighter requires fresh evidence')
    status={'schema':'bounded_attached_native_highlight_recovery_v1','variant':experiment.variant,
            'failure':None,'cleanup':{},'game_lifecycle_operations':False,
            'reason':'Detached camera rendered the target but public PickFacing returned None',
            'public_camera_mode':'ordinary attached first person','pick_range_modified':False}
    camera,player,entity=None,None,None
    platform_backup,target_backup=None,None

    def save():
        path.write_text(json.dumps(status,indent=2),encoding='utf-8')
        experiment.save()

    try:
        camera=experiment.call('attached_highlight_camera_backup',expression=
            "{'player':api.GetLocalPlayerId(),'position':probe.camera.GetPosition(),"
            "'rotation':probe.camera.GetCameraRotation(),'anchor':probe.camera.GetCameraAnchor(),"
            "'offset':probe.camera.GetCameraOffset(),'perspective':probe.factory.CreatePlayerView(api.GetLocalPlayerId()).GetPerspective()}")
        entity=camera['player']
        player=_player(experiment,'attached_highlight_player_backup',entity)
        status.update(camera_backup=camera,player_backup=player)
        # Grounded foot y=-60 is supported by top of platform blocks at y=-61.
        plan=[((x,-61,z),'minecraft:stone') for x in range(-1,2) for z in range(-5,-2)]
        plan += [((x,y,z),'minecraft:air') for x in range(-1,2)
                 for y in range(-60,-56) for z in range(-5,-2)]
        platform_backup=_backup(experiment,'attached_highlight_platform_backup',[pos for pos,name in plan])
        status['platform_backup']=platform_backup
        save()
        status['platform_placed']=_place(experiment,'attached_highlight_platform_place',plan)
        status['player_moved']=_player(experiment,'attached_highlight_player_place',entity,(.5,-60.,-3.5),(8.,0.))
        experiment.call('attached_highlight_camera_attach',
            "probe.camera.ResetCameraPos()\nprobe.camera.UnDepartCamera()\n"
            "if not probe.camera.ResetCameraBindActorId(): raise RuntimeError('Native player camera bind reset rejected')\n"
            "if not probe.factory.CreatePlayerView(api.GetLocalPlayerId()).SetPerspective(0): raise RuntimeError('First person rejected')\n"
            "if not probe.camera.SetCameraAnchor((0.,0.,0.)): raise RuntimeError('Ordinary camera anchor rejected')\n"
            "if not probe.factory.CreateRot(api.GetLocalPlayerId()).SetRot((8.,0.)): raise RuntimeError('Local player aim rejected')")
        time.sleep(1.2)
        attached=experiment.call('attached_highlight_actual_eye',expression=
            "{'eye':probe.camera.GetPosition(),'forward':probe.camera.GetForward(),"
            "'pick_range':probe.factory.CreatePlayer(api.GetLocalPlayerId()).GetPickRange(),"
            "'perspective':probe.factory.CreatePlayerView(api.GetLocalPlayerId()).GetPerspective(),"
            "'player_foot':probe.factory.CreatePos(api.GetLocalPlayerId()).GetFootPos()}")
        status['attached']=attached
        eye,forward=attached['eye'],attached['forward']
        if attached['perspective']!=0 or abs(forward[0])>.05 or abs(forward[2])<.9:
            raise RuntimeError('Attached camera must settle at first-person near-cardinal Z')
        if attached['pick_range']<2.:
            raise RuntimeError('Existing native player pick range is too short')
        target=tuple(int(math.floor(eye[index]+forward[index]*2.)) for index in range(3))
        # Adjacent ordinary block provides an independent same-plane surface guard.
        adjacent=(target[0]+1,target[1],target[2])
        target_backup=_backup(experiment,'attached_highlight_target_backup',[target,adjacent])
        status['target_backup']=target_backup
        save()
        status['target_placed']=_place(experiment,'attached_highlight_target_place',
            [(target,'minecraft:stone'),(adjacent,'minecraft:stone')])
        time.sleep(.7)
        pick=experiment.call('attached_highlight_native_pick',expression='probe.camera.PickFacing()')
        status['pick']=pick
        if pick.get('type')!='Block' or tuple(pick.get(key) for key in ('x','y','z'))!=target:
            raise RuntimeError('Attached ordinary player camera did not pick its owned near target')
        face=_face_world(target,eye)
        if abs(pick.get('hitPosZ',float('inf'))-face[0][2])>.011:
            raise RuntimeError('Native pick must hit the declared near Z face, not a top or side face')
        gx,gy,gz=adjacent
        face_z=face[0][2]
        control=[(gx+.05,gy+.3,face_z),(gx+.20,gy+.3,face_z),
                 (gx+.20,gy+.6,face_z),(gx+.05,gy+.6,face_z)]
        frozen=verify.make_plan(experiment.viewport,experiment.roi,
            previous._project(experiment,'attached_highlight_face_projection',face),
            previous._project(experiment,'attached_highlight_guard_projection',control),pick)
        status.update(plan=frozen,target=target,face_world=face,control_world=control)
        save()
        baseline,states=_triplet(experiment,'attached_highlight_native','off',target)
        status['native_snapshots']=states
        status['native_state_gate']=verify.compare_snapshots(states,frozen)
        status['native_visual']=verify.compare_visible(*previous._images(baseline),frozen)
        status['native_captures']=[report['capture_file'] for report in baseline]
        save()
        if not status['native_state_gate']['pass'] or not status['native_visual']['pass']:
            raise RuntimeError('Attached native face highlight positive control failed')
        if experiment.variant=='carrier':
            active,states=_triplet(experiment,'attached_highlight_active','all',target)
            status['active_snapshots']=states
            status['active_state_gate']=verify.compare_snapshots(states,frozen)
            _snapshot(experiment,'attached_highlight_payload_on',True,target)
            data=experiment.data_checks('attached_highlight_payload')
            status['coexistence']=verify.compare_coexistence(previous._images(baseline),previous._images(active),frozen,data,experiment.payload)
            status['payload_captures']=[report['capture_file'] for report in data]
            save()
            if not status['active_state_gate']['pass'] or not status['coexistence']['pass']:
                raise RuntimeError('Attached native highlight and exact64KiB coexistence failed')
        status['pass']=True
    except Exception as error:
        status['failure']=repr(error)
        raise
    finally:
        def cleanup(label,operation):
            try:
                result=operation()
                status['cleanup'][label]=result
                return result
            except Exception as error:
                status['cleanup'][label]={'failure':repr(error)}
                status['failure']=status['failure'] or 'Attached highlighter cleanup failed'
                status['pass']=False
                return None

        if entity is not None:
            cleanup('highlight_off',lambda: experiment.call('attached_highlight_off_final',
                'probe.factory.CreatePlayerView(probe.level).HighlightBoxSelection(False)'))
        if player is not None:
            restored=cleanup('player_restored',lambda: _player(experiment,'attached_highlight_player_restore',entity,player['foot'],player['rotation']))
            exact=restored is not None and all(
                all(abs(first-second)<=.001 for first,second in zip(restored[key],player[key]))
                for key in ('foot','rotation'))
            status['cleanup']['player_matches_backup']=exact
            if not exact:
                status['failure']=status['failure'] or 'Player restoration readback differed'
                status['pass']=False
        if camera is not None and player is not None:
            cleanup('camera_requested',lambda: experiment.call('attached_highlight_camera_restore',
                "probe.factory.CreateRot(api.GetLocalPlayerId()).SetRot(%r)\n"
                "probe.factory.CreatePlayerView(api.GetLocalPlayerId()).SetPerspective(%r)\n"
                "probe.camera.SetCameraAnchor(%r)\nprobe.camera.SetCameraOffset(%r)\n"
                "probe.camera.DepartCamera()\nprobe.camera.SetCameraPos(%r)\nprobe.camera.SetCameraRotation(%r)"%
                (tuple(player['rotation']),camera['perspective'],tuple(camera['anchor']),tuple(camera['offset']),
                 tuple(camera['position']),tuple(camera['rotation']))))
            time.sleep(.7)
            restored=cleanup('camera_after',lambda: experiment.call('attached_highlight_camera_restored',expression=
                "{'position':probe.camera.GetPosition(),'rotation':probe.camera.GetCameraRotation(),"
                "'anchor':probe.camera.GetCameraAnchor(),'offset':probe.camera.GetCameraOffset(),"
                "'perspective':probe.factory.CreatePlayerView(api.GetLocalPlayerId()).GetPerspective()}"))
            if restored is not None:
                exact=restored['perspective']==camera['perspective'] and all(
                    all(abs(first-second)<=.001 for first,second in zip(restored[key],camera[key]))
                    for key in ('position','rotation','anchor','offset'))
                status['cleanup']['camera_matches_backup']=exact
                if not exact:
                    status['failure']=status['failure'] or 'Attached camera restoration readback differed'
                    status['pass']=False
        for label,backup in (('target',target_backup),('platform',platform_backup)):
            if backup is not None:
                restored=cleanup(label+'_blocks',lambda: _restore_blocks(experiment,'attached_highlight_'+label+'_restore',backup))
                if restored is None or not restored['all_exact']:
                    status['failure']=status['failure'] or 'Attached highlighter block restoration failed'
                    status['pass']=False
        save()
    return status
