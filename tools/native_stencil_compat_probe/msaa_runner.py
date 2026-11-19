"""Record native AA witness and full fixed dataset from an owned instance."""
import argparse
import json
from pathlib import Path
import time

from msaa import verify
from runner import Experiment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--requested-samples',type=int,choices=(1,4),required=True)
    args=parser.parse_args()
    args.project,args.evidence=args.project.resolve(),args.evidence.resolve()
    exp=Experiment(args)
    result={'requested_samples':args.requested_samples,'error':None}
    try:
        camera_attempts = []
        for step in range(10):
            time.sleep(.6)
            current = exp.call('pre_scene_ready_%02d'%step,
                expression="{'position':probe.camera.GetPosition(),'forward':probe.camera.GetForward(),"
                           "'dimension':probe.game.GetCurrentDimension()}")
            camera_attempts.append(current)
            if current['position'] is not None and current['forward'] is not None and current['dimension']==0:
                break
        else:
            raise RuntimeError('Native camera never reported stable position and direction')
        result['initial_camera']=camera_attempts
        exp.call('request_fixed_camera',
             "position=probe.camera.GetPosition()\n"
             "probe.origin=(int(position[0]),int(position[1])-1,int(position[2]))\n"
             "probe.camera.DepartCamera()\n"
             "if not (probe.camera.SetCameraPos((probe.origin[0],probe.origin[1]+1.,probe.origin[2])) "
             "and probe.camera.SetCameraRotation((8.,180.,0.))): raise RuntimeError('Native fixed camera rejected')")
        for step in range(10):
            time.sleep(.6)
            current=exp.call('fixed_camera_ready_%02d'%step,
                expression="{'position':probe.camera.GetPosition(),'forward':probe.camera.GetForward()}")
            if current['position'] is not None and current['forward'] is not None:
                break
        else:
            raise RuntimeError('Detached camera never reported stable position and direction')
        exp.call('initialize_delayed_anchor',
            "position=probe.camera.GetPosition()\nforward=probe.camera.GetForward()\n"
            "probe.anchor=tuple(position[i]+forward[i]*3. for i in range(3))\n"
            "api.HideHudGUI(True)\nprobe.native_hud_hidden=True\n"
            "probe.clear_actor=probe._new_actor('clear',0)")
        result['initial_state']=exp.initialize()
        mark=exp.raw_capture('active_msaa_witness','all')
        result['native_shader_witness']=verify(mark['capture_file'])
        for mode in (1,2,3):
            report=exp.capture('active_msaa_mode%d'%mode,mode,expected=False,output_y=650)
            result.setdefault('payload',[]).append({'mode':mode,'exact':report['exact'],
                'data_errors':report['data_error_pixels'],'guard_errors':report['guard_error_pixels']})
    except (RuntimeError,ValueError,OSError,KeyError) as error:
        result['error']=repr(error)
    finally:
        exp.save()
        path=args.evidence/'msaa-result.json'
        path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:result.get(key) for key in ('requested_samples','error','native_shader_witness','payload')}))


if __name__=='__main__':
    main()
