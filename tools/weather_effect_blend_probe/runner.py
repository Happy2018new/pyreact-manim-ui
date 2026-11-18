"""Finite native k2 blend proof; no activation, input, or continuous updates."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('blend_order_runner',HERE.parent/'weather_effect_order_probe/runner.py')
base=importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
base.HERE=HERE
base.OWNER='manim-weather-effect-blend'
spec=importlib.util.spec_from_file_location('independent_scene_codec',HERE.parent/'scene_codec_probe/codec.py')
codec=importlib.util.module_from_spec(spec)
spec.loader.exec_module(codec)
PAYLOADS=[
    [0,255,1,254,2,253,127,128,129,0,0,0,255,255,255,255,0,255,0,255,0,1,0,1,0,1,0,254,255,254,255,254],
    list(hashlib.sha256(b'host-selected real bytes, no GPU seed, weather probe R2 A').digest()),
    [255,255,255,128,0,0,127,255,255,0,0,1,0,1,0,1,0,0,85,170,255,255,170,85,254,1,128,129,254,127,0,255],
]
COUNT=576*216
CELL=np.floor((np.arange(576)+.5)*43/576).astype(np.int64)


def decode_triplets(path):
    with Image.open(path) as image:
        array=np.asarray(image.convert('RGB'))
    triples=array[500:1019,:,:].reshape(-1,3)[:COUNT*3].reshape(COUNT,3,3)
    return triples[:,0,:].copy(),triples[:,1,:].copy(),triples[:,2,:].copy()


def pixel_symbols(rgb):
    q=rgb.astype(np.int16)//64
    return q[:,0]+4*q[:,1]+16*q[:,2]


def verify_pair(raw,alpha,restored,values):
    symbols=np.asarray(codec.payload_to_symbols(bytes(values),2),dtype=np.int16)
    expected=np.tile(symbols[CELL],216)
    decoded=pixel_symbols(raw)
    wrong=decoded!=expected
    low=alpha[:,0]!=255
    restoration=((raw.astype(np.int16)%64)*255*2+63)//126
    counts=low.reshape(-1,32).sum(axis=1)
    return {'source_pixels':COUNT,'symbol_error_pixels':int(wrong.sum()),
        'low_alpha_pixels':int(low.sum()),'wrong_symbol_low_alpha_pixels':int((wrong&low).sum()),
        'correct_symbol_low_alpha_pixels':int((~wrong&low).sum()),
        'alpha_gray_errors':int(np.any(alpha!=alpha[:,:1],axis=1).sum()),
        'alpha_histogram':dict(Counter(int(x) for x in alpha[:,0])),
        'block_pixels':32,'alpha_exception_definition':'Abyte !=255, linear source pixel order',
        'complete_blocks':len(counts),'exception_histogram':dict(Counter(int(x) for x in counts)),
        'alpha_blocks_over4':int((counts>4).sum()),'max_alpha_exceptions':int(counts.max()),
        'restore_shader_vs_sameframe_raw_errors':int(np.any(restored!=restoration,axis=1).sum()),
        'center_symbols':decoded.reshape(216,576)[108,[int((i+.5)*576/43) for i in range(43)]].tolist(),
        'expected_symbols':symbols.tolist(),'final_two_padding_bits_zero':int(symbols[-1])<16}


class Experiment(base.Experiment):
    def __init__(self,args):
        base.Experiment.__init__(self,args)
        self.values=None
        self.name=None
        self.baseline=None
        self.baseline_after=None
        self.clear_rows=[]

    def select(self,name,values,visible=True):
        self.call('write_'+name,'probe.write(%r)\nprobe.configure(%r,15)'%(values,visible))
        if self.state['payload']!=values or self.state['symbols']!=list(codec.payload_to_symbols(bytes(values),2)):
            raise RuntimeError('Game Python payload/symbols differ from independent host bytes')
        self.values,self.name=list(values),name

    def capture(self,label,slot=3,mode=0,visible=True,restoring=True,verify=True):
        self.call(label+'_controls','probe.configure(%r,15)\nprobe.inspect(True,%d,True,%d,%r)'%(visible,slot,mode,restoring))
        time.sleep(.5)
        self.call(label+'_settled')
        self.invoke([sys.executable,'-B','-X','utf8',str(HERE/'host.py'),'capture','--project',str(self.args.project.resolve()),
            '--evidence',str(self.evidence),'--label',label],label+'_capture')
        receipt=json.loads((self.evidence/(label+'.json')).read_text(encoding='utf-8'))
        if not receipt['ok'] or receipt['backend']!='Windows.Graphics.Capture' or [receipt['width'],receipt['height']]!=[720,1080] or receipt['frame_qpc_100ns']<receipt['request_qpc_100ns'] or receipt.get('agent_activation_allowed') is not False:
            raise RuntimeError('Invalid fresh passive native capture')
        row={'label':label,'payload':self.values,'payload_name':self.name,'slot':slot,'mode':mode,
            'visible':visible,'restore':restoring,'raining':self.weather_is_raining,'state':self.state}
        if mode==0:
            raw,alpha,restored=decode_triplets(self.evidence/(label+'.png'))
            if visible and verify:
                row.update(verify_pair(raw,alpha,restored,self.values))
                row['exact']=row['symbol_error_pixels']==0 and row['restore_shader_vs_sameframe_raw_errors']==0 and row['alpha_gray_errors']==0
            elif not restoring:
                row.update({'raw_vs_passthrough_rgb_errors':int(np.any(raw!=restored,axis=1).sum()),
                    'alpha_not255':int((alpha[:,0]!=255).sum()),'exact':bool(np.array_equal(raw,restored))})
            else:
                row['exact']=True
            if not self.weather_is_raining and visible and self.baseline is not None:
                delta=np.abs(restored.astype(np.int16)-self.baseline.astype(np.int16))
                q=np.stack([np.tile(np.asarray(codec.payload_to_symbols(bytes(self.values),2))[CELL]//(4**channel)%4,216) for channel in range(3)],axis=1)
                ideal=64*q+((self.baseline.astype(np.int16)*63*2+255)//510)
                row.update({'restored_vs_baseline_max_channel_error':int(delta.max()),
                    'restored_vs_baseline_pixels_over2':int(np.any(delta>2,axis=1).sum()),
                    'coded_vs_integer_blend_pixels_wrong':int(np.any(raw!=ideal,axis=1).sum()),
                    'baseline_equality_gate':'pending after capture'})
                self.clear_rows.append(row)
        else:
            with Image.open(self.evidence/(label+'.png')) as image:
                count=43 if mode==1 else 32
                observed=[list(image.getpixel((int((i+.5)*720/count),750))[:3]) for i in range(count)]
            expected_values=list(codec.payload_to_symbols(bytes(self.values),2)) if mode==1 else list(self.values)
            if mode==3:
                expected_values=[self.values[((131*i+29)%32+3*self.values[(131*i+29)%32]+7)%32] for i in range(32)]
            expected=[[v,(v*71+43)%256,(v*131+17)%256] for v in expected_values]
            row.update({'observed':observed,'expected':expected,'exact':observed==expected})
        self.reports.append(row)
        self.save()
        print(json.dumps({key:row[key] for key in ('label','exact','symbol_error_pixels','low_alpha_pixels','alpha_blocks_over4','restored_vs_baseline_max_channel_error') if key in row}),flush=True)
        if verify and not row['exact']:
            raise RuntimeError('Native k2 rendering/readback gate failed; preserve original evidence')
        return row

    def save(self):
        (self.evidence/'results.json').write_text(json.dumps({'schema':'weather_effect_k2_blend32_v1','reports':self.reports},indent=2),encoding='utf-8')

    def run(self):
        self.call('initial')
        self.call('camera','api.HideCrossHairGUI(True)\nprobe.prepare_camera()')
        self.weather('prepare_clear',False,True)
        self.call('create','probe.create()\nprobe.install_post()')
        self.select('baseline',PAYLOADS[0],False)
        self.capture('010_clear_baseline_before',visible=False,restoring=False)
        self.baseline=decode_triplets(self.evidence/'010_clear_baseline_before.png')[0]
        for index,values in enumerate(PAYLOADS):
            self.select('clear_%d'%index,values)
            self.capture('020_clear_%d_t3'%index)
        self.capture('021_clear_t1',slot=1)
        self.capture('022_clear_baseline_after',visible=False,restoring=False)
        self.baseline_after=decode_triplets(self.evidence/'022_clear_baseline_after.png')[0]
        stable=np.array_equal(self.baseline,self.baseline_after)
        for row in self.clear_rows:
            row['baseline_equality_gate']='pass' if stable else 'fail'
        self.save()
        (self.evidence/'clear-baseline-gate.json').write_text(json.dumps({'whole_roi_pixels':COUNT,
            'before_after_exact':bool(stable),'changed_pixels':int(np.any(self.baseline!=self.baseline_after,axis=1).sum()),
            'max_channel_change':int(np.abs(self.baseline.astype(np.int16)-self.baseline_after.astype(np.int16)).max()),
            'all_restored_within2':all(row['restored_vs_baseline_max_channel_error']<=2 for row in self.clear_rows),
            'all_native_blend_exact':all(row['coded_vs_integer_blend_pixels_wrong']==0 for row in self.clear_rows)},indent=2))
        if not stable or any(row['restored_vs_baseline_max_channel_error']>2 or row['coded_vs_integer_blend_pixels_wrong'] for row in self.clear_rows):
            raise RuntimeError('Whole-ROI clear baseline gate or hardware blend bound failed')
        for index,values in enumerate(PAYLOADS):
            self.select('clear_query_%d'%index,values)
            for mode in (1,2,3):
                self.capture('023_clear_%d_mode%d'%(index,mode),mode=mode)
        self.weather('rain_on',True)
        self.capture('030_wet_hidden',visible=False,restoring=False)
        for index in (0,1):
            self.select('wet_%d'%index,PAYLOADS[index])
            for slot in (1,3):
                self.capture('031_wet_%d_t%d'%(index,slot),slot=slot)
            for mode in (1,2,3):
                self.capture('032_wet_%d_mode%d'%(index,mode),mode=mode)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    exp=Experiment(args)
    completed=False
    try:
        exp.run()
        completed=True
    finally:
        if exp.weather_is_raining:
            exp.weather('cleanup_rain_off',False)
        if exp.state.get('effect_count'):
            exp.call('cleanup_remove','probe.remove()')
        if exp.state.get('installed'):
            exp.call('cleanup_post_off',"probe.post.SetEnableByName('weather_effect_oracle',False)")
        (args.evidence/'final-host-status.json').write_text(json.dumps({'completed':completed,'reports':len(exp.reports),
            'all_exact':all(row['exact'] for row in exp.reports),'rain_reversion_required':exp.weather_is_raining,
            'last_state':exp.state},indent=2),encoding='utf-8')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
