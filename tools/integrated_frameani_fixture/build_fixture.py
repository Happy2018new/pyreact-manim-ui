"""Add ordinary four-route FrameAni assets without changing materials or shaders."""
import hashlib
import json
from pathlib import Path
import struct
import zlib


HERE = Path(__file__).resolve().parent
ROUTES = {'sequence': (False, 1), 'point_sequence': (True, 1),
          'point_sequence_add': (True, 2), 'sequence_add': (False, 2)}
QUADRANTS = ((240, 32, 48, 255), (32, 224, 64, 192),
             (40, 64, 240, 128), (0, 0, 0, 0))


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def _texture(path):
    def chunk(kind, body):
        return struct.pack('>I', len(body))+kind+body+struct.pack('>I', zlib.crc32(kind+body)&0xffffffff)
    rows = []
    for y in range(16):
        rows.append(b'\x00'+b''.join(bytes(QUADRANTS[(y//8)*2+x//8]) for x in range(16)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB',16,16,8,6,0,0,0))+
                     chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b''))


def install(project, game_exe):
    """Install once in a fresh generated project; existing material bytes stay exact."""
    project, game_exe = Path(project).resolve(), Path(game_exe).resolve()
    resource, package = project/'resource_pack', project/'behavior_pack/stencil_large'
    if not package.is_dir() or not resource.is_dir():
        raise ValueError('An existing generated stencil_large project is required')
    targets = [package/'ordinary_frameani_fixture.py', project/'frameani_fixture_receipt.json']
    targets += [resource/('effects/native_frameani_'+name+'.json') for name in ROUTES]
    if any(path.exists() for path in targets):
        raise ValueError('FrameAni fixture must be installed once without overwriting prior files')
    before = {path.relative_to(resource).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
              for path in resource.rglob('*') if path.is_file() and
              (path.suffix=='.material' or 'shaders' in path.parts)}
    native_path = game_exe.parent/'data/resource_packs/vanilla_netease/materials/sfx.material'
    native = native_path.read_bytes()
    texture = resource/'textures/native_frameani_fixture/quadrants.png'
    _texture(texture)
    _json(texture.with_suffix('.json'), {'frames':[{'filename':'quadrants.png',
        'frame':{'x':0,'y':0,'w':16,'h':16}, 'rotated':False, 'trimmed':False,
        'sourceSize':{'w':16,'h':16}, 'spriteSourceSize':{'x':0,'y':0,'w':16,'h':16},
        'scale':{'x':1.,'y':1.,'z':1.}}],
        'meta':{'image':'quadrants.png','size':{'w':16,'h':16},'scale':'1'}})
    for name, (point, blend) in ROUTES.items():
        _json(resource/('effects/native_frameani_'+name+'.json'), {'frameeffect':{
            'texture':'textures/native_frameani_fixture/quadrants', 'layer':1,
            'scale':[1.,1.,1.], 'shuffle':False, 'fps':1, 'cylinder_enable':False,
            'fade_distance':0., 'depth_test':False, 'delay_in_loop':False, 'delay':0.,
            'sub_layer':0, 'lerp_scale':False, 'tex_repeat_num':[1,1],
            'point_filtering':point, 'first_person_enable':True, 'face_camera':True,
            'rot_speed':[0,0,0], 'frame_color':[], 'loop':True, 'blend_mode':blend}})
    (package/'ordinary_frameani_fixture.py').write_bytes((HERE/'runtime.py').read_bytes())
    for relative, digest in before.items():
        if hashlib.sha256((resource/relative).read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Ordinary fixture changed a material or shader: '+relative)
    files = targets+[texture,texture.with_suffix('.json')]
    files = [path for path in files if path.is_file()]
    receipt = {'schema':'ordinary_native_frameani_fixture_v1', 'routes':{
        name:{'point_filtering':point,'blend_mode':blend,'native_material_family':name,
              'effect':'effects/native_frameani_'+name+'.json'} for name,(point,blend) in ROUTES.items()},
        'texture_quadrants_rgba':[list(value) for value in QUADRANTS],
        'native_sfx_source':str(native_path),'native_sfx_sha256':hashlib.sha256(native).hexdigest(),
        'materials_or_shaders_modified':False,'runtime_file_writes':False,
        'native_quad_unit_size_documented':False,'native_baseline_positive_gate_required':True,
        'material_and_shader_hashes_unchanged':before,
        'hashes':{path.relative_to(project).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in files}}
    _json(project/'frameani_fixture_receipt.json',receipt)
    return receipt
