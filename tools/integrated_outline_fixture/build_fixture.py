# -*- coding: utf-8 -*-
"""Offline assets for the shipped native entity-outline stencil control."""
import hashlib
import json
from pathlib import Path
import struct
import zlib


HERE = Path(__file__).resolve().parent
CLIENT = Path('D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.467018')
ENTITY = 'pmanim_integrated_outline:cube'
QUERY = 'query.mod.pmanim_integrated_outline_enabled'
GEOMETRY = 'geometry.pmanim_integrated_outline.cube'
CONTROLLER = 'controller.render.pmanim_integrated_outline.'
MATERIALS = {
    'plain': 'entity_alphatest_netease',
    'stencil_base': 'netease_entity_alphatest_outline_base',
    'outline': 'netease_entity_alphatest_outline'}


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')


def _opaque_texture(path):
    """A constant gray RGBA texture; alpha-test cannot discard fixture faces."""
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack(
            '>I', zlib.crc32(kind + body) & 0xffffffff)
    pixel_row = b'\x00' + bytes((224, 224, 224, 255)) * 2
    encoded = b'\x89PNG\r\n\x1a\n'
    encoded += chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 6, 0, 0, 0))
    encoded += chunk(b'IDAT', zlib.compress(pixel_row * 2)) + chunk(b'IEND', b'')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def _native_receipt(game_exe):
    client = Path(game_exe).resolve().parent if game_exe is not None else CLIENT
    material_path = client / 'data/resource_packs/vanilla_netease/materials/entity.material'
    material_bytes = material_path.read_bytes()
    native = json.loads(material_bytes.decode('utf-8-sig'))['materials']
    names = {
        'plain': 'entity_alphatest_netease:entity_nocull_netease',
        'stencil_base': 'netease_entity_alphatest_outline_base:entity_alphatest_netease',
        'outline': 'netease_entity_alphatest_outline:netease_entity_outline',
        'outline_parent': 'netease_entity_outline:entity_static_netease'}
    # The plain material's parent name varies between native client versions.
    plain_keys = [key for key in native if key.split(':')[0] == MATERIALS['plain']]
    if len(plain_keys) != 1:
        raise ValueError('Installed native plain alpha-test material is missing or ambiguous')
    names['plain'] = plain_keys[0]
    if any(key not in native for key in names.values()):
        raise ValueError('Installed native outline material recipe is incomplete')
    base, outline = native[names['stencil_base']], native[names['outline_parent']]
    for material in (base, outline):
        if any(material.get(field) != 117 for field in (
                'stencilRef', 'stencilReadMask', 'stencilWriteMask')):
            raise ValueError('Native outline masks differ from the reviewed 117 recipe')
    if ('NETEASE_DRAWLINE' not in outline.get('+defines', [])
            or base.get('frontFace', {}).get('stencilPassOp') != 'Replace'
            or outline.get('frontFace', {}).get('stencilFunc') != 'NotEqual'):
        raise ValueError('Native outline stencil semantics differ from reviewed recipe')
    sources = {str(material_path): hashlib.sha256(material_bytes).hexdigest()}
    for relative in ('entityVertexUtil.h', 'entityFragmentUtil.h', 'entity.fragment'):
        path = client / 'data/shaders/glsl' / relative
        sources[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        'client_root': str(client), 'source_sha256': sources,
        'native_material_definitions': {name: native[key] for name, key in names.items()},
        'source_document': 'NeteaseGuide/mcguide/16-美术/7-材质与着色器/2-内置材质清单.md',
        'recipe': 'documented shipped native alpha-test base + outline render controllers',
        'stencil_ref': 117, 'stencil_read_mask': 117, 'stencil_write_mask': 117,
        'transport_mask': 192, 'shared_transport_bits': 117 & 192,
        'native_material_or_shader_modified': False}


def _write_entity(behavior, resource):
    _write_json(behavior / 'entities/integrated_outline_cube.json', {
        'format_version': '1.16.0', 'minecraft:entity': {
            'description': {'identifier': ENTITY, 'is_spawnable': False,
                            'is_summonable': False, 'is_experimental': False},
            'components': {
                'minecraft:physics': {'has_gravity': False, 'has_collision': False},
                'minecraft:collision_box': {'width': 0.0, 'height': 0.0},
                'minecraft:pushable': {'is_pushable': False, 'is_pushable_by_piston': False}}}})
    _write_json(resource / 'entity/integrated_outline_cube.entity.json', {
        'format_version': '1.10.0', 'minecraft:client_entity': {'description': {
            'identifier': ENTITY, 'materials': MATERIALS,
            'textures': {'default': 'textures/pmanim_integrated_outline/opaque_gray'},
            'geometry': {'default': GEOMETRY},
            'render_controllers': [CONTROLLER + 'base', CONTROLLER + 'outline']}}})
    _write_json(resource / 'models/entity/integrated_outline_cube.geo.json', {
        'format_version': '1.12.0', 'minecraft:geometry': [{
            'description': {'identifier': GEOMETRY, 'texture_width': 2, 'texture_height': 2,
                            'visible_bounds_width': 4, 'visible_bounds_height': 4,
                            'visible_bounds_offset': [0, .5, 0]},
            'bones': [{'name': 'root', 'pivot': [0, 0, 0], 'cubes': [
                {'origin': [-8, 0, -8], 'size': [16, 16, 16], 'uv': [0, 0]}]}]}]})


def _write_controllers(resource):
    active = QUERY + ' > 0.5'
    common = {'geometry': 'Geometry.default', 'textures': ['Texture.default'],
              'ignore_lighting': True}
    base = dict(common, arrays={'materials': {
        'Array.base': ['Material.plain', 'Material.stencil_base']}},
        materials=[{'*': 'Array.base[' + active + ' ? 1 : 0]'}])
    outline = dict(common, materials=[{'*': 'Material.outline'}],
        part_visibility=[{'*': active}], smooth_normal=True,
        overlay_color={'r': '1.0', 'g': '0.0', 'b': '1.0', 'a': '0.12'})
    _write_json(resource / 'render_controllers/integrated_outline_cube.json', {
        'format_version': '1.8.0', 'render_controllers': {
            CONTROLLER + 'base': base, CONTROLLER + 'outline': outline}})


def build_assets(output, game_exe=None):
    """Add only fixture assets to an isolated probe output, never installed packs."""
    output = Path(output).resolve()
    repository = HERE.parents[1]
    if (repository / '.runtime').resolve() not in output.parents:
        raise ValueError('Outline assets require an isolated output below repository .runtime')
    receipt = _native_receipt(game_exe)
    behavior, resource = output / 'behavior_pack', output / 'resource_pack'
    _write_entity(behavior, resource)
    _write_controllers(resource)
    _opaque_texture(resource / 'textures/pmanim_integrated_outline/opaque_gray.png')
    runtime = HERE / 'runtime.py'
    package = behavior / 'stencil_large'
    package.mkdir(parents=True, exist_ok=True)
    (package / 'outline_fixture.py').write_bytes(runtime.read_bytes())
    receipt.update({
        'kind': 'integrated_native_outline_fixture_v1', 'entity_identifier': ENTITY,
        'query': QUERY, 'default_enabled': False, 'outline_color': [1., 0., 1.],
        'outline_width_world': .12, 'static_cube_world_size': [1., 1., 1.],
        'runtime_file_writes': False, 'game_started': False,
        'native_visible_positive_control_verified': False,
        'native_data_compatibility_verified': False,
        'runtime_sha256': hashlib.sha256(runtime.read_bytes()).hexdigest()})
    _write_json(output / 'outline_fixture_resources.json', receipt)
    return receipt
