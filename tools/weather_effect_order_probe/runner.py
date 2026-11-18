"""Finite clear/rain effect-order POC; never activate or input to the game."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SCRIPTS=ROOT/'.agents/skills/pyreact-debugging/scripts'
OWNER='manim-weather-effect-order'
SOURCE=(72,162,576,216)


def marker(seed,index):
    value=(seed+43*index)%251
    value=(value*value+17*value+73*index)%256
    return (value,(value*71+43)%256,(value*131+17)%256)


def verify_pair(image,seed=None,payload=None):
    pixels=image.load()
    rgb_bad=0
    alpha_changed=0
    joint_intact=0
    joint_corrupt=0
    alpha_gray_bad=0
    alpha_codes=Counter()
    first_bad=[]
    first_joint=[]
    count=SOURCE[2]*SOURCE[3]
    for index in range(count):
        ordinal=index*2
        x,y=ordinal%720,600+ordinal//720
        color=tuple(pixels[x,y][:3])
        alpha=tuple(pixels[x+1,y][:3])
        cell=(index%SOURCE[2])*32//SOURCE[2]
        value=payload[cell] if payload is not None else marker(seed,cell)[0]
        expected=(value,(value*71+43)%256,(value*131+17)%256)
        exact=color==expected
        changed=alpha[0]!=255
        alpha_codes[alpha[0]]+=1
        alpha_gray_bad+=len(set(alpha))!=1
        rgb_bad+=not exact
        alpha_changed+=changed
        joint_intact+=changed and exact
        joint_corrupt+=changed and not exact
        if not exact and len(first_bad)<10:
            first_bad.append({'source_pixel':[SOURCE[0]+index%SOURCE[2],SOURCE[1]+index//SOURCE[2]],
                'rgb':color,'expected':expected,'alpha':alpha[0]})
        if changed and exact and len(first_joint)<10:
            first_joint.append({'source_pixel':[SOURCE[0]+index%SOURCE[2],SOURCE[1]+index//SOURCE[2]],
                'rgb':color,'alpha':alpha[0]})
    centers=[]
    for cell in range(32):
        index=(SOURCE[3]//2)*SOURCE[2]+cell*18+9
        ordinal=index*2
        centers.append(list(pixels[ordinal%720,600+ordinal//720][:3]))
    return {'source_pixels':count,'rgb_error_pixels':rgb_bad,'exact_all_source_rgb':rgb_bad==0,
        'alpha_not255_pixels':alpha_changed,'intact_rgb_and_alpha_not255_pixels':joint_intact,
        'corrupt_rgb_and_alpha_not255_pixels':joint_corrupt,'alpha_pair_not_gray':alpha_gray_bad,
        'alpha_histogram':dict(alpha_codes),'center_rgb':centers,
        'center_32_exact':all(tuple(color)==((payload[index],(payload[index]*71+43)%256,(payload[index]*131+17)%256)
            if payload is not None else marker(seed,index)) for index,color in enumerate(centers)),
        'first_rgb_errors':first_bad,'first_intact_alpha_changed':first_joint,
        'same_texture_same_frame_rgb_alpha_pairs':True}


class Experiment:
    def __init__(self,args):
        self.args=args
        self.evidence=args.evidence.resolve()
        self.commands=self.evidence/'commands'
        self.commands.mkdir(exist_ok=False)
        self.session=json.loads((self.evidence/'launch.json').read_text(encoding='utf-8'))['session_file']
        self.serial=0
        self.state={}
        self.reports=[]
        self.flip=True
        self.weather_is_raining=False

    def invoke(self,command,label):
        with (self.evidence/(label+'.log')).open('x',encoding='utf-8') as stream:
            result=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                timeout=140,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:
            raise RuntimeError('Owned operation failed; inspect '+label+'.log before replay')

    def call(self,label,code=''):
        self.serial+=1
        name='%03d_%s'%(self.serial,label)
        path=self.commands/(name+'.py')
        path.write_text("probe=api.GetSystem('pmanim_weather_effect_order','probe')\n"+code+
            '\n_result=json.dumps(probe.snapshot())\n',encoding='utf-8')
        self.invoke([sys.executable,'-B','-X','utf8',str(HERE/'host.py'),'call',
            '--project',str(self.args.project.resolve()),'--evidence',str(self.evidence),
            '--label',name,'--timeout','120','--code',str(path)],name)
        self.state=json.loads((self.evidence/(name+'.state.json')).read_text(encoding='utf-8'))
        return self.state

    def server(self,label,code):
        path=self.commands/(label+'.server.py')
        path.write_text('import json\nimport mod.server.extraServerApi as api\n'+code,encoding='utf-8')
        self.invoke([sys.executable,'-B','-X','utf8',str(SCRIPTS/'instances.py'),'exec',
            '--session',self.session,'--owner',OWNER,'--','mcdk.py','exec',str(path),'--server'],label)
        result=json.loads((self.evidence/(label+'.log')).read_text(encoding='utf-8-sig'))
        if isinstance(result,str):
            result=json.loads(result)
        (self.evidence/(label+'.server.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        return result

    def weather(self,label,raining,initialize=False):
        code="weather=api.GetEngineCompFactory().CreateWeather(api.GetLevelId())\nbefore=weather.GetDimensionLocalWeatherInfo(0)\n"
        if initialize:
            code+="accepted=[weather.SetDimensionUseLocalWeather(0,True),weather.SetDimensionLocalDoWeatherCycle(0,False),weather.SetDimensionLocalThunder(0,0.,12000000)]\n"
        else:
            code='accepted=[]\n'+code
        code+="accepted.append(weather.SetDimensionLocalRain(0,%r,12000000))\n_result=json.dumps({'accepted':accepted,'before':before,'after':weather.GetDimensionLocalWeatherInfo(0),'local':weather.GetDimensionUseLocalWeather(0),'requested_rain':%r})"%(1. if raining else 0.,bool(raining))
        receipt=self.server(label,code)
        if not all(receipt['accepted']) or not receipt['local']:
            raise RuntimeError('Owned local weather configuration rejected')
        self.weather_is_raining=bool(raining)
        time.sleep(3.)

    def capture(self,label,visible,seed,layer,slot=0,paired=True):
        code='probe.configure(%r,%d,%d)'%(visible,seed,layer)
        if self.state.get('installed'):
            code+='\nprobe.inspect(%r,%d,%r,0)'%(paired,slot,self.flip)
        self.call(label+'_controls',code)
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
        report={'label':label,'visible':visible,'seed':seed,'layer_requested':layer,'post_slot':slot,
            'state':self.state,'capture':str(self.evidence/(label+'.png')),'paired':paired,
            'native720x1080':True,'noactivation':receipt.get('background_before',{}).get('window_noactivate')}
        if paired:
            report.update(verify_pair(image,seed))
        else:
            report['direct_center_rgb']=[list(image.getpixel((72+18*index+9,270))) for index in range(32)]
            report['direct_center_32_exact']=all(tuple(value)==marker(seed,index)
                for index,value in enumerate(report['direct_center_rgb']))
        self.reports.append(report)
        (self.evidence/'results.json').write_text(json.dumps({'schema':'weather_effect_order_v1',
            'reports':self.reports},indent=2),encoding='utf-8')
        print(json.dumps({k:report[k] for k in ('label','direct_center_32_exact','center_32_exact',
            'rgb_error_pixels','alpha_not255_pixels','intact_rgb_and_alpha_not255_pixels') if k in report}),flush=True)
        return report

    def run(self):
        self.call('initial')
        self.call('camera',"api.HideCrossHairGUI(True)\nprobe.prepare_camera()")
        self.weather('prepare_clear',False,True)
        self.call('create_effect','probe.create()')
        self.capture('010_direct_hidden',False,42,1,paired=False)
        direct=self.capture('011_direct_layer1_42',True,42,1,paired=False)
        self.capture('012_direct_layer1_201',True,201,1,paired=False)
        self.capture('013_direct_layer15_201',True,201,15,paired=False)
        if not direct['direct_center_32_exact']:
            raise RuntimeError('Custom frame marker clear visible gate failed; no order inference')
        self.call('install_post','probe.install_post()')
        time.sleep(.5)
        self.capture('020_clear_hidden',False,42,1)
        first=self.capture('021_clear_l1_s42_t0',True,42,1)
        if not first['center_32_exact']:
            self.flip=False
            first=self.capture('022_clear_l1_s42_t0_flip',True,42,1)
        if not first['center_32_exact']:
            raise RuntimeError('Clear T0 byte gate failed under both source orientations')
        clear=[first]
        for layer in (1,15):
            for seed in (42,201):
                for slot in (0,1):
                    if (layer,seed,slot)==(1,42,0):
                        continue
                    clear.append(self.capture('023_clear_l%d_s%d_t%d'%(layer,seed,slot),True,seed,layer,slot))
        if not all(row['center_32_exact'] for row in clear):
            raise RuntimeError('Clear layer1/15 T0/T1 exact32B gate failed; no rain expansion')
        self.weather('rain_enabled',True)
        for iteration in range(3):
            self.capture('030_rain_%d_hidden'%iteration,False,201,1)
            self.capture('031_rain_%d_layer1'%iteration,True,201,1)
            self.capture('032_rain_%d_layer15'%iteration,True,201,15)
        self.weather('rain_disabled',False)
        self.capture('040_clear_return_l1',True,201,1)
        self.capture('041_clear_return_l15',True,201,15)
        self.call('remove','probe.remove()')
        self.call('post_off','probe.inspect(False)')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    experiment=Experiment(args)
    try:
        experiment.run()
    finally:
        # Preserve any failure and the owned scene state; host cleanup remains
        # explicit so a network timeout is never blindly replayed as a mutation.
        (args.evidence/'final-host-status.json').write_text(json.dumps({'reports':len(experiment.reports),
            'last_state':experiment.state,'rain_reversion_required':experiment.weather_is_raining},indent=2),encoding='utf-8')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
