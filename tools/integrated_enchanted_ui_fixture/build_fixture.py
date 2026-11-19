"""Offline native inventory_item_renderer fixture; no game operations."""
import hashlib
import json
from pathlib import Path
import struct
import zlib

HERE=Path(__file__).resolve().parent
NAMESPACE='pmanim_native_enchanted_fixture'
PHYSICAL=(720,1080)
SOURCE=(8,128,512,512)
BACKDROP=(0,0,0)


def _write_pixel(path):
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,6,0,0,0))+
        chunk(b'IDAT',zlib.compress(bytes((0,0,0,0,255))))+chunk(b'IEND',b''))


def _control(kind,size,offset=(0,0),**extra):
    result={'type':kind,'size':list(size),'offset':list(offset),'anchor_from':'top_left','anchor_to':'top_left'}
    result.update(extra)
    return result


def install(project):
    project=Path(project)
    resource,package=project/'resource_pack',project/'behavior_pack/stencil_large'
    targets=[project/'enchanted_ui_fixture_receipt.json',package/'enchanted_ui_fixture.py',
        package/'enchanted_ui_config.py',resource/'ui/native_enchanted_fixture.json']
    if any(path.exists() for path in targets):
        raise ValueError('Install enchanted fixture once in a fresh project')
    if not package.is_dir():
        raise ValueError('Expected generated behavior_pack/stencil_large')
    slots=[]
    for location,x,ys in (('source_inside',32,(160,264,368)),('source_outside',536,(160,264,368))):
        for role,y in zip(('normal','enchanted','empty'),ys):
            slots.append({'id':location+'_'+role,'role':role,'source_membership':location,
                'rect':[x,y,88,88],'renderer_local':[8,8,72,72],
                'renderer_rect':[x+8,y+8,72,72],'border_patch':[x+2,y+2,4,4],
                'item':'minecraft:diamond_sword','aux':0,'default_enchanted':role=='enchanted',
                'item_visible':role!='empty'})
    config={'schema':'native_inventory_item_glint_fixture_v1','namespace':NAMESPACE,'key':'fixture',
        'class_path':'stencil_large.enchanted_ui_fixture.NativeItemScreen','screen_def':NAMESPACE+'.main',
        'physical':list(PHYSICAL),'source_roi':list(SOURCE),'slots':slots,'backdrop_rgb':list(BACKDROP),
        'route':'custom JSON UI with unmodified native inventory_item_renderer',
        'stock_inventory_screen':False,'runtime_file_writes':False,'custom_materials':False,
        'modes':['off','normal_all','mixed','enchanted_all'],'temporal_observations_required':True,
        'data_diagnostic_y':650,'visible_slot_rectangles_end_y':456}
    cards=[]
    for slot in slots:
        cards.append({slot['id']:_control('panel',(88,88),slot['rect'][:2],layer=2,controls=[
            {'background':_control('image',(88,88),texture='textures/native_enchanted_fixture/black',
                color=[1.,1.,1.],alpha=1.,bilinear=False,keep_ratio=False,nineslice_size=0,layer=0)},
            {'item':_control('custom',(72,72),(8,8),renderer='inventory_item_renderer',layer=1,
                visible=slot['item_visible'])}])})
    ui={'namespace':NAMESPACE,'main':_control('screen',('100%','100%'),layer=1000,controls=[
        {'fixture':_control('panel',('100%','100%'),visible=False,controls=cards)}])}
    targets[3].parent.mkdir(parents=True,exist_ok=True)
    targets[3].write_text(json.dumps(ui,indent=2)+'\n',encoding='utf-8')
    defs_path=resource/'ui/_ui_defs.json'
    defs=json.loads(defs_path.read_text(encoding='utf-8')) if defs_path.exists() else {'ui_defs':[]}
    definition='ui/native_enchanted_fixture.json'
    if definition not in defs.setdefault('ui_defs',[]): defs['ui_defs'].append(definition)
    defs_path.write_text(json.dumps(defs,indent=2)+'\n',encoding='utf-8')
    _write_pixel(resource/'textures/native_enchanted_fixture/black.png')
    targets[1].write_bytes((HERE/'runtime.py').read_bytes())
    targets[2].write_text('# -*- coding: utf-8 -*-\nCONFIG = '+repr(config)+'\n',encoding='utf-8')
    config['generated_sha256']={str(path.relative_to(project)):hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (targets[1],targets[2],targets[3],resource/'textures/native_enchanted_fixture/black.png')}
    targets[0].write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
    return config
