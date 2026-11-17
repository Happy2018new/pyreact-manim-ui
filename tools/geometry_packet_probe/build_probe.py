"""Build an isolated native block-geometry data probe; never launch Minecraft."""
import argparse
import json
from pathlib import Path
import shutil
import struct
import uuid
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MARKER = '.pmanim_geometry_packet_probe.json'
IDENTIFIER = 'pmanim_geometry_packet:quad'
NAMESPACE = uuid.UUID('994cb915-d73c-4e35-9dbd-fc84a34e7780')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def write_pixel(path, alpha):
    def chunk(kind, value):
        return (struct.pack('>I', len(value))+kind+value+
                struct.pack('>I', zlib.crc32(kind+value)&0xffffffff))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+
                     chunk(b'IHDR', struct.pack('>IIBBBBB',1,1,8,6,0,0,0))+
                     chunk(b'IDAT', zlib.compress(bytes((0,255,255,255,alpha))))+
                     chunk(b'IEND', b''))


def control(kind, size, layer, **extra):
    value = {'type':kind,'size':size,'layer':layer,
             'anchor_from':'top_left','anchor_to':'top_left','offset':[0,0]}
    value.update(extra)
    return value


def write_ui(resource):
    write_json(resource/'ui/geometry_packet_probe.json', {
        'namespace':'pmanim_geometry_packet_probe',
        'main':control('screen',['100%','100%'],1000,controls=[
            {'background':control('image',['100%','100%'],0,
                texture='textures/pmanim_geometry_packet/black',
                color=[17/255.,53/255.,97/255.],keep_ratio=False)},
            {'carrier':control('image',[1,1],10,
                texture='textures/pmanim_geometry_packet/transparent',
                color=[0,0,0],alpha=1,keep_ratio=False)},
            {'canvas':control('custom',['100%','100%'],11,
                renderer='netease_paper_doll_renderer',rotation='none',
                init_rot_x=0,init_rot_y=0,init_rot_z=0,screen_scale=1,
                enable_scissor_test=True)}])})
    write_json(resource/'ui/_ui_defs.json',{'ui_defs':['ui/geometry_packet_probe.json']})


def write_block(resource, behavior):
    write_json(behavior/'netease_blocks/geometry_packet_quad.json',{
        'format_version':'1.10.0','minecraft:block':{
            'description':{'identifier':IDENTIFIER,'register_to_creative_menu':False},
            'components':{'netease:render_layer':{'value':'blend'},
                'netease:no_crop_face_block':{},'minecraft:block_light_absorption':{'value':0}}}})
    write_json(resource/'blocks.json',{'format_version':'1.21.40',IDENTIFIER:{
        'netease_model':IDENTIFIER,'sound':'stone'}})
    write_json(resource/'models/netease_block/geometry_packet_quad.json',{
        'format_version':'1.13.0','netease:block_geometry':{
            'description':{'identifier':IDENTIFIER,'textures':['quartz_block_top'],
                'item_texture':'quartz_block_top','use_ao':False},
            'bones':[{'name':'byte_plane','pivot':[0,0,0],'cubes':[{
                'origin':[-4,0,-4],'size':[8,0,8],
                'uv':{'up':{'uv':[0,0],'uv_size':[16,16]}}}]}]}})
    materials={'version':'1.0.0','pmanim_geometry_packet:netease_block_as_entity_mesh':{
        'vertexShader':'shaders/glsl/geometry_packet.vertex',
        'fragmentShader':'shaders/glsl/geometry_packet.fragment',
        '+defines':['BLEND'],
        '+states':['Blending','DisableCulling','DisableDepthTest','DisableDepthWrite'],
        'blendSrc':'SourceAlpha','blendDst':'OneMinusSrcAlpha'}}
    for name in ('netease_block_as_mesh_blend','netease_block_as_mesh_blend_enable_transparency',
                 'netease_block_as_mesh_blend_far','netease_block_as_mesh_blend_no_culling'):
        materials[name+':pmanim_geometry_packet']={}
    write_json(resource/'materials/terrain.material',{'materials':materials})


def build(output):
    output=Path(output).resolve()
    if output in (ROOT,ROOT/'behavior_pack',ROOT/'resource_pack',HERE):
        raise ValueError('Output must be an isolated generated directory')
    if output.exists() and any(output.iterdir()) and not (output/MARKER).is_file():
        raise ValueError('Nonempty output lacks geometry probe ownership marker')
    if (output/MARKER).is_file():
        marker=json.loads((output/MARKER).read_text(encoding='utf-8'))
        if marker!={'kind':'pmanim_geometry_packet_probe','version':1}:
            raise ValueError('Existing output belongs to a different probe configuration')
    scripts={name:(HERE/name).read_text(encoding='utf-8')
             for name in ('runtime.py','modMain.py')}
    write_json(output/MARKER,{'kind':'pmanim_geometry_packet_probe','version':1})
    behavior,resource=output/'behavior_pack',output/'resource_pack'
    package=behavior/'geometry_packet_probe'
    package.mkdir(parents=True,exist_ok=True)
    (package/'__init__.py').write_text('# -*- coding: utf-8 -*-\n',encoding='utf-8')
    for name,source in scripts.items():
        (package/name).write_text(source,encoding='utf-8')
    for name,module in (('behavior_pack','data'),('resource_pack','resources')):
        write_json(output/name/'manifest.json',{'format_version':2,'header':{
            'name':'PManim Geometry Packet Probe '+module,
            'description':'Isolated runtime byte -> block POSITION -> shader experiment',
            'uuid':str(uuid.uuid5(NAMESPACE,name)),'version':[0,0,1],
            'min_engine_version':[1,18,0]},'modules':[{'type':module,
                'uuid':str(uuid.uuid5(NAMESPACE,name+'/module')),'version':[0,0,1]}]})
    write_ui(resource)
    write_block(resource,behavior)
    for name in ('geometry_packet.vertex','geometry_packet.fragment'):
        target=resource/'shaders/glsl'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(HERE/name,target)
    write_pixel(resource/'textures/pmanim_geometry_packet/transparent.png',0)
    write_pixel(resource/'textures/pmanim_geometry_packet/black.png',255)
    write_json(output/'probe_resources.json',{
        'version':1,'kind':'geometry_packet_probe_v1','slots':[],
        'ui_namespace':'pmanim_geometry_packet_probe',
        'ui_definition':'pmanim_geometry_packet_probe.main',
        'runtime':{'package':'geometry_packet_probe','entrypoint':'geometry_packet_probe.modMain',
                   'system_namespace':'pmanim_geometry_packet_probe','system_name':'probe'},
        'encoding':{'byte_source':'POSITION.y','record_id':'x*stride+z',
                    'palette_volume':'(stride,stride,256)','local_quad_span':[-.25,.25],
                    'query_source':'CURRENT_COLOR','maximum_experimental_bytes':1048576},
        'production_resources_modified':False})
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(build(args.output))
