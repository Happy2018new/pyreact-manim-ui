"""Finite static sampler checks with independent host oracles and WGC evidence."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image

HERE=Path(__file__).resolve().parent
STATIC_SEEDS=(17,83,149)


def byte_at(seed,index):
    return (seed*37+index*73+(index//3)*19)%256


def oracle(seed,query):
    result=[]
    for index in range(32):
        location=index if query==0 else (131*index+29)%32
        if query==2:
            location=(location+byte_at(seed,location)*3+7)%32
        result.append(byte_at(seed,location))
    return result


def read_bytes(image,roi):
    x,y,w,h=roi
    positions=[(int(math.floor(x+(index+.5)*w/32)),int(math.floor(y+h*.5))) for index in range(32)]
    values=[]
    for px,py in positions:
        patch=[image.getpixel((px+dx,py+dy)) for dx in (-1,0,1) for dy in (-1,0,1)]
        values.append(patch)
    return positions,values


def compare(patches,expected):
    errors=[max(abs(channel-value) for pixel in patch for channel in pixel[:3])
        for patch,value in zip(patches,expected)]
    return {'exact':all(error==0 for error in errors),'checked_bytes':len(errors),
        'mismatch_bytes':sum(error!=0 for error in errors),'maximum_error':max(errors),
        'observed_rgb':[list(patch[4][:3]) for patch in patches],
        'expected_bytes':expected}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--image-only',action='store_true')
    args=parser.parse_args()
    evidence=args.evidence.resolve()
    commands=evidence/'commands'
    commands.mkdir(parents=True,exist_ok=True)
    if (evidence/'results.json').exists() and not args.image_only:
        raise ValueError('Choose a fresh result evidence directory')
    reports=json.loads((evidence/'results.json').read_text(encoding='utf-8'))['cases'] if args.image_only else []

    def host(action,label,code=None):
        command=[sys.executable,'-B','-X','utf8',str(HERE/'host.py'),action,
            '--project',str(args.project.resolve()),'--evidence',str(evidence),'--label',label,'--timeout','90']
        if code is not None:
            path=commands/(label+'.py')
            path.write_text("probe=api.GetSystem('pmanim_ui_texture_probe','probe')\n"+code+
                '\n_result=json.dumps(probe.snapshot())\n',encoding='utf-8')
            command+=['--code',str(path)]
        with (evidence/(label+'.'+action+'.log')).open('w',encoding='utf-8') as stream:
            subprocess.run(command,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                check=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if action=='call':
            return json.loads((evidence/(label+'.state.json')).read_text(encoding='utf-8'))

    def capture(label,parameters,static=False,prelude='',ordering=False,require_writer=True):
        code=prelude+'\nprobe.configure(**%r)'%parameters
        if ordering:
            code+="\nprobe.screen.GetBaseUIControl('/background').SetVisible(False,False)\nprobe.screen.controls['bound'][0].SetVisible(False,False)\nprobe.screen.controls['default'][0].SetVisible(False,False)\nprobe.screen.UpdateScreen(True)"
        state=host('call',label,code)
        time.sleep(.5)
        host('capture',label)
        receipt=json.loads((evidence/(label+'.json')).read_text(encoding='utf-8'))
        if (not receipt['ok'] or receipt['backend']!='Windows.Graphics.Capture' or
                (receipt['width'],receipt['height'])!=(720,1080) or receipt.get('agent_activation_allowed') is not False):
            raise ValueError('Invalid passive native capture')
        with Image.open(evidence/(label+'.png')) as source:
            image=source.convert('RGB')
        screen=state['screen']
        target_roi=[72.,864.,576.,162.] if ordering else screen['receiver_roi']
        receiver_points,receiver=read_bytes(image,target_roi)
        _,writer=read_bytes(image,screen['producer_roi'])
        seed=STATIC_SEEDS[screen['slot']] if static else screen['seed']
        report={'name':label,'state':state,'capture':str(evidence/(label+'.png')),
            'classification':'known static source control' if static else 'exploratory candidate; no render target binding claimed',
            'receiver':compare(receiver,oracle(seed,screen['query'])),
            'producer':compare(writer,oracle(screen['seed'],0)),
            'receiver_centers':receiver_points,'capture_size':[receipt['width'],receipt['height']],
            'ordering_probe':bool(ordering),
            'actual_foreground':receipt.get('background_before',{}).get('foreground'),
            'noactivation':receipt.get('background_before',{}).get('window_noactivate'),
            'receiver_histogram':dict(Counter(tuple(row[4]) for row in receiver))}
        report['receiver_histogram']=[{'rgb':list(color),'count':count}
            for color,count in report['receiver_histogram'].items()]
        reports.append(report)
        (evidence/'results.json').write_text(json.dumps({'schema':'finite_ui_texture_binding_v1','cases':reports},indent=2),encoding='utf-8')
        print(json.dumps({'name':label,'receiver_exact':report['receiver']['exact'],
            'receiver_first':report['receiver']['observed_rgb'][:6],
            'producer_exact':report['producer']['exact']}),flush=True)
        if static and screen['slot']==0 and not report['receiver']['exact']:
            raise ValueError('Known source texture positive control failed: '+label)
        if require_writer and screen['writer'] and not report['producer']['exact']:
            raise ValueError('Producer GPU bytes failed host oracle: '+label)
        return report

    state=host('call','000_open',"if probe is None:\n    raise RuntimeError('Probe missing')\napi.HideCrossHairGUI(True)\nprobe.open()")
    for index in range(20):
        if state['ready']:
            break
        time.sleep(.2)
        state=host('call','001_ready_%02d'%index,'')
    if not state['ready']:
        raise RuntimeError('UI never ready')
    if args.image_only:
        host('call','080_image_setup',"probe.set_post(False)\nprobe.bind_hud()\nprobe.screen.SetScreenVisible(True)\nprobe.screen.GetBaseUIControl('/background').SetVisible(True,False)")
        for slot in range(3):
            for sprite in (0,1):
                capture('081_image_slot%d_sprite%d'%(slot,sprite),{'slot':slot,'sample_mode':3,
                    'query':0,'seed':201,'writer':True},
                    prelude="probe.screen.controls['default'][1].SetSprite('textures/ui_texture_probe/static_%d')"%sprite)
        host('call','082_image_hide',"probe.configure(writer=False)\nprobe.screen.SetScreenVisible(False)")
        return 0
    # Verify the receiver can perform arbitrary indexed source reads, before
    # interpreting any missing dynamic binding as a negative transport result.
    for slot in range(3):
        for query in range(3):
            capture('010_static_%d_q%d'%(slot,query),{'receiver':'bound','slot':slot,'query':query,
                'sample_mode':1,'seed':42,'writer':True},static=True)
    for slot in range(3):
        capture('020_default_local_%d'%slot,{'slot':slot,'sample_mode':3,'query':0,'seed':42,'writer':False})
    for slot in range(3):
        for label,seed,writer,after in (('off',42,False,False),('seed42',42,True,False),
                ('seed201',201,True,False),('order',201,True,True)):
            capture('030_slot%d_%s'%(slot,label),{'slot':slot,'sample_mode':2,'query':0,
                'seed':seed,'writer':writer,'writer_after':after})
        capture('031_slot%d_flip'%slot,{'slot':slot,'sample_mode':2,'query':0,'seed':201,'writer':True,'flip':True})
    host('call','050_install_post','probe.install_post()')
    time.sleep(.5)
    for binding in ('hud','world'):
        if binding=='world':
            state=host('call','060_world_create','probe.bind_world()')
            for index in range(20):
                if state['ready']:
                    break
                time.sleep(.2)
                state=host('call','061_world_ready_%02d'%index,'')
            if not state['ready']:
                raise RuntimeError('World-bound UI never ready')
        positive=capture('062_'+binding+'_visible',{'seed':42,'writer':True},
            prelude='probe.set_post(False)',ordering=True,require_writer=False)
        if not positive['producer']['exact']:
            host('call','063_'+binding+'_inconclusive',"probe.screen.SetScreenVisible(False)")
            continue
        for label,seed,writer,slot in (('off',42,False,0),('seed42',42,True,0),('seed201',201,True,0),('t1',201,True,1)):
            capture('064_'+binding+'_'+label,{'seed':seed,'writer':writer},
                prelude='probe.set_post(True,%d,False)'%slot,ordering=True)
        capture('065_'+binding+'_alpha',{'seed':201,'writer':True},
            prelude='probe.set_post(True,0,True)',ordering=True)
    host('call','098_restore',"probe.set_post(False)\nprobe.bind_hud()")
    host('call','099_hide',"probe.configure(writer=False)\nprobe.screen.SetScreenVisible(False)")
    return 0


if __name__=='__main__':
    raise SystemExit(main())
