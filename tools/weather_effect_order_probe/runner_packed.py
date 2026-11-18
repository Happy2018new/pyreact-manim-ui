"""Finite arbitrary32B upload/readback through four public mix-color controls."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

from PIL import Image
from runner import Experiment as BaseExperiment, HERE, verify_pair


def symbol(value):
    return (value,(value*71+43)%256,(value*131+17)%256)


PAYLOADS=[
    [0,255,1,254,2,253,127,128,129,0,0,0,255,255,255,255,0,255,0,255,0,1,0,1,0,1,0,254,255,254,255,254],
    list(hashlib.sha256(b'host-selected real bytes, no GPU seed, weather probe R2 A').digest()),
    [255,255,255,128,0,0,127,255,255,0,0,1,0,1,0,1,0,0,85,170,255,255,170,85,254,1,128,129,254,127,0,255],
]


class Experiment(BaseExperiment):
    def __init__(self,args):
        BaseExperiment.__init__(self,args)
        self.payload=None
        self.payload_name=None

    def select(self,name,values):
        self.call('write_'+name,'probe.write(%r)\nprobe.configure(True,15)'%values)
        if self.state['payload']!=values:
            raise RuntimeError('Game Python actual byte payload differs from host input')
        self.payload=list(values)
        self.payload_name=name

    def capture(self,label,slot=0,mode=0,post=True):
        if post:
            self.call(label+'_controls','probe.inspect(True,%d,True,%d)'%(slot,mode))
        time.sleep(.5)
        self.call(label+'_settled')
        self.invoke([sys.executable,'-B','-X','utf8',str(HERE/'host.py'),'capture',
            '--project',str(self.args.project.resolve()),'--evidence',str(self.evidence),'--label',label],label+'_capture')
        receipt=json.loads((self.evidence/(label+'.json')).read_text(encoding='utf-8'))
        if (not receipt['ok'] or receipt['backend']!='Windows.Graphics.Capture' or
                [receipt['width'],receipt['height']]!=[720,1080] or
                receipt['frame_qpc_100ns']<receipt['request_qpc_100ns'] or
                receipt.get('agent_activation_allowed') is not False):
            raise RuntimeError('Invalid fresh passive native capture')
        with Image.open(self.evidence/(label+'.png')) as source:
            image=source.convert('RGB')
        report={'label':label,'payload_name':self.payload_name,'payload':self.payload,
            'payload_sha256':hashlib.sha256(bytes(self.payload)).hexdigest(),
            'mode':mode if post else 'direct','slot':slot if post else None,'state':self.state,
            'weather_raining':self.weather_is_raining,'capture':str(self.evidence/(label+'.png'))}
        if post and mode==0:
            report.update(verify_pair(image,payload=self.payload))
            report['exact']=report['exact_all_source_rgb']
        else:
            observed=[list(image.getpixel((int((i+.5)*720/32),750))[:3]) for i in range(32)] if post else [list(image.getpixel((72+18*i+9,270))) for i in range(32)]
            expected=[]
            for i in range(32):
                index=i
                if post and mode==2:
                    index=(131*i+29)%32
                    index=(index+3*self.payload[index]+7)%32
                expected.append(list(symbol(self.payload[index])))
            report.update({'observed':observed,'expected':expected,'exact':observed==expected})
        self.reports.append(report)
        (self.evidence/'results.json').write_text(json.dumps({'schema':'weather_effect_packed32_v1','reports':self.reports},indent=2),encoding='utf-8')
        print(json.dumps({key:report[key] for key in ('label','exact','rgb_error_pixels','alpha_not255_pixels','intact_rgb_and_alpha_not255_pixels') if key in report}),flush=True)
        if not report['exact']:
            raise RuntimeError('Arbitrary32B rendered readback failed; stop at precision gate')
        return report

    def run(self):
        self.call('initial')
        self.call('camera','api.HideCrossHairGUI(True)\nprobe.prepare_camera()')
        self.weather('prepare_clear',False,True)
        self.call('create','probe.create()')
        for index,payload in enumerate(PAYLOADS):
            self.select('clear_direct_%d'%index,payload)
            self.capture('010_direct_%d'%index,post=False)
        self.call('install_post','probe.install_post()')
        for index,payload in enumerate(PAYLOADS):
            self.select('clear_post_%d'%index,payload)
            self.capture('020_clear_%d_t0_pairs'%index)
            self.capture('021_clear_%d_t0_identity'%index,mode=1)
            self.capture('022_clear_%d_t0_dependent'%index,mode=2)
        self.capture('023_clear_t1_pairs',slot=1)
        self.weather('rain_on',True)
        for index in (0,1):
            self.select('wet_%d'%index,PAYLOADS[index])
            for slot in (0,1):
                self.capture('030_wet_%d_t%d_pairs'%(index,slot),slot=slot)
                self.capture('031_wet_%d_t%d_identity'%(index,slot),slot=slot,mode=1)
                self.capture('032_wet_%d_t%d_dependent'%(index,slot),slot=slot,mode=2)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    experiment=Experiment(args)
    completed=False
    try:
        experiment.run()
        completed=True
    finally:
        if experiment.weather_is_raining:
            experiment.weather('cleanup_rain_off',False)
        if experiment.state.get('effect_count'):
            experiment.call('cleanup_remove','probe.remove()')
        if experiment.state.get('installed'):
            experiment.call('cleanup_post_off',"probe.post.SetEnableByName('weather_effect_oracle',False)")
        (args.evidence/'final-host-status.json').write_text(json.dumps({'completed':completed,
            'reports':len(experiment.reports),'all_exact':all(row['exact'] for row in experiment.reports),
            'last_state':experiment.state,'rain_reversion_required':experiment.weather_is_raining},indent=2),encoding='utf-8')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
