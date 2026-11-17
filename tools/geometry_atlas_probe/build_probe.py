"""Build isolated world geometry -> scene alpha -> postprocess atlas assets."""
import argparse
import importlib.util
import json
from pathlib import Path
import uuid


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKET = HERE.parent / 'geometry_packet_probe'
MARKER = '.pmanim_geometry_atlas_probe.json'
NAMESPACE = uuid.UUID('cc7b047c-6371-44e9-a0b6-44241b0a4984')
IDENTIFIER = 'pmanim_geometry_atlas:quad'
ANCHOR = 'pmanim_geometry_atlas:anchor'
_SPEC = importlib.util.spec_from_file_location('geometry_atlas_packet_assets', PACKET / 'build_probe.py')
PACKET_BUILDER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(PACKET_BUILDER)
write_json = PACKET_BUILDER.write_json


def write_anchor(behavior, resource):
    """Transparent BB anchor adapted from the same author's BBE world fixture."""
    write_json(behavior / 'entities/geometry_atlas_anchor.json', {
        'format_version': '1.16.0', 'minecraft:entity': {
            'description': {'identifier': ANCHOR, 'is_spawnable': False,
                            'is_summonable': False, 'is_experimental': False},
            'components': {
                'minecraft:physics': {'has_gravity': False, 'has_collision': False},
                'minecraft:collision_box': {'width': 0.0, 'height': 0.0},
                'minecraft:pushable': {'is_pushable': False, 'is_pushable_by_piston': False}}}})
    geometry = 'geometry.pmanim_geometry_atlas.anchor'
    controller = 'controller.render.pmanim_geometry_atlas.anchor'
    write_json(resource / 'entity/geometry_atlas_anchor.entity.json', {
        'format_version': '1.10.0', 'minecraft:client_entity': {'description': {
            'identifier': ANCHOR, 'materials': {'default': 'entity_alphatest'},
            'textures': {'default': 'textures/pmanim_geometry_atlas/transparent'},
            'geometry': {'default': geometry}, 'render_controllers': [controller]}}})
    write_json(resource / 'models/entity/geometry_atlas_anchor.geo.json', {
        'format_version': '1.12.0', 'minecraft:geometry': [{
            'description': {'identifier': geometry, 'texture_width': 2, 'texture_height': 2,
                            'visible_bounds_width': 192, 'visible_bounds_height': 192,
                            'visible_bounds_offset': [0, 32, 0]},
            'bones': [{'name': 'root', 'pivot': [0, 0, 0], 'cubes': [
                {'origin': [-.01, 0, -.01], 'size': [.02, .02, .02], 'uv': [0, 0]}]}]}]})
    write_json(resource / 'render_controllers/geometry_atlas_anchor.json', {
        'format_version': '1.8.0', 'render_controllers': {controller: {
            'geometry': 'Geometry.default', 'materials': [{'*': 'Material.default'}],
            'textures': ['Texture.default']}}})
    PACKET_BUILDER.write_pixel(resource / 'textures/pmanim_geometry_atlas/transparent.png', 0)


def write_blocks(behavior, resource, rgb_writer):
    blocks = {'format_version': '1.21.40'}
    templates = [(IDENTIFIER, 'geometry_atlas_quad', 0)]
    templates.extend(('pmanim_geometry_atlas:quad_compact8_%02d' % template,
                      'geometry_atlas_quad_compact8_%02d' % template, template + .5)
                     for template in range(16))
    for identifier, filename, origin_y in templates:
        PACKET_BUILDER.write_block_template(resource, behavior, identifier, filename, origin_y)
        blocks[identifier] = {'netease_model': identifier, 'sound': 'stone'}
    write_json(resource / 'blocks.json', blocks)
    states = ['Blending', 'DisableCulling', 'DisableDepthTest', 'DisableDepthWrite']
    if not rgb_writer:
        states.append('DisableRGBWrite')
    material = {
        'vertexShader': 'shaders/glsl/scatter.vertex',
        'fragmentShader': 'shaders/glsl/scatter.fragment',
        '+defines': ['BLEND'], '-defines': ['ALPHA_TEST'],
        '-states': ['DisableAlphaWrite', 'EnableAlphaToCoverage'], '+states': states,
        'blendSrc': 'One' if rgb_writer else 'Zero',
        'blendDst': 'Zero' if rgb_writer else 'One',
        'alphaSrc': 'One', 'alphaDst': 'Zero', 'msaaSupport': 'Both'}
    materials = {'version': '1.0.0',
                 'pmanim_geometry_atlas:netease_block_as_entity_mesh': material}
    for name in ('netease_block_as_mesh_blend', 'netease_block_as_mesh_blend_enable_transparency',
                 'netease_block_as_mesh_blend_far', 'netease_block_as_mesh_blend_no_culling'):
        materials[name + ':pmanim_geometry_atlas'] = {}
    write_json(resource / 'materials/terrain.material', {'materials': materials})


def post_material(fragment):
    return {'vertexShader': 'shaders/uv_fullscreen.vertex',
            'fragmentShader': 'shaders/glsl/geometry_atlas_' + fragment,
            'vertexFields': [{'field': 'Position'}, {'field': 'UV0'}],
            'samplerStates': [{'samplerIndex': index, 'textureWrap': 'Clamp',
                               'textureFilter': 'Point'} for index in (0, 1, 3)],
            'states': ['DisableDepthTest', 'DisableDepthWrite'],
            '-states': ['DisableAlphaWrite', 'EnableAlphaToCoverage'],
            'msaaSupport': 'Both'}


def pipeline_config():
    return {'name': 'pmanim_geometry_atlas_gather', 'enable': False, 'paras': [
        {'name': 'query', 'value': [0., 256., 0., 0.], 'range': [0., 1048576.]},
        {'name': 'layout', 'value': [256., 16., 8., 64.], 'range': [0., 1048576.]},
        {'name': 'dimensions', 'value': [4., 720., 1080., 0.], 'range': [0., 1048576.]}],
        'pass_array': [
            {'render_target': {'width': 1., 'height': 1.},
             'material': 'pmanim_geometry_atlas_' + name, 'depth_enable': False}
            for name in ('copy', 'poison', 'consumer')]}


def build(output, rgb_writer=False):
    output = Path(output).resolve()
    if output in (ROOT, ROOT / 'behavior_pack', ROOT / 'resource_pack', HERE, PACKET):
        raise ValueError('Output must be an isolated generated directory')
    marker = {'kind': 'pmanim_geometry_atlas_probe', 'version': 1,
              'rgb_writer': bool(rgb_writer)}
    if output.exists() and any(output.iterdir()) and not (output / MARKER).is_file():
        raise ValueError('Nonempty output lacks geometry atlas ownership marker')
    if (output / MARKER).is_file():
        if json.loads((output / MARKER).read_text(encoding='utf-8')) != marker:
            raise ValueError('Existing output belongs to a different atlas configuration')
    # Read all required sources before writing the ownership marker.
    scripts = {name: (HERE / name).read_text(encoding='utf-8')
               for name in ('runtime.py', 'modMain.py')}
    scripts['codec.py'] = (PACKET / 'codec.py').read_text(encoding='utf-8')
    shaders = {name: (HERE / name).read_bytes() for name in ('scatter.vertex', 'scatter.fragment')}
    for name in ('consumer.fragment', 'copy.fragment', 'poison.fragment'):
        if (HERE / name).is_file():
            shaders[name] = (HERE / name).read_bytes()
    write_json(output / MARKER, marker)
    behavior, resource = output / 'behavior_pack', output / 'resource_pack'
    package = behavior / 'geometry_atlas_probe'
    package.mkdir(parents=True, exist_ok=True)
    (package / '__init__.py').write_text('# -*- coding: utf-8 -*-\n', encoding='utf-8')
    for name, source in scripts.items():
        (package / name).write_text(source, encoding='utf-8')
    pipeline = pipeline_config()
    write_json(package / 'pipeline.json', pipeline)
    (package / 'pipeline_config.py').write_text(
        '# -*- coding: utf-8 -*-\nPROCESS = ' + repr(pipeline) + '\n',encoding='utf-8')
    for name, module in (('behavior_pack', 'data'), ('resource_pack', 'resources')):
        write_json(output / name / 'manifest.json', {'format_version': 2, 'header': {
            'name': 'PManim Geometry Alpha Atlas ' + module,
            'description': 'Isolated native geometry -> scene alpha -> indexed shader lookup',
            'uuid': str(uuid.uuid5(NAMESPACE, name)), 'version': [0, 0, 1],
            'min_engine_version': [1, 18, 0]}, 'modules': [{'type': module,
                'uuid': str(uuid.uuid5(NAMESPACE, name + '/module')), 'version': [0, 0, 1]}]})
    write_anchor(behavior, resource)
    write_blocks(behavior, resource, rgb_writer)
    for name, source in shaders.items():
        target_name = name if name.startswith('scatter.') else 'geometry_atlas_' + name
        path = resource / 'shaders/glsl' / target_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source)
    materials = {'pmanim_geometry_atlas_' + name.split('.')[0]: post_material(name)
                 for name in ('consumer.fragment', 'copy.fragment', 'poison.fragment') if name in shaders}
    write_json(resource / 'materials/postprocess.material', materials)
    write_json(output / 'probe_resources.json', {
        'version': 1, 'kind': 'geometry_atlas_probe_v1', 'slots': [],
        'runtime': {'package': 'geometry_atlas_probe', 'entrypoint': 'geometry_atlas_probe.modMain',
                    'system_namespace': 'pmanim_geometry_atlas_probe', 'system_name': 'probe'},
        'anchor_identifier': ANCHOR, 'rgb_writer': bool(rgb_writer),
        'encoding': {'mode': 'compact8', 'palette_height': 16, 'template_count': 16,
                     'record_id': 'x*stride+z', 'byte_source': 'POSITION.y',
                     'source_center': 'explicit EXTRA_ACTOR_UNIFORM3.yzw; calibrate world input'},
        'scatter': {'uniform1': ['stride', 'y_offset', 'slot_count', 'atlas_columns'],
                    'uniform2': ['left_px', 'top_px', 'cell_px', 'width_px'],
                    'uniform3': ['height_px', 'center_x', 'center_y', 'center_z'],
                    'uniform4': ['writer_visible', 'debug_rgb', 'reserved', 'reserved'],
                    'alpha_mode': 'replace', 'rgb_preserved': not rgb_writer},
        'postprocess_materials': list(materials),
        'postprocess': {'process': pipeline,
                        'connection': ['pmanim_geometry_atlas_gather', 0,
                                       'pmanim_geometry_atlas_gather', 2, 3],
                        'source': 'scene alpha from TEXTURE_1 copied in pass 0',
                        'consumer_input': 'TEXTURE_3 from pass 0; pass 1 poisons previous output'},
        'production_resources_modified': False, 'native_scene_alpha_verified': False})
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rgb-writer', action='store_true')
    args = parser.parse_args()
    print(build(args.output, args.rgb_writer))
