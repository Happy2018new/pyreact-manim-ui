"""Disable test fixtures and stop only the verified owned native compatibility instance."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from runner import Experiment,HERE,OWNER


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--previous-evidence',type=Path,required=True)
    args=parser.parse_args()
    args.project,args.evidence,args.previous_evidence=(p.resolve() for p in (args.project,args.evidence,args.previous_evidence))
    args.evidence.mkdir(exist_ok=False)
    shutil.copyfile(args.previous_evidence/'launch.json',args.evidence/'launch.json')
    exp=Experiment(args)
    session=json.loads(Path(exp.session).read_text(encoding='utf-8-sig'))
    result={'owner':OWNER,'session':session['id'],'game_pid':session['game_pid'],'mcdk_pid':session['mcdk_pid'],
            'failure':None,'normal_stop':None,'force_stop':None}

    def processes():
        code="@{games=@(Get-CimInstance Win32_Process -Filter \"Name='Minecraft.Windows.exe'\" | Select-Object ProcessId,ThreadCount,HandleCount); owned=@(Get-CimInstance Win32_Process | Where-Object ProcessId -in @(%d,%d) | Select-Object ProcessId,Name,ThreadCount,HandleCount)} | ConvertTo-Json -Depth 5 -Compress"%(session['game_pid'],session['mcdk_pid'])
        run=subprocess.run(['powershell.exe','-NoProfile','-Command',code],capture_output=True,text=True,check=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return json.loads(run.stdout)
    try:
        result['before']=processes()
        try:
            exp.weather('final_clear',False)
            result['last_state']=exp.call('disable_owned_fixtures',
            "if hasattr(probe,'ordinary_frameani'): probe.ordinary_frameani.destroy()\n"
            "if hasattr(probe,'enchanted_fixture'): probe.enchanted_fixture.destroy()\n"
            "probe.configure_known_fixture(False)\n"
            "if probe.outline is not None and probe.outline.entity is not None: probe.configure_outline(False)\n"
            "probe.configure('off')\n"
            "if probe.pipeline_ready: probe.inspect(0,enabled=False,restore_enabled=False)\n"
            "for name in list(probe.post.GetPostProcessOrder() or []):\n"
            "    if name.startswith('stencil_integrated_'): probe.post.SetEnableByName(name,False)")
        except Exception as error:
            # Native transitions may invalidate the client-only fixture. The
            # owner/session/process identity still authorizes bounded shutdown.
            result['disable_error']=repr(error)
        exp.save()
        command=[sys.executable,'-B','-X','utf8',str(HERE/'host.py'),'stop','--project',str(args.project),'--evidence',str(args.evidence)]
        for label,suffix in (('normal_stop',[]),('force_stop',['--force'])):
            run=subprocess.run(command+suffix,capture_output=True,text=True,timeout=50,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            (args.evidence/(label+'.log')).write_text(run.stdout+run.stderr,encoding='utf-8')
            result[label]={'returncode':run.returncode,'log':label+'.log'}
            if run.returncode==0: break
        else:
            raise RuntimeError('Owner-bound force cleanup failed')
        result['after']=processes()
        result['active_game_count']=sum(bool(r['ThreadCount'] or r['HandleCount']) for r in result['after']['games'])
        result['owned_pids_absent']=not result['after']['owned']
        result['session_state']=json.loads(Path(exp.session).read_text(encoding='utf-8-sig'))['state']
        if result['active_game_count'] or not result['owned_pids_absent']:
            raise RuntimeError('Owned native cleanup not absent')
    except Exception as error:
        result['failure']=repr(error)
        raise
    finally:
        (args.evidence/'cleanup.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)


if __name__=='__main__':
    main()
