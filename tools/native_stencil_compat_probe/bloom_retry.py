"""Controlled bloom option retry and native-only A/B/A response witness."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

import numpy as np
from PIL import Image

from lifecycle import screenshot
from msaa import EMPTY_GAME_CHECK, sha
from runner import Experiment, HERE, module


KEYS = ('bloom_strength', 'bloom_custom_strength')
OPTIONS_PATTERN = re.compile(rb'(?m)^(bloom_strength|bloom_custom_strength):([0-9]+(?:\.[0-9]+)?)(?=\r?$)')
EFFECTS = HERE.parent/'native_stencil_post_fixture/native_effects.py'


def options(path, receipt, restore):
    active = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',
                             EMPTY_GAME_CHECK],check=True,capture_output=True,text=True,timeout=25)
    if active.stdout.strip()!='0':
        raise RuntimeError('Options changes need zero active Minecraft processes')
    data=path.read_bytes()
    matches=tuple(OPTIONS_PATTERN.finditer(data))
    existing={match[1].decode():match[2].decode() for match in matches}
    if len(matches)!=2 or set(existing)!=set(KEYS):
        raise ValueError('Expected both of the built-in bloom settings')
    if restore:
        previous=json.loads(receipt.read_bytes())
        if Path(previous['path']).resolve()!=path.resolve() or any(
                existing[key] not in (previous['before'][key],str(previous['requested'][key]),'1.0') for key in KEYS):
            raise ValueError('Bloom settings changed outside this test')
        wanted=previous['before']
    else:
        wanted=dict.fromkeys(KEYS,'1')
        with receipt.open('x',encoding='utf-8') as record:
            json.dump({'path':str(path.resolve()),'before':existing,'requested':wanted,
                       'original_sha256':sha(data)},record,indent=2)
    altered=OPTIONS_PATTERN.sub(lambda m:m[1]+b':'+wanted[m[1].decode()].encode(),data)
    path.write_bytes(altered)
    return {'before':existing,'after':wanted,'sha256':sha(altered)}


class BloomExperiment(Experiment):
    def load(self, size):
        super().load(size)
        result={'snapshots':[], 'rgb_captures':[]}
        try:
            for label,varying in (('opaque',False),('varying',True),('opaque_return',False)):
                state=self.call('native_only_'+label,
                    "probe.configure('off')\nprobe.configure_known_fixture(True,%r)"%varying)
                if state['pipeline_registered'] or state['oracle_installed'] or not dict(state['native_post_flags'])['bloom']:
                    raise RuntimeError('Native-only witness requires only the built-in bloom path')
                result['snapshots'].append({'state':state,'mode':label})
                time.sleep(.65)
                result['rgb_captures'].append(screenshot(self,'native_only_'+label))
            x,y,w,h=self.roi
            frames=[]
            for sample in result['rgb_captures']:
                with Image.open(sample['image']) as img:
                    frames.append(np.array(img.convert('RGB').crop((x,y,x+w,y+h)),dtype=np.int16))
            result['fixture_rect_pixels']=w*h
            result['changed_pixels_gt2']=int((np.max(np.abs(frames[1]-frames[0]),axis=2)>2).sum())
            result['opaque_return_identical']=bool(np.array_equal(frames[0],frames[2]))
        finally:
            (self.evidence/'bloom_without_custom_passes.json').write_text(
                json.dumps(result,indent=2)+'\n',encoding='utf-8')
            self.call('native_only_finished','probe.configure_known_fixture(False)')


def run(args):
    args.evidence.mkdir(exist_ok=False)
    shutil.copyfile(args.previous_evidence/'launch.json',args.evidence/'launch.json')
    native=module('native_stencil_bloom_retry',EFFECTS)
    exp=BloomExperiment(args)
    native.initialize(exp,'bloom')
    result=native.run(exp,'bloom')
    return {key:result.get(key) for key in ('status','compatibility','failure','late_full_data_passed',
                                            'native_positive_response_observed')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    set_opt=sub.add_parser('options')
    set_opt.add_argument('options',type=Path)
    set_opt.add_argument('receipt',type=Path)
    set_opt.add_argument('--restore',action='store_true')
    retry=sub.add_parser('run')
    for key in ('project','evidence','previous-evidence'):
        retry.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(options(args.options,args.receipt,args.restore) if args.action=='options' else run(args)))


if __name__=='__main__':
    main()
