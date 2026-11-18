"""Build an isolated in-memory RGB geometry / alpha-block codec experiment."""
import argparse
import importlib.util
import json
from pathlib import Path
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = HERE.parent / 'geometry_atlas_probe'
NAMESPACE = uuid.UUID('c207fbb7-ad3e-4ec3-8bf2-c95228f862a8')
spec = importlib.util.spec_from_file_location('scene_codec_geometry_builder', BASE / 'build_probe.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
write_json = base.write_json


def process(name, fragment):
    return {'name': 'scene_codec_'+name, 'enable': False,
            'paras': [{'name': 'codec', 'value': [2., 255., 0., 0.], 'range': [0., 1048576.]},
                      {'name': 'roi', 'value': [8., 32., 32., 128.], 'range': [0., 1048576.]},
                      {'name': 'physical', 'value': [720., 1080., 1., 1.], 'range': [0., 1048576.]}],
            'pass_array': [{'render_target': {'width': 1., 'height': 1.},
                            'material': 'scene_codec_'+name, 'depth_enable': False}]}


def build(output):
    output = Path(output).resolve()
    root = (ROOT / '.runtime').resolve()
    if root not in output.parents:
        raise ValueError('Scene codec output must stay within this repository .runtime directory')
    sources = {'runtime.py': (HERE / 'runtime.py').read_text(encoding='utf-8'),
               'scene_layout.py': (HERE / 'layout.py').read_text(encoding='utf-8'),
               'scene_codec.py': (HERE / 'codec.py').read_text(encoding='utf-8')}
    entries = [('raw', 'copy.fragment'), ('fixture', 'fixture.fragment'),
               ('encode', 'alpha_block_encode.fragment'), ('decode', 'alpha_block_decode.fragment'),
               ('consumer', 'payload_consumer.fragment'), ('diagnostic', 'alpha_diagnostic.fragment'),
               ('inspect', 'inspect.fragment')]
    shader_sources = {}
    for name, filename in entries:
        source = HERE / filename if name in ('raw', 'inspect') else HERE / 'shaders' / filename
        shader_sources[name] = source.read_bytes()
    writer = (HERE / 'shaders/rgb_scatter.fragment').read_bytes()
    base.build(output)
    package = output / 'behavior_pack/geometry_atlas_probe'
    old_runtime = (package / 'runtime.py').read_bytes()
    (package / 'base_runtime.py').write_bytes(old_runtime)
    for filename, source in sources.items():
        (package / filename).write_text(source, encoding='utf-8')
    processes = [process(name, filename) for name, filename in entries]
    (package / 'scene_config.py').write_text('# -*- coding: utf-8 -*-\nPROCESSES = '+repr(processes)+'\n',
                                           encoding='utf-8')
    resource = output / 'resource_pack'
    shaders = resource / 'shaders/glsl'
    (shaders / 'scene_codec_scatter.vertex').write_bytes((BASE / 'scatter.vertex').read_bytes())
    (shaders / 'scene_codec_scatter.fragment').write_bytes(writer)
    terrain_path = resource / 'materials/terrain.material'
    terrain = json.loads(terrain_path.read_text(encoding='utf-8'))
    material = terrain['materials']['pmanim_geometry_atlas:netease_block_as_entity_mesh']
    material.update(vertexShader='shaders/glsl/scene_codec_scatter.vertex',
                    fragmentShader='shaders/glsl/scene_codec_scatter.fragment',
                    blendSrc='SourceAlpha', blendDst='OneMinusSrcAlpha', alphaSrc='Zero', alphaDst='One')
    material['-states'] = ['EnableAlphaToCoverage', 'DisableRGBWrite']
    material['+states'] = ['Blending', 'DisableCulling', 'DisableDepthTest', 'DisableDepthWrite', 'DisableAlphaWrite']
    write_json(terrain_path, terrain)
    materials = {}
    for name, filename in entries:
        target = 'scene_codec_'+filename
        (shaders / target).write_bytes(shader_sources[name])
        materials['scene_codec_'+name] = {
            'vertexShader': 'shaders/uv_fullscreen.vertex',
            'fragmentShader': 'shaders/glsl/'+target,
            'vertexFields': [{'field': 'Position'}, {'field': 'UV0'}],
            'samplerStates': [{'samplerIndex': slot, 'textureWrap': 'Clamp', 'textureFilter': 'Point'}
                              for slot in (0, 1, 3, 4, 5)],
            'states': ['DisableDepthTest', 'DisableDepthWrite'],
            '-states': ['DisableAlphaWrite', 'EnableAlphaToCoverage', 'Blending'], 'msaaSupport': 'Both'}
    write_json(resource / 'materials/postprocess.material', materials)
    for pack, kind in [('behavior_pack', 'data'), ('resource_pack', 'resources')]:
        write_json(output / pack / 'manifest.json', {'format_version': 2, 'header': {
            'name': 'Scene codec native '+kind, 'description': 'In-memory RGB blend and alpha block probe',
            'uuid': str(uuid.uuid5(NAMESPACE, pack)), 'version': [0, 0, 1], 'min_engine_version': [1, 18, 0]},
            'modules': [{'type': kind, 'uuid': str(uuid.uuid5(NAMESPACE, pack+'/module')), 'version': [0, 0, 1]}]})
    write_json(output / '.mcdev.json', {
        'game_executable_path': 'D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.448891/Minecraft.Windows.exe',
        'included_mod_dirs': ['./'], 'auto_hot_reload_mods': False, 'auto_hot_reload_ui': False,
        'auto_hot_reload_shaders': False, 'auto_hot_reload_materials': False})
    write_json(output / 'probe_resources.json', {
        'kind': 'scene_codec_probe_v1', 'runtime': {'package': 'geometry_atlas_probe',
         'entrypoint': 'geometry_atlas_probe.modMain', 'system_namespace': 'pmanim_geometry_atlas_probe',
         'system_name': 'probe'}, 'processes': processes, 'game_runtime_file_writes': False,
        'production_resources_modified': False})
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.output))
