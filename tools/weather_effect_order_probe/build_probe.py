"""Build one isolated native frame-effect ordering probe; never start a game."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import uuid

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
NAMESPACE=uuid.UUID('3e65d407-3a12-4d09-94c2-1fa684d66ea5')


def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def frame_config():
    """Editor frameeffect fields verified against SDK docs and native samples."""
    return {'frameeffect':{'texture':'textures/weather_effect_order/white',
        'layer':1,
        'scale':[1.,1.,1.],'shuffle':False,'fps':1,'cylinder_enable':False,
        'fade_distance':0.,'depth_test':False,'delay_in_loop':False,'delay':0.,
        'sub_layer':0,'lerp_scale':False,'tex_repeat_num':[1,1],
        'point_filtering':True,'first_person_enable':True,'face_camera':True,
        'rot_speed':[0,0,0],'frame_color':[],'loop':True,'blend_mode':1}}


def build(output,game_exe,mode='scalar'):
    output=Path(output).resolve()
    if output.exists() or (ROOT/'.runtime').resolve() not in output.parents:
        raise ValueError('Choose a fresh isolated output under this repository .runtime')
    game_exe=Path(game_exe).resolve()
    if not game_exe.is_file():
        raise ValueError('Installed game executable is missing')
    if mode not in ('scalar','packed'):
        raise ValueError('Unknown finite effect mode')
    names=('runtime.py','modMain.py','effect.vertex','effect.fragment','post.fragment')
    sources={name:(HERE/name).read_bytes() for name in names}
    if mode=='packed':
        sources['runtime_base.py']=sources['runtime.py']
        sources['runtime.py']=(HERE/'runtime_packed.py').read_bytes()
        sources['effect.fragment']=(HERE/'effect_packed.fragment').read_bytes()
    spec=importlib.util.spec_from_file_location('weather_effect_packet_base',HERE.parent/'runtime_packet_probe/build_probe.py')
    base=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    bp,rp=output/'behavior_pack',output/'resource_pack'
    for pack,typ in (('behavior_pack','data'),('resource_pack','resources')):
        write_json(output/pack/'manifest.json',{'format_version':2,'header':{
            'name':'Finite weather effect ordering '+typ,
            'description':'FrameAni layer1/15, destination-alpha-preserving 32-byte marker',
            'uuid':str(uuid.uuid5(NAMESPACE,pack)),'version':[0,0,1],'min_engine_version':[1,18,0]},
            'modules':[{'type':typ,'uuid':str(uuid.uuid5(NAMESPACE,pack+'/module')),'version':[0,0,1]}]})
    package=bp/'weather_effect_order_probe'
    package.mkdir(parents=True)
    (package/'__init__.py').write_text('# -*- coding: utf-8 -*-\n',encoding='utf-8')
    for name in ('runtime.py','modMain.py')+ (('runtime_base.py',) if mode=='packed' else ()):
        (package/name).write_bytes(sources[name])
    write_json(rp/'effects/order_frame.json',frame_config())
    native_path=game_exe.parent/'data/resource_packs/vanilla_netease/materials/sfx.material'
    native_bytes=native_path.read_bytes()
    native=json.loads(native_bytes.decode('utf-8-sig'))
    material=copy.deepcopy(native)
    updates={
            'vertexShader':'shaders/glsl/weather_effect.vertex',
            'fragmentShader':'shaders/glsl/weather_effect.fragment',
            'vertexFields':[{'field':'Position'},{'field':'UV0'}],
            '+states':['Blending','DisableCulling','DisableDepthTest','DisableDepthWrite','DisableAlphaWrite'],
            '-states':['DisableRGBWrite','EnableAlphaToCoverage'],
            'blendSrc':'One','blendDst':'Zero','alphaSrc':'Zero','alphaDst':'One',
            'msaaSupport':'Both',
            'samplerStates':[{'samplerIndex':0,'textureWrap':'Clamp','textureFilter':'Point'}]}
    material['materials']['sequence:billboard_base'].update(updates)
    for name,value in native['materials'].items():
        if name!='sequence:billboard_base' and value!=material['materials'][name]:
            raise ValueError('Unexpected change outside native sequence material')
    write_json(rp/'materials/sfx.material',material)
    post_config_path=game_exe.parent/'data/resource_packs/vanilla_netease/graphics_settings/post_process.json'
    native_post_bytes=post_config_path.read_bytes()
    native_post=json.loads(native_post_bytes.decode('utf-8-sig'))
    post_config=copy.deepcopy(native_post)
    for process in post_config['process_array']:
        process['enable']=False
    write_json(rp/'graphics_settings/post_process.json',post_config)
    write_json(output/'material_source_receipt.json',{'source':str(native_path),
        'original_sha256':hashlib.sha256(native_bytes).hexdigest(),
        'generated_sha256':hashlib.sha256((rp/'materials/sfx.material').read_bytes()).hexdigest(),
        'changed_materials':['sequence:billboard_base'],'changed_fields':sorted(updates),
        'other_material_entries_identical':True,'native_precipitation_files_modified':False,
        'post_config_source':str(post_config_path),'post_original_sha256':hashlib.sha256(native_post_bytes).hexdigest(),
        'post_generated_sha256':hashlib.sha256((rp/'graphics_settings/post_process.json').read_bytes()).hexdigest(),
        'post_config_changes':['process_array[*].enable=false']})
    untouched={}
    for pack in ('vanilla','vanilla_base','vanilla_netease'):
        material_root=game_exe.parent/'data/resource_packs'/pack/'materials'
        for filename in ('ui3D.material','weather.material','particles.material'):
            path=material_root/filename
            if path.is_file():
                untouched[str(path)]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                    'overlay_exists':(rp/'materials'/filename).exists()}
    write_json(output/'native_untouched_materials.json',untouched)
    post=base.post_material('weather_effect_post.fragment')
    post['fragmentShader']='shaders/glsl/weather_effect_post.fragment'
    write_json(rp/'materials/postprocess.material',{'weather_effect_oracle':post})
    shaders=rp/'shaders/glsl'
    shaders.mkdir(parents=True)
    for source,target in (('effect.vertex','weather_effect.vertex'),
                          ('effect.fragment','weather_effect.fragment'),
                          ('post.fragment','weather_effect_post.fragment')):
        (shaders/target).write_bytes(sources[source])
    base.write_pixel(rp/'textures/weather_effect_order/white.png',(255,255,255,255))
    write_json(output/'.mcdev.json',{'game_executable_path':str(game_exe),'included_mod_dirs':['./'],
        'auto_hot_reload_mods':False,'auto_hot_reload_ui':False,
        'auto_hot_reload_shaders':False,'auto_hot_reload_materials':False})
    receipt={'kind':'finite_weather_effect_order_v1','mode':mode,
        'runtime_namespace':'pmanim_weather_effect_order','effect':'effects/order_frame.json',
        'material':'isolated native sequence override','postprocess_material':'weather_effect_oracle',
        'native_post_effects':'isolated original config with enable flags false',
        'bytes':32,'roi_native720x1080':[72,162,576,216],
        'ndc_roi':[-.8,.7,1.6,.4],'seed_uniform':'EXTRA_VECTOR3.r via documented SetMixColor',
        'byte_formula':'s=(seed+43*i)%251; byte=(s*s+17*s+73*i)%256',
        'alpha_write':False,'destination_alpha_preserved':True,
        'native_weather_overrides':False,'runtime_file_writes':False,
        'private_texture_upload':False,'continuous_update':False,
        'source_sha256':{name:hashlib.sha256(value).hexdigest() for name,value in sources.items()}}
    if mode=='packed':
        receipt.update({'kind':'finite_weather_effect_packed32_v1','seed_uniform':None,'byte_formula':None,
            'arbitrary_32_byte_upload':True,'controls':4,'bytes_per_control':9,
            'payload_encoding':'3 uint24 RGB words normalized by 2^24; alpha=(page+1)/8',
            'payload_source':'host-selected actual byte list passed to game Python write(values)',
            'gpu_payload_seed':False})
    write_json(output/'probe_resources.json',receipt)
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--game-exe',required=True)
    parser.add_argument('--mode',choices=('scalar','packed'),default='scalar')
    args=parser.parse_args()
    print(build(args.output,args.game_exe,args.mode))
