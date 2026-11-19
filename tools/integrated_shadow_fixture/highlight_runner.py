"""Finite world target highlighter branch for an already owned Experiment."""
import importlib.util
import json
from pathlib import Path
import time

from PIL import Image


HERE=Path(__file__).resolve().parent
_SPEC=importlib.util.spec_from_file_location('bounded_target_highlight_oracle',HERE/'highlight.py')
verify=importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verify)


def _images(reports):
    frames=[]
    for report in reports:
        with Image.open(report['capture_file']) as image:
            frames.append(image.convert('RGB'))
    return frames


def _project(experiment,label,world):
    values=experiment.call(label,expression='[probe.camera.WorldToScreenPoint(*point) for point in %r]'%(world,))
    if any(not value or value.get('depth',0)<=0 for value in values):
        raise RuntimeError('Target face must project in front of the fixed camera')
    return [[value['screenX'],value['screenY']] for value in values]


def _snapshot(experiment,label,enabled,target):
    return experiment.call(label,
        'probe.factory.CreatePlayerView(probe.level).HighlightBoxSelection(%r)'%enabled,
        expression="{'highlight_requested':%r,'pick':probe.camera.PickFacing(),"
        "'camera':{'position':probe.camera.GetPosition(),'forward':probe.camera.GetForward()},"
        "'block_readback':probe.factory.CreateBlockInfo(probe.level).GetBlockNew(%r,0)}"%(enabled,tuple(target)))


def _triplet(experiment,prefix,configuration,target):
    reports,states=[],[]
    for suffix,enabled in (('off_before',False),('on',True),('off_after',False)):
        states.append(_snapshot(experiment,prefix+'_'+suffix+'_toggle',enabled,target))
        reports.append(experiment.raw_capture(prefix+'_'+suffix,configuration=configuration))
    return reports,states


def run(experiment):
    """No launch/stop/input. Two backed-up blocks and one restored camera position."""
    path=experiment.evidence/'highlight-status.json'
    if path.exists():
        raise RuntimeError('Target highlight requires fresh evidence')
    status={'schema':'bounded_native_target_highlight_v1','variant':experiment.variant,
            'failure':None,'cleanup':{},'game_lifecycle_operations':False}
    backup,camera=None,None

    def save():
        path.write_text(json.dumps(status,indent=2),encoding='utf-8')
        experiment.save()

    try:
        camera=experiment.call('highlight_camera_before',expression=
            "{'position':probe.camera.GetPosition(),'rotation':probe.camera.GetCameraRotation()}")
        target=(-1,-59,-1)
        positions=[target,(0,-59,-1)]
        backup=experiment.server('highlight_block_backup',
            "blocks=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\n"
            "rows=[{'pos':pos,'before':blocks.GetBlockNew(pos,0)} for pos in %r]\n"
            "if any(row['before'] is None for row in rows): raise RuntimeError('Target blocks require loaded terrain')\n"
            "_result=json.dumps(rows)"%(positions,))
        status['backup']=backup
        save()
        placed=experiment.server('highlight_block_place',
            "blocks=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\nrows=[]\n"
            "for pos in %r:\n"
            "    blocks.SetBlockNew(tuple(pos),{'name':'minecraft:stone','aux':0},0,0,True,False)\n"
            "    rows.append({'pos':pos,'after':blocks.GetBlockNew(tuple(pos),0)})\n"
            "_result=json.dumps(rows)"%(positions,))
        status['placed']=placed
        if any(row['after'].get('name')!='minecraft:stone' for row in placed):
            raise RuntimeError('Target block readback failed')
        experiment.call('highlight_camera_fixed',
            "if not (probe.camera.SetCameraPos((-.5,-58.,-3.)) and probe.camera.SetCameraRotation((8.,180.,0.))): raise RuntimeError('Fixed target camera rejected')")
        time.sleep(.7)
        pick=experiment.call('highlight_native_target',expression='probe.camera.PickFacing()')
        if pick.get('type')!='Block' or tuple(pick.get(key) for key in ('x','y','z'))!=target:
            status['pick']=pick
            raise RuntimeError('Fixed target camera did not pick the owned stone block')
        face=[(-1.,-59.,-1.001),(0.,-59.,-1.001),(0.,-58.,-1.001),(-1.,-58.,-1.001)]
        control=[(.05,-58.7,-1.001),(.20,-58.7,-1.001),(.20,-58.4,-1.001),(.05,-58.4,-1.001)]
        plan=verify.make_plan(experiment.viewport,experiment.roi,
            _project(experiment,'highlight_face_projection',face),
            _project(experiment,'highlight_guard_projection',control),pick)
        status.update(plan=plan,face_world=face,control_world=control)
        save()  # Plan is fixed before observing native highlight pixels.
        baseline,states=_triplet(experiment,'highlight_native','off',target)
        status['native_snapshots']=states
        status['native_state_gate']=verify.compare_snapshots(states,plan)
        status['native_visual']=verify.compare_visible(*_images(baseline),plan)
        status['native_captures']=[report['capture_file'] for report in baseline]
        save()
        if not status['native_state_gate']['pass'] or not status['native_visual']['pass']:
            raise RuntimeError('Native target surface highlight positive control failed')
        if experiment.variant=='carrier':
            active,states=_triplet(experiment,'highlight_active','all',target)
            status['active_snapshots']=states
            status['active_state_gate']=verify.compare_snapshots(states,plan)
            _snapshot(experiment,'highlight_payload_on',True,target)
            data=experiment.data_checks('highlight_payload')
            status['coexistence']=verify.compare_coexistence(_images(baseline),_images(active),plan,data,experiment.payload)
            save()
            if not status['active_state_gate']['pass'] or not status['coexistence']['pass']:
                raise RuntimeError('Native target highlight and exact64KiB coexistence failed')
        status['pass']=True
    except Exception as error:
        status['failure']=repr(error)
        raise
    finally:
        experiment.call('highlight_native_off_final',
            'probe.factory.CreatePlayerView(probe.level).HighlightBoxSelection(False)')
        if camera is not None:
            status['cleanup']['camera_requested']=experiment.call('highlight_camera_restore',
                'probe.camera.SetCameraPos(%r)\nprobe.camera.SetCameraRotation(%r)'%(tuple(camera['position']),tuple(camera['rotation'])))
            time.sleep(.7)
            status['cleanup']['camera_after']=experiment.call('highlight_camera_restored_receipt',expression=
                "{'position':probe.camera.GetPosition(),'rotation':probe.camera.GetCameraRotation()}")
        if backup is not None:
            status['cleanup']['blocks']=experiment.server('highlight_blocks_restore',
                "blocks=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\nrows=[]\n"
                "for row in %r:\n"
                "    pos=tuple(row['pos']); block=row['before']\n"
                "    blocks.SetBlockNew(pos,block,0,0,False,False)\n"
                "    after=blocks.GetBlockNew(pos,0)\n"
                "    rows.append({'pos':pos,'exact':after is not None and after.get('name')==block.get('name') and after.get('aux',0)==block.get('aux',0)})\n"
                "_result=json.dumps({'all_exact':all(row['exact'] for row in rows),'rows':rows})"%(backup,))
        save()
    return status
