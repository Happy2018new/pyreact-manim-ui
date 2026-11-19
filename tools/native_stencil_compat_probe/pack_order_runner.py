"""Observe both real material-conflict orders without asserting a preferred winner."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from PIL import Image
from runner import Experiment,HERE,OWNER,module
from frameani_runner import run as run_frameani

packs=module('native_conflict_pack_build_api',HERE.parent/'native_stencil_pack_order_fixture/build_fixture.py')
canary_verify=module('native_conflict_pack_canary_oracle',HERE.parent/'native_stencil_pack_order_fixture/verify.py')


class DiagnosticExperiment(Experiment):
    def data_checks(self,prefix):
        # A stock material winner is expected to break the carrier. Decode and
        # preserve the complete output even when that outcome is negative.
        return [self.capture(prefix+'_m%d'%mode,mode,output_y=650,expected=False) for mode in (1,3)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--plan',type=Path,required=True)
    args=parser.parse_args()
    args.project,args.evidence,args.plan=(p.resolve() for p in (args.project,args.evidence,args.plan))
    plan=json.loads(args.plan.read_text(encoding='utf-8'))
    exp=DiagnosticExperiment(args)
    session_bytes=Path(exp.session).read_bytes()
    session_snapshot=args.evidence/'assigned-session-snapshot.json'
    session_snapshot.write_bytes(session_bytes)
    status={'failure':None,'plan_file':str(args.plan),'canary':[],'actual_order':None,
        'assigned_session_snapshot':str(session_snapshot),
        'assigned_session_sha256':hashlib.sha256(session_bytes).hexdigest(),
        'host_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'frameani_runner_sha256':hashlib.sha256((HERE/'frameani_runner.py').read_bytes()).hexdigest(),
        'canary_verifier_sha256':hashlib.sha256((HERE.parent/'native_stencil_pack_order_fixture/verify.py').read_bytes()).hexdigest()}
    try:
        status['actual_order']=packs.deployed_order(exp.session,args.project,plan['fixture'],OWNER)
        exp.initialize()
        exp.call('pack_canary_open',
            "accepted=api.RegisterUI('pmanim_pack_order_canary','canary','pmanim_pack_order_fixture.runtime.PackOrderCanary','pmanim_pack_order_canary.main')\n"
            "if not accepted: raise RuntimeError('Unique pack canary RegisterUI failed')\n"
            "probe.pack_order_canary=api.CreateUI('pmanim_pack_order_canary','canary',{'isHud':1})\n"
            "if probe.pack_order_canary is None: raise RuntimeError('Unique pack canary CreateUI failed')")
        time.sleep(.7)
        exp.call('pack_canary_visible',"probe.pack_order_canary.configure(True,(720,1080),(632,160))")
        for configuration in ('off','all'):
            report=exp.raw_capture('pack_canary_'+configuration,configuration)
            with Image.open(report['capture_file']) as image:
                result=canary_verify.verify(image.convert('RGB'),(632,160))
            status['canary'].append({'configuration':configuration,'result':result,'capture_file':report['capture_file']})
            (args.evidence/'pack-order-status.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
        status['frameani']=run_frameani(exp,('inside',))
        reports=[row for row in exp.reports if row['mode'] in (1,3)]
        status['payload_checks']=[{'label':row['label'],'mode':row['mode'],'exact':row['exact'],
                                  'error_pixels':row['error_pixels']} for row in reports]
    except Exception as error:
        status['failure']=repr(error)
        raise
    finally:
        try:
            exp.call('pack_canary_remove',"if getattr(probe,'pack_order_canary',None) is not None: probe.pack_order_canary.SetRemove()")
            status['canary_removed']=True
        except Exception as error:
            status['canary_cleanup_error']=repr(error)
        exp.save()
        status['last_state']=exp.state
        (args.evidence/'pack-order-status.json').write_text(json.dumps(status,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
