"""Freeze a separate package; only native enable flags differ from the engine config."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NATIVE = Path('D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.448891/data')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(output, native_data=NATIVE):
    output = Path(output).resolve()
    if output.exists() or (ROOT/'.runtime').resolve() not in output.parents:
        raise ValueError('Choose a fresh output inside this repository .runtime')
    source_paths = list((HERE.parent/'scene_codec_probe').glob('*.py'))
    source_paths += list((HERE.parent/'scene_codec_probe/shaders').glob('*.fragment'))
    source_paths += [HERE.parent/'scene_codec_probe/inspect.fragment', HERE/'runtime.py',
                     HERE/'diagnostic.fragment', HERE.parent/'scene_codec_compat_probe/scene_server.py',
                     Path(native_data)/'resource_packs/vanilla_netease/graphics_settings/post_process.json']
    manifest = {str(path): {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                           'bytes': path.stat().st_size} for path in source_paths}
    bundle = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode('utf-8')).hexdigest()
    builder = load('rain_geometry_scene_builder', HERE.parent/'scene_codec_probe/build_probe.py')
    builder.build(output)
    package = output/'behavior_pack/geometry_atlas_probe'
    (package/'runtime.py').rename(package/'scene_runtime.py')
    (package/'runtime.py').write_bytes((HERE/'runtime.py').read_bytes())
    (package/'rain_config.py').write_text('SOURCE_BUNDLE_SHA256='+repr(bundle)+'\n', encoding='utf-8')
    (package/'rain_scene_server.py').write_bytes((HERE.parent/'scene_codec_compat_probe/scene_server.py').read_bytes())
    mod = (package/'modMain.py').read_text(encoding='utf-8').replace('pmanim_geometry_atlas_probe', 'pmanim_rain_geometry')
    (package/'modMain.py').write_text(mod, encoding='utf-8')
    shader = output/'resource_pack/shaders/glsl/scene_codec_scatter.fragment'
    writer = shader.read_text(encoding='utf-8')
    shader.write_text(writer.replace('#define SCENE_CODEC_RGB_BITS 0', '#define SCENE_CODEC_RGB_BITS 2'), encoding='utf-8')
    (output/'resource_pack/shaders/glsl/scene_codec_inspect.fragment').write_bytes((HERE/'diagnostic.fragment').read_bytes())
    original = json.loads(source_paths[-1].read_text(encoding='utf-8-sig'))
    for item in original['process_array']:
        item['enable'] = False
    builder.write_json(output/'resource_pack/graphics_settings/post_process.json', original)
    for pack in ('resource_pack', 'behavior_pack'):
        path = output/pack/'manifest.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['header']['name'] = 'Rain transparent geometry probe '+pack
        data['header']['uuid'] = str(uuid.uuid5(uuid.NAMESPACE_URL, 'rain_geometry_probe/'+pack))
        data['modules'][0]['uuid'] = str(uuid.uuid5(uuid.NAMESPACE_URL, 'rain_geometry_probe/'+pack+'/module'))
        builder.write_json(path, data)
    builder.write_json(output/'probe_resources.json', {'kind': 'rain_geometry_probe_v1',
        'source_bundle_sha256': bundle, 'system_namespace': 'pmanim_rain_geometry',
        'physical_size': [720, 1080], 'logical_bytes': 65536,
        'payload_roi': [296, 192, 128, 683], 'rgb_bits': 2,
        'native_effects_off_config': True, 'game_runtime_file_writes': False})
    generated = {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in output.rglob('*') if path.is_file()}
    builder.write_json(output/'source_manifest.json', {'source_bundle_sha256': bundle,
        'inputs': manifest, 'generated_sha256': generated,
        'native_config_changes': ['process_array[*].enable=false'],
        'runtime_file_writes': False, 'continuous_updates': False})
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native-data-root', type=Path, default=NATIVE)
    args = parser.parse_args()
    print(build(args.output, args.native_data_root))
