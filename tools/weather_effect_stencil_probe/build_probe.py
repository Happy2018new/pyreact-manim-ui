"""Build a tiny public geometry/stencil/layer15 bridge; never launch a game."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ROI = [96, 192, 128, 128]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def stencil(compare, reference, write):
    face = {'stencilFunc': compare, 'stencilFailOp': 'Keep',
            'stencilDepthFailOp': 'Keep', 'stencilPassOp': 'Replace' if write else 'Keep'}
    return {'frontFace': dict(face), 'backFace': dict(face), 'stencilRef': reference,
            'stencilReadMask': 128, 'stencilWriteMask': 128 if write else 0}


def build(output, game_exe):
    output = Path(output).resolve()
    if output.exists() or (ROOT / '.runtime').resolve() not in output.parents:
        raise ValueError('Choose a fresh isolated .runtime output')
    game_exe = Path(game_exe).resolve()
    geometry = module('stencil_geometry_builder', HERE.parent / 'geometry_atlas_probe/build_probe.py')
    order = module('stencil_order_builder', HERE.parent / 'weather_effect_order_probe/build_probe.py')
    geometry.build(output)
    bp, rp = output / 'behavior_pack', output / 'resource_pack'
    package = bp / 'weather_effect_stencil_probe'
    package.mkdir()
    for name in ('__init__.py', 'runtime.py', 'modMain.py'):
        content = '' if name == '__init__.py' else (HERE / name).read_text(encoding='utf-8')
        (package / name).write_text(content, encoding='utf-8')
    # The old entrypoint is not loaded alongside the new probe.
    (bp / 'geometry_atlas_probe/modMain.py').unlink()
    shaders = rp / 'shaders/glsl'
    for name in ('writer.fragment', 'clear.fragment', 'check.fragment', 'effect.vertex', 'effect.fragment'):
        (shaders / ('weather_stencil_' + name)).write_bytes((HERE / name).read_bytes())
    terrain_path = rp / 'materials/terrain.material'
    terrain = json.loads(terrain_path.read_text(encoding='utf-8'))
    source = terrain['materials']['pmanim_geometry_atlas:netease_block_as_entity_mesh']
    source['+states'] = ['Blending', 'DisableCulling', 'DisableDepthTest', 'DisableDepthWrite',
                         'DisableColorWrite', 'EnableStencilTest', 'StencilWrite']
    source['-states'] = ['EnableAlphaToCoverage']
    source['fragmentShader'] = 'shaders/glsl/weather_stencil_writer.fragment'
    source.update(stencil('Always', 128, True))
    clear = copy.deepcopy(source)
    clear['fragmentShader'] = 'shaders/glsl/weather_stencil_clear.fragment'
    clear.update(stencil('Always', 0, True))
    terrain['materials']['netease_block_as_mesh_opaque:pmanim_geometry_atlas'] = clear
    check = copy.deepcopy(source)
    check['fragmentShader'] = 'shaders/glsl/weather_stencil_check.fragment'
    check['+states'] = ['DisableCulling', 'DisableDepthTest', 'DisableDepthWrite']
    check['-states'] = ['EnableAlphaToCoverage', 'Blending', 'DisableColorWrite',
                       'DisableRGBWrite', 'DisableAlphaWrite', 'EnableStencilTest', 'StencilWrite']
    check['blendSrc'], check['blendDst'] = 'One', 'Zero'
    for key in stencil('Always', 0, False):
        check.pop(key, None)
    terrain['materials']['netease_block_as_mesh_alpha:pmanim_geometry_atlas'] = check
    terrain['materials']['netease_block_as_mesh_alpha_single_side:pmanim_geometry_atlas'] = check
    geometry.write_json(terrain_path, terrain)
    blocks = json.loads((rp / 'blocks.json').read_text(encoding='utf-8'))
    for kind, layer in (('clear', 'opaque'), ('check', 'alpha')):
        for template in range(16):
            identifier = 'pmanim_geometry_stencil:%s_%02d' % (kind, template)
            filename = 'stencil_%s_%02d' % (kind, template)
            geometry.write_atlas_block_template(rp, bp, identifier, filename, template + .5)
            block_path = bp / ('netease_blocks/' + filename + '.json')
            block = json.loads(block_path.read_text(encoding='utf-8'))
            block['minecraft:block']['components']['netease:render_layer']['value'] = layer
            geometry.write_json(block_path, block)
            blocks[identifier] = {'netease_model': identifier, 'sound': 'stone'}
    geometry.write_json(rp / 'blocks.json', blocks)
    native_path = game_exe.parent / 'data/resource_packs/vanilla_netease/materials/sfx.material'
    native_bytes = native_path.read_bytes()
    sfx = json.loads(native_bytes.decode('utf-8-sig'))
    update = {'vertexShader': 'shaders/glsl/weather_stencil_effect.vertex',
              'fragmentShader': 'shaders/glsl/weather_stencil_effect.fragment',
              'vertexFields': [{'field': 'Position'}, {'field': 'UV0'}],
              '+states': ['Blending', 'DisableCulling', 'DisableDepthTest', 'DisableDepthWrite', 'DisableAlphaWrite'],
              '-states': ['DisableColorWrite', 'DisableRGBWrite', 'EnableAlphaToCoverage', 'EnableStencilTest', 'StencilWrite'],
              'blendSrc': 'One', 'blendDst': 'Zero', 'alphaSrc': 'Zero', 'alphaDst': 'One', 'msaaSupport': 'Both'}
    sfx['materials']['sequence:billboard_base'].update(update)
    masked = copy.deepcopy(update)
    masked['+states'].append('EnableStencilTest')
    masked['-states'].remove('EnableStencilTest')
    masked.update(stencil('Equal', 128, False))
    sfx['materials']['point_sequence:sequence'].update(masked)
    positive = copy.deepcopy(masked)
    positive.update(stencil('Always', 128, False))
    sfx['materials']['point_sequence_add:point_sequence'].update(positive)
    geometry.write_json(rp / 'materials/sfx.material', sfx)
    for name, point in (('background', False), ('masked', True), ('positive', True)):
        config = order.frame_config()
        config['frameeffect']['point_filtering'] = point
        config['frameeffect']['blend_mode'] = 2 if name == 'positive' else 1
        config['frameeffect']['texture'] = 'textures/weather_stencil/white'
        geometry.write_json(rp / ('effects/stencil_' + name + '.json'), config)
    geometry.PACKET_BUILDER.write_pixel(rp / 'textures/weather_stencil/white.png', 255)
    post_source = game_exe.parent / 'data/resource_packs/vanilla_netease/graphics_settings/post_process.json'
    post = json.loads(post_source.read_text(encoding='utf-8-sig'))
    for process in post['process_array']:
        process['enable'] = False
    geometry.write_json(rp / 'graphics_settings/post_process.json', post)
    geometry.write_json(output / '.mcdev.json', {'game_executable_path': str(game_exe), 'included_mod_dirs': ['./'],
        'auto_hot_reload_mods': False, 'auto_hot_reload_ui': False, 'auto_hot_reload_shaders': False, 'auto_hot_reload_materials': False})
    receipt = {'kind': 'weather_effect_stencil_bit_v1', 'roi': ROI, 'stencil_mask': 128,
        'runtime_namespace': 'pmanim_weather_effect_stencil', 'runtime_file_writes': False,
        'private_texture_upload': False, 'six_bit_capacity_claimed': False,
        'source_material': str(native_path), 'source_sha256': hashlib.sha256(native_bytes).hexdigest(),
        'changed_sfx_materials': ['sequence:billboard_base', 'point_sequence:sequence', 'point_sequence_add:point_sequence'],
        'stencil_doc': 'NeteaseGuide/mcguide/16-美术/7-材质与着色器/3-材质配置说明.md',
        'source_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.iterdir() if p.is_file()}}
    geometry.write_json(output / 'probe_resources.json', receipt)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--game-exe', required=True)
    args = parser.parse_args()
    print(build(args.output, args.game_exe))
