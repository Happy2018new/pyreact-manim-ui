"""Tiny native stencil survival matrix; preserve failed controls and stop gates."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

from PIL import Image

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('stencil_host_experiment',HERE.parent/'weather_effect_order_probe/runner.py')
order=importlib.util.module_from_spec(spec)
spec.loader.exec_module(order)
order.HERE=HERE
order.OWNER='manim-weather-stencil'
ROI=(96,192,128,128)
CYAN=(0,255,255)
MAGENTA=(255,0,255)
YELLOW=(255,255,0)


def bit_at(pattern,x,y):
    return pattern=='ones' or (pattern!='zero' and (((x//8+y//8)%2==0)==(pattern=='a')))


def verify(path,pattern,mode,expected):
    with Image.open(path) as source:
        pixels=source.convert('RGB')
    bad=0
    present=0
    unexpected=0
    colors={}
    examples=[]
    for y in range(ROI[3]):
        for x in range(ROI[2]):
            actual=pixels.getpixel((ROI[0]+x,ROI[1]+y))
            colors[actual]=colors.get(actual,0)+1
            bit=bit_at(pattern,x,y)
            present+=actual==MAGENTA
            if mode=='early':
                mismatch=(actual!=MAGENTA) if bit else (actual==MAGENTA)
            else:
                target=YELLOW if mode=='positive' else (CYAN if mode=='baseline' else (MAGENTA if bit else CYAN))
                mismatch=actual!=target
            unexpected+=(actual==MAGENTA and not bit)
            bad+=mismatch
            if mismatch and len(examples)<8:
                examples.append({'xy':[ROI[0]+x,ROI[1]+y],'rgb':list(actual),'expected_bit':bit})
    return {'source_pixels':ROI[2]*ROI[3],'error_pixels':bad,'exact':bad==0 if expected else None,
        'magenta_pixels':present,'unexpected_magenta_pixels':unexpected,'expected_asserted':expected,
        'colors':[{'rgb':list(color),'pixels':count} for color,count in sorted(colors.items(),key=lambda item:-item[1])[:12]],
        'first_errors':examples}


class Experiment(order.Experiment):
    def call(self,label,code=''):
        self.serial+=1
        name='%03d_%s'%(self.serial,label)
        path=self.commands/(name+'.py')
        path.write_text("probe=api.GetSystem('pmanim_weather_effect_stencil','probe')\n"+code+
            '\n_result=json.dumps(probe.snapshot())\n',encoding='utf-8')
        self.invoke([sys.executable,'-B','-X','utf8',str(HERE/'host.py'),'call','--project',str(self.args.project.resolve()),
            '--evidence',str(self.evidence),'--label',name,'--timeout','120','--code',str(path)],name)
        self.state=json.loads((self.evidence/(name+'.state.json')).read_text(encoding='utf-8'))
        return self.state

    def capture(self,label,pattern,mode,clear=True,writer=True,expected=True):
        self.call(label+'_control','probe.configure(%r,%r,%r,%r)'%(pattern,mode,clear,writer))
        time.sleep(.7)
        self.call(label+'_settled')
        if any(enabled for name,enabled in self.state['native_post_flags']):
            raise RuntimeError('Native post-process unexpectedly enabled')
        self.invoke([sys.executable,'-B','-X','utf8',str(HERE/'host.py'),'capture','--project',str(self.args.project.resolve()),
            '--evidence',str(self.evidence),'--label',label],label+'_capture')
        receipt=json.loads((self.evidence/(label+'.json')).read_text(encoding='utf-8'))
        if (not receipt['ok'] or receipt['backend']!='Windows.Graphics.Capture' or [receipt['width'],receipt['height']]!=[720,1080]
            or receipt['frame_qpc_100ns']<receipt['request_qpc_100ns'] or receipt.get('agent_activation_allowed') is not False):
            raise RuntimeError('Invalid fresh passive stencil capture')
        report={'label':label,'pattern':pattern,'mode':mode,'clear':clear,'writer':writer,
            'raining':self.weather_is_raining,'state':self.state,'capture_receipt':receipt}
        report.update(verify(self.evidence/(label+'.png'),pattern,mode,expected))
        self.reports.append(report)
        (self.evidence/'results.json').write_text(json.dumps({'schema':'weather_effect_stencil_bit_v1','reports':self.reports},indent=2),encoding='utf-8')
        print(json.dumps({key:report[key] for key in ('label','error_pixels','exact','magenta_pixels')}),flush=True)
        return report

    def run(self):
        self.call('initial')
        self.call('prepare','api.HideCrossHairGUI(True)\nprobe.prepare_camera()\nprobe.open()')
        self.weather('prepare_clear',False,True)
        for attempt in range(15):
            if self.call('wait_ready_%02d'%attempt)['ready']:
                break
            time.sleep(.5)
        if not self.state['ready']:
            raise RuntimeError('Geometry actor not ready')
        self.call('build_pages','probe.build_pages()')
        positives=[self.capture('010_source_a','a','source',False,False),
            self.capture('011_source_inverse','inverse','source',False,False),
            self.capture('012_unmasked','zero','baseline',False,False),
            self.capture('013_point_always','zero','positive',False,False),
            self.capture('014_unmasked_writer','a','baseline',True,True)]
        if not all(row['exact'] for row in positives):
            raise RuntimeError('Source/material positive control failed; do not infer stencil survival')
        for pattern in ('zero','a','inverse','ones','zero'):
            self.capture('020_early_%02d_%s'%(len(self.reports),pattern),pattern,'early')
        late=[]
        for pattern in ('zero','a','inverse','ones','zero'):
            late.append(self.capture('030_late_%02d_%s'%(len(self.reports),pattern),pattern,'late'))
        self.capture('031_no_writer_cleared','zero','late',True,False)
        self.capture('032_seed_stale','a','late',True,True)
        self.capture('033_no_clear_no_writer','a','late',False,False,False)
        self.capture('034_clear_again','zero','late',True,False)
        if not all(row['exact'] for row in late):
            raise RuntimeError('Late stencil bridge not established; preserve early and material controls')
        self.weather('rain_on',True)
        for iteration in range(2):
            for pattern in ('a','inverse','zero'):
                self.capture('040_rain_%d_%s'%(iteration,pattern),pattern,'late')
        self.weather('rain_off',False)
        self.capture('050_return_a','a','late')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    experiment=Experiment(args)
    try:
        experiment.run()
    finally:
        # A timeout is not blindly replayed. Cleanup command is recorded once.
        status={'reports':len(experiment.reports),'last_state':experiment.state,'cleanup_attempted':False}
        (args.evidence/'final-host-status.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
        try:
            if experiment.state.get('stencil_pages',{}).get('zero') and len(experiment.state.get('effects',[]))==3:
                status['cleanup_attempted']=True
                experiment.call('cleanup','probe.configure("zero","off",False,False)')
            if experiment.weather_is_raining:
                experiment.weather('cleanup_rain_off',False)
        finally:
            status['last_state']=experiment.state
            (args.evidence/'final-host-status.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
