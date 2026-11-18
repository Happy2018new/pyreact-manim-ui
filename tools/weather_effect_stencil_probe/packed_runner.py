"""One finite64B native test, explicit gates and same-fetch rain-alpha witness."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

from PIL import Image
from packed_verify import verify

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('packed_base_experiment',HERE.parent/'weather_effect_order_probe/runner.py')
order=importlib.util.module_from_spec(spec)
spec.loader.exec_module(order)
order.HERE=HERE
order.OWNER='manim-stencil-packed64'


class Experiment(order.Experiment):
    def call(self,label,code=''):
        self.serial+=1
        name='%03d_%s'%(self.serial,label)
        path=self.commands/(name+'.py')
        path.write_text("probe=api.GetSystem('pmanim_stencil_packed','probe')\n"+code+'\n_result=json.dumps(probe.snapshot())\n',encoding='utf-8')
        self.invoke([sys.executable,'-B','-X','utf8',str(HERE/'packed_host.py'),'call','--project',str(self.args.project.resolve()),
            '--evidence',str(self.evidence),'--label',name,'--timeout','120','--code',str(path)],name)
        self.state=json.loads((self.evidence/(name+'.state.json')).read_text(encoding='utf-8'))
        return self.state

    def capture(self,label,mode,slot=0,fixture=False,hide=False,expected=True):
        code='probe.configure(%r,%r)\nprobe.inspect(%d,%d,True)'%('fixture' if fixture else 'all',fixture or not self.weather_is_raining,mode,slot)
        if hide:
            code+='\nprobe.hide_payload()'
        self.call(label+'_control',code)
        time.sleep(.6)
        self.call(label+'_settled')
        if any(enabled for name,enabled in self.state['native_post_flags']) or not self.state['oracle_enabled']:
            raise RuntimeError('Packed render state gate rejected')
        self.invoke([sys.executable,'-B','-X','utf8',str(HERE/'packed_host.py'),'capture','--project',str(self.args.project.resolve()),
            '--evidence',str(self.evidence),'--label',label],label+'_capture')
        receipt=json.loads((self.evidence/(label+'.json')).read_text(encoding='utf-8'))
        if (not receipt['ok'] or receipt['backend']!='Windows.Graphics.Capture' or [receipt['width'],receipt['height']]!=[720,1080]
            or receipt['frame_qpc_100ns']<receipt['request_qpc_100ns'] or receipt.get('agent_activation_allowed') is not False):
            raise RuntimeError('Packed passive frame gate rejected')
        with Image.open(self.evidence/(label+'.png')) as source:
            measured=verify(source.convert('RGB'),mode,self.state['payload'],slot,fixture=fixture,raining=self.weather_is_raining)
        report={'label':label,'mode':mode,'slot':slot,'fixture':fixture,'hidden_payload':hide,'expected_asserted':expected,
            'raining':self.weather_is_raining,'state':self.state,'capture_receipt':receipt}
        report.update(measured)
        if hide:
            report['negative_rejected']=not report['exact']
        self.reports.append(report)
        (self.evidence/'results.json').write_text(json.dumps({'schema':'weather_stencil_packed64_v1','reports':self.reports},indent=2),encoding='utf-8')
        print(json.dumps({key:report[key] for key in ('label','exact','negative_rejected','error_pixels','alpha_not255_pixels','max_color_error') if key in report}),flush=True)
        if expected and not report['exact']:
            raise RuntimeError('Packed pixel gate failed at '+label)
        if hide and not report['negative_rejected']:
            raise RuntimeError('Hidden-geometry negative failed to reject')
        return report

    def run(self):
        self.call('initial')
        self.call('prepare','api.HideCrossHairGUI(True)\nprobe.prepare()')
        self.weather('prepare_clear',False,True)
        for attempt in range(15):
            if self.call('ready_%02d'%attempt)['ready']:
                break
            time.sleep(.5)
        if not self.state['ready']:
            raise RuntimeError('Packed actor readiness failed')
        self.call('create','probe.create()')
        self.call('install_oracle','probe.install_oracle()')
        time.sleep(.5)
        self.capture('010_native_background',0,fixture=True)
        for value,label in ((0,'zero'),(85,'bit64'),(170,'bit128'),(255,'both')):
            self.call('write_control_'+label,'probe.write(%r)'%([value]*64,))
            self.capture('020_route_'+label,1)
        boundaries=[0,1,2,3,15,16,63,64,65,127,128,129,191,192,254,255]*4
        digest=list(hashlib.sha512(b'host-selected-stencil64-arbitrary-A').digest())
        other=list(hashlib.sha512(b'independent-host-selected-payload-B').digest())
        payloads=[boundaries,digest,other]
        for index,payload in enumerate(payloads):
            self.call('arbitrary_%d'%index,'probe.write(%r)'%(payload,))
            self.capture('030_clear_%d_pairs'%index,0)
            self.capture('031_clear_%d_restore'%index,3)
            for slot in (0,1):
                for mode in (1,2):
                    self.capture('032_clear_%d_t%d_m%d'%(index,slot,mode),mode,slot)
        self.capture('033_hidden_negative',1,hide=True,expected=False)
        self.capture('034_return_positive',1)
        self.weather('rain_on',True)
        wet=[]
        for index,payload in enumerate(payloads[1:]):
            self.call('wet_arbitrary_%d'%index,'probe.write(%r)'%(payload,))
            for slot in (0,1):
                wet.append(self.capture('040_wet_%d_t%d_pairs'%(index,slot),0,slot))
                for mode in (1,2):
                    self.capture('041_wet_%d_t%d_m%d'%(index,slot,mode),mode,slot)
        if not any(row.get('alpha_not255_pixels',0)>0 for row in wet):
            raise RuntimeError('No same-fetch native rain-alpha witness in the source ROI')
        self.weather('rain_off',False)
        self.capture('050_clear_return_pairs',0)
        self.capture('051_clear_return_restore',3)
        self.capture('052_clear_return_query',1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    experiment=Experiment(args)
    try:
        experiment.run()
    finally:
        status={'reports':len(experiment.reports),'last_state':experiment.state,'cleanup_attempted':False}
        (args.evidence/'final-host-status.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
        try:
            if len(experiment.state.get('effects',[]))==3:
                status['cleanup_attempted']=True
                experiment.call('cleanup','probe.configure("off",False)\nprobe.inspect(0,0,False)')
            if experiment.weather_is_raining:
                experiment.weather('cleanup_rain_off',False)
        finally:
            status['last_state']=experiment.state
            (args.evidence/'final-host-status.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
