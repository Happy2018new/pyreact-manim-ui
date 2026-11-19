"""Offline-only isolated native-post candidates; never starts or contacts a game.

Call install() on a fresh carrier from native_stencil_compat_probe.build_probe.
The old native_post_startup receipt remains a frozen record of the input; this
candidate has its own validator because its DOF final material is derived.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import uuid


HERE = Path(__file__).resolve().parent
CASES = ('dof-identity', 'dof-active', 'bloom-control')
RECEIPT = 'native_post_candidate.json'
VIEWPORT, ROI = [720, 1080], [8, 128, 512, 512]
NAMESPACE = uuid.UUID('dcd84210-a43c-4bb8-badb-fc415d0bf19d')
RAW_SAMPLE = re.compile(r'texture\s*\(\s*TEXTURE_1\s*,\s*uv\s*\)')
HELPER_NAME = 'pmanimCandidateClearSample'


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


def derive_dof(source, active=False):
    """Wrap one raw-T1 sample, leaving every original native statement intact.

    Active is a STATIC phase, not a runtime switch. Its runner must enable the
    carrier before enabling DOF and disable DOF before hiding the carrier.
    """
    if HELPER_NAME in source or len(RAW_SAMPLE.findall(source)) != 1:
        raise ValueError('Expected exactly one original raw TEXTURE_1/uv sample')
    required = ('TEXTURE_0', 'TEXTURE_2', 'DEPTH_OF_FIELD_VECTOR4_1',
                'DEPTH_OF_FIELD_FLOAT1_1', 'depth_sample_auto', 'depth_sample_defined')
    if any(name not in source for name in required):
        raise ValueError('Native DOF automatic inputs/math no longer match the candidate')
    first = re.search(r'(?m)^(?:float|vec[234]|void)\s+\w+\s*\(', source)
    if first is None:
        raise ValueError('Native DOF has no recognizable function insertion point')
    body = '    vec4 clearScene = texture(TEXTURE_1, sampleUV);\n'
    if active:
        body += '''    highp vec2 point = floor(vec2(sampleUV.x, 1.0 - sampleUV.y) * vec2(720.0, 1080.0));
    if (point.x >= 8.0 && point.y >= 128.0 && point.x < 520.0 && point.y < 640.0) {
        highp vec3 encoded = floor(clearScene.rgb * 255.0 + 0.5);
        highp vec3 lowSix = mod(encoded, 64.0);
        clearScene.rgb = floor(lowSix * 255.0 / 63.0 + 0.5) / 255.0;
    }
'''
    helper = ('// Isolated candidate: preserve raw alpha, native blur, depth and focus.\n'
              'vec4 ' + HELPER_NAME + '(highp vec2 sampleUV) {\n' + body +
              '    return clearScene;\n}\n\n')
    original_sample = RAW_SAMPLE.search(source).group(0)
    patched = source[:first.start()] + helper + RAW_SAMPLE.sub(HELPER_NAME + '(uv)', source[first.start():])
    # Mechanically reverse the wrapper and require byte-exact native source.
    reversed_source = patched.replace(helper, '', 1).replace(HELPER_NAME + '(uv)', original_sample, 1)
    if reversed_source != source:
        raise AssertionError('Unexpected modification to native DOF math')
    return patched


def _candidate_files(project, game_exe, case, startup):
    native = game_exe.parent / 'data/resource_packs/vanilla_netease'
    files, changes = {}, []
    if case.startswith('dof-'):
        materials = read_json(native / 'materials/postprocess.material')
        old = materials['depth_sample_with_blur']
        if old['fragmentShader'] != 'shaders/depth_sample.fragment':
            raise ValueError('Unexpected native DOF final fragment route')
        source_path = native / 'shaders/glsl/depth_sample.fragment'
        source = source_path.read_text(encoding='utf-8')
        material_name = 'pmanim_dof_candidate_' + case.split('-')[1]
        fragment_name = material_name + '.fragment'
        derived = copy.deepcopy(old)
        derived['fragmentShader'] = 'shaders/glsl/' + fragment_name
        files['resource_pack/materials/native_post_candidate.material'] = json_bytes({material_name: derived})
        files['resource_pack/shaders/glsl/' + fragment_name] = derive_dof(source, case == 'dof-active').encode('utf-8')
        for relative in startup['config_outputs']:
            config = read_json(project / relative)
            index = next(i for i, item in enumerate(config['process_array']) if item['name'] == 'depthoffield')
            effect = config['process_array'][index]
            if effect['pass_array'][-1]['material'] != 'depth_sample_with_blur':
                raise ValueError('Unexpected final DOF material in ' + relative)
            effect['pass_array'][-1]['material'] = material_name
            changes.append(relative + '/process_array/%d/pass_array/%d/material' % (index, len(effect['pass_array'])-1))
            if case == 'dof-active':
                effect['enable'] = False
                changes.append(relative + '/process_array/%d/enable' % index)
            files[relative] = json_bytes(config)
        return files, changes, {'native_dof_fragment': str(source_path), 'native_dof_sha256': sha(source_path),
                               'native_material': old, 'material_name': material_name,
                               'decode_static_enabled': case == 'dof-active',
                               'original_native_math_reversible': True,
                               'native_auto_inputs_preserved': True}
    bloom = module('native_candidate_bloom_resources', HERE / 'bloom.py')
    resources = bloom.resources()
    files['resource_pack/materials/native_post_candidate.material'] = json_bytes(resources['materials'])
    for name, source in resources['shaders'].items():
        if Path(name).name != name or not name.endswith('.fragment'):
            raise ValueError('Unsafe candidate shader basename')
        files['resource_pack/shaders/glsl/' + name] = source.encode('utf-8')
    return files, changes, {'original_bloom_sources_unchanged': True,
                           'source_slot0_ordinary_chain': True, 'explicit_input_slot': 3}


def install(project, game_exe, case):
    """Install only into a caller-created, fresh offline carrier project."""
    if case not in CASES:
        raise ValueError('Unknown isolated candidate case')
    project, game_exe = Path(project).resolve(), Path(game_exe).resolve()
    if (project / RECEIPT).exists():
        raise ValueError('Preserve existing candidates; use a fresh project')
    startup_module = module('native_candidate_startup_assets', HERE.parent / 'native_stencil_post_fixture/assets.py')
    # Startup installer validates the actual game path, hot reload flags,
    # original sources and local prelaunch receipts before doing any writes.
    effect = 'bloom' if case == 'bloom-control' else 'depthoffield'
    startup = startup_module.install_startup(project, effect, game_exe)
    files, changes, detail = _candidate_files(project, game_exe, case, startup)
    mapping = {}
    manifests = {}
    for folder in ('behavior_pack', 'resource_pack'):
        relative = folder + '/manifest.json'
        value = read_json(project / relative)
        for label, item in [('header', value['header'])] + [(str(i), row) for i, row in enumerate(value['modules'])]:
            prior = item['uuid']
            item['uuid'] = str(uuid.uuid5(NAMESPACE, case + '/' + folder + '/' + label))
            mapping[prior] = item['uuid']
        value['header']['name'] = 'Native post candidate ' + case + ' ' + folder
        manifests[relative] = value
    for relative, value in manifests.items():
        for dependency in value.get('dependencies', []):
            dependency['uuid'] = mapping.get(dependency['uuid'], dependency['uuid'])
        files[relative] = json_bytes(value)
    # Record the untouched carrier tree as well as every candidate output.
    before = {str(path.relative_to(project)).replace('\\', '/'): sha(path)
              for folder in ('behavior_pack', 'resource_pack')
              for path in (project / folder).rglob('*') if path.is_file()}
    receipt = {'schema': 'native_post_candidate_build_v1', 'case': case, 'effect': effect,
               'project': str(project), 'game_executable_path': str(game_exe),
               'viewport': VIEWPORT, 'source_roi': ROI, 'capacity': 65536,
               'startup_input': startup, 'startup_receipt_sha256': sha(project / 'native_post_startup.json'),
               'native_detail': detail, 'candidate_changed_paths': changes,
               'native_execution_verified': False, 'compatibility_verified': False,
               'runtime_file_writes': False, 'host_only_offline_install': True,
               'active_requires_identity_gate': case == 'dof-active',
               'active_requires_full_carrier_before_native_enable': case == 'dof-active',
               'source_sha256': sha(__file__),
               'frozen_files': {name: digest for name, digest in before.items() if name not in files},
               'outputs': {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
               'config_file_count': len(startup['config_outputs'])}
    for relative, content in files.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (project / RECEIPT).write_bytes(json_bytes(receipt))
    validate(project, case)
    return receipt


def validate(project, case=None):
    """Read-only source and complete output validation, safe after launch."""
    project = Path(project).resolve()
    receipt = read_json(project / RECEIPT)
    if (receipt.get('schema') != 'native_post_candidate_build_v1'
            or receipt['project'] != str(project) or receipt['case'] not in CASES
            or (case is not None and receipt['case'] != case)):
        raise ValueError('Candidate identity mismatch')
    for name, expected in {**receipt['frozen_files'], **receipt['outputs']}.items():
        if sha(project / name) != expected:
            raise ValueError('Candidate/frozen file changed: ' + name)
    if sha(project / 'native_post_startup.json') != receipt['startup_receipt_sha256']:
        raise ValueError('Frozen startup input receipt changed')
    startup = receipt['startup_input']
    source_records = [startup['native_material']]
    source_records += list(startup['config_outputs'].values())
    source_records += [row for rows in startup['native_shader_sources'].values() for row in rows]
    for row in source_records:
        if sha(row['source_file']) != row.get('sha256', row.get('source_sha256')):
            raise ValueError('Installed native input changed: ' + row['source_file'])
    if receipt['case'].startswith('dof-'):
        detail = receipt['native_detail']
        if sha(detail['native_dof_fragment']) != detail['native_dof_sha256']:
            raise ValueError('Native DOF source changed')
        # Config reconstruction starts from originals rather than already
        # derived project output, so check their exact expected differences.
        for relative, native_row in startup['config_outputs'].items():
            original = read_json(native_row['source_file'])
            for process in original['process_array']:
                process['enable'] = process['name'] == 'depthoffield' and receipt['case'] == 'dof-identity'
                if process['name'] == 'depthoffield':
                    process['pass_array'][-1]['material'] = detail['material_name']
            if read_json(project / relative) != original:
                raise ValueError('DOF config changed beyond final material and enable flags')
        fragment = project / ('resource_pack/shaders/glsl/' + detail['material_name'] + '.fragment')
        source = Path(detail['native_dof_fragment']).read_text(encoding='utf-8')
        if fragment.read_text(encoding='utf-8') != derive_dof(source, receipt['case'] == 'dof-active'):
            raise ValueError('DOF derivative does not preserve exact native math')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--game-exe', type=Path)
    parser.add_argument('--case', choices=CASES, required=True)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    if args.validate_only:
        result = validate(args.project, args.case)
    else:
        if args.game_exe is None:
            parser.error('--game-exe is required for offline install')
        result = install(args.project, args.game_exe, args.case)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
