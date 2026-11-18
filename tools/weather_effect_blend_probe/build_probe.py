"""Fresh isolated layer15 k2 blend probe, based on the verified order carrier."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def write_json(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def build(output,game_exe):
    spec=importlib.util.spec_from_file_location('verified_order_builder',HERE.parent/'weather_effect_order_probe/build_probe.py')
    order=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(order)
    output=order.build(output,game_exe,'scalar')
    package=output/'behavior_pack/weather_effect_order_probe'
    (package/'runtime_base.py').write_bytes((package/'runtime.py').read_bytes())
    (package/'runtime.py').write_bytes((HERE/'runtime.py').read_bytes())
    shaders=output/'resource_pack/shaders/glsl'
    for source,target in (('effect.fragment','weather_effect.fragment'),('copy.fragment','blend_copy.fragment'),
            ('restore.fragment','blend_restore.fragment'),('inspect.fragment','blend_inspect.fragment')):
        (shaders/target).write_bytes((HERE/source).read_bytes())
    material_path=output/'resource_pack/materials/sfx.material'
    material=json.loads(material_path.read_text(encoding='utf-8'))
    material['materials']['sequence:billboard_base'].update({'blendSrc':'SourceAlpha','blendDst':'OneMinusSrcAlpha',
        'alphaSrc':'Zero','alphaDst':'One'})
    write_json(material_path,material)
    post_base=json.loads((output/'resource_pack/materials/postprocess.material').read_text())['weather_effect_oracle']
    posts={}
    for name in ('copy','restore','inspect'):
        entry=dict(post_base)
        entry['fragmentShader']='shaders/glsl/blend_'+name+'.fragment'
        entry['samplerStates']=[{'samplerIndex':slot,'textureWrap':'Clamp','textureFilter':'Point'} for slot in (0,1,3)]
        posts['blend_'+name]=entry
    write_json(output/'resource_pack/materials/postprocess.material',posts)
    receipt_path=output/'material_source_receipt.json'
    receipt=json.loads(receipt_path.read_text())
    receipt.update({'generated_sha256':hashlib.sha256(material_path.read_bytes()).hexdigest(),
        'rgb_blend':['SourceAlpha','OneMinusSrcAlpha'],'alpha_blend':['Zero','One'],
        'source_alpha':'192/255 in custom effect fragment','alpha_write_disabled':True})
    write_json(receipt_path,receipt)
    sources={'runtime.py':(package/'runtime.py'),'runtime_base.py':(package/'runtime_base.py'),
        'effect.fragment':shaders/'weather_effect.fragment','effect.vertex':shaders/'weather_effect.vertex',
        'copy.fragment':shaders/'blend_copy.fragment','restore.fragment':shaders/'blend_restore.fragment',
        'inspect.fragment':shaders/'blend_inspect.fragment'}
    resources=json.loads((output/'probe_resources.json').read_text())
    resources.update({'kind':'weather_effect_k2_blend32_v1','mode':'k2_native_blend','bytes':32,'symbols':43,'bits_per_symbol':6,
        'symbol_order':'little endian bits across source bytes; final two bits zero',
        'transport':'four public SetMixColor, 4 six-bit symbols per uint24 RGB word',
        'native_effect_layer':15,'rgb_blend':['SourceAlpha','OneMinusSrcAlpha'],'source_alpha':192/255,
        'restoration':'round((encodedRGBbyte mod64)*255/63)','raw_copy_slot':3,
        'post_chain':['raw_copy','restore_rgb_pass_alpha','late_consumer_reads_raw_TEXTURE_3'],
        'source_sha256':{name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in sources.items()},
        'runtime_file_writes':False,'continuous_update':False})
    resources.pop('byte_formula',None)
    resources.pop('seed_uniform',None)
    write_json(output/'probe_resources.json',resources)
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--game-exe',required=True)
    args=parser.parse_args()
    print(build(args.output,args.game_exe))
