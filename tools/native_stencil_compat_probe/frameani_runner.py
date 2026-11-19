"""Finite ordinary FrameAni stock/carrier comparison, with exact carrier reads."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from PIL import Image
from runner import Experiment, HERE, module

verify = module('native_frameani_fixed_oracle', HERE.parent/'integrated_frameani_fixture/verify.py')
ROUTES = ('sequence','point_sequence','point_sequence_add','sequence_add')


def images(reports):
    result=[]
    for report in reports:
        with Image.open(report['capture_file']) as image:
            result.append(image.convert('RGB'))
    return result


def backdrop(experiment):
    return experiment.server('frameani_static_wall', """factory=api.GetEngineCompFactory()
level=api.GetLevelId()
game=factory.CreateGame(level)
rules=game.SetGameRulesInfoServer({'cheat_info':{'daylight_cycle':False,'weather_cycle':False,'mob_spawn':False,'random_tick_speed':0}})
time_ok=factory.CreateTime(level).SetTimeOfDay(6000)
blocks=factory.CreateBlockInfo(level)
edits=[]
for x in range(-5,5):
    for y in range(-61,-51):
        pos=(x,y,3)
        before=blocks.GetBlockNew(pos,0)
        if before is None: raise RuntimeError('Owned loaded wall position required')
        blocks.SetBlockNew(pos,{'name':'minecraft:stone','aux':0},0,0,True,False)
        after=blocks.GetBlockNew(pos,0)
        edits.append({'pos':pos,'before':before,'after':after})
        if after.get('name')!='minecraft:stone': raise RuntimeError('Wall placement mismatch')
_result=json.dumps({'rules_ok':rules,'time_ok':time_ok,'edits':edits,'blocks':100})
""")


def restore_wall(experiment, receipt):
    code = "blocks=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\n"
    code += "backup=%r\nrestored=[]\n" % ([(row['pos'],row['before']) for row in receipt['edits']],)
    code += "for pos,before in backup:\n"
    code += "    blocks.SetBlockNew(tuple(pos),before,0,0,False,False)\n"
    code += "    after=blocks.GetBlockNew(tuple(pos),0)\n"
    code += "    restored.append({'pos':pos,'exact':after is not None and after.get('name')==before.get('name') and after.get('aux',0)==before.get('aux',0)})\n"
    code += "_result=json.dumps({'count':len(restored),'all_exact':all(row['exact'] for row in restored),'edits':restored})"
    result=experiment.server('frameani_restore_wall',code)
    if not result['all_exact']:
        raise RuntimeError('Owned FrameAni wall backup restoration failed')
    return result


def run(experiment, locations=('inside','outside')):
    status={'variant':experiment.variant,'cases':[],'failure':None,'cleanup':{},
            'ordinary_fixture_materials_modified':False,'first_failure_observed':None}
    path=experiment.evidence/'frameani-status.json'

    def save():
        path.write_text(json.dumps(status,indent=2),encoding='utf-8')
        experiment.save()

    wall=None
    try:
        wall=backdrop(experiment)
        status['wall']=wall
        save()
        for location in locations:
            fixture=experiment.call(location+'_frameani_create',
                "from stencil_large.ordinary_frameani_fixture import FrameAniFixture\n"
                "probe.ordinary_frameani=FrameAniFixture(probe)\n"
                "probe.ordinary_frameani.create(location=%r)" % location,
                expression='probe.ordinary_frameani.snapshot()')
            status.setdefault('predeclared_fixtures',{})[location]=fixture
            save()
            configurations=('off',) if experiment.variant=='stock' else ('off','all')
            for configuration in configurations:
                for route in ROUTES:
                    label=location+'_'+configuration+'_'+route
                    reports,snapshots=[],[]
                    for suffix,enabled in (('off_before',False),('on',True),('off_after',False)):
                        snapshots.append(experiment.frameani(route,enabled,label+'_'+suffix+'_fixture'))
                        reports.append(experiment.raw_capture(label+'_'+suffix,configuration))
                    state=verify.compare_snapshots(*snapshots)
                    pixels=verify.compare_visible(*images(reports),snapshots[1])
                    item={'label':label,'configuration':configuration,'route':route,'location':location,
                          'fixture_snapshots':snapshots,'capture_labels':[row['label'] for row in reports],
                          'snapshots':state,'pixels':pixels,'pass':state['pass'] and pixels['pass']}
                    status['cases'].append(item)
                    if not item['pass'] and status['first_failure_observed'] is None:
                        status['first_failure_observed']=label
                    print(json.dumps({'native_frameani':label,'visible_pass':pixels['pass'],'snapshot_pass':state['pass'],
                                      'patch_errors':[row['wrong_pixels'] for row in pixels['patches']]}),flush=True)
                    save()
                    if experiment.variant=='carrier':
                        experiment.frameani(route,True,label+'_data_fixture')
                        item['payload_captures']=[row['label'] for row in experiment.data_checks(label+'_payload')]
                        experiment.frameani(route,False,label+'_after_data_off')
                        save()
            experiment.call(location+'_frameani_destroy','probe.ordinary_frameani.destroy()',
                            expression='probe.ordinary_frameani.snapshot()')
        status['complete']=True
    except Exception as error:
        status['failure']=repr(error)
        raise
    finally:
        try:
            experiment.call('frameani_cleanup',
                "if hasattr(probe,'ordinary_frameani'): probe.ordinary_frameani.destroy()")
            status['cleanup']['effects_destroyed']=True
        except Exception as error:
            status['cleanup']['effect_error']=repr(error)
        if wall is not None:
            try:
                status['cleanup']['wall']=restore_wall(experiment,wall)
            except Exception as error:
                status['cleanup']['wall_error']=repr(error)
        save()
    return status


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--inside-only',action='store_true')
    args=parser.parse_args()
    args.project,args.evidence=args.project.resolve(),args.evidence.resolve()
    experiment=Experiment(args)
    experiment.initialize()
    experiment.raw_capture('initial_scene')
    experiment.data_checks('initial_payload')
    run(experiment,('inside',) if args.inside_only else ('inside','outside'))


if __name__=='__main__':
    main()
