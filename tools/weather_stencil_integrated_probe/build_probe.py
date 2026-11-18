"""Extend the frozen bulk probe with three linked integrated post processes."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import uuid


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SHADERS = ('copy.fragment', 'restore.fragment', 'consumer.fragment')
NAMESPACE = uuid.UUID('9aa91911-9c0d-452e-8ef4-5a3d58f5af7d')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')


def post_material(fragment):
    return {'vertexShader': 'shaders/uv_fullscreen.vertex',
            'fragmentShader': 'shaders/glsl/stencil_integrated_'+fragment,
            'vertexFields': [{'field': 'Position'}, {'field': 'UV0'}],
            'samplerStates': [{'samplerIndex': index, 'textureWrap': 'Clamp',
                               'textureFilter': 'Point'} for index in (0, 1, 3, 4)],
            'states': ['DisableDepthTest', 'DisableDepthWrite'],
            '-states': ['DisableAlphaWrite', 'EnableAlphaToCoverage', 'Blending'],
            'msaaSupport': 'Both'}


def build(output, game_exe, include_ui=False, include_outline=False):
    # Read the integrated inputs before the base builder creates its fresh output.
    sources = {name: (HERE/name).read_bytes() for name in ('runtime.py', 'modMain.py')+SHADERS}
    scene_sources = {
        'scene_fixtures.py': (HERE.parent/'scene_codec_compat_probe/scene_server.py').read_bytes(),
        'translucent.particle.json': (HERE.parent/'scene_codec_compat_probe/translucent.particle.json').read_bytes()}
    known_builder = module('integrated_known_fixture_assets', HERE/'known_fixture_assets.py')
    ui_builder = (module('integrated_ui_fixture_assets', HERE.parent/'integrated_ui_clip_fixture/build_fixture.py')
                  if include_ui else None)
    outline_builder = (module('integrated_outline_fixture_assets', HERE.parent/'integrated_outline_fixture/build_fixture.py')
                       if include_outline else None)
    bulk = module('integrated_frozen_bulk_builder', HERE.parent/'weather_stencil_large_probe/build_probe.py')
    output = bulk.build(output, game_exe)
    behavior, resource = output/'behavior_pack', output/'resource_pack'
    package = behavior/'stencil_large'
    base_receipt = json.loads((output/'probe_resources.json').read_text(encoding='utf-8'))
    base_runtime_hash = hashlib.sha256((package/'runtime.py').read_bytes()).hexdigest()
    for folder in ('behavior_pack', 'resource_pack'):
        path = output/folder/'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['header']['uuid'] = str(uuid.uuid5(NAMESPACE, folder+'/header'))
        manifest['header']['name'] = 'Integrated stencil probe '+folder
        for index, value in enumerate(manifest['modules']):
            value['uuid'] = str(uuid.uuid5(NAMESPACE, folder+'/module/'+str(index)))
        write_json(path, manifest)
    (package/'integrated_runtime.py').write_bytes(sources['runtime.py'])
    (package/'modMain.py').write_bytes(sources['modMain.py'])
    (package/'scene_fixtures.py').write_bytes(scene_sources['scene_fixtures.py'])
    particle_path = resource/'particles/pmanim_scene_compat_translucent.particle.json'
    particle_path.parent.mkdir(parents=True, exist_ok=True)
    particle_path.write_bytes(scene_sources['translucent.particle.json'])
    (package/'integrated_config.py').write_text(
        '# -*- coding: utf-8 -*-\nWITH_UI = '+repr(bool(include_ui))+'\nWITH_OUTLINE = '+repr(bool(include_outline))+'\n',
        encoding='utf-8')
    fixture_info = known_builder.add_known_fixture(output)
    ui_info = (ui_builder.install(resource, package, package_name='stencil_large',
                                 source_roi=[8, 128, 512, 512],
                                 diagnostic_rects=[[408, 704, 296, 304]], physical=(720, 1080))
               if ui_builder is not None else None)
    outline_info = outline_builder.build_assets(output, game_exe) if outline_builder is not None else None
    materials_path = resource/'materials/postprocess.material'
    materials = json.loads(materials_path.read_text(encoding='utf-8'))
    for name in SHADERS:
        (resource/'shaders/glsl'/('stencil_integrated_'+name)).write_bytes(sources[name])
        materials['stencil_integrated_'+name.split('.')[0]] = post_material(name)
    write_json(materials_path, materials)
    receipt = dict(base_receipt)
    receipt.update(kind='weather_stencil_integrated_v1', version=1,
        runtime={'package': 'stencil_large', 'entrypoint': 'stencil_large.modMain',
                 'system_namespace': 'pmanim_stencil_integrated', 'system_name': 'probe',
                 'class': 'stencil_large.integrated_runtime.ProbeSystem'},
        runtime_namespace='pmanim_stencil_integrated', postprocess_pass_count=3,
        integrated_manifest_uuid_namespace=str(NAMESPACE),
        postprocess_materials=list(materials),
        integrated_processes=['stencil_integrated_copy', 'stencil_integrated_restore', 'stencil_integrated_consumer'],
        integrated_texture_links=[['stencil_integrated_copy', 0, 'stencil_integrated_restore', 0, 3],
                                  ['stencil_integrated_copy', 0, 'stencil_integrated_consumer', 0, 3],
                                  ['stencil_integrated_restore', 0, 'stencil_integrated_consumer', 0, 4]],
        frozen_bulk_runtime_sha256=base_runtime_hash, frozen_bulk_receipt=base_receipt,
        integrated_source_hashes={name: hashlib.sha256(value).hexdigest() for name, value in sources.items()},
        integrated_builder_sha256=hashlib.sha256((HERE/'build_probe.py').read_bytes()).hexdigest(),
        optional_scene_fixture_source_hashes={name: hashlib.sha256(value).hexdigest()
                                             for name, value in scene_sources.items()},
        optional_scene_fixture_registered=False,
        known_fixture=fixture_info, ui_clip_fixture=ui_info, outline_fixture=outline_info,
        diagnostic_output_y=128, shape_bounds=[408, 704, 296, 304],
        integrated_native_verified=False, same_frame_alpha_preservation_verified=False,
        native_ui_compatibility_verified=False, native_outline_compatibility_verified=False,
        performance_claimed=False)
    if hashlib.sha256((package/'runtime.py').read_bytes()).hexdigest() != base_runtime_hash:
        raise RuntimeError('Integrated hooks changed the frozen bulk runtime')
    write_json(output/'probe_resources.json', receipt)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--game-exe', required=True)
    parser.add_argument('--include-ui', action='store_true')
    parser.add_argument('--include-outline', action='store_true')
    args = parser.parse_args()
    print(build(args.output, args.game_exe, args.include_ui, args.include_outline))
