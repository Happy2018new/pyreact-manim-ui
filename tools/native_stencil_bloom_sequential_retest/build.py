"""Build two offline Bloom controls without changing installed game resources.

Only fresh carrier projects are accepted. The source-control phase starts every
native effect disabled; native starts only the original Bloom. Both packages
carry the same owned source/observer resources. Importing this module is inert.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import uuid


HERE = Path(__file__).resolve().parent
PHASES = ('source-control', 'native')
SCHEMA = 'native_bloom_sequential_build_v1'
RECEIPT = 'native_bloom_sequential_build.json'
MATERIAL_PATH = 'resource_pack/materials/postprocess.material'
SOURCE = 'pmanim_bloom_candidate_source'
OBSERVER = 'pmanim_bloom_sequential_observer'
NAMESPACE = uuid.UUID('f6285361-bb35-5cf8-91da-e00110e98f88')


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


def runner_module():
    return module('sequential_bloom_resources_for_build', HERE / 'runner.py')


def resources():
    """Load the shared resources lazily and independently pin the source."""
    pinned = module('pinned_bloom_source_for_sequential_build',
                    HERE.parent / 'native_stencil_post_retest/bloom_retest.py').resources()
    value = runner_module().resources()
    if set(value) != {'materials', 'shaders'} or set(value['materials']) != {SOURCE, OBSERVER}:
        raise ValueError('Sequential Bloom requires exactly the two owned materials')
    expected = copy.deepcopy(pinned['materials'][SOURCE])
    expected['fragmentShader'] = 'shaders/' + SOURCE + '.fragment'
    if (value['materials'][SOURCE] != expected
            or value['shaders'].get(SOURCE + '.fragment') != pinned['shaders'][SOURCE + '.fragment']):
        raise ValueError('Sequential Bloom source differs from the pinned candidate')
    expected_shaders = {name + '.fragment' for name in (SOURCE, OBSERVER)}
    if set(value['shaders']) != expected_shaders:
        raise ValueError('Unexpected sequential Bloom shader inventory')
    for name, source in value['shaders'].items():
        if ('/' in name or '\\' in name or not isinstance(source, str)
                or value['materials'][name[:-9]].get('fragmentShader') != 'shaders/' + name):
            raise ValueError('Owned shaders must use the native shaders/ filename alias')
    return value


def _startup_module():
    return module('original_native_startup_for_sequential_bloom',
                  HERE.parent / 'native_stencil_post_fixture/assets.py')


def _phase(phase):
    if phase not in PHASES:
        raise ValueError('Unknown sequential Bloom phase')
    return phase


def _pack_files(project):
    result = {}
    for folder in ('behavior_pack', 'resource_pack'):
        for path in (project / folder).rglob('*'):
            if path.is_symlink():
                raise ValueError('Sequential Bloom packs cannot contain symbolic links')
            if path.is_file():
                result[path.relative_to(project).as_posix()] = sha(path)
    return result


def _registration(project, game_exe):
    native = game_exe.parent / 'data/resource_packs/vanilla_netease'
    paths = [native / 'materials/common.json']
    common = read_json(paths[0])
    if not any(row.get('path') == 'materials/postprocess.material' for row in common):
        raise ValueError('Installed common.json does not register postprocess.material')
    for name in ('common.json', 'fancy.json', 'sad.json'):
        if (project / 'resource_pack/materials' / name).exists():
            raise ValueError('Project overrides the installed material registration')
        path = native / 'materials' / name
        if name != 'common.json' and path.exists():
            paths.append(path)
    return {str(path): sha(path) for path in paths}


def _native_plan(project, game_exe, phase, startup_module):
    native = game_exe.parent / 'data/resource_packs/vanilla_netease'
    files, targets, records = {}, [], _registration(project, game_exe)
    for name in startup_module.CONFIG_NAMES:
        config, target, record = startup_module._config(native, name, 'bloom')
        for process in config['process_array']:
            process['enable'] = phase == 'native' and process['name'] == 'bloom'
        files['resource_pack/graphics_settings/' + name] = json_bytes(config)
        targets.append(target)
        records[record['source_file']] = record['source_sha256']
    material, shaders = startup_module._native_sources(project, game_exe, targets)
    records[material['source_file']] = material['sha256']
    for rows in shaders.values():
        for row in rows:
            records[row['source_file']] = row['sha256']
    return files, records


def _manifests(originals, phase):
    values, mapping = copy.deepcopy(originals), {}
    for relative, value in values.items():
        folder = relative.split('/')[0]
        for label, item in [('header', value['header'])] + [
                ('module/' + str(index), row) for index, row in enumerate(value['modules'])]:
            old = item['uuid']
            if old in mapping:
                raise ValueError('Carrier manifests contain duplicate UUIDs')
            item['uuid'] = str(uuid.uuid5(NAMESPACE, phase + '/' + folder + '/' + label))
            mapping[old] = item['uuid']
        value['header']['name'] = 'Sequential Bloom ' + phase + ' ' + folder
    for value in values.values():
        for dependency in value.get('dependencies', []):
            dependency['uuid'] = mapping.get(dependency.get('uuid'), dependency.get('uuid'))
    return {relative: json_bytes(value) for relative, value in values.items()}


def _outputs(project, game_exe, phase, originals, owned, startup_module):
    materials = copy.deepcopy(originals['materials'])
    if not isinstance(materials, dict) or 'materials' in materials:
        raise ValueError('Carrier requires a flat loaded postprocess material map')
    if set(materials) & set(owned['materials']):
        raise ValueError('Carrier collides with owned sequential Bloom materials')
    materials.update(owned['materials'])
    files, inputs = _native_plan(project, game_exe, phase, startup_module)
    files[MATERIAL_PATH] = json_bytes(materials)
    for name, source in owned['shaders'].items():
        files['resource_pack/shaders/glsl/' + name] = source.encode('utf-8')
    files.update(_manifests(originals['manifests'], phase))
    return files, inputs


def _prelaunch(project):
    paths = [project / 'launch.json']
    for root in (project, project.parent):
        paths.extend(root / folder / name for folder in ('evidence', 'run-evidence')
                     for name in ('launch.json', 'assigned-session.json', 'assigned-session-snapshot.json'))
        paths.extend(root / name for name in ('assigned-session.json', 'assigned-session-snapshot.json'))
    found = [str(path) for path in paths if path.exists()]
    if found:
        raise ValueError('Build sequential Bloom before launch; launch/session receipt exists: ' + ', '.join(found))
    return [str(path) for path in paths]


def install(project, game_exe, phase):
    """Install a fresh offline carrier variant; never launch or contact a game."""
    phase = _phase(phase)
    project, game_exe = Path(project).resolve(), Path(game_exe).resolve()
    if any((project / name).exists() for name in (
            RECEIPT, 'native_post_startup.json', 'native_post_candidate.json', 'native_post_retest.json')):
        raise ValueError('Sequential Bloom requires a fresh carrier project')
    checked = _prelaunch(project)
    startup_module = _startup_module()
    startup_module._project(project, game_exe)
    owned = resources()  # Authenticate every generated source before a write.
    identity = runner_module().fixture_identity()
    originals = {'materials': read_json(project / MATERIAL_PATH), 'manifests': {
        folder + '/manifest.json': read_json(project / folder / 'manifest.json')
        for folder in ('behavior_pack', 'resource_pack')}}
    files, inputs = _outputs(project, game_exe, phase, originals, owned, startup_module)
    before = _pack_files(project)
    for name in owned['shaders']:
        if (project / 'resource_pack/shaders/glsl' / name).exists() or (
                project / 'resource_pack/shaders' / name).exists():
            raise ValueError('Carrier overrides an owned sequential Bloom shader')
    # Reuse the reviewed original-native fixture's preflight and receipt. Its
    # intermediate Bloom-only flags are replaced by the exact phase plan below.
    startup = startup_module.install_startup(project, 'bloom', game_exe)
    receipt = {'schema': SCHEMA, 'phase': phase, 'effect': 'bloom',
               'project': str(project), 'game_executable_path': str(game_exe),
               'startup_enabled_effects': ['bloom'] if phase == 'native' else [],
               'startup_input': startup, 'startup_receipt_sha256': sha(project / 'native_post_startup.json'),
               'original_carrier': originals, 'fixture_identity': identity,
               'resources_sha256': hashlib.sha256(json_bytes(owned)).hexdigest(),
               'native_input_sources': inputs, 'source_sha256': sha(__file__),
               'dependency_sources': {str(HERE / 'runner.py'): sha(HERE / 'runner.py'),
                                      str(Path(startup_module.__file__)): sha(startup_module.__file__)},
               'control_files': {name: sha(project / name) for name in ('probe_resources.json', '.mcdev.json')},
               'frozen_files': {name: digest for name, digest in before.items() if name not in files},
               'outputs': {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
               'material_registration': {'loaded_path': 'materials/postprocess.material'},
               'prelaunch_local_receipts_checked': checked,
               'external_session_absence_not_inferred': True,
               'host_only_offline_install': True, 'runtime_file_writes': False,
               'original_native_math': True, 'original_pass_arrays': True,
               'capacity_tested': 0, 'native_execution_verified': False,
               'compatibility_verified': False}
    for relative, content in files.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (project / RECEIPT).write_bytes(json_bytes(receipt))
    validate(project, phase)
    return receipt


def validate(project, phase=None):
    """Read-only validation, including regenerated owned/native output bytes."""
    project = Path(project).resolve()
    receipt = read_json(project / RECEIPT)
    declared = _phase(receipt.get('phase'))
    if (receipt.get('schema') != SCHEMA or receipt.get('project') != str(project)
            or (phase is not None and _phase(phase) != declared)):
        raise ValueError('Sequential Bloom build identity mismatch')
    game_exe = Path(receipt['game_executable_path']).resolve()
    startup_module = _startup_module()
    startup_module._project(project, game_exe)
    owned = resources()
    if (receipt.get('fixture_identity') != runner_module().fixture_identity()
            or receipt.get('resources_sha256') != hashlib.sha256(json_bytes(owned)).hexdigest()):
        raise ValueError('Sequential Bloom fixture identity changed')
    files, inputs = _outputs(project, game_exe, declared, receipt['original_carrier'], owned, startup_module)
    expected = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    if receipt.get('outputs') != expected:
        raise ValueError('Sequential Bloom output receipt differs from regenerated outputs')
    if receipt.get('native_input_sources') != inputs:
        raise ValueError('Installed native input changed')
    dependencies = {str(HERE / 'runner.py'): sha(HERE / 'runner.py'),
                    str(Path(startup_module.__file__)): sha(startup_module.__file__)}
    if receipt.get('source_sha256') != sha(__file__) or receipt.get('dependency_sources') != dependencies:
        raise ValueError('Sequential Bloom build dependency changed')
    for name, digest in receipt['control_files'].items():
        if sha(project / name) != digest:
            raise ValueError('Frozen carrier control file changed: ' + name)
    if (sha(project / 'native_post_startup.json') != receipt['startup_receipt_sha256']
            or read_json(project / 'native_post_startup.json') != receipt['startup_input']):
        raise ValueError('Original native startup receipt changed')
    actual = _pack_files(project)
    expected_inventory = {**receipt['frozen_files'], **expected}
    if set(actual) != set(expected_inventory):
        raise ValueError('Sequential Bloom pack file inventory changed')
    for name, digest in expected_inventory.items():
        if actual[name] != digest:
            raise ValueError('Sequential Bloom pack file changed: ' + name)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--game-exe', type=Path)
    parser.add_argument('--phase', choices=PHASES)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    if not args.validate_only and (args.game_exe is None or args.phase is None):
        parser.error('--game-exe and --phase are required for an offline install')
    result = validate(args.project, args.phase) if args.validate_only else install(args.project, args.game_exe, args.phase)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
