"""Build a bounded static-texture control and exploratory UI sampler probe."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import uuid
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAMESPACE = uuid.UUID('1e18df7f-726c-453a-b4c4-b8055417ab79')
STATIC_SEEDS = (17, 83, 149)
KINDS = ('producer', 'bound', 'default')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')


def sequence(seed):
    return [(seed*37+index*73+(index//3)*19)%256 for index in range(32)]


def write_row(path, values):
    """One offline 32x1 UNORM8 resource; no game runtime file operations."""
    def chunk(kind, value):
        return struct.pack('>I',len(value))+kind+value+struct.pack('>I',zlib.crc32(kind+value)&0xffffffff)
    pixels=bytes(channel for value in values for channel in (value,value,value,255))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',len(values),1,8,6,0,0,0))+
        chunk(b'IDAT',zlib.compress(b'\x00'+pixels))+chunk(b'IEND',b''))


def build(output, game_exe):
    output=Path(output).resolve()
    if output.exists() or (ROOT/'.runtime').resolve() not in output.parents:
        raise ValueError('Choose a fresh isolated output under repository .runtime')
    game_exe=Path(game_exe).resolve()
    if not game_exe.is_file():
        raise ValueError('Installed game executable is missing')
    spec=importlib.util.spec_from_file_location('ui_texture_packet_base',HERE.parent/'runtime_packet_probe/build_probe.py')
    base=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    bp,rp=output/'behavior_pack',output/'resource_pack'
    for pack,typ in (('behavior_pack','data'),('resource_pack','resources')):
        write_json(output/pack/'manifest.json',{'format_version':2,'header':{
            'name':'Finite UI texture binding '+typ,'description':'32-byte static control and default-slot observation',
            'uuid':str(uuid.uuid5(NAMESPACE,pack)),'version':[0,0,1],'min_engine_version':[1,18,0]},
            'modules':[{'type':typ,'uuid':str(uuid.uuid5(NAMESPACE,pack+'/module')),'version':[0,0,1]}]})
    package=bp/'ui_texture_binding_probe'
    package.mkdir(parents=True)
    (package/'__init__.py').write_text('# -*- coding: utf-8 -*-\n',encoding='utf-8')
    for name in ('runtime.py','modMain.py'):
        shutil.copyfile(HERE/name,package/name)
    base.write_entities(rp,bp,3)
    controller_path=rp/'render_controllers/pmanim_packet.render_controllers.json'
    write_json(controller_path,{'format_version':'1.8.0','render_controllers':{
        'controller.render.ui_texture_bound':{'geometry':'Geometry.default','materials':[{'*':'Material.default'}],
            'textures':['Texture.slot0','Texture.slot1','Texture.slot2']},
        'controller.render.ui_texture_default':{'geometry':'Geometry.default','materials':[{'*':'Material.default'}],
            'textures':['Texture.slot0']}}})
    for index,kind in enumerate(KINDS):
        path=rp/('entity/pmanim_packet_slot_%03d.entity.json'%index)
        entity=json.loads(path.read_text(encoding='utf-8'))
        description=entity['minecraft:client_entity']['description']
        description['materials']={'default':'pmanim_ui_texture_'+kind}
        description['textures']={'slot%d'%slot:'textures/ui_texture_probe/static_%d'%slot for slot in range(3)}
        description['render_controllers']=['controller.render.ui_texture_'+('bound' if kind=='bound' else 'default')]
        write_json(path,entity)
    controls=[{'background':base.control('image',('100%','100%'),texture='textures/pmanim_packet/white',
        color=[17/255.,53/255.,97/255.],keep_ratio=False)}]
    for index,kind in enumerate(KINDS):
        controls.append({kind:base.control('panel',(200,160),layer=10+index*10,visible=False,controls=[
            {'carrier':base.control('image',(1,1),layer=0,texture='textures/pmanim_packet/transparent',
                color=[17/255.,0.25,0.75],alpha=1.,keep_ratio=False)},
            {'canvas':base.control('custom',(200,160),layer=1,renderer='netease_paper_doll_renderer',
                rotation='none',init_rot_x=0.,init_rot_y=0.,init_rot_z=0.,screen_scale=1.,enable_scissor_test=True)}])})
    write_json(rp/'ui/ui_texture_probe.json',{'namespace':'pmanim_ui_texture_probe',
        'main':base.control('screen',('100%','100%'),layer=1000,controls=controls)})
    write_json(rp/'ui/_ui_defs.json',{'ui_defs':['ui/ui_texture_probe.json']})
    materials={'version':'1.0.0'}
    for kind in KINDS:
        material={'vertexShader':'shaders/ui_texture_probe.vertex','fragmentShader':'shaders/ui_texture_probe.fragment',
            '+states':['DisableCulling','DisableDepthTest','DisableDepthWrite','Blending'],
            '-states':['DisableAlphaWrite','EnableAlphaToCoverage'],'blendSrc':'One','blendDst':'Zero',
            'alphaSrc':'One','alphaDst':'Zero','msaaSupport':'Both',
            'samplerStates':[{'samplerIndex':slot,'textureWrap':'Clamp','textureFilter':'Point'} for slot in range(3)]}
        if kind=='bound':
            material['+defines']=['USE_MULTITEXTURE']
        materials['pmanim_ui_texture_'+kind+':entity_static']=material
    write_json(rp/'materials/entity.material',{'materials':materials})
    oracle=base.post_material('ui_texture_oracle.fragment')
    oracle['fragmentShader']='shaders/glsl/ui_texture_oracle.fragment'
    write_json(rp/'materials/postprocess.material',{'ui_texture_oracle':oracle})
    shaders=rp/'shaders/glsl'
    shaders.mkdir(parents=True)
    shutil.copyfile(HERE/'probe.vertex',shaders/'ui_texture_probe.vertex')
    shutil.copyfile(HERE/'probe.fragment',shaders/'ui_texture_probe.fragment')
    shutil.copyfile(HERE/'post_oracle.fragment',shaders/'ui_texture_oracle.fragment')
    for slot,seed in enumerate(STATIC_SEEDS):
        write_row(rp/('textures/ui_texture_probe/static_%d.png'%slot),sequence(seed))
    base.write_pixel(rp/'textures/pmanim_packet/white.png',(255,255,255,255))
    base.write_pixel(rp/'textures/pmanim_packet/transparent.png',(255,255,255,0))
    write_json(output/'.mcdev.json',{'game_executable_path':str(game_exe),'included_mod_dirs':['./'],
        'auto_hot_reload_mods':False,'auto_hot_reload_ui':False,'auto_hot_reload_shaders':False,'auto_hot_reload_materials':False})
    write_json(output/'probe_resources.json',{'kind':'finite_ui_texture_binding_v1','bytes':32,
        'static_seeds':list(STATIC_SEEDS),'static_sequences':[sequence(seed) for seed in STATIC_SEEDS],
        'producer_sequence':'(seed*37+i*73+(i//3)*19)%256',
        'bound_slots':[0,1,2],'default_receiver_bound_slots':[0],
        'default_slots_1_2':'exploratory engine bindings; no render-target alias promised',
        'uniforms':{'EXTRA_ACTOR_UNIFORM1':['mode','slot','query','flip_y'],
            'EXTRA_ACTOR_UNIFORM2':['source_uv_left','source_uv_bottom','source_uv_width','source_uv_height'],
            'EXTRA_ACTOR_UNIFORM3':['ndc_left','ndc_top','ndc_width','ndc_height']},
        'modes':{'0':'CURRENT_COLOR-seeded producer','1':'static local indexed sampler',
            '2':'source-screen-UV indexed sampler','3':'local-UV indexed sampler'},
        'queries':{'0':'direct','1':'(131*i+29)%32','2':'j=(131*i+29)%32; j=(j+3*sample_byte(j)+7)%32'},
        'post_oracle':{'material':'ui_texture_oracle','samplers':[0,1],
            'control':['source_0_previous_1_original','output_0_rgb_1_alpha'],
            'output_screen_roi':[.1,.8,.8,.15],'source_uv_y':.75},
        'runtime_file_writes':False,'private_texture_upload':False,'continuous_update':False})
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--game-exe',required=True)
    args=parser.parse_args()
    print(build(args.output,args.game_exe))
