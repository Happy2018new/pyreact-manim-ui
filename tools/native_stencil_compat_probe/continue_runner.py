"""Hydrate a fresh evidence continuation on the same owned native test instance."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil

from runner import Experiment, HERE, integrated, module


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--previous-evidence',type=Path,required=True)
    parser.add_argument('--stage',choices=('enchanted','shadow','shadow_recovery','highlight','attached_highlight','attached_highlight_visible_hud','attached_highlight_selective_hud','lifecycle','dimension','post_bloom','post_depthoffield'),required=True)
    args=parser.parse_args()
    for key in ('project','evidence','previous_evidence'):
        setattr(args,key,getattr(args,key).resolve())
    args.evidence.mkdir(exist_ok=False)
    shutil.copyfile(args.previous_evidence/'launch.json',args.evidence/'launch.json')
    prior_path=args.previous_evidence/'results.json'
    prior_bytes=prior_path.read_bytes()
    prior=json.loads(prior_bytes)
    experiment=Experiment(args)
    experiment.viewport,experiment.roi=[720,1080],[8,128,512,512]
    experiment.payload=integrated.verify_module.payload_bytes(65536)
    experiment.loads=copy.deepcopy(prior['loads'])
    if experiment.loads:
        load=experiment.loads[-1]
        experiment.viewport,experiment.roi=load['viewport'],load['roi']
        experiment.payload=Path(load['input_file']).read_bytes()
    result,failure=None,None
    try:
        experiment.call('continuation_initial')
        if args.stage.startswith('post_'):
            helper=module('native_compat_post_helper',HERE.parent/'native_stencil_post_fixture/native_effects.py')
            result=helper.run(experiment,args.stage[5:])
        elif args.stage in ('highlight','attached_highlight','attached_highlight_visible_hud','attached_highlight_selective_hud'):
            filename={'highlight':'highlight_runner.py','attached_highlight':'attached_highlight_runner.py',
                      'attached_highlight_visible_hud':'visible_hud_highlight_runner.py',
                      'attached_highlight_selective_hud':'selective_hud_highlight_runner.py'}[args.stage]
            helper=module('native_compat_highlight_helper',HERE.parent/'integrated_shadow_fixture'/filename)
            result=helper.run(experiment)
        else:
            filename = {'lifecycle':'lifecycle.py','dimension':'lifecycle.py','shadow_recovery':'shadow_runner_recovery.py'}.get(args.stage,args.stage+'_runner.py')
            helper=module('native_compat_'+args.stage+'_helper',HERE/filename)
            if args.stage=='lifecycle':
                result=helper.run(experiment,include_dimension=False)
            elif args.stage=='dimension':
                result=helper.dimension(experiment)
            else:
                result=helper.run(experiment)
    except Exception as error:
        failure=repr(error)
        raise
    finally:
        experiment.save()
        (args.evidence/'continuation-status.json').write_text(json.dumps({'failure':failure,
            'stage':args.stage,'result':result,'last_state':experiment.state,'same_instance':True,
            'previous_results_file':str(prior_path),'previous_results_sha256':hashlib.sha256(prior_bytes).hexdigest(),
            'previous_results_unchanged':prior_path.read_bytes()==prior_bytes,
            'launch_or_stop_performed':False},indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
