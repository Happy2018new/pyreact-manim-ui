"""Build a fresh, isolated byte-record stencil probe; never launch a game."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import uuid


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAMESPACE = uuid.UUID('c0929450-cdd7-48d7-9957-231fb371f429')
MARKER = '.pmanim_stencil_large_probe.json'
MAX_BYTES = 524288
PAGE_BYTES = 65536
SHADERS = ('scatter.vertex', 'writer64.fragment', 'writer128.fragment',
           'clear.vertex', 'clear.fragment', 'effect.vertex', 'effect.fragment',
           'copy.fragment', 'oracle.fragment')
SFX_MATERIALS = ('sequence:billboard_base', 'point_sequence:sequence',
                 'point_sequence_add:point_sequence')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def stencil(compare, reference, read_mask, write_mask):
    face = {'stencilFunc': compare, 'stencilFailOp': 'Keep',
            'stencilDepthFailOp': 'Keep',
            'stencilPassOp': 'Replace' if write_mask else 'Keep'}
    return {'frontFace': dict(face), 'backFace': dict(face),
            'stencilRef': reference, 'stencilReadMask': read_mask,
            'stencilWriteMask': write_mask}


def geometry_material(fragment, mask, clear=False):
    states = ['DisableCulling', 'DisableColorWrite', 'DisableDepthTest',
              'DisableDepthWrite', 'EnableStencilTest', 'StencilWrite']
    removed = ['EnableAlphaToCoverage']
    if clear:
        removed.append('Blending')
    else:
        states.append('Blending')
    result = {
        'vertexShader': 'shaders/glsl/stencil_large_' + ('clear.vertex' if clear else 'scatter.vertex'),
        'fragmentShader': 'shaders/glsl/stencil_large_' + fragment,
        '+defines': ['BLEND'], '-defines': ['ALPHA_TEST'],
        '+states': states, '-states': removed,
        'blendSrc': 'Zero', 'blendDst': 'One',
        'alphaSrc': 'Zero', 'alphaDst': 'One', 'msaaSupport': 'Both'}
    result.update(stencil('Always', 0 if clear else mask, 192, mask))
    return result


def write_blocks(geo, behavior, resource):
    blocks = {'format_version': '1.21.40'}
    for kind, layer, count in (('clear', 'opaque', 1), ('bit64', 'alpha', 16),
                                ('bit128', 'blend', 16)):
        for template in range(count):
            identifier = 'pmanim_stencil_large:%s_%02d' % (kind, template)
            filename = 'stencil_large_%s_%02d' % (kind, template)
            geo.write_atlas_block_template(resource, behavior, identifier,
                                           filename, template + .5)
            path = behavior / ('netease_blocks/' + filename + '.json')
            block = json.loads(path.read_text(encoding='utf-8'))
            block['minecraft:block']['components']['netease:render_layer']['value'] = layer
            geo.write_json(path, block)
            blocks[identifier] = {'netease_model': identifier, 'sound': 'stone'}
    geo.write_json(resource / 'blocks.json', blocks)
    writer64 = geometry_material('writer64.fragment', 64)
    writer128 = geometry_material('writer128.fragment', 128)
    materials = {'version': '1.0.0',
                 'pmanim_geometry_atlas:netease_block_as_entity_mesh': writer128,
                 'netease_block_as_mesh_opaque:pmanim_geometry_atlas':
                     geometry_material('clear.fragment', 192, clear=True)}
    for name in ('netease_block_as_mesh_alpha', 'netease_block_as_mesh_alpha_single_side'):
        materials[name + ':pmanim_geometry_atlas'] = copy.deepcopy(writer64)
    for name in ('netease_block_as_mesh_blend', 'netease_block_as_mesh_blend_enable_transparency',
                 'netease_block_as_mesh_blend_far', 'netease_block_as_mesh_blend_no_culling'):
        materials[name + ':pmanim_geometry_atlas'] = copy.deepcopy(writer128)
    geo.write_json(resource / 'materials/terrain.material', {'materials': materials})


def sfx_override(mask=0):
    result = {
        'vertexShader': 'shaders/glsl/stencil_large_effect.vertex',
        'fragmentShader': 'shaders/glsl/stencil_large_effect.fragment',
        'vertexFields': [{'field': 'Position'}, {'field': 'UV0'}],
        '+states': ['Blending', 'DisableCulling', 'DisableDepthTest',
                    'DisableDepthWrite', 'DisableAlphaWrite'],
        '-states': ['DisableColorWrite', 'DisableRGBWrite', 'EnableAlphaToCoverage',
                    'EnableStencilTest', 'StencilWrite'],
        '-defines': ['ALPHA_TEST'],
        'blendSrc': 'One' if mask else 'SourceAlpha',
        'blendDst': 'One' if mask else 'OneMinusSrcAlpha',
        'alphaSrc': 'Zero', 'alphaDst': 'One', 'msaaSupport': 'Both'}
    if mask:
        result['+states'].append('EnableStencilTest')
        result['-states'].remove('EnableStencilTest')
        result.update(stencil('Equal', mask, mask, 0))
    return result


def write_effects(geo, order, resource, native_sfx):
    sfx = copy.deepcopy(native_sfx)
    for name, mask in zip(SFX_MATERIALS, (0, 64, 128)):
        sfx['materials'][name].update(sfx_override(mask))
    for name, value in native_sfx['materials'].items():
        if name not in SFX_MATERIALS and sfx['materials'][name] != value:
            raise ValueError('Unexpected native SFX material change: ' + name)
    geo.write_json(resource / 'materials/sfx.material', sfx)
    for kind, point, blend in (('base', False, 1), ('bit64', True, 1), ('bit128', True, 2)):
        config = order.frame_config()
        config['frameeffect'].update(point_filtering=point, blend_mode=blend,
                                      texture='textures/stencil_large/white')
        geo.write_json(resource / ('effects/stencil_large_' + kind + '.json'), config)
    geo.PACKET_BUILDER.write_pixel(resource / 'textures/stencil_large/white.png', 255)


def post_material(fragment):
    return {'vertexShader': 'shaders/uv_fullscreen.vertex',
            'fragmentShader': 'shaders/glsl/stencil_large_' + fragment,
            'vertexFields': [{'field': 'Position'}, {'field': 'UV0'}],
            'samplerStates': [{'samplerIndex': index, 'textureWrap': 'Clamp',
                               'textureFilter': 'Point'} for index in (0, 1)],
            'states': ['DisableDepthTest', 'DisableDepthWrite'],
            '-states': ['DisableAlphaWrite', 'EnableAlphaToCoverage', 'Blending'],
            'msaaSupport': 'Both'}


def write_manifests(geo, output):
    for name, kind in (('behavior_pack', 'data'), ('resource_pack', 'resources')):
        geo.write_json(output / name / 'manifest.json', {
            'format_version': 2, 'header': {
                'name': 'Large byte-record stencil probe ' + kind,
                'description': 'Isolated host bytes to two experimental native stencil bits',
                'uuid': str(uuid.uuid5(NAMESPACE, name)), 'version': [0, 0, 1],
                'min_engine_version': [1, 18, 0]},
            'modules': [{'type': kind, 'uuid': str(uuid.uuid5(NAMESPACE, name + '/module')),
                         'version': [0, 0, 1]}]})


def read_inputs(game_exe):
    source = {name: (HERE / name).read_bytes()
              for name in ('runtime.py', 'modMain.py') + SHADERS}
    source['codec.py'] = (HERE.parent / 'geometry_packet_probe/codec.py').read_bytes()
    native_root = game_exe.parent / 'data/resource_packs/vanilla_netease'
    native_paths = {
        'sfx': native_root / 'materials/sfx.material',
        'post': native_root / 'graphics_settings/post_process.json'}
    native_bytes = {name: path.read_bytes() for name, path in native_paths.items()}
    native = {name: json.loads(value.decode('utf-8-sig'))
              for name, value in native_bytes.items()}
    if any(name not in native['sfx']['materials'] for name in SFX_MATERIALS):
        raise ValueError('Installed native SFX material routes are incomplete')
    if not isinstance(native['post'].get('process_array'), list):
        raise ValueError('Installed native post-process configuration is missing process_array')
    return source, native_paths, native_bytes, native


def build(output, game_exe):
    output = Path(output).resolve()
    runtime_root = (ROOT / '.runtime').resolve()
    if output.exists() or runtime_root not in output.parents:
        raise ValueError('Choose a fresh isolated output under this repository .runtime')
    game_exe = Path(game_exe).resolve()
    if not game_exe.is_file():
        raise ValueError('Installed game executable is missing')
    # Missing runtime/shader/native inputs must fail before creating any output.
    source, native_paths, native_bytes, native = read_inputs(game_exe)
    geo = module('stencil_large_geometry_builder', HERE.parent / 'geometry_atlas_probe/build_probe.py')
    order = module('stencil_large_order_builder', HERE.parent / 'weather_effect_order_probe/build_probe.py')
    behavior, resource = output / 'behavior_pack', output / 'resource_pack'
    geo.write_json(output / MARKER, {'kind': 'weather_stencil_large_v1', 'version': 1})
    write_manifests(geo, output)
    package = behavior / 'stencil_large'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('# -*- coding: utf-8 -*-\n', encoding='utf-8')
    for name in ('runtime.py', 'modMain.py', 'codec.py'):
        (package / name).write_bytes(source[name])
    geo.write_anchor(behavior, resource)
    write_blocks(geo, behavior, resource)
    write_effects(geo, order, resource, native['sfx'])
    post_config = copy.deepcopy(native['post'])
    for process in post_config['process_array']:
        process['enable'] = False
    geo.write_json(resource / 'graphics_settings/post_process.json', post_config)
    geo.write_json(resource / 'materials/postprocess.material', {
        'stencil_large_copy': post_material('copy.fragment'),
        'stencil_large_oracle': post_material('oracle.fragment')})
    shader_root = resource / 'shaders/glsl'
    shader_root.mkdir(parents=True)
    for name in SHADERS:
        (shader_root / ('stencil_large_' + name)).write_bytes(source[name])
    geo.write_json(output / '.mcdev.json', {
        'game_executable_path': str(game_exe), 'included_mod_dirs': ['./'],
        'auto_hot_reload_mods': False, 'auto_hot_reload_ui': False,
        'auto_hot_reload_shaders': False, 'auto_hot_reload_materials': False})
    receipt = {
        'kind': 'weather_stencil_large_v1', 'version': 1,
        'runtime': {'package': 'stencil_large', 'entrypoint': 'stencil_large.modMain',
                    'system_namespace': 'pmanim_stencil_large', 'system_name': 'probe'},
        'runtime_namespace': 'pmanim_stencil_large', 'anchor_identifier': geo.ANCHOR,
        'max_payload_bytes': MAX_BYTES, 'native_page_bytes': PAGE_BYTES,
        'native_writer_pages_at_maximum': 2 * (MAX_BYTES // PAGE_BYTES),
        'native_clear_records': 1, 'source_pixels_per_payload_byte': 4,
        'source_bits_per_pixel': 2,
        'geometry_records_per_payload_byte': {'per_bitplane': 1, 'total_two_bitplanes': 2},
        'encoding': 'compact8; one actual payload byte per native geometry record',
        'payload_source': 'actual host byte lists delivered in chunks of at most4096',
        'arbitrary_host_bytes': True, 'game_or_gpu_payload_prng': False,
        'source_roi_and_viewport': 'supplied by load_begin; source width is divisible by4',
        'stencil_mask': 192, 'stencil_bits': [64, 128], 'stencil_bits_reserved': False,
        'geometry_rgba_writes': False, 'geometry_depth_write_or_test': False,
        'clear': 'one opaque compact8 zero quad stretched over the source ROI',
        'late_effects': ['base RGB times63/255', 'add64red under bit64', 'add128red under bit128'],
        'material_requests_destination_alpha_preservation': True,
        'effect_roi_transport': 'SetMixColor uint24 coordinate pairs; alpha=(role+1)/4',
        'postprocess_materials': ['stencil_large_copy', 'stencil_large_oracle'],
        'postprocess_pass_count': 2, 'native_post_effects_enabled_by_default': False,
        'runtime_file_writes': False, 'private_texture_upload': False,
        'continuous_update': False, 'performance_claimed': False,
        'native_large_payload_verified': False, 'native_clear_coverage_verified': False,
        'native_geometry_memory_reclamation_verified': False,
        'host_memory_preflight': 'at least4GiB available commit before load_begin and every native page build',
        'source_hashes': {name: hashlib.sha256(value).hexdigest() for name, value in source.items()},
        'build_source_hashes': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (HERE / 'build_probe.py', HERE.parent / 'geometry_atlas_probe/build_probe.py',
                         HERE.parent / 'geometry_packet_probe/build_probe.py',
                         HERE.parent / 'weather_effect_order_probe/build_probe.py')},
        'source_material': str(native_paths['sfx']),
        'source_material_sha256': hashlib.sha256(native_bytes['sfx']).hexdigest(),
        'source_post_config': str(native_paths['post']),
        'source_post_config_sha256': hashlib.sha256(native_bytes['post']).hexdigest(),
        'changed_sfx_materials': list(SFX_MATERIALS),
        'other_native_sfx_entries_identical': True, 'native_precipitation_files_modified': False,
        'production_resources_modified': False}
    geo.write_json(output / 'probe_resources.json', receipt)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--game-exe', required=True)
    args = parser.parse_args()
    print(build(args.output, args.game_exe))
