"""Offline native JSON UI clip fixture; never launch or connect to Minecraft."""
import hashlib
import json
from pathlib import Path
import struct
import zlib

HERE=Path(__file__).resolve().parent
NAMESPACE='pmanim_integrated_ui_clip'
CARD=(96,64)
BLUE=(0,0,255)
YELLOW=(255,255,0)


def intersects(a,b):
    return a[0]<b[0]+b[2] and b[0]<a[0]+a[2] and a[1]<b[1]+b[3] and b[1]<a[1]+a[3]


def contained(a,b,inset=0):
    return a[0]>=b[0]+inset and a[1]>=b[1]+inset and a[0]+a[2]<=b[0]+b[2]-inset and a[1]+a[3]<=b[1]+b[3]-inset


def png(path,rgb):
    def chunk(kind,value):
        return struct.pack('>I',len(value))+kind+value+struct.pack('>I',zlib.crc32(kind+value)&0xffffffff)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,6,0,0,0))+
        chunk(b'IDAT',zlib.compress(bytes([0]+list(rgb)+[255])))+chunk(b'IEND',b''))


def control(kind,size,offset=(0,0),**extra):
    result={'type':kind,'size':list(size),'offset':list(offset),'anchor_from':'top_left','anchor_to':'top_left'}
    result.update(extra)
    return result


def image(texture,size,offset=(0,0),**extra):
    return control('image',size,offset,texture=texture,color=[1.,1.,1.],alpha=1.,keep_ratio=False,
        bilinear=False,nineslice_size=0,**extra)


def plan(source_roi,diagnostic_rects,physical):
    width,height=physical
    if len(source_roi)!=4 or not contained(source_roi,(0,0,width,height)):
        raise ValueError('Source ROI must be a finite in-viewport rectangle')
    blocked=[list(rect) for rect in diagnostic_rects]+[[0,0,width,128],[0,height-56,width,56]]
    cases=[]
    patch_specs=(('child_inside',[28,20,40,24],YELLOW),
        ('left_outside',[12,24,8,16],None),('right_outside',[76,24,8,16],None),
        ('top_outside',[32,8,32,4],None),('bottom_outside',[32,52,32,4],None),
        ('backdrop_positive',[2,2,4,4],BLUE))
    for location,clipped in (('source_inside',True),('source_inside',False),('source_outside',True),('source_outside',False)):
        chosen=None
        for y in range(128,height-CARD[1]-55,8):
            for x in range(8,width-CARD[0]-7,8):
                rect=[x,y,CARD[0],CARD[1]]
                membership=contained(rect,source_roi,8) if location=='source_inside' else not intersects(rect,source_roi)
                if not membership or any(intersects(rect,other) for other in blocked):
                    continue
                chosen=rect
                break
            if chosen is not None:
                break
        if chosen is None:
            raise ValueError('No safe '+location+' 96x64 card fits without covering excluded output')
        patches=[]
        for name,rect,color in patch_specs:
            wanted=color if color is not None else (BLUE if clipped else YELLOW)
            patches.append({'name':name,'rect':[chosen[0]+rect[0],chosen[1]+rect[1],rect[2],rect[3]],'rgb':list(wanted)})
        identifier=location+('_clipped' if clipped else '_unclipped')
        cases.append({'id':identifier,'source_membership':location,'clipped':clipped,'rect':chosen,
            'clip_rect_local':[24,16,48,32],'child_rect_relative':[-16,-12,80,56],
            'child_rect_without_clip_local':[8,4,80,56],'patches':patches})
        blocked.append([chosen[0]-8,chosen[1]-8,chosen[2]+16,chosen[3]+16])
    return cases


def install(resource_pack,behavior_package,source_roi,diagnostic_rects,physical=(720,1080),package_name='stencil_large'):
    """Append independent resources and copy UI runtime into an existing package.

    diagnostic_rects are exclusion rectangles in the UI-visible compatibility
    frame, e.g. the bar shape; diagnostic captures themselves keep this UI off.
    No original HUD definition is patched. Existing _ui_defs entries are retained.
    """
    resource_pack,behavior_package=Path(resource_pack),Path(behavior_package)
    physical=[int(value) for value in physical]
    cases=plan(list(source_roi),list(diagnostic_rects),physical)
    receipt_path=resource_pack.parent/'ui_clip_fixture_receipt.json'
    runtime_path=behavior_package/'ui_clip_fixture.py'
    config_path=behavior_package/'ui_clip_fixture_config.py'
    ui_path=resource_pack/'ui/integrated_ui_clip_fixture.json'
    if any(path.exists() for path in (receipt_path,runtime_path,config_path,ui_path)):
        raise ValueError('Preserve prior fixture files; install once in a fresh build')
    config={'schema':'native_json_ui_clip_fixture_v1','namespace':NAMESPACE,'key':'fixture',
        'class_path':package_name+'.ui_clip_fixture.NativeClipScreen','screen_def':NAMESPACE+'.main',
        'physical':physical,'source_roi':list(source_roi),'diagnostic_exclusions':list(diagnostic_rects),
        'cases':cases,'all_ui_off_for_data_diagnostics':True,
        'native_json_ui_only':True,'custom_shaders':False,'runtime_file_writes':False}
    controls=[]
    for case in cases:
        clip=control('panel',(48,32),(24,16),layer=1,clips_children=case['clipped'],allow_clipping=True,
            clip_offset=[0,0],controls=[{'child':image('textures/integrated_ui_clip/yellow',(80,56),(-16,-12),layer=1)}])
        card=control('panel',CARD,case['rect'][:2],layer=10,clips_children=False,controls=[
            {'backdrop':image('textures/integrated_ui_clip/blue',CARD,layer=0)}, {'clip':clip}])
        controls.append({case['id']:card})
    ui={'namespace':NAMESPACE,'main':control('screen',('100%','100%'),layer=1000,controls=[
        {'fixture':control('panel',('100%','100%'),visible=False,clips_children=False,controls=controls)}])}
    ui_path.parent.mkdir(parents=True,exist_ok=True)
    ui_path.write_text(json.dumps(ui,indent=2)+'\n',encoding='utf-8')
    defs_path=resource_pack/'ui/_ui_defs.json'
    defs=json.loads(defs_path.read_text(encoding='utf-8')) if defs_path.exists() else {'ui_defs':[]}
    definition='ui/integrated_ui_clip_fixture.json'
    if definition not in defs.setdefault('ui_defs',[]):
        defs['ui_defs'].append(definition)
    defs_path.write_text(json.dumps(defs,indent=2)+'\n',encoding='utf-8')
    png(resource_pack/'textures/integrated_ui_clip/blue.png',BLUE)
    png(resource_pack/'textures/integrated_ui_clip/yellow.png',YELLOW)
    runtime_path.write_bytes((HERE/'runtime.py').read_bytes())
    config_path.write_text('# -*- coding: utf-8 -*-\nCONFIG = '+repr(config)+'\n',encoding='utf-8')
    config['oracle_compared_pixels']=sum(patch['rect'][2]*patch['rect'][3] for case in cases for patch in case['patches'])
    config['file_sha256']={str(path.relative_to(resource_pack.parent)):hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (runtime_path,config_path,ui_path,resource_pack/'textures/integrated_ui_clip/blue.png',resource_pack/'textures/integrated_ui_clip/yellow.png')}
    receipt_path.write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
    return config
