"""Root-authorized same-instance continuation after failed native RGB fixture."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

from PIL import Image
from packed_runner import Experiment as BaseExperiment,HERE
from packed_verify import verify,GUARD


def raw_pairs(path):
    with Image.open(path) as source:
        pixels=source.convert('RGB')
    return [(pixels.getpixel(((2*i)%720,600+(2*i)//720)),pixels.getpixel(((2*i+1)%720,600+(2*i+1)//720))[0]) for i in range(16384)]


class Experiment(BaseExperiment):
    def capture(self,label,mode,slot=0,baseline=False,hide=False):
        code='probe.configure(%r,False)\nprobe.inspect(%d,%d,True)'%('fixture' if baseline else 'all',mode,slot)
        if hide:
            code+='\nprobe.hide_payload()'
        self.call(label+'_control',code)
        time.sleep(.5)
        self.call(label+'_settled')
        if not self.state['oracle_enabled'] or any(flag for name,flag in self.state['native_post_flags']):
            raise RuntimeError('Followup actual render flags failed')
        self.invoke([sys.executable,'-B','-X','utf8',str(HERE/'packed_host.py'),'capture','--project',str(self.args.project.resolve()),
            '--evidence',str(self.evidence),'--label',label],label+'_capture')
        receipt=json.loads((self.evidence/(label+'.json')).read_text(encoding='utf-8'))
        if (not receipt['ok'] or receipt['backend']!='Windows.Graphics.Capture' or [receipt['width'],receipt['height']]!=[720,1080]
            or receipt['frame_qpc_100ns']<receipt['request_qpc_100ns'] or receipt.get('agent_activation_allowed') is not False):
            raise RuntimeError('Followup passive receipt gate failed')
        path=self.evidence/(label+'.png')
        with Image.open(path) as source:
            image=source.convert('RGB')
        if mode==3:
            guard_bad=sum(image.getpixel((i%720,600+i//720))!=GUARD for i in range(16384,720*256))
            measured={'exact':None,'guard_error_pixels':guard_bad,'error_pixels':None,'restoration_oracle_pending_stable_baseline':True}
        else:
            measured=verify(image,mode,self.state['payload'],slot,fixture=baseline,raining=not baseline)
            if baseline:
                measured['fixture_oracle_invalid_for_followup']=True
                measured['exact']=None
        report={'label':label,'mode':mode,'slot':slot,'natural_scene_baseline':baseline,'hidden_payload':hide,
            'expected_asserted':not baseline and not hide and mode!=3,'raining_actual':self.weather_is_raining,
            'same_instance_followup':True,'state':self.state,'capture_receipt':receipt}
        report.update(measured)
        if hide:
            report['negative_rejected']=not report['exact']
        self.reports.append(report)
        self.save()
        print(json.dumps({key:report[key] for key in ('label','exact','error_pixels','alpha_not255_pixels','negative_rejected') if key in report}),flush=True)
        if report.get('guard_error_pixels') or report.get('alpha_pair_not_gray_pixels'):
            raise RuntimeError('Followup guard/alpha diagnostic failed')
        if report['expected_asserted'] and not report['exact']:
            raise RuntimeError('Followup payload gate failed at '+label)
        if hide and not report['negative_rejected']:
            raise RuntimeError('Followup hidden geometry negative failed')
        return report

    def save(self):
        (self.evidence/'results.json').write_text(json.dumps({'schema':'weather_stencil_packed64_followup_v1','reports':self.reports},indent=2),encoding='utf-8')

    def restoration(self,before,encoded,restored,after):
        a=raw_pairs(self.evidence/(before+'.png'))
        b=raw_pairs(self.evidence/(after+'.png'))
        stable=sum(left!=right for left,right in zip(a,b))
        with Image.open(self.evidence/(restored+'.png')) as source:
            image=source.convert('RGB')
        maximum=[0,0,0]
        bad=0
        for index,(original,alpha) in enumerate(a):
            actual=image.getpixel((index%720,600+index//720))
            differences=[abs(x-y) for x,y in zip(original,actual)]
            maximum=[max(x,y) for x,y in zip(maximum,differences)]
            bad+=any(error>2 for error in differences)
        result={'schema':'packed64_natural_stable_restoration_v1','before':before,'encoded':encoded,'restored':restored,'after':after,
            'baseline_rgba_source_pixels':16384,'baseline_changed_pixels':stable,'maximum_rgb_error':maximum,
            'error_pixels_gt2':bad,'passed':stable==0 and bad==0,'restoration_claim_qualified':stable==0,
            'scope':'Finite sunny natural-scene before/after identity only; no changing-rain RGB oracle.'}
        (self.evidence/'restoration.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)

    def run(self):
        self.call('same_instance_initial')
        # Retain failed varied-height opaque fixture; hide it and add the
        # allzero clear geometry shape already established by r3.
        code='probe.render.SetActorBlockGeometryVisible(probe.clear_page,False)\nprobe.clear_page=probe.page([0]*256,"clear")\n'
        code+='probe.oracle_installed=False\nprobe.install_oracle()'
        self.call('allzero_clear_and_oracle',code)
        time.sleep(.5)
        for value,label in ((0,'zero'),(85,'bit64'),(170,'bit128'),(255,'both')):
            self.call('route_'+label,'probe.write(%r)'%([value]*64,))
            self.capture('010_route_'+label,1)
        payloads=[[0,1,2,3,15,16,63,64,65,127,128,129,191,192,254,255]*4,
            list(hashlib.sha512(b'host-selected-stencil64-arbitrary-A').digest()),
            list(hashlib.sha512(b'independent-host-selected-payload-B').digest())]
        self.call('stable_payload','probe.write(%r)'%(payloads[0],))
        self.capture('020_natural_before',0,baseline=True)
        self.capture('021_natural_encoded',0)
        self.capture('022_natural_restored',3)
        self.capture('023_natural_after',0,baseline=True)
        self.restoration('020_natural_before','021_natural_encoded','022_natural_restored','023_natural_after')
        for index,payload in enumerate(payloads):
            self.call('arbitrary_%d'%index,'probe.write(%r)'%(payload,))
            for slot in (0,1):
                for mode in (1,2):
                    self.capture('030_clear_%d_t%d_m%d'%(index,slot,mode),mode,slot)
        self.capture('031_hidden_negative',1,hide=True)
        self.capture('032_return_positive',1)
        self.weather('rain_on',True)
        wet=[]
        for index,payload in enumerate(payloads[1:]):
            self.call('wet_%d'%index,'probe.write(%r)'%(payload,))
            for slot in (0,1):
                wet.append(self.capture('040_wet_%d_t%d_pair'%(index,slot),0,slot))
                for mode in (1,2):
                    self.capture('041_wet_%d_t%d_m%d'%(index,slot,mode),mode,slot)
        if not any(row['alpha_not255_pixels'] for row in wet):
            raise RuntimeError('No same-source rain-alpha witness')
        self.weather('rain_off',False)
        self.capture('050_clear_return',1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--parent-evidence',type=Path,required=True)
    args=parser.parse_args()
    args.evidence.mkdir(exist_ok=False)
    shutil.copyfile(args.parent_evidence/'launch.json',args.evidence/'launch.json')
    experiment=Experiment(args)
    try:
        experiment.run()
    finally:
        status={'reports':len(experiment.reports),'last_state':experiment.state}
        (args.evidence/'final-host-status.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
        try:
            experiment.call('cleanup','probe.configure("off",False)\nprobe.inspect(0,0,False)')
            if experiment.weather_is_raining:
                experiment.weather('cleanup_rain_off',False)
        finally:
            status['last_state']=experiment.state
            (args.evidence/'final-host-status.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
