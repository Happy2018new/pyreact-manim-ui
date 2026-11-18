"""Fresh offline build of bounded2bit64B stencil transport, not a launcher."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from build_probe import HERE,ROOT,build,stencil,module


def make(output,game_exe):
    output=build(output,game_exe)
    bp,rp=output/'behavior_pack',output/'resource_pack'
    (bp/'weather_effect_stencil_probe/modMain.py').unlink()
    package=bp/'stencil_packed'
    package.mkdir()
    (package/'__init__.py').write_text('',encoding='utf-8')
    (package/'runtime.py').write_bytes((HERE/'packed_runtime.py').read_bytes())
    (package/'modMain.py').write_bytes((HERE/'packed_modMain.py').read_bytes())
    geo=module('packed_geo_builder',HERE.parent/'geometry_atlas_probe/build_probe.py')
    blocks=json.loads((rp/'blocks.json').read_text(encoding='utf-8'))
    for kind,layer in (('clear','opaque'),('bit64','alpha'),('bit128','blend')):
        for template in range(16):
            identifier='pmanim_stencil_packed:%s_%02d'%(kind,template)
            filename='packed_%s_%02d'%(kind,template)
            geo.write_atlas_block_template(rp,bp,identifier,filename,template+.5)
            path=bp/('netease_blocks/'+filename+'.json')
            block=json.loads(path.read_text(encoding='utf-8'))
            block['minecraft:block']['components']['netease:render_layer']['value']=layer
            geo.write_json(path,block)
            blocks[identifier]={'netease_model':identifier,'sound':'stone'}
    geo.write_json(rp/'blocks.json',blocks)
    terrain=json.loads((rp/'materials/terrain.material').read_text(encoding='utf-8'))
    materials=terrain['materials']
    writer=copy.deepcopy(materials['pmanim_geometry_atlas:netease_block_as_entity_mesh'])
    bit64=copy.deepcopy(writer)
    bit64['fragmentShader']='shaders/glsl/stencil_packed_writer64.fragment'
    bit64.update(stencil('Always',64,True),stencilReadMask=192,stencilWriteMask=64)
    for name in ('netease_block_as_mesh_alpha','netease_block_as_mesh_alpha_single_side'):
        materials[name+':pmanim_geometry_atlas']=copy.deepcopy(bit64)
    clear=copy.deepcopy(writer)
    clear['fragmentShader']='shaders/glsl/stencil_packed_clear.fragment'
    clear['+states']=['Blending','DisableCulling','DisableDepthTest','DisableDepthWrite','DisableAlphaWrite','StencilWrite','EnableStencilTest']
    clear['-states']=['EnableAlphaToCoverage','DisableColorWrite','DisableRGBWrite']
    clear['blendSrc'],clear['blendDst']='SourceAlpha','OneMinusSrcAlpha'
    clear.update(stencil('Always',0,True),stencilReadMask=192,stencilWriteMask=192)
    materials['netease_block_as_mesh_opaque:pmanim_geometry_atlas']=clear
    geo.write_json(rp/'materials/terrain.material',terrain)
    sfx=json.loads((rp/'materials/sfx.material').read_text(encoding='utf-8'))
    seq=sfx['materials']['sequence:billboard_base']
    seq['fragmentShader']='shaders/glsl/stencil_packed_effect.fragment'
    seq['blendSrc'],seq['blendDst']='SourceAlpha','OneMinusSrcAlpha'
    for name,mask in (('point_sequence:sequence',64),('point_sequence_add:point_sequence',128)):
        material=sfx['materials'][name]
        material['fragmentShader']='shaders/glsl/stencil_packed_effect.fragment'
        material['blendSrc'],material['blendDst']='One','One'
        material.update(stencil('Equal',mask,False),stencilReadMask=mask)
    geo.write_json(rp/'materials/sfx.material',sfx)
    old=json.loads((rp/'effects/stencil_background.json').read_text(encoding='utf-8'))
    for kind,point,blend in (('base',False,1),('bit64',True,1),('bit128',True,2)):
        config=copy.deepcopy(old)
        config['frameeffect'].update(point_filtering=point,blend_mode=blend)
        geo.write_json(rp/('effects/stencil_packed_'+kind+'.json'),config)
    shaders=rp/'shaders/glsl'
    for source,target in (('packed_writer64.fragment','stencil_packed_writer64.fragment'),('packed_clear.fragment','stencil_packed_clear.fragment'),
                          ('packed_effect.fragment','stencil_packed_effect.fragment'),('packed_copy.fragment','stencil_packed_copy.fragment'),('packed_post.fragment','stencil_packed_post.fragment')):
        (shaders/target).write_bytes((HERE/source).read_bytes())
    post={}
    for name,fragment in (('copy','copy'),('oracle','post')):
        post['stencil_packed_'+name]={'vertexShader':'shaders/uv_fullscreen.vertex','fragmentShader':'shaders/glsl/stencil_packed_'+fragment+'.fragment',
            'vertexFields':[{'field':'Position'},{'field':'UV0'}],
            'samplerStates':[{'samplerIndex':slot,'textureWrap':'Clamp','textureFilter':'Point'} for slot in (0,1)],
            'states':['DisableDepthTest','DisableDepthWrite'],'-states':['DisableAlphaWrite','EnableAlphaToCoverage','Blending'],'msaaSupport':'Both'}
    geo.write_json(rp/'materials/postprocess.material',post)
    receipt=json.loads((output/'probe_resources.json').read_text(encoding='utf-8'))
    receipt.update(kind='weather_stencil_packed64_v1',runtime_namespace='pmanim_stencil_packed',logical_bytes=64,
        source_bits_per_record=2,record_count=256,arbitrary_host_bytes=True,performance_claimed=False,
        stencil_mask=192,known_background='native opaque geometry with blend coefficients1or0; original alpha preserved',
        source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.iterdir() if p.is_file()})
    geo.write_json(output/'probe_resources.json',receipt)
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--game-exe',required=True)
    args=parser.parse_args()
    print(make(args.output,args.game_exe))
