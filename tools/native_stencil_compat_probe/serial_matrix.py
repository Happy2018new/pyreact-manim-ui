"""Run explicitly selected fresh native cases sequentially, always owned cleanup."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def run_command(command,log,timeout):
    with log.open('x',encoding='utf-8') as stream:
        completed=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
            timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return {'returncode':completed.returncode,'log':str(log)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,required=True)
    parser.add_argument('--cases',nargs='+',choices=('order-first','order-last','bloom','dof'),required=True)
    args=parser.parse_args()
    base=args.base.resolve()
    receipt_path=base/('serial-matrix-'+str(time.time_ns())+'.json')
    results=[]
    py=[sys.executable,'-B','-X','utf8']
    for name in args.cases:
        case=base/name
        project=case/'project'
        launch=case/'launch-evidence'
        evidence=case/'run-evidence'
        cleanup=case/'cleanup-evidence'
        row={'case':name,'failure':None,'launch':None,'run':None,'cleanup':None}
        results.append(row)
        def save(): receipt_path.write_text(json.dumps(results,indent=2),encoding='utf-8')
        save()
        try:
            print(json.dumps({'case':name,'action':'launch'}),flush=True)
            row['launch']=run_command(py+[str(HERE/'host.py'),'launch','--project',str(project),'--evidence',str(launch)],case/'matrix-launch.log',240)
            save()
            if row['launch']['returncode']:
                raise RuntimeError('Owned case launch failed')
            print(json.dumps({'case':name,'action':'native_run'}),flush=True)
            if name.startswith('order-'):
                evidence.mkdir(exist_ok=False)
                import shutil
                shutil.copyfile(launch/'launch.json',evidence/'launch.json')
                command=py+[str(HERE/'pack_order_runner.py'),'--project',str(project),
                    '--evidence',str(evidence),'--plan',str(case/'pack-order-plan.json')]
            else:
                command=py+[str(HERE.parent/'native_stencil_post_fixture/native_effects.py'),
                    '--project',str(project),'--evidence',str(evidence),'--previous-evidence',str(launch),
                    '--effect','bloom' if name=='bloom' else 'depthoffield','--initialize']
            row['run']=run_command(command,case/'matrix-run.log',900)
            save()
            if row['run']['returncode']:
                row['failure']='Native case returned failure; see preserved run log'
        except Exception as error:
            row['failure']=repr(error)
        finally:
            if (launch/'launch.json').is_file():
                print(json.dumps({'case':name,'action':'owned_cleanup'}),flush=True)
                try:
                    row['cleanup']=run_command(py+[str(HERE/'cleanup.py'),'--project',str(project),
                        '--evidence',str(cleanup),'--previous-evidence',str(launch)],case/'matrix-cleanup.log',150)
                    if row['cleanup']['returncode']:
                        raise RuntimeError('Cleanup returned failure; stop serial work')
                    check=json.loads((cleanup/'cleanup.json').read_text(encoding='utf-8'))
                    if check.get('active_game_count')!=0 or check.get('owned_pids_absent') is not True:
                        raise RuntimeError('Cleanup did not verify zero active/owned process absence')
                except Exception as error:
                    row['cleanup_failure']=repr(error)
                    save()
                    raise
            save()
        print(json.dumps({'case':name,'complete':True,'failure':row['failure']}),flush=True)
    print(json.dumps({'matrix_receipt':str(receipt_path),'cases':len(results)}),flush=True)


if __name__=='__main__':
    main()
