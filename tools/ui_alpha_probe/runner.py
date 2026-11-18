"""Run finite static POC cases and save native state, WGC receipts and ROI stats."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image

HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--skip-destination-reader',action='store_true')
    parser.add_argument('--resume-post',action='store_true')
    parser.add_argument('--post-off-baseline',action='store_true')
    args=parser.parse_args()
    evidence=args.evidence.resolve()
    commands=evidence/'commands'
    commands.mkdir(parents=True,exist_ok=True)
    reports=(json.loads((evidence/'results.json').read_text(encoding='utf-8'))['cases']
        if args.resume_post else [])

    def host(action,label,code=None):
        command=[sys.executable,'-B','-X','utf8',str(HERE/'host.py'),action,
            '--project',str(args.project.resolve()),'--evidence',str(evidence),'--label',label,'--timeout','90']
        if code is not None:
            path=commands/(label+'.py')
            path.write_text("probe=api.GetSystem('pmanim_ui_alpha_probe','probe')\n"+code+
                "\n_result=probe.snapshot()\n_result['post_enabled']=dict((kind,probe.post.CheckEnabledByName('ui_alpha_'+kind)) for kind in ('copy','t0','t1')) if probe.installed else {}\n_result=json.dumps(_result)\n",encoding='utf-8')
            command+=['--code',str(path)]
        with (evidence/(label+'.'+action+'.log')).open('w',encoding='utf-8') as stream:
            subprocess.run(command,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                check=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if action=='call':
            return json.loads((evidence/(label+'.state.json')).read_text(encoding='utf-8'))

    def capture(label,code):
        state=host('call',label,code)
        time.sleep(.7)
        host('capture',label)
        receipt=json.loads((evidence/(label+'.json')).read_text(encoding='utf-8'))
        if not receipt['ok'] or receipt['backend']!='Windows.Graphics.Capture':
            raise ValueError('Invalid passive capture receipt')
        with Image.open(evidence/(label+'.png')) as source:
            image=source.convert('RGB')
        width,height=image.size
        points=[(int(width*fx),int(height*fy)) for fy in (.4,.5,.6) for fx in (.35,.5,.65)]
        pixels=[image.getpixel(point) for point in points]
        roi=image.crop((int(width*.3),int(height*.35),int(width*.7),int(height*.65)))
        counts=Counter(roi.getdata())
        report={'name':label,'state':state,'image_size':[width,height],'points':points,'pixels':pixels,
            'common_roi_rgb':counts.most_common(5),'capture':str(evidence/(label+'.png')),
            'foreground_allowed':receipt.get('user_foreground_allowed'),
            'actual_foreground_pid':receipt.get('background_before',{}).get('foreground',{}).get('pid'),
            'noactivation':receipt.get('background_before',{}).get('window_noactivate')}
        reports.append(report)
        (evidence/'results.json').write_text(json.dumps({'schema':'finite_ui_alpha_v1','cases':reports},indent=2),encoding='utf-8')
        print(json.dumps({'name':label,'center':pixels[4],'common':report['common_roi_rgb'][:2]}),flush=True)

    state=host('call','000_open',"if probe is None:\n    raise RuntimeError('Probe missing')\napi.HideCrossHairGUI(True)\nprobe.open()")
    for index in range(20):
        if state['ready']:
            break
        time.sleep(.2)
        state=host('call','001_ready_%02d'%index,'')
    if not state['ready']:
        raise RuntimeError('UI never ready')
    cases=[('010_baseline','hidden',42,False,False),('011_rgb_42','rgb',42,False,False),
        ('012_rgb_201','rgb',201,False,False),('013_rgb_offscreen','rgb',201,False,True),
        ('014_rgb_restored','rgb',201,False,False),('020_alpha_42','alpha',42,False,False),
        ('021_alpha_201','alpha',201,False,False),('022_alpha_offscreen','alpha',201,False,True)]
    for name,writer,value,reader,offscreen in cases:
        if args.resume_post:
            continue
        if args.skip_destination_reader and reader:
            continue
        capture(name,'probe.configure(%r,%d,%r,%r)'%(writer,value,reader,offscreen))
    for index,(value,carrier_offscreen) in enumerate(((42,False),(201,True),(42,True),(201,False),(42,False))):
        if args.resume_post:
            continue
        capture('038_carrier_%d'%index,'probe.configure(%r,%d,False,False,%r)'%('rgb',value,carrier_offscreen))
    if not state['post_installed']:
        host('call','040_install_post','probe.install_post()')
        time.sleep(.5)
        host('call','041_finish_post','probe.finish_post()')
    for post in (() if args.post_off_baseline else ('t0','t1')):
        for writer,value in (('hidden',42),('alpha',42),('alpha',201),('rgb',201)):
            if args.resume_post:
                continue
            label='05'+('0' if post=='t0' else '1')+'_'+post+'_'+writer+'_'+str(value)
            capture(label,'probe.configure(%r,%d,False,False)\nprobe.set_post(%r)'%(writer,value,post))
    for post in (('off',) if args.post_off_baseline else ('t0','t1')):
        for writer,value in (('hidden',42),('alpha',42),('alpha',201),('rgb',201)):
            label='06'+('0' if post=='t0' else '1' if post=='t1' else '2')+'_'+post+'_'+writer+'_'+str(value)
            capture(label,"probe.screen.GetBaseUIControl('/background').SetVisible(False,False)\n"+
                'probe.configure(%r,%d,False,False)\nprobe.set_post(%r)'%(writer,value,post))
    if args.post_off_baseline:
        for post in ('t0','t1'):
            capture('070_guard_'+post,"probe.screen.GetBaseUIControl('/background').SetVisible(False,False)\n"+
                "probe.configure('alpha',201,False,False)\nprobe.set_post(%r)"%post)
    host('call','099_restore',"probe.set_post('off')\nprobe.screen.GetBaseUIControl('/background').SetVisible(True,False)\nprobe.configure('hidden',42,False,False)")
    return 0


if __name__=='__main__':
    raise SystemExit(main())
