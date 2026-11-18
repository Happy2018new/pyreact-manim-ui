"""Build an isolated finite UI alpha writer/readout experiment; never launch."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAMESPACE = uuid.UUID('d2189f7e-c4c4-4500-9a44-70a9701ee8e9')
KINDS = ('rgb', 'alpha', 'reader')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')


def build(output, game_exe, reader_factor='SourceAlpha'):
    output = Path(output).resolve()
    if output.exists() or (ROOT/'.runtime').resolve() not in output.parents:
        raise ValueError('Choose a fresh isolated directory under repository .runtime')
    if reader_factor!='SourceAlpha':
        raise ValueError('Only the supported SourceAlpha arithmetic control is permitted; DestAlpha asserted in native OGL')
    spec = importlib.util.spec_from_file_location('ui_alpha_base', HERE.parent/'runtime_packet_probe/build_probe.py')
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    output.mkdir(parents=True)
    bp, rp = output/'behavior_pack', output/'resource_pack'
    for name, typ in (('behavior_pack','data'),('resource_pack','resources')):
        write_json(output/name/'manifest.json', {'format_version':2,'header':{
            'name':'Finite UI alpha probe '+typ,'description':'RGB mask and destination alpha diagnostic',
            'uuid':str(uuid.uuid5(NAMESPACE,name)),'version':[0,0,1],'min_engine_version':[1,18,0]},
            'modules':[{'type':typ,'uuid':str(uuid.uuid5(NAMESPACE,name+'/module')),'version':[0,0,1]}]})
    package = bp/'ui_alpha_probe'
    package.mkdir(parents=True)
    (package/'__init__.py').write_text('# -*- coding: utf-8 -*-\n',encoding='utf-8')
    for name in ('runtime.py','modMain.py'):
        shutil.copyfile(HERE/name,package/name)
    base.write_entities(rp,bp,3)
    for index, kind in enumerate(KINDS):
        path=rp/('entity/pmanim_packet_slot_%03d.entity.json'%index)
        entity=json.loads(path.read_text(encoding='utf-8'))
        entity['minecraft:client_entity']['description']['materials']['default']='pmanim_ui_alpha_'+kind
        write_json(path,entity)
    controls=[{'background':base.control('image',('100%','100%'),texture='textures/pmanim_packet/white',
                color=[17/255.,53/255.,97/255.],keep_ratio=False)}]
    for index,kind in enumerate(KINDS):
        controls.append({kind:base.control('panel',(200,160),layer=10+index*10,visible=False,controls=[
            {'carrier':base.control('image',(1,1),layer=0,texture='textures/pmanim_packet/transparent',
                color=[42/255.,0.25,0.75],alpha=1.,keep_ratio=False)},
            {'canvas':base.control('custom',(200,160),layer=1,renderer='netease_paper_doll_renderer',
                rotation='none',init_rot_x=0.,init_rot_y=0.,init_rot_z=0.,screen_scale=1.,enable_scissor_test=True)}])})
    write_json(rp/'ui/ui_alpha_probe.json',{'namespace':'pmanim_ui_alpha_probe',
        'main':base.control('screen',('100%','100%'),layer=1000,controls=controls)})
    write_json(rp/'ui/_ui_defs.json',{'ui_defs':['ui/ui_alpha_probe.json']})
    materials={'version':'1.0.0'}
    for kind in KINDS:
        states=['DisableCulling','DisableDepthTest','DisableDepthWrite','Blending']
        if kind=='alpha': states.append('DisableRGBWrite')
        materials['pmanim_ui_alpha_'+kind+':entity_static']={
            'vertexShader':'shaders/ui_alpha.vertex','fragmentShader':'shaders/ui_alpha_'+kind+'.fragment',
            '+states':states,'blendSrc':reader_factor if kind=='reader' else 'One','blendDst':'Zero',
            '-states':['DisableAlphaWrite','EnableAlphaToCoverage'],
            'msaaSupport':'Both',
            'alphaSrc':'Zero' if kind=='reader' else 'One','alphaDst':'One' if kind=='reader' else 'Zero'}
    write_json(rp/'materials/entity.material',{'materials':materials})
    write_json(rp/'materials/postprocess.material',{
        'ui_alpha_'+kind:base.post_material('ui_alpha_post_'+kind+'.fragment') for kind in ('copy','t0','t1')})
    shaders=rp/'shaders/glsl'
    shaders.mkdir(parents=True)
    shutil.copyfile(HERE.parent/'runtime_packet_probe/packet_probe.vertex',shaders/'ui_alpha.vertex')
    for name in ('rgb','alpha','reader'):
        shutil.copyfile(HERE/('ui_alpha_'+name+'.fragment'),shaders/('ui_alpha_'+name+'.fragment'))
    for name in ('copy','t0','t1'):
        shutil.copyfile(HERE/('ui_alpha_post_'+name+'.fragment'),shaders/('ui_alpha_post_'+name+'.fragment'))
    base.write_pixel(rp/'textures/pmanim_packet/white.png',(255,255,255,255))
    base.write_pixel(rp/'textures/pmanim_packet/transparent.png',(255,255,255,0))
    write_json(output/'.mcdev.json',{'game_executable_path':str(Path(game_exe).resolve()),'included_mod_dirs':['./'],
        'auto_hot_reload_mods':False,'auto_hot_reload_ui':False,'auto_hot_reload_shaders':False,'auto_hot_reload_materials':False})
    write_json(output/'probe_resources.json',{'kind':'finite_ui_alpha_v1','reader_factor':reader_factor,
        'runtime_file_writes':False,'private_texture_upload':False,'byte_values':[0,42,201,255],
        'reader':'SourceAlpha arithmetic control only; DestAlpha native assertion archived separately'})
    return output


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--game-exe',required=True)
    p.add_argument('--reader-factor',default='SourceAlpha',choices=('SourceAlpha',))
    a=p.parse_args()
    print(build(a.output,a.game_exe,a.reader_factor))
