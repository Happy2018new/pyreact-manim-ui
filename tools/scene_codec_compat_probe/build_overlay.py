"""Host-only resource overlay preserving native bloom and depth-of-field math.

Build resources before launch. The identity and carrier variants require separate
runs. Game Python never writes resources. Native TEXTURE_0 is already restored;
only raw scene TEXTURE_1 is decoded, and only inside the compile-fixed writer ROI.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil


TARGETS = (
    ('bloom', 'daul_blur_up_blend', 'daul_blur_up_sample.fragment',
     'pmanim_scene_compat_bloom_final'),
    ('depthoffield', 'depth_sample_with_blur', 'depth_sample.fragment',
     'pmanim_scene_compat_dof_final'),
)
ALPHA_PROCESS = {
    'name': 'pmanim_scene_compat_alpha_math', 'enable': False,
    'paras': [{'name': 'alpha', 'value': [-1., 0., 0., 0.], 'range': [-1., 255.]}],
    'pass_array': [{'render_target': {'width': 1., 'height': 1.},
                    'material': 'pmanim_scene_compat_alpha_math', 'depth_enable': False}],
}
SAMPLE = re.compile(r'texture\s*\(\s*TEXTURE_1\s*,\s*uv\s*\)')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_layout(physical_size, roi, rgb_bits):
    if len(physical_size) != 2 or len(roi) != 4:
        raise ValueError('Expected physical width,height and ROI left,top,width,height')
    if any(isinstance(value, bool) or int(value) != value for value in tuple(physical_size) + tuple(roi)):
        raise ValueError('Physical size and ROI must use integer pixels')
    width, height = physical_size
    left, top, roi_width, roi_height = roi
    if min(width, height, roi_width, roi_height) <= 0 or min(left, top) < 0:
        raise ValueError('Invalid physical size or ROI')
    if left + roi_width > width or top + roi_height > height:
        raise ValueError('Writer ROI exceeds physical render target')
    if rgb_bits not in (1, 2, 3):
        raise ValueError('Supported high RGB carrier bit counts are 1, 2, 3')


def helper_source(physical_size, roi, rgb_bits, carrier_decode):
    if not carrier_decode:
        return ('highp vec4 pmanimSceneCompatSample(highp vec2 sampleUV) {\n'
                '    return texture(TEXTURE_1, sampleUV);\n}\n\n')
    width, height = physical_size
    left, top, roi_width, roi_height = roi
    levels = 2 ** (8 - rgb_bits)
    return '''// Decode only the raw scene binding. Preserve its alpha and native uniforms.
highp vec4 pmanimSceneCompatSample(highp vec2 sampleUV) {
    highp vec4 rawScene = texture(TEXTURE_1, sampleUV);
    highp vec2 point = floor(vec2(sampleUV.x, 1.0 - sampleUV.y) * vec2(%d.0, %d.0));
    if (point.x >= %d.0 && point.y >= %d.0 && point.x < %d.0 && point.y < %d.0) {
        highp vec3 code = floor(rawScene.rgb * 255.0 + 0.5);
        highp vec3 quantized = mod(code, %d.0);
        rawScene.rgb = floor(quantized * 255.0 / %d.0 + 0.5) / 255.0;
    }
    return rawScene;
}

''' % (width, height, left, top, left + roi_width, top + roi_height, levels, levels - 1)


def patch_fragment(source, physical_size, roi, rgb_bits, carrier_decode):
    if len(SAMPLE.findall(source)) != 1:
        raise ValueError('Native shader changed: expected exactly one raw TEXTURE_1/uv sample')
    patched = SAMPLE.sub('pmanimSceneCompatSample(uv)', source)
    first_function = re.search(r'(?m)^(?:float|vec[234]|void)\s+\w+\s*\(', patched)
    if first_function is None:
        raise ValueError('Native shader has no recognized insertion point')
    offset = first_function.start()
    return patched[:offset] + helper_source(physical_size, roi, rgb_bits, carrier_decode) + patched[offset:]


def changed_paths(before, after, path=''):
    if isinstance(before, dict) and isinstance(after, dict) and before.keys() == after.keys():
        result = []
        for key in before:
            result.extend(changed_paths(before[key], after[key], path + '/' + str(key)))
        return result
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        result = []
        for index, (old, new) in enumerate(zip(before, after)):
            result.extend(changed_paths(old, new, path + '/' + str(index)))
        return result
    return [] if before == after else [path]


def derive_native_effects(original, materials, native, shaders, layout):
    config, derived, records = copy.deepcopy(original), {}, []
    expected_paths, source_hashes = [], {}
    for process_name, material_name, fragment_name, owned_name in TARGETS:
        matches = [(index, item) for index, item in enumerate(config['process_array'])
                   if item['name'] == process_name]
        if len(matches) != 1:
            raise ValueError('Native process is missing or duplicated: ' + process_name)
        process_index, process = matches[0]
        passes = process['pass_array']
        if passes[-1]['material'] != material_name:
            raise ValueError('Native final pass changed: ' + process_name)
        original_material = materials[material_name]
        if Path(original_material['fragmentShader']).name != fragment_name:
            raise ValueError('Native material fragment changed: ' + material_name)
        native_fragment = native / 'shaders/glsl' / fragment_name
        source_hashes[str(native_fragment)] = sha(native_fragment)
        source = native_fragment.read_text(encoding='utf-8')
        target_name = owned_name + '.fragment'
        (shaders / target_name).write_text(patch_fragment(
            source, *layout), encoding='utf-8')
        derived[owned_name] = copy.deepcopy(original_material)
        derived[owned_name]['fragmentShader'] = 'shaders/glsl/' + target_name
        passes[-1]['material'] = owned_name
        change_path = '/process_array/%d/pass_array/%d/material' % (process_index, len(passes) - 1)
        expected_paths.append(change_path)
        records.append({'process': process_name, 'pass_index': len(passes) - 1,
                        'old_material': material_name, 'new_material': owned_name,
                        'config_change_path': change_path,
                        'native_parameters': copy.deepcopy(process.get('paras')),
                        'native_pass_count': len(passes),
                        'native_final_pass': copy.deepcopy(original['process_array'][process_index]['pass_array'][-1]),
                        'material_changed_paths': changed_paths(original_material, derived[owned_name])})
    actual_paths = changed_paths(original, config)
    if sorted(actual_paths) != sorted(expected_paths):
        raise ValueError('Unexpected native post-process mutation: ' + repr(actual_paths))
    return config, derived, records, source_hashes, actual_paths


def native_math_validation(original):
    return {
        'fixture_process': ALPHA_PROCESS,
        'fixture_scope': 'synthetic bloom threshold check; not real-world alpha or native DOF equivalence',
        'legacy_threshold_formula': 'mask = step(threshold, 1 - restored_source_alpha)',
        'threshold': next(item for item in original['process_array'] if item['name'] == 'bloom')['paras']['threshold'],
        'alpha_bytes_at_threshold_half': [{'alpha': 0, 'mask': 1}, {'alpha': 127, 'mask': 1},
                                         {'alpha': 128, 'mask': 0}, {'alpha': 255, 'mask': 0}],
        'procedure': ['Keep restored RGB, raw T1, writer, camera and native bloom parameters fixed.',
                      'Insert the custom alpha-only fixture after final restored source and before native bloom.',
                      'In a later render turn connect restored source to fixture TEXTURE_3, then enable it.',
                      'Use public DOF disable for isolated bloom check; restore the prior DOF state afterward.',
                      'Capture alpha=-1 identity and alpha=0,127,128,255 with effect and source receipts.',
                      'Check alpha=0/127 agree and alpha=128/255 agree; the former must show bloom contribution.',
                      'At a stable bright patch compare native eight-tap upsample + clamp(maxBrightness)*intensity + decoded rawT1.',
                      'Disable fixture for all real-world alpha/payload compatibility and performance cases.'],
        'required_evidence': ['unchanged restored RGB hash', 'source alpha and native enable state',
                              'effect-on image differences in fixed ROI',
                              'native effect parameter/config hashes', 'exact alpha and full payload checks'],
    }


def write_optional_fixtures(resource, derived):
    shaders = resource / 'shaders/glsl'
    fixture_path = Path(__file__).resolve().parent / 'alpha_math_fixture.fragment'
    shutil.copyfile(fixture_path, shaders / 'pmanim_scene_compat_alpha_math.fragment')
    particle_path = Path(__file__).resolve().parent / 'translucent.particle.json'
    particle_output = resource / 'particles/pmanim_scene_compat_translucent.particle.json'
    particle_output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(particle_path, particle_output)
    derived['pmanim_scene_compat_alpha_math'] = {
        'vertexShader': 'shaders/uv_fullscreen.vertex',
        'fragmentShader': 'shaders/glsl/pmanim_scene_compat_alpha_math.fragment',
        'vertexFields': [{'field': 'Position'}, {'field': 'UV0'}],
        'samplerStates': [{'samplerIndex': 3, 'textureWrap': 'Clamp', 'textureFilter': 'Point'}],
        'states': ['DisableDepthTest', 'DisableDepthWrite'],
        '-states': ['DisableAlphaWrite', 'EnableAlphaToCoverage', 'Blending'], 'msaaSupport': 'Both',
    }


def particle_validation():
    return {
        'identifier': 'pmanim_scene_compat:translucent', 'material': 'particles_blend',
        'tint_alpha': .35,
        'source': 'Derived from vanilla_netease/particles/netease_tutorial.particle.json: '
                  'identifier, material, active_time and constant RGBA tint changed.',
        'classification': 'real Bedrock particle rendering; random motion requires same-frame comparisons',
        'must_check': ['Visible pixels overlap writer ROI', 'source alpha has non-255 values',
                       'full payload remains exact if particles draw after the carrier geometry'],
    }


def build_overlay(output, native_data_root, physical_size, roi, rgb_bits=2,
                  carrier_decode=True, renderer_branch='legacy'):
    """Return a manifest; output/resource_pack can be installed into a built probe."""
    validate_layout(physical_size, roi, rgb_bits)
    if renderer_branch != 'legacy':
        raise ValueError('RNGL is unverified: bloom scene color uses TEXTURE_2; legacy only')
    output, native = Path(output).resolve(), Path(native_data_root).resolve()
    if (output / 'resource_pack/manifest.json').exists():
        raise ValueError('Build overlay in a separate directory, then use install_overlay(project, overlay)')
    native_pack = native / 'resource_packs/vanilla_netease'
    config_path = native_pack / 'graphics_settings/post_process.json'
    materials_path = native_pack / 'materials/postprocess.material'
    original = json.loads(config_path.read_text(encoding='utf-8-sig'))
    materials = json.loads(materials_path.read_text(encoding='utf-8-sig'))
    resource = output / 'resource_pack'
    shaders = resource / 'shaders/glsl'
    shaders.mkdir(parents=True, exist_ok=True)
    config, derived, records, source_hashes, actual_paths = derive_native_effects(
        original, materials, native, shaders, (physical_size, roi, rgb_bits, carrier_decode))
    source_hashes.update({str(config_path): sha(config_path), str(materials_path): sha(materials_path)})
    write_optional_fixtures(resource, derived)
    write_json(resource / 'graphics_settings/post_process.json', config)
    write_json(resource / 'materials/postprocess.material', derived)
    manifest = {
        'kind': 'scene_codec_native_compat_overlay_v1', 'renderer_branch': renderer_branch,
        'carrier_decode': bool(carrier_decode), 'physical_size': list(physical_size),
        'roi_top_left_pixels': list(roi), 'rgb_bits': rgb_bits,
        'native_data_root': str(native), 'source_sha256': source_hashes,
        'native_render_order': copy.deepcopy(original['render_order']),
        'config_changed_paths': actual_paths, 'effects': records,
        'unmodified': ['all native effect parameters', 'render order', 'enable states',
                       'pass counts and target sizes', 'shaderPassName', 'TEXTURE_0 and TEXTURE_2 reads',
                       'native uniforms, sampler states, material variants', 'raw source alpha'],
        'runtime_contract': {
            'insert_restored_source_before_native_effects': True,
            'decode_only_raw_texture_1_within_writer_roi': True,
            'new_uniform_bindings': [], 'game_runtime_file_writes': False,
            'same_roi_physical_size_and_k_as_writer_required': True,
            'baseline': 'Build carrier_decode=False, disable carrier writer, restart; compare against vanilla.',
            'carrier': 'Build carrier_decode=True, enable writer, restart; T0 must already be restored.',
            'limitations': ['legacy renderer only; RNGL scene-color T2 path remains unverified',
                            'ROI must contain only the intended writer; overlays drawn after it need separate verification',
                            'independent runs require deterministic scene/time/weather and are not an atomic reference'],
        },
        'validation_status': 'offline construction only; native loading, images and alpha/effect math require game evidence',
        'particle_fixture': particle_validation(),
        'native_math_validation': native_math_validation(original),
    }
    manifest['output_sha256'] = {str(path.relative_to(output)).replace('\\', '/'): sha(path)
                                 for path in sorted(resource.rglob('*')) if path.is_file()}
    write_json(output / 'compat_manifest.json', manifest)
    return manifest


def install_overlay(project, overlay):
    """Host merge preserving all previously generated custom material entries."""
    project, overlay = Path(project).resolve(), Path(overlay).resolve()
    if not (project / 'resource_pack/manifest.json').exists():
        raise ValueError('Expected an already built project with resource_pack/manifest.json')
    manifest = json.loads((overlay / 'compat_manifest.json').read_text(encoding='utf-8'))
    source = overlay / 'resource_pack'
    for relative, expected_sha in manifest['output_sha256'].items():
        if sha(overlay / relative) != expected_sha:
            raise ValueError('Overlay file changed after build: ' + relative)
    target_material = project / 'resource_pack/materials/postprocess.material'
    existing = json.loads(target_material.read_text(encoding='utf-8')) if target_material.exists() else {}
    owned = json.loads((source / 'materials/postprocess.material').read_text(encoding='utf-8'))
    if 'materials' in existing:
        raise ValueError('Native postprocess materials require the flat material format')
    existing.update(owned)
    write_json(target_material, existing)
    for path in source.rglob('*'):
        if not path.is_file() or path == source / 'materials/postprocess.material':
            continue
        target = project / 'resource_pack' / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    write_json(project / 'scene_codec_compat_manifest.json', manifest)
    package = project / 'behavior_pack/geometry_atlas_probe'
    if package.is_dir():
        here = Path(__file__).resolve().parent
        for filename in ('runtime_client.py', 'scene_server.py'):
            shutil.copyfile(here / filename, package / ('compat_' + filename))
        config = {key: manifest[key] for key in ('physical_size', 'roi_top_left_pixels',
                                                'rgb_bits', 'carrier_decode', 'renderer_branch')}
        (package / 'compat_config.py').write_text('CONFIG = ' + repr(config) + '\nALPHA_PROCESS = ' +
                                                repr(ALPHA_PROCESS) + '\n', encoding='utf-8')
    return project


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--native-data-root', required=True, type=Path)
    parser.add_argument('--physical', type=int, nargs=2, required=True)
    parser.add_argument('--roi', type=int, nargs=4, required=True)
    parser.add_argument('--rgb-bits', type=int, default=2)
    parser.add_argument('--identity-baseline', action='store_true')
    parser.add_argument('--install-project', type=Path)
    args = parser.parse_args()
    manifest = build_overlay(args.output, args.native_data_root, args.physical, args.roi,
                             args.rgb_bits, not args.identity_baseline)
    if args.install_project:
        install_overlay(args.install_project, args.output)
    print(json.dumps({'output': str(args.output), 'carrier_decode': manifest['carrier_decode'],
                      'config_changed_paths': manifest['config_changed_paths']}))
