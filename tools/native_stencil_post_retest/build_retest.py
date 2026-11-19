"""Offline retests with definitions merged into the loaded postprocess map.

Only fresh caller-created carrier projects are accepted. Installed game files,
frozen candidates, previous projects and runtime sessions are never modified.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import uuid


HERE = Path(__file__).resolve().parent
CASES = ('dof-identity', 'dof-active', 'dof-sentinel', 'dof-raw-t1', 'bloom-control')
RECEIPT = 'native_post_retest.json'
VIEWPORT, ROI = [720, 1080], [8, 128, 512, 512]
MATERIAL_PATH = 'resource_pack/materials/postprocess.material'
NAMESPACE = uuid.UUID('e32f445a-b231-46fb-82ca-3b79890edba2')
FROZEN_BUILDER_SHA256 = '2c5fcb7758b2146f2af1bef80cfd73da70248150c07b5fd3e77dd3c6f2c0a19c'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def candidate_builder():
    path = HERE.parent / 'native_stencil_post_candidate/build_candidate.py'
    if sha(path) != FROZEN_BUILDER_SHA256:
        raise ValueError('Frozen candidate shader builder changed')
    return module('frozen_post_candidate_builder_for_retest',
                  path)


def fragment_source(source, case):
    if case == 'dof-identity':
        return source
    if case == 'dof-active':
        return candidate_builder().derive_dof(source, active=True)
    if case not in ('dof-sentinel', 'dof-raw-t1'):
        raise ValueError('Expected a DOF retest case')
    old = 'gl_FragColor = depth_sample2(color);'
    if source.count(old) != 1:
        raise ValueError('Native final DOF assignment changed')
    replacement = ('gl_FragColor = vec4(0.2, 0.8, 0.4, 1.0);' if case == 'dof-sentinel'
                   else 'gl_FragColor = texture(TEXTURE_1, uv);')
    return source.replace(old, replacement, 1)


def _outputs(project, game_exe, case, startup):
    native = game_exe.parent / 'data/resource_packs/vanilla_netease'
    original_materials = read_json(project / MATERIAL_PATH)
    materials = copy.deepcopy(original_materials)
    if 'materials' in materials:
        raise ValueError('The loaded postprocess map must use flat material definitions')
    files = {}
    if case.startswith('dof-'):
        definitions = read_json(native / 'materials/postprocess.material')
        name = 'depth_sample_with_blur'
        original = definitions[name]
        if original['fragmentShader'] != 'shaders/depth_sample.fragment' or name in materials:
            raise ValueError('Unexpected native final material or existing native override')
        path = native / 'shaders/glsl/depth_sample.fragment'
        source = path.read_bytes().decode('utf-8')
        basename = 'pmanim_dof_retest_' + case[4:].replace('-', '_') + '.fragment'
        derived = copy.deepcopy(original)
        # Keep the exact native material name and the native-style shader alias.
        # Its GLSL file remains owned by this isolated offline project.
        derived['fragmentShader'] = 'shaders/' + basename
        materials[name] = derived
        files['resource_pack/shaders/glsl/' + basename] = fragment_source(source, case).encode('utf-8')
        for relative, record in startup['config_outputs'].items():
            config = read_json(project / relative)
            effect = next(item for item in config['process_array'] if item['name'] == 'depthoffield')
            if effect['pass_array'][-1]['material'] != name:
                raise ValueError('Native DOF final pass template changed')
            if case == 'dof-active':
                effect['enable'] = False
            files[relative] = json_bytes(config)
        detail = {'native_dof_fragment': str(path), 'native_dof_sha256': sha(path),
                  'material_name': name, 'native_material': original,
                  'fragment_alias': derived['fragmentShader'],
                  'fragment_file': 'resource_pack/shaders/glsl/' + basename,
                  'native_pass_material_names_preserved': True,
                  'native_pass_templates_preserved': True,
                  'identity_source_byte_exact': case == 'dof-identity',
                  'decode_static_enabled': case == 'dof-active',
                  'sentinel_only': case == 'dof-sentinel'}
    else:
        bloom = module('pinned_bloom_resources_for_retest', HERE / 'bloom_retest.py')
        resources = bloom.resources()
        if set(materials) & set(resources['materials']):
            raise ValueError('Existing carrier collides with owned Bloom material')
        materials.update(resources['materials'])
        for name, source in resources['shaders'].items():
            if Path(name).name != name or not name.endswith('.fragment'):
                raise ValueError('Unsafe Bloom shader basename')
            files['resource_pack/shaders/glsl/' + name] = source.encode('utf-8')
        detail = {'original_bloom_sources_unchanged': True,
                  'source_slot0_ordinary_chain': True, 'explicit_input_slot': 3}
    files[MATERIAL_PATH] = json_bytes(materials)
    detail.update(materials_loaded_via='materials/postprocess.material',
                  original_carrier_materials=original_materials,
                  owned_material_names=sorted(set(materials) - set(original_materials)))
    return files, detail


def install(project, game_exe, case):
    if case not in CASES:
        raise ValueError('Unknown isolated retest case')
    project, game_exe = Path(project).resolve(), Path(game_exe).resolve()
    if any((project / name).exists() for name in (RECEIPT, 'native_post_candidate.json', 'native_post_startup.json')):
        raise ValueError('Preserve prior builds; retest requires a fresh carrier project')
    registration = game_exe.parent / 'data/resource_packs/vanilla_netease/materials/common.json'
    if not any(item.get('path') == 'materials/postprocess.material' for item in read_json(registration)):
        raise ValueError('Installed common.json does not register postprocess.material')
    if any((project / ('resource_pack/materials/' + name)).exists()
           for name in ('common.json', 'fancy.json', 'sad.json')):
        raise ValueError('Retest expects the unmodified installed material registration lists')
    # Authenticate reusable shader generators before the first project write.
    candidate_builder()
    if case == 'bloom-control':
        module('preflight_pinned_bloom_for_retest', HERE / 'bloom_retest.py').resources()
    startup_module = module('original_post_startup_for_retest', HERE.parent / 'native_stencil_post_fixture/assets.py')
    effect = 'bloom' if case == 'bloom-control' else 'depthoffield'
    startup = startup_module.install_startup(project, effect, game_exe)
    files, detail = _outputs(project, game_exe, case, startup)
    mapping, manifests = {}, {}
    for folder in ('behavior_pack', 'resource_pack'):
        relative = folder + '/manifest.json'
        value = read_json(project / relative)
        for label, item in [('header', value['header'])] + [(str(i), row) for i, row in enumerate(value['modules'])]:
            previous = item['uuid']
            item['uuid'] = str(uuid.uuid5(NAMESPACE, case + '/' + folder + '/' + label))
            mapping[previous] = item['uuid']
        value['header']['name'] = 'Native post retest ' + case + ' ' + folder
        manifests[relative] = value
    for relative, value in manifests.items():
        for dependency in value.get('dependencies', []):
            dependency['uuid'] = mapping.get(dependency['uuid'], dependency['uuid'])
        files[relative] = json_bytes(value)
    before = {str(path.relative_to(project)).replace('\\', '/'): sha(path)
              for folder in ('behavior_pack', 'resource_pack')
              for path in (project / folder).rglob('*') if path.is_file()}
    receipt = {'schema': 'native_post_retest_build_v1', 'case': case, 'effect': effect,
               'project': str(project), 'game_executable_path': str(game_exe),
               'viewport': VIEWPORT, 'source_roi': ROI, 'capacity': 65536,
               'startup_input': startup, 'startup_receipt_sha256': sha(project / 'native_post_startup.json'),
               'native_detail': detail, 'native_execution_verified': False,
               'compatibility_verified': False, 'runtime_file_writes': False,
               'host_only_offline_install': True, 'source_sha256': sha(__file__),
               'material_registration': {'source_file': str(registration), 'sha256': sha(registration),
                                         'loaded_path': 'materials/postprocess.material'},
               'active_requires_identity_gate': case == 'dof-active',
               'frozen_files': {name: value for name, value in before.items() if name not in files},
               'outputs': {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}}
    for relative, content in files.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (project / RECEIPT).write_bytes(json_bytes(receipt))
    validate(project, case)
    return receipt


def validate(project, case=None):
    project = Path(project).resolve()
    receipt = read_json(project / RECEIPT)
    if (receipt.get('schema') != 'native_post_retest_build_v1' or receipt['project'] != str(project)
            or receipt['case'] not in CASES or (case is not None and receipt['case'] != case)):
        raise ValueError('Retest identity mismatch')
    actual_files = {str(path.relative_to(project)).replace('\\', '/')
                    for folder in ('behavior_pack', 'resource_pack')
                    for path in (project / folder).rglob('*') if path.is_file()}
    if actual_files != set(receipt['frozen_files']) | set(receipt['outputs']):
        raise ValueError('Retest pack file inventory changed')
    for name, expected in {**receipt['frozen_files'], **receipt['outputs']}.items():
        if sha(project / name) != expected:
            raise ValueError('Retest/frozen file changed: ' + name)
    if sha(project / 'native_post_startup.json') != receipt['startup_receipt_sha256']:
        raise ValueError('Frozen startup input receipt changed')
    startup = receipt['startup_input']
    registration = receipt['material_registration']
    if not any(item.get('path') == registration['loaded_path'] for item in read_json(registration['source_file'])):
        raise ValueError('Installed material registration changed')
    if any((project / ('resource_pack/materials/' + name)).exists()
           for name in ('common.json', 'fancy.json', 'sad.json')):
        raise ValueError('Project overrides installed material registration')
    records = [startup['native_material'], registration] + list(startup['config_outputs'].values())
    records += [row for rows in startup['native_shader_sources'].values() for row in rows]
    for row in records:
        if sha(row['source_file']) != row.get('sha256', row.get('source_sha256')):
            raise ValueError('Installed native input changed: ' + row['source_file'])
    detail = receipt['native_detail']
    materials = read_json(project / MATERIAL_PATH)
    for name, value in detail['original_carrier_materials'].items():
        if materials.get(name) != value:
            raise ValueError('Carrier material changed: ' + name)
    if set(materials) != set(detail['original_carrier_materials']) | set(detail['owned_material_names']):
        raise ValueError('Unexpected material map entries')
    for relative, record in startup['config_outputs'].items():
        original = read_json(record['source_file'])
        for process in original['process_array']:
            process['enable'] = process['name'] == receipt['effect'] and receipt['case'] != 'dof-active'
        if read_json(project / relative) != original:
            raise ValueError('Native process config changed beyond isolated enable flags')
    if receipt['case'].startswith('dof-'):
        expected = copy.deepcopy(detail['native_material'])
        expected['fragmentShader'] = detail['fragment_alias']
        if materials.get('depth_sample_with_blur') != expected:
            raise ValueError('Native named DOF material changed beyond isolated shader route')
        source = Path(detail['native_dof_fragment']).read_bytes().decode('utf-8')
        if sha(detail['native_dof_fragment']) != detail['native_dof_sha256']:
            raise ValueError('Native DOF input changed')
        if (project / detail['fragment_file']).read_bytes().decode('utf-8') != fragment_source(source, receipt['case']):
            raise ValueError('DOF retest shader changed')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--game-exe', type=Path)
    parser.add_argument('--case', choices=CASES, required=True)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    if not args.validate_only and args.game_exe is None:
        parser.error('--game-exe is required for offline install')
    result = validate(args.project, args.case) if args.validate_only else install(args.project, args.game_exe, args.case)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
