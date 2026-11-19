"""Build explicit benign/conflicting addons and read-only pack order receipts."""
import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import struct
import uuid
import zlib


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAMESPACE = uuid.UUID('dfb1ca59-720d-4c99-a58b-e2a977d681f8')
PACKAGE = 'pmanim_pack_order_fixture'
UI_NAMESPACE = 'pmanim_pack_order_canary'
TEXTURE = 'textures/pmanim_pack_order_fixture/canary'
VERSION = [1, 0, 1]
RECEIPT = 'pack_order_fixture.json'
COLORS = ((239, 43, 67), (23, 211, 101), (37, 83, 241), (251, 197, 29))
VARIANTS = ('benign', 'stock_sfx_conflict')


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')


def _png(path, color):
    def chunk(kind, data):
        return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data)&0xffffffff)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))+
                     chunk(b'IDAT', zlib.compress(bytes([0]+list(color)+[255])))+chunk(b'IEND', b''))


def _control(kind, size, offset=(0, 0), **extra):
    value = {'type': kind, 'size': list(size), 'offset': list(offset),
             'anchor_from': 'top_left', 'anchor_to': 'top_left'}
    value.update(extra)
    return value


def _read_fixture(value):
    if isinstance(value, dict):
        return value
    path = Path(value)
    return json.loads((path/RECEIPT if path.is_dir() else path).read_text(encoding='utf-8-sig'))


def install(output, variant='benign', game_exe=None):
    """Create a fresh passive addon under .runtime; return paths, UUIDs and hashes.

    A minimal ModSDK entry makes the ScreenNode module discoverable and imports
    it only on the client. It creates no systems, events, UI or effects. The
    explicit stock_sfx_conflict variant copies installed sfx.material bytes.
    """
    if variant not in VARIANTS:
        raise ValueError('Choose benign or stock_sfx_conflict')
    output = Path(output).resolve()
    if output.exists() or (ROOT/'.runtime').resolve() not in output.parents:
        raise ValueError('Choose a fresh fixture output under repository .runtime')
    runtime = (HERE/'runtime.py').read_bytes()
    native_path, native_sfx = None, None
    if variant == 'stock_sfx_conflict':
        if game_exe is None or not Path(game_exe).resolve().is_file():
            raise ValueError('Conflict variant requires the installed game executable')
        native_path = Path(game_exe).resolve().parent/'data/resource_packs/vanilla_netease/materials/sfx.material'
        native_sfx = native_path.read_bytes()
        materials = json.loads(native_sfx.decode('utf-8-sig'))['materials']
        required = ('sequence:billboard_base', 'point_sequence:sequence',
                    'point_sequence_add:point_sequence', 'sequence_add:sequence')
        if any(name not in materials for name in required):
            raise ValueError('Installed sfx.material does not contain the four expected native routes')
    output.mkdir(parents=True)
    ids = {}
    for folder, kind in (('behavior_pack', 'data'), ('resource_pack', 'resources')):
        identity = folder if variant == 'benign' else variant+'/'+folder
        pack_id = str(uuid.uuid5(NAMESPACE, identity))
        ids[kind] = pack_id
        _json(output/folder/'manifest.json', {'format_version': 2, 'header': {
            'name': 'Pack order '+variant+' '+kind,
            'description': ('Unique assets; no native material overrides' if native_sfx is None
                            else 'Explicit conflict: byte-exact installed native sfx.material'),
            'uuid': pack_id, 'version': VERSION, 'min_engine_version': [1, 18, 0]},
            'modules': [{'type': kind, 'uuid': str(uuid.uuid5(NAMESPACE, identity+'/module')), 'version': VERSION}]})
    behavior, resource = output/'behavior_pack', output/'resource_pack'
    package = behavior/PACKAGE
    package.mkdir()
    (package/'__init__.py').write_text('# -*- coding: utf-8 -*-\n', encoding='utf-8')
    (package/'modMain.py').write_bytes((HERE/'modMain.py').read_bytes())
    (package/'runtime.py').write_bytes(runtime)
    controls = []
    for index, color in enumerate(COLORS):
        path = TEXTURE+'_'+str(index)
        _png(resource/(path+'.png'), color)
        controls.append({'patch%d' % index: _control('image', (16, 32), (index*16, 0),
            texture=path, color=[1., 1., 1.], alpha=1., keep_ratio=False,
            bilinear=False, nineslice_size=0)})
    _json(resource/'ui/pack_order_canary.json', {'namespace': UI_NAMESPACE,
        'main': _control('screen', ('100%', '100%'), layer=1000, controls=[
            {'canary': _control('panel', (64, 32), visible=False, clips_children=False, controls=controls)}])})
    _json(resource/'ui/_ui_defs.json', {'ui_defs': ['ui/pack_order_canary.json']})
    # The effect and texture use unique names and a stock FrameAni route. The
    # explicit stock_sfx_conflict material override is installed separately below.
    _png(resource/(TEXTURE+'.png'), COLORS[0])
    _json(resource/(TEXTURE+'.json'), {'frames': [{'filename': 'canary.png',
        'frame': {'x': 0, 'y': 0, 'w': 1, 'h': 1}, 'rotated': False, 'trimmed': False,
        'sourceSize': {'w': 1, 'h': 1}, 'spriteSourceSize': {'x': 0, 'y': 0, 'w': 1, 'h': 1},
        'scale': {'x': 1., 'y': 1., 'z': 1.}}],
        'meta': {'image': 'canary.png', 'size': {'w': 1, 'h': 1}, 'scale': '1'}})
    _json(resource/'effects/pmanim_pack_order/ordinary.json', {'frameeffect': {
        'texture': TEXTURE, 'layer': 1, 'scale': [1., 1., 1.], 'shuffle': False,
        'fps': 1, 'cylinder_enable': False, 'fade_distance': 0., 'depth_test': True,
        'delay_in_loop': False, 'delay': 0., 'sub_layer': 0, 'lerp_scale': False,
        'tex_repeat_num': [1, 1], 'point_filtering': False, 'first_person_enable': True,
        'face_camera': True, 'rot_speed': [0, 0, 0], 'frame_color': [], 'loop': True, 'blend_mode': 1}})
    if native_sfx is not None:
        target = resource/'materials/sfx.material'
        target.parent.mkdir()
        target.write_bytes(native_sfx)
        if target.read_bytes() != native_path.read_bytes():
            raise RuntimeError('Conflict pack sfx.material must match installed native bytes exactly')
    files = {path.relative_to(output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in output.rglob('*') if path.is_file()}
    receipt = {'schema': 'native_stencil_pack_order_fixture_v1', 'variant': variant, 'root': str(output),
        'resource_pack': str(resource), 'behavior_pack': str(behavior),
        'resource_uuid': ids['resources'], 'behavior_uuid': ids['data'], 'version': VERSION,
        'python_class': PACKAGE+'.runtime.PackOrderCanary', 'ui_namespace': UI_NAMESPACE,
        'ui_key': 'canary', 'ui_definition': UI_NAMESPACE+'.main',
        'ordinary_effect': 'effects/pmanim_pack_order/ordinary.json',
        'colors': [list(color) for color in COLORS], 'canary_size': [64, 32],
        'native_materials_modified': native_sfx is not None, 'native_shaders_modified': False,
        'existing_assets_overridden': native_sfx is not None,
        'material_overrides': ['materials/sfx.material'] if native_sfx is not None else [],
        'installed_source_files_modified': False,
        'stock_material_source': str(native_path) if native_path is not None else None,
        'stock_material_sha256': hashlib.sha256(native_sfx).hexdigest() if native_sfx is not None else None,
        'stock_material_byte_exact': native_sfx is not None,
        'loader_entrypoint': PACKAGE+'.modMain',
        'client_lifecycle_imports_canary': True,
        'automatic_runtime_initialization': True,
        'automatic_ui_or_effect_initialization': False,
        'automatic_system_registration': False,
        'server_lifecycle_imports_client_runtime': False,
        'file_sha256': files, 'builder_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    _json(output/RECEIPT, receipt)
    return receipt


def config_plan(project, fixture, position='last'):
    """Return reversible .mcdev.json bytes and readable text; never write or launch.

    first/last describes the input list only. Actual engine order must be read
    from the owned deployed world's world_resource_packs.json after launch.
    """
    project = Path(project).resolve(strict=True)
    fixture = _read_fixture(fixture)
    if position not in ('first', 'last'):
        raise ValueError('Choose included_mod_dirs first or last')
    target = project/'.mcdev.json'
    before = target.read_bytes()
    config = json.loads(before.decode('utf-8-sig'))
    directories = list(config.get('included_mod_dirs', ['./']))
    extra = str(Path(fixture['root']).resolve(strict=True))
    for item in directories:
        path = item if isinstance(item, str) else item['path']
        if (project/path).resolve() == Path(extra):
            raise ValueError('Canary pack already appears in included_mod_dirs')
    config = copy.deepcopy(config)
    config['included_mod_dirs'] = ([extra]+directories if position == 'first' else directories+[extra])
    after = json.dumps(config, indent=2, ensure_ascii=False)+'\n'
    return {'schema': 'pack_order_config_plan_v1', 'config_path': str(target),
        'input_position': position, 'before_sha256': hashlib.sha256(before).hexdigest(),
        'before_base64': base64.b64encode(before).decode('ascii'),
        'before_text': before.decode('utf-8-sig'), 'after_text': after,
        'after_base64': base64.b64encode(after.encode('utf-8')).decode('ascii'),
        'after_sha256': hashlib.sha256(after.encode('utf-8')).hexdigest(),
        'extra_root': extra, 'resource_uuid': fixture['resource_uuid'],
        'variant': fixture.get('variant', 'benign'),
        'input_list_is_not_actual_engine_priority_proof': True,
        'apply_and_restore_owned_by_lifecycle_runner': True}


def deployed_order(session_file, project, fixture, expected_owner, expected_relation=None):
    """Read assigned-session world pack UUIDs and deployed canary file hashes.

    expected_relation is 'before'/'after' relative to the project's resource
    UUID in the saved world list. It does not label either side high priority.
    """
    if expected_relation not in (None, 'before', 'after'):
        raise ValueError('Expected relation must be before, after or None')
    session_path, project = Path(session_file).resolve(strict=True), Path(project).resolve(strict=True)
    session = json.loads(session_path.read_text(encoding='utf-8-sig'))
    if session['owner'] != expected_owner or Path(session['project']).resolve() != project:
        raise ValueError('Pack order receipt must use the assigned owner/project session')
    fixture = _read_fixture(fixture)
    candidates = [Path(session[key])/'world_resource_packs.json'
                  for key in ('world_path', 'world_link') if session.get(key)]
    path = next((path for path in candidates if path.is_file()), None)
    if path is None:
        raise FileNotFoundError('Assigned deployed world has no world_resource_packs.json')
    raw = path.read_bytes()
    entries = json.loads(raw.decode('utf-8-sig'))
    ids = [entry['pack_id'].lower() for entry in entries]
    own_id = json.loads((project/'resource_pack/manifest.json').read_text(encoding='utf-8-sig'))['header']['uuid'].lower()
    extra_id = fixture['resource_uuid'].lower()
    if ids.count(own_id) != 1 or ids.count(extra_id) != 1:
        raise RuntimeError('Both project and extra resource UUID must occur once in actual world pack list')
    own_index, extra_index = ids.index(own_id), ids.index(extra_id)
    relation = 'before' if extra_index < own_index else 'after'
    if expected_relation is not None and relation != expected_relation:
        raise RuntimeError('Actual deployed pack relation differs from requested assertion: '+relation)
    roots = [path.parent/'resource_packs']
    if session.get('appdata'):
        roots.append(Path(session['appdata'])/'MinecraftPE_Netease/games/com.netease/resource_packs')
    deployed = []
    for root in roots:
        for pack in root.iterdir() if root.is_dir() else []:
            manifest = pack/'manifest.json'
            if not manifest.is_file():
                continue
            header = json.loads(manifest.read_text(encoding='utf-8-sig')).get('header', {})
            if str(header.get('uuid', '')).lower() != extra_id:
                continue
            checked = {}
            for relative, digest in fixture['file_sha256'].items():
                if relative.startswith('resource_pack/'):
                    member = pack/relative[len('resource_pack/'):]
                    checked[relative] = member.is_file() and hashlib.sha256(member.read_bytes()).hexdigest() == digest
            if not checked or not all(checked.values()):
                raise RuntimeError('Deployed extra resource pack differs from built source')
            deployed.append({'path': str(pack), 'resolved_path': str(pack.resolve()), 'all_resource_hashes_match': True})
    if not deployed:
        raise RuntimeError('Cannot resolve deployed extra pack by its manifest UUID')
    return {'schema': 'deployed_pack_order_receipt_v1', 'session_file': str(session_path),
        'session_id': session['id'], 'owner': expected_owner, 'project': str(project),
        'world_list_path': str(path), 'world_list_sha256': hashlib.sha256(raw).hexdigest(),
        'actual_resource_packs': entries, 'project_uuid': own_id, 'extra_uuid': extra_id,
        'project_index': own_index, 'extra_index': extra_index, 'extra_relation': relation,
        'variant': fixture.get('variant', 'benign'),
        'material_conflict_present': bool(fixture.get('material_overrides')),
        'stock_material_sha256': fixture.get('stock_material_sha256'),
        'deployed_canary_packs': deployed, 'material_precedence_inferred': False,
        'remaining_render_gate': 'ordinary native effect and exact independent UI canary in same captured frame'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--variant', choices=VARIANTS, default='benign')
    parser.add_argument('--game-exe', type=Path)
    args = parser.parse_args()
    print(json.dumps(install(args.output, args.variant, args.game_exe), indent=2))
