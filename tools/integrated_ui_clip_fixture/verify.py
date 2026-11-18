"""Independent fixed-coordinate WGC pixel oracle for native UI clipping."""
import argparse
import json
from pathlib import Path

from PIL import Image


def verify(image,receipt):
    """Compare every interior patch pixel, with no translation/search/tolerance."""
    if not isinstance(image,Image.Image):
        with Image.open(image) as source:
            image=source.convert('RGB')
    else:
        image=image.convert('RGB')
    if list(image.size)!=receipt['physical']:
        raise ValueError('Native UI clipping oracle requires exact physical viewport')
    patches=[]
    for case in receipt['cases']:
        for patch in case['patches']:
            x,y,width,height=patch['rect']
            values=list(image.crop((x,y,x+width,y+height)).getdata())
            wanted=tuple(patch['rgb'])
            bad=sum(value!=wanted for value in values)
            patches.append({'case':case['id'],'source_membership':case['source_membership'],
                'clipped':case['clipped'],'patch':patch['name'],'rect':patch['rect'],
                'expected_rgb':patch['rgb'],'pixels':len(values),'wrong_pixels':bad,
                'first_observed_rgb':list(values[0]),'exact':bad==0})
    return {'schema':'native_json_ui_clip_pixels_v1','all_exact':all(row['exact'] for row in patches),
        'case_count':len(receipt['cases']),'patch_count':len(patches),
        'compared_pixels':sum(row['pixels'] for row in patches),
        'wrong_pixels':sum(row['wrong_pixels'] for row in patches),'patches':patches,
        'requires_fresh_native_capture_receipt':True,'edge_pixels_excluded':True,'pixel_tolerance':0,
        'alignment_search':False,'scope':'ordinary native image under rectangular panel clips_children'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=verify(args.image,json.loads(args.receipt.read_text(encoding='utf-8')))
    if args.output:
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:result[key] for key in ('all_exact','case_count','patch_count','compared_pixels','wrong_pixels')}))
    raise SystemExit(0 if result['all_exact'] else 1)
