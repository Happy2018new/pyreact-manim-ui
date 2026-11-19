"""Isolated Win32 MSAA experiment using the carrier's actual FrameAni shader."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SHADER = 'resource_pack/shaders/glsl/stencil_large_effect.fragment'
OFF_COLOR = (43, 151, 229)
ON_COLOR = (197, 53, 109)
PATCH = (660, 138, 676, 154)
EMPTY_GAME_CHECK = (
    "@(Get-CimInstance Win32_Process -Filter \"Name='Minecraft.Windows.exe'\" "
    "| Where-Object {$_.ThreadCount -gt 0 -or $_.HandleCount -gt 0}).Count"
)
LINE = re.compile(rb'(?m)^gfx_msaa:([0-9]+)(?=\r?$)')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(project):
    project = project.resolve()
    if (ROOT/'.runtime').resolve() not in project.parents:
        raise ValueError('Use an isolated generated carrier project')
    path = project/SHADER
    original = path.read_bytes()
    source = original.decode('utf-8')
    marker = '    if (pixel.x < origin.x || pixel.y < origin.y ||'
    if source.count(marker) != 1:
        raise ValueError('Unexpected uninstrumented effect source')
    addition = '''    if (abs(EXTRA_VECTOR3.a - 0.25) < 0.01
            && pixel.x >= 660.0 && pixel.x < 676.0
            && pixel.y >= 138.0 && pixel.y < 154.0) {
#ifdef MSAA_FRAMEBUFFER_ENABLED
        gl_FragColor = vec4(197.0, 53.0, 109.0, 255.0) / 255.0;
#else
        gl_FragColor = vec4(43.0, 151.0, 229.0, 255.0) / 255.0;
#endif
        return;
    }
'''
    altered = source.replace(marker, addition+marker).encode('utf-8')
    path.write_bytes(altered)
    return {'shader':SHADER, 'original_sha256':sha(original),
            'instrumented_sha256':sha(altered), 'patch_xyxy':list(PATCH),
            'colors':{'no_msaa_macro':list(OFF_COLOR),'msaa_macro':list(ON_COLOR)}}


def verify(path):
    with Image.open(path) as image:
        if image.size != (720,1080):
            raise ValueError('MSAA witness requires native 720x1080')
        patch = np.array(image.convert('RGB').crop(PATCH))
    counts = {name:int(np.all(patch==color, axis=2).sum()) for name, color in
              [('no_msaa_macro',OFF_COLOR),('msaa_macro',ON_COLOR)]}
    return {**counts,'pixels':int(patch.shape[0]*patch.shape[1])}


def refresh(options, receipt, mode):
    active = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',
                             EMPTY_GAME_CHECK],check=True,capture_output=True,text=True)
    if active.stdout.strip() != '0':
        raise RuntimeError('Options changes require zero active Minecraft processes')
    body = options.read_bytes()
    hits = list(LINE.finditer(body))
    if len(hits)!=1:
        raise ValueError('Expected exactly one gfx_msaa entry')
    previous = int(hits[0][1])
    if mode == 'restore':
        saved = json.loads(receipt.read_bytes())
        if Path(saved['path']).resolve()!=options.resolve() or previous not in (
                saved['prior'],saved['requested']):
            raise ValueError('Options path or AA value changed outside this trial')
        wanted = saved['prior']
    else:
        if mode not in ('1','4'):
            raise ValueError('Use the intended 1×/4× pair')
        wanted = int(mode)
        with receipt.open('x',encoding='utf-8') as record:
            json.dump({'path':str(options.resolve()),'prior':previous,
                       'requested':wanted,'original_sha256':sha(body)},record)
    new = LINE.sub(b'gfx_msaa:'+str(wanted).encode('ascii'),body)
    if new!=body:
        options.write_bytes(new)
    return {'prior':previous,'current':wanted,'sha256':sha(new)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='action',required=True)
    build = subparsers.add_parser('prepare')
    build.add_argument('project',type=Path)
    capture = subparsers.add_parser('verify')
    capture.add_argument('screenshot',type=Path)
    options = subparsers.add_parser('options')
    options.add_argument('options',type=Path)
    options.add_argument('receipt',type=Path)
    options.add_argument('mode',choices=('1','4','restore'))
    args=parser.parse_args()
    if args.action=='prepare':
        result=prepare(args.project)
    elif args.action=='verify':
        result=verify(args.screenshot)
    else:
        result=refresh(args.options,args.receipt,args.mode)
    print(json.dumps(result))


if __name__=='__main__':
    main()
