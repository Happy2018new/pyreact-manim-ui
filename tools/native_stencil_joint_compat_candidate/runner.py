"""Finite joint native diagnostics on one already owned session; no launch/stop."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import time

import numpy as np
from PIL import Image

HERE=Path(__file__).resolve().parent
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
compat=module('joint_native_compat_host',HERE.parent/'native_stencil_compat_probe/runner.py')
attached=module('joint_attached_public_helpers',HERE.parent/'integrated_shadow_fixture/attached_highlight_runner.py')
hover=module('joint_hover_public_helpers',HERE.parent/'native_stencil_compat_probe/shadow_runner_recovery.py')
outline_verify=module('joint_native_outline_verifier',HERE.parent/'integrated_outline_fixture/verify_resolved.py')
ui_verify=module('joint_native_ui_verifier',HERE.parent/'integrated_ui_clip_fixture/verify.py')
candidate=module('joint_shadow_candidate_provenance',HERE.parent/'native_stencil_shadow_candidate/build_candidate.py')
ambient=module('joint_existing_nonplayer_guard',HERE/'ambient_guard.py')

def images(reports):
    result=[]
    for row in reports:
        with Image.open(row['capture_file']) as image:result.append(image.convert('RGB'))
    return result

def close_native(actual,wanted,tolerance=.001):
    if isinstance(wanted,(list,tuple)):
        return isinstance(actual,(list,tuple)) and len(actual)==len(wanted) and all(close_native(a,b,tolerance)for a,b in zip(actual,wanted))
    if isinstance(wanted,(int,float)) and not isinstance(wanted,bool):
        return isinstance(actual,(int,float)) and not isinstance(actual,bool) and math.isfinite(actual) and abs(actual-wanted)<=tolerance
    return actual==wanted

def restore_blocks(exp,label,backup):
    first=attached._restore_blocks(exp,label,backup)
    if first['all_exact']:
        return first
    failed={tuple(row['pos'])for row in first['rows']if not row['exact']}
    retry=attached._restore_blocks(exp,label+'_bounded_retry',[row for row in backup if tuple(row['pos'])in failed])
    replaced={tuple(row['pos']):row for row in retry['rows']}
    rows=[replaced.get(tuple(row['pos']),row)for row in first['rows']]
    return {'all_exact':all(row['exact']for row in rows),'rows':rows,
            'first_attempt':first,'one_bounded_failed_position_retry':retry}

def target_plan(exp,target,eye,ui_receipt):
    world=attached._face_world(target,eye)
    polygon=attached.previous._project(exp,'joint_target_face_projection',world)
    # This farther target deliberately uses an explicit inside-ROI positive
    # control; historical near-target cross-boundary coverage is not claimed.
    plan={'viewport':exp.viewport,'roi':exp.roi,'face_polygon':polygon,'output_y':650,
          'coverage':'visible face interior; no ROI-boundary requirement','wireframe_excluded':True,
          'ui_rectangles_excluded':[case['rect'] for case in ui_receipt['cases']],
          'pixel_derived_masks':False,'alignment_search':False}
    return plan

def target_mask(plan):
    poly=np.asarray(plan['face_polygon']);center=poly.mean(axis=0)
    mask=hover.verify._polygon((plan['viewport'][1],plan['viewport'][0]),(center+(poly-center)*.8).tolist())
    mask[650:]=False
    for x,y,w,h in plan['ui_rectangles_excluded']:mask[y:y+h,x:x+w]=False
    return mask

def target_visible(frames,plan):
    arrays=[np.asarray(frame).astype(np.int16) for frame in frames]
    mask=target_mask(plan)
    delta=np.minimum(np.max(np.abs(arrays[1]-arrays[0]),axis=2),np.max(np.abs(arrays[1]-arrays[2]),axis=2))
    count=int((mask&(delta>=8)).sum())
    off_changed=int((mask&(np.max(np.abs(arrays[0]-arrays[2]),axis=2)>4)).sum())
    stable=off_changed<=.01*int(mask.sum())
    return {'pass':count>=100 and stable,'filled_face_changed_pixels':count,'wireframe_excluded':True,
            'predeclared_face_pixels':int(mask.sum()),'requires_roi_crossing':False,
            'off_replay_stable':stable,'off_replay_changed_pixels':off_changed}

class Experiment(compat.Experiment):
    def data_checks(self,prefix):
        return [self.capture(prefix+'_m%d'%mode,mode,output_y=650,expected=False)for mode in(1,3)]

def run(exp):
    status={'schema':'joint_native_shadow_outline_target_ui_v1','failure':None,'weather':[],
            'mask':191,'capacity':65536,'cleanup':{},'production_change':False}
    status['runner_source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    status['ambient_guard_source_sha256']=hashlib.sha256((HERE/'ambient_guard.py').read_bytes()).hexdigest()
    output=exp.evidence/'joint-status.json'
    backups={};camera=player=None;entity=None;guard=ambient.AmbientGuard(exp)
    def save():
        exp.save();output.write_text(json.dumps(status,indent=2),encoding='utf-8')
    def attempt(label,fn):
        try:status['cleanup'][label]=fn()
        except Exception as error:status['cleanup'][label]={'failure':repr(error)}
    try:
        status['candidate']=candidate.validate(exp.args.project,191)
        guard.prepare();status['ambient_guard']=guard.receipt;save()
        exp.initialize()
        camera=exp.call('joint_camera_backup',expression="{'position':probe.camera.GetPosition(),'rotation':probe.camera.GetCameraRotation(),'anchor':probe.camera.GetCameraAnchor(),'offset':probe.camera.GetCameraOffset(),'perspective':probe.factory.CreatePlayerView(api.GetLocalPlayerId()).GetPerspective(),'player':api.GetLocalPlayerId()}")
        entity=camera['player'];player=attached._player(exp,'joint_player_backup',entity)
        platform=[((x,-61,z),'minecraft:stone')for x in range(-1,2)for z in range(-5,-2)]
        platform += [((x,y,z),'minecraft:air')for x in range(-1,2)for y in range(-60,-56)for z in range(-5,-2)]
        backups['platform']=attached._backup(exp,'joint_platform_backup',[pos for pos,name in platform]);save()
        attached._place(exp,'joint_platform_place',platform)
        attached._player(exp,'joint_player_place',entity,(.5,-60.,-3.5),(8.,0.))
        exp.call('joint_attach_camera',"probe.camera.ResetCameraPos()\nprobe.camera.UnDepartCamera()\nprobe.camera.ResetCameraBindActorId()\nprobe.factory.CreatePlayerView(api.GetLocalPlayerId()).SetPerspective(0)\nprobe.camera.SetCameraAnchor((0.,0.,0.))\nprobe.factory.CreateRot(api.GetLocalPlayerId()).SetRot((8.,0.))\napi.HideHudGUI(False)\napi.HideCrossHairGUI(False)\napi.HideSlotBarGui(True)\napi.HideHealthGui(True)\napi.HideArmorGui(True)")
        time.sleep(1.)
        view=exp.call('joint_attached_view',expression="{'eye':probe.camera.GetPosition(),'forward':probe.camera.GetForward(),'range':probe.factory.CreatePlayer(api.GetLocalPlayerId()).GetPickRange()}")
        status['view']=view
        if not isinstance(view['range'],(int,float)) or view['range']<4.:
            raise RuntimeError('Joint target requires existing public pick range at least four; range is not changed')
        target=tuple(int(math.floor(view['eye'][i]+view['forward'][i]*4.))for i in range(3))
        backups['target']=attached._backup(exp,'joint_target_backup',[target]);save()
        attached._place(exp,'joint_target_place',[(target,'minecraft:stone')]);time.sleep(.7)
        pick=exp.call('joint_target_pick',expression='probe.camera.PickFacing()');status['pick']=pick
        if pick.get('type')!='Block' or tuple(pick.get(k)for k in('x','y','z'))!=target:
            raise RuntimeError('Joint normal attached camera must actually select its target')
        declared_face=attached._face_world(target,view['eye'])
        if abs(pick.get('hitPosZ',float('inf'))-declared_face[0][2])>.011:
            raise RuntimeError('Joint native PickFacing must hit the declared near Z face')
        ui_receipt=json.loads((exp.args.project/'ui_clip_fixture_receipt.json').read_text())
        status['target_plan']=target_plan(exp,target,view['eye'],ui_receipt)
        ray=exp.call('joint_shadow_ray',expression="probe.camera.GetWorldRayFromScreenPoint(520.,550.)")
        origin,direction=ray['origin'],ray['direction'];distance=(-59.-origin[1])/direction[1]
        foot=[origin[i]+direction[i]*distance for i in range(3)];foot[1]=-58.25
        backups['floor']=hover._floor(exp,foot);save()
        status['floor_placed']=hover._place_floor(exp,backups['floor'])
        if (not status['floor_placed']['rules_ok'] or not status['floor_placed']['time_ok'] or
                len(status['floor_placed']['rows'])!=36 or any(row['after'].get('name')!='minecraft:stone'
                or row['after'].get('aux',0)!=0 for row in status['floor_placed']['rows'])):
            raise RuntimeError('Joint floor/rules/daytime native readback rejected')
        exp.call('joint_cube','probe.prepare_outline(position=%r)\nprobe.configure_outline(True)'%(tuple(foot),))
        cube=exp.state['outline']['entity'];status['caster']=cube
        body=hover._body(exp,cube,'cube');px,_,pz=foot
        receiver=[(px-1.25,-59.,pz-1.25),(px+1.25,-59.,pz-1.25),(px+1.25,-59.,pz+1.25),(px-1.25,-59.,pz+1.25)]
        control=[(px-.35,-59.,pz+1.7),(px+.35,-59.,pz+1.7),(px+.35,-59.,pz+2.2),(px-.35,-59.,pz+2.2)]
        plan=hover.verify.make_plan(exp.viewport,exp.roi,hover._polygon(exp,'joint_receiver',receiver),body,hover._polygon(exp,'joint_floor_control',control))
        status['shadow_plan']=plan
        exp.call('joint_ui_open','from stencil_large.ui_clip_fixture import UiClipFixture\nprobe.ui_clip=UiClipFixture(probe)\nprobe.open_ui()');time.sleep(.7);exp.call('joint_ui_on','probe.configure_ui(True)')
        status['ui_receipt']=ui_receipt
        for weather,raining in(('sunny',False),('rain',True)):
            row={'weather':weather,'roles':{},'failure':None};status['weather'].append(row)
            exp.weather('joint_'+weather+'_weather',raining)
            guard.check()
            def controls(shadow=True,outline=True,highlight=True):
                return "probe.factory.CreateModel(%r).SetEntityShadowShow(%r)\nprobe.configure_outline(%r)\nprobe.factory.CreatePlayerView(probe.level).HighlightBoxSelection(%r)\nprobe.configure_ui(True)"%(cube,shadow,outline,highlight)
            for role in('shadow','outline','highlight'):
                frames=[];states=[]
                for suffix,on in(('off_before',False),('on',True),('off_after',False)):
                    flags={'shadow':True,'outline':True,'highlight':True};flags[role]=on
                    exp.call('joint_'+weather+'_'+role+'_'+suffix+'_set',controls(**flags))
                    frames.append(exp.raw_capture('joint_'+weather+'_'+role+'_'+suffix,'off'))
                    states.append(exp.call('joint_'+weather+'_'+role+'_'+suffix+'_state',expression='probe.outline.snapshot()'))
                pics=images(frames)
                if role=='shadow':result=hover.verify.compare_shadow(*pics,plan)
                elif role=='outline':
                    result=outline_verify.compare_outline(*pics,exp.roi,states[1]['projected_bounds'])
                    result['state_gate']=outline_verify.compare_snapshots(*states)
                else:result=target_visible(pics,status['target_plan'])
                row['roles'][role]={'result':result,'captures':[f['capture_file']for f in frames],
                                    'states':states};save()
            exp.call('joint_'+weather+'_all_on',controls())
            native=exp.raw_capture('joint_'+weather+'_all_on_native','off')
            active=exp.raw_capture('joint_'+weather+'_all_on_active','all')
            data=exp.data_checks('joint_'+weather+'_all_roles_payload')
            row['same_frame_reports']=data;row['native_all_on']=native;row['active_all_on']=active
            row['ui_same_frame']=[ui_verify.verify(f['capture_file'],ui_receipt)for f in data]
            row['same_frame_data_pass']=all(f['exact']for f in data)
            row['same_frame_ui_pass']=all(f['all_exact']for f in row['ui_same_frame'])
            row['same_frame_visuals']=[]
            baseline=np.asarray(images([native])[0]).astype(np.int16)
            receiver,bodymask,control,_,_=hover.verify._masks(plan)
            shadow_region=receiver|bodymask|control
            for report in data:
                current=images([report])[0]
                visual={'label':report['label'],'mode':report['mode']}
                for role in('shadow','outline','highlight'):
                    controls_frames=images([{'capture_file':path}for path in row['roles'][role]['captures']])
                    joint=[controls_frames[0],current,controls_frames[2]]
                    if role=='shadow':visual[role]=hover.verify.compare_shadow(*joint,plan)
                    elif role=='outline':visual[role]=outline_verify.compare_outline(*joint,exp.roi,row['roles'][role]['states'][1]['projected_bounds'])
                    else:visual[role]=target_visible(joint,status['target_plan'])
                arr=np.asarray(current).astype(np.int16)
                bounds=row['roles']['outline']['result'].get('fixture_window')
                regions={'shadow':shadow_region,'highlight':target_mask(status['target_plan'])}
                if bounds:regions['outline']=outline_verify._ORIGINAL._rectangle(arr.shape[:2],bounds)
                visual['strict_native_all_on_preservation']={name:hover.verify._change(baseline,arr,region,2)for name,region in regions.items()}
                visual['all_roles_visible']=all(visual[role]['pass']for role in('shadow','outline','highlight'))
                visual['all_regions_preserved']=all(item['changed_pixels']==0 for item in visual['strict_native_all_on_preservation'].values())
                row['same_frame_visuals'].append(visual)
            # Authenticate all roles are still requested and bound in the exact
            # mode1/3 states, alongside their separate actual visual controls.
            row['joint_role_state']=exp.call('joint_'+weather+'_all_role_readback',expression="{'outline':probe.outline.snapshot(),'pick':probe.camera.PickFacing(),'ui':probe.ui_clip.snapshot(),'camera':{'position':probe.camera.GetPosition(),'forward':probe.camera.GetForward()}}")
            row['all_visual_positive_controls_pass']=all(role['result']['pass']for role in row['roles'].values()) and row['roles']['outline']['result']['state_gate']['pass']
            row['same_frame_visual_pass']=all(item['all_roles_visible'] and item['all_regions_preserved']for item in row['same_frame_visuals'])
            row['pass']=row['same_frame_data_pass'] and row['same_frame_ui_pass'] and row['all_visual_positive_controls_pass'] and row['same_frame_visual_pass']
            row['weather_motion_can_make_strict_cross_frame_visuals_inconclusive']=raining
            guard.check()
            save()
        status['pass']=all(row['pass']for row in status['weather'])
    except Exception as error:
        status['failure']=repr(error);save();raise
    finally:
        attempt('weather_clear',lambda:exp.weather('joint_cleanup_weather',False))
        attempt('roles_off',lambda:exp.call('joint_roles_off',"probe.factory.CreatePlayerView(probe.level).HighlightBoxSelection(False)\nprobe.configure_ui(False)\nprobe.outline.destroy()"))
        for label in('floor','target','platform'):
            if label in backups:
                attempt(label,lambda label=label:restore_blocks(exp,'joint_restore_'+label,backups[label]))
        if player is not None:attempt('player',lambda:attached._player(exp,'joint_player_restore',entity,player['foot'],player['rotation']))
        if camera is not None and player is not None:
            attempt('camera',lambda:exp.call('joint_camera_restore',"probe.factory.CreatePlayerView(api.GetLocalPlayerId()).SetPerspective(%r)\nprobe.camera.SetCameraAnchor(%r)\nprobe.camera.SetCameraOffset(%r)\nprobe.camera.DepartCamera()\nprobe.camera.SetCameraPos(%r)\nprobe.camera.SetCameraRotation(%r)"%(camera['perspective'],tuple(camera['anchor']),tuple(camera['offset']),tuple(camera['position']),tuple(camera['rotation']))))
            time.sleep(.7)
            attempt('camera_readback',lambda:exp.call('joint_camera_restore_readback',expression="{'position':probe.camera.GetPosition(),'rotation':probe.camera.GetCameraRotation(),'anchor':probe.camera.GetCameraAnchor(),'offset':probe.camera.GetCameraOffset(),'perspective':probe.factory.CreatePlayerView(api.GetLocalPlayerId()).GetPerspective()}"))
            actual=status['cleanup'].get('camera_readback',{})
            status['cleanup']['camera_within_0_001']={key:close_native(actual.get(key),camera[key])for key in('position','rotation','anchor','offset','perspective')}
            status['cleanup']['player_within_0_001']={key:close_native(status['cleanup'].get('player',{}).get(key),player[key])for key in('foot','rotation')}
        attempt('hud',lambda:exp.call('joint_hud_restore',"api.HideSlotBarGui(False)\napi.HideHealthGui(False)\napi.HideArmorGui(False)\napi.HideCrossHairGUI(True)\napi.HideHudGUI(True)"))
        status['ambient_guard']=guard.cleanup()
        status['cleanup_pass']=all('failure'not in value if isinstance(value,dict)else True for value in status['cleanup'].values())
        for key in('floor','target','platform'):
            if key in status['cleanup']:status['cleanup_pass'] &= status['cleanup'][key].get('all_exact')is True
        for key in('camera_within_0_001','player_within_0_001'):
            if key in status['cleanup']:status['cleanup_pass'] &= all(status['cleanup'][key].values())
        status['cleanup_pass'] &= status['ambient_guard']['cleanup_failure'] is None
        if 'pass' in status:status['pass'] &= status['cleanup_pass']
        save()
    return status

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True);parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--previous-evidence',type=Path,required=True);args=parser.parse_args()
    args.project=args.project.resolve();args.evidence=args.evidence.resolve();args.evidence.mkdir(exist_ok=False)
    shutil.copyfile(args.previous_evidence/'launch.json',args.evidence/'launch.json')
    launch=json.loads((args.evidence/'launch.json').read_text());session=Path(launch['session_file'])
    (args.evidence/'assigned-session-snapshot.json').write_bytes(session.read_bytes())
    status=run(Experiment(args));print(json.dumps({key:status.get(key)for key in('pass','failure','cleanup_pass')}))
    raise SystemExit(0 if status.get('pass') else 1)

if __name__=='__main__':main()
