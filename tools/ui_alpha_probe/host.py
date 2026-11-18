"""Finite alpha probe uses the established owner-bound passive native host."""
import importlib.util
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

SOURCE=Path(__file__).resolve().parents[1]/'runtime_packet_probe/host.py'
spec=importlib.util.spec_from_file_location('ui_alpha_owned_host',SOURCE)
owned_host=importlib.util.module_from_spec(spec)
spec.loader.exec_module(owned_host)
owned_host.OWNER='manim-ui-alpha'


def launch():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('launch',))
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    project,evidence=args.project.resolve(),args.evidence.resolve()
    evidence.mkdir(parents=True,exist_ok=True)
    if (evidence/'launch.private.json').exists() or (evidence/'launch.json').exists():
        raise ValueError('Preserve prior launch receipts; choose a fresh evidence directory')
    if not (project/'probe_resources.json').is_file():
        raise ValueError('Expected generated research project')
    sys.path.insert(0,str(owned_host.SCRIPTS))
    starter=owned_host.load_file('alpha_start_dev',owned_host.ROOT/'tools/start_dev.py')
    background=starter.background_arguments(owned_host.ROOT/'background-tools.local.json')
    settings=starter.ensure_fps_60(starter.native_options_path(),evidence/'options-backups')
    command=[sys.executable,'-B','-X','utf8',str(owned_host.SCRIPTS/'instances.py'),
        'start','--project',str(project),'--owner',owned_host.OWNER,'--preset','ui','--wait','120']+background
    environment=dict(os.environ)
    environment['MCDEV_ALLOW_USER_FOREGROUND']='1'
    with (evidence/'launch.private.json').open('wb') as output,(evidence/'launch.stderr.log').open('wb') as error:
        result=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=output,stderr=error,env=environment,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    receipt=json.loads((evidence/'launch.private.json').read_text(encoding='utf-8-sig'))
    summary={'state':receipt.get('state'),'session_file':receipt.get('session_file'),'fps':settings['fps'],
        'background_only':False,'user_foreground_allowed':True,'agent_activation_allowed':False}
    (evidence/'launch.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    (evidence/'fps-options-receipt.json').write_text(json.dumps(settings,indent=2),encoding='utf-8')
    print(json.dumps(summary))
    return result.returncode


if __name__=='__main__':
    os.environ['MCDEV_ALLOW_USER_FOREGROUND']='1'
    if len(sys.argv)>1 and sys.argv[1]=='launch':
        raise SystemExit(launch())
    raise SystemExit(owned_host.main())
