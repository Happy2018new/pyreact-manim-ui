"""Offline build with a hashed snapshot of the stable32-alpha codec shaders."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import uuid

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
BASE=HERE.parent/'geometry_atlas_probe'
CODEC=HERE.parent/'scene_codec_probe'
NAMESPACE=uuid.UUID('c3bb5664-a458-4e89-b2ac-2c9f979e0c4b')


def process(name):
    return {'name':'scene_large_'+name,'enable':False,'paras':[
        {'name':'codec','value':[2.,255.,0.,0.],'range':[0.,1048576.]},
        {'name':'roi','value':[8.,128.,704.,993.],'range':[0.,1048576.]},
        {'name':'physical','value':[1080.,1440.,1.,1.],'range':[0.,1048576.]}],
        'pass_array':[{'render_target':{'width':1.,'height':1.},
            'material':'scene_large_'+name,'depth_enable':False}]}


def native_effects_off(config):
    isolated=copy.deepcopy(config)
    names=[item['name'] for item in isolated['process_array']]
    if len(names)!=len(set(names)) or set(names)!=set(isolated['render_order']):
        raise ValueError('Native post-process order and declarations disagree')
    for item in isolated['process_array']:
        item['enable']=False
    return isolated


def build(output,native_data_root=None,logical_bytes=None,carrier_decode=True,native_effects_off_data_root=None):
    output=Path(output).resolve()
    if output.exists() or (ROOT/'.runtime').resolve() not in output.parents:
        raise ValueError('Choose a fresh isolated output inside this repository.runtime')
    if logical_bytes is not None and logical_bytes not in (262144,524288):
        raise ValueError('An optional fixed contract must be256or512KiB')
    if native_data_root is not None and logical_bytes is None:
        raise ValueError('Native compatibility overlay requires one fixed capacity/ROI per project')
    if native_data_root is not None and native_effects_off_data_root is not None:
        raise ValueError('Choose compatibility overlay or native-effects-off isolation')
    paths={'runtime.py':HERE/'runtime.py','large_layout.py':HERE/'layout.py',
        'scene_codec.py':CODEC/'codec.py','scatter.vertex':BASE/'scatter.vertex',
        'scatter.fragment':HERE/'scatter.fragment',
        'raw.fragment':CODEC/'copy.fragment',
        'encode.fragment':CODEC/'shaders/alpha_block_encode.fragment',
        'decode.fragment':CODEC/'shaders/alpha_block_decode.fragment',
        'consumer.fragment':HERE/'consumer.fragment','integrity.fragment':HERE/'integrity.fragment'}
    if native_data_root is not None:
        paths['compat_builder.py']=HERE.parent/'scene_codec_compat_probe/build_overlay.py'
    if native_effects_off_data_root is not None:
        paths['native_post_process.json']=Path(native_effects_off_data_root)/'resource_packs/vanilla_netease/graphics_settings/post_process.json'
    sources={name:path.read_bytes() for name,path in paths.items()}
    if b'EXTRA_ACTOR_UNIFORM' in sources['scatter.fragment']:
        raise ValueError('Large fixed-k2 fragment must not read actor controls used by the paged vertex shader')
    manifest={name:{'path':str(paths[name]),'sha256':hashlib.sha256(content).hexdigest(),
        'bytes':len(content)} for name,content in sources.items()}
    bundle_hash=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode('utf-8')).hexdigest()
    spec=importlib.util.spec_from_file_location('large_codec_asset_base',BASE/'build_probe.py')
    base=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    base.build(output)
    package=output/'behavior_pack/geometry_atlas_probe'
    for name in ('runtime.py','large_layout.py','scene_codec.py'):
        (package/name).write_bytes(sources[name])
    processes=[process(name) for name in ('raw','encode','decode','consumer','integrity')]
    (package/'large_config.py').write_text('# -*- coding: utf-8 -*-\nPROCESSES='+repr(processes)+
        '\nSOURCE_BUNDLE_SHA256='+repr(bundle_hash)+'\nFIXED_LOGICAL_BYTES='+repr(logical_bytes)+
        '\nCOMPAT_OVERLAY='+repr(native_data_root is not None)+'\n',encoding='utf-8')
    mod=(BASE/'modMain.py').read_text(encoding='utf-8').replace('pmanim_geometry_atlas_probe','pmanim_scene_codec_large')
    (package/'modMain.py').write_text(mod,encoding='utf-8')
    resource=output/'resource_pack'
    if native_effects_off_data_root is not None:
        original=json.loads(sources['native_post_process.json'].decode('utf-8-sig'))
        isolated=native_effects_off(original)
        base.write_json(resource/'graphics_settings/post_process.json',isolated)
        base.write_json(output/'native_effects_off.manifest.json',{
            'native_source':manifest['native_post_process.json'],
            'only_changed_fields':['process_array[*].enable'],
            'render_order_unchanged':isolated['render_order']==original['render_order'],
            'native_names':isolated['render_order'],
            'generated_sha256':hashlib.sha256((resource/'graphics_settings/post_process.json').read_bytes()).hexdigest(),
            'native_effects_compatibility_claimed':False})
    shaders=resource/'shaders/glsl'
    scatter_source=sources['scatter.vertex'].decode('utf-8')
    insertion='vec2 grid = vec2(mod(record, columns), floor(record / columns));'
    if scatter_source.count(insertion)!=1:
        raise ValueError('Source scatter contract changed; inspect the global-base insertion before building')
    scatter=scatter_source.replace(insertion,
        'record += EXTRA_ACTOR_UNIFORM4.w; // global record base after local validation\n'
        '    vec2 grid = vec2(mod(record, columns), floor(record / columns));')
    (shaders/'scene_large_scatter.vertex').write_text(scatter,encoding='utf-8')
    (shaders/'scene_large_scatter.fragment').write_bytes(sources['scatter.fragment'])
    terrain=json.loads((resource/'materials/terrain.material').read_text(encoding='utf-8'))
    material=terrain['materials']['pmanim_geometry_atlas:netease_block_as_entity_mesh']
    material.update(vertexShader='shaders/glsl/scene_large_scatter.vertex',
        fragmentShader='shaders/glsl/scene_large_scatter.fragment',blendSrc='SourceAlpha',
        blendDst='OneMinusSrcAlpha',alphaSrc='Zero',alphaDst='One')
    material['-states']=['EnableAlphaToCoverage','DisableRGBWrite']
    material['+states']=['Blending','DisableCulling','DisableDepthTest','DisableDepthWrite','DisableAlphaWrite']
    base.write_json(resource/'materials/terrain.material',terrain)
    materials={}
    for name in ('raw','encode','decode','consumer','integrity'):
        filename='scene_large_'+name+'.fragment'
        (shaders/filename).write_bytes(sources[name+'.fragment'])
        materials['scene_large_'+name]={'vertexShader':'shaders/uv_fullscreen.vertex',
            'fragmentShader':'shaders/glsl/'+filename,
            'vertexFields':[{'field':'Position'},{'field':'UV0'}],
            'samplerStates':[{'samplerIndex':slot,'textureWrap':'Clamp','textureFilter':'Point'} for slot in (0,1,3,4,5)],
            'states':['DisableDepthTest','DisableDepthWrite'],
            '-states':['DisableAlphaWrite','EnableAlphaToCoverage','Blending'],'msaaSupport':'Both'}
    base.write_json(resource/'materials/postprocess.material',materials)
    for pack,kind in (('behavior_pack','data'),('resource_pack','resources')):
        base.write_json(output/pack/'manifest.json',{'format_version':2,'header':{
            'name':'Scene codec large '+kind,'description':'Paged in-memory RGB and32-alpha blocks',
            'uuid':str(uuid.uuid5(NAMESPACE,pack)),'version':[0,0,1],'min_engine_version':[1,18,0]},
            'modules':[{'type':kind,'uuid':str(uuid.uuid5(NAMESPACE,pack+'/module')),'version':[0,0,1]}]})
    config=json.loads((ROOT/'.mcdev.json').read_text(encoding='utf-8'))
    config['included_mod_dirs']=['./']
    base.write_json(output/'.mcdev.json',config)
    base.write_json(output/'source_manifest.json',{'source_bundle_sha256':bundle_hash,'sources':manifest})
    base.write_json(output/'probe_resources.json',{'kind':'scene_codec_large_probe_v1',
        'runtime':{'system_namespace':'pmanim_scene_codec_large','system_name':'probe'},
        'screen_size':[1080,1440],'rgb_bits':2,'block_bytes':24,'block_pixels':32,
        'page_record_budget':65536,'source_bundle_sha256':bundle_hash,'fixed_logical_bytes':logical_bytes,
        'native_compat_overlay_installed':native_data_root is not None,
        'native_effects_off_config_installed':native_effects_off_data_root is not None,
        'game_runtime_file_writes':False,'source_probe_modified':False})
    if native_data_root is not None:
        layout_spec=importlib.util.spec_from_file_location('scene_large_build_layout',HERE/'layout.py')
        layout=importlib.util.module_from_spec(layout_spec)
        layout_spec.loader.exec_module(layout)
        overlay_path=output.parent/(output.name+'-native-overlay')
        if overlay_path.exists():
            raise ValueError('Preserve existing compatibility overlay output; choose a fresh project name')
        overlay_spec=importlib.util.spec_from_file_location('scene_large_compat_overlay',paths['compat_builder.py'])
        overlay=importlib.util.module_from_spec(overlay_spec)
        overlay_spec.loader.exec_module(overlay)
        overlay.build_overlay(overlay_path,native_data_root,[1080,1440],layout.plan_payload(logical_bytes)['roi'],
            rgb_bits=2,carrier_decode=bool(carrier_decode),renderer_branch='legacy')
        overlay.install_overlay(output,overlay_path)
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--native-data-root',type=Path)
    parser.add_argument('--native-effects-off-data-root',type=Path)
    parser.add_argument('--logical-bytes',type=int,choices=(262144,524288))
    parser.add_argument('--identity-native-overlay',action='store_true')
    args=parser.parse_args()
    print(build(args.output,args.native_data_root,args.logical_bytes,not args.identity_native_overlay,
        args.native_effects_off_data_root))
