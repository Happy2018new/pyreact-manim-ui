"""Fresh diagnostic191 shadow/outline/target/UI composition; host only."""
import argparse
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

def build(output,game_exe):
    compat=module('joint_compat_build',HERE.parent/'native_stencil_compat_probe/build_probe.py')
    ui=module('joint_ui_build',HERE.parent/'integrated_ui_clip_fixture/build_fixture.py')
    shadow=module('joint_shadow_build',HERE.parent/'native_stencil_shadow_candidate/build_candidate.py')
    project=compat.build(Path(output),Path(game_exe),'carrier')
    package=project/'behavior_pack/stencil_large'
    ui.install(project/'resource_pack',package,[8,128,512,512],[[0,650,720,430]],(720,1080),'stencil_large')
    receipt=json.loads((project/'probe_resources.json').read_text(encoding='utf-8'))
    receipt['joint_diagnostic_candidate']={'shadow_mask':191,'native_outline':True,'native_target_selection':True,
        'rectangular_native_ui_clip':True,'weather':['sunny','rain'],'capacity':65536,'production_change':False}
    (project/'probe_resources.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    shadow.install(project,game_exe,191)
    return project

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--game-exe',type=Path,required=True)
    args=parser.parse_args();print(build(args.output,args.game_exe))
