"""Install an original native bloom/DOF startup variant into an offline probe.

This is a host-only build step.  Call it on a fresh carrier project before its
first launch.  It never changes an installed game, a shader, a material, or the
frozen probe build receipts.  The caller owns the game lifecycle; absence of a
local launch receipt cannot establish that an external session is not running.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import uuid


SCHEMA = 'native_stencil_post_startup_v1'
RECEIPT = 'native_post_startup.json'
NAMESPACE = uuid.UUID('c84664e3-0f3c-58ea-8aec-728b731a8647')
CONFIG_NAMES = ('post_process.json', 'post_process_rngl.json')


def effect_name(effect):
    """Return the actual installed native process name."""
    if effect == 'dof':
        return 'depthoffield'
    if effect not in ('bloom', 'depthoffield'):
        raise ValueError('Native startup effect must be bloom or depthoffield')
    return effect


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode('utf-8')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _project(project, game_exe):
    project = Path(project).resolve()
    probe_path = project/'probe_resources.json'
    probe = read_json(probe_path)
    if probe.get('native_compatibility', {}).get('variant') != 'carrier':
        raise ValueError('Original native startup fixture requires a carrier comparison build')
    settings_path = project/'.mcdev.json'
    settings = read_json(settings_path)
    configured = Path(settings['game_executable_path']).resolve()
    game_exe = configured if game_exe is None else Path(game_exe).resolve()
    if game_exe != configured or not game_exe.is_file():
        raise ValueError('Native source executable must match this generated project .mcdev.json')
    if any(settings.get(name) is not False for name in (
            'auto_hot_reload_mods', 'auto_hot_reload_ui',
            'auto_hot_reload_shaders', 'auto_hot_reload_materials')):
        raise ValueError('Startup variant requires all generated hot-reload settings disabled')
    for folder in ('behavior_pack', 'resource_pack'):
        if not (project/folder/'manifest.json').is_file():
            raise ValueError('Both generated probe packs and their manifests are required')
    return project, game_exe, probe_path, settings_path


def _prelaunch(project):
    # The standard probe layout stores evidence beside project/.  These are
    # deliberately bounded checks, not a claim to discover every external
    # owner/session.  An already installed identical variant is checked first.
    paths = (project/'launch.json', project/'evidence/launch.json',
             project.parent/'evidence/launch.json')
    found = [str(path) for path in paths if path.exists()]
    if found:
        raise ValueError('Install native startup flags before launch; launch receipt exists: '+', '.join(found))
    return [str(path) for path in paths]


def _config(native_root, name, effect):
    path = native_root/'graphics_settings'/name
    original_bytes = path.read_bytes()
    original = json.loads(original_bytes.decode('utf-8-sig'))
    processes = original.get('process_array')
    if not isinstance(processes, list) or not processes:
        raise ValueError('Installed native configuration lacks a process_array: '+str(path))
    names = [item.get('name') for item in processes]
    if len(set(names)) != len(names) or names.count(effect) != 1:
        raise ValueError('Installed native configuration has ambiguous or missing effect: '+str(path))
    result = copy.deepcopy(original)
    changes = []
    for index, process in enumerate(result['process_array']):
        if not isinstance(process.get('enable'), bool):
            raise ValueError('Every native process must expose a Boolean startup flag')
        expected = process['name'] == effect
        if process['enable'] != expected:
            changes.append({'path': '/process_array/%d/enable' % index,
                            'process': process['name'], 'before': process['enable'], 'after': expected})
        process['enable'] = expected
    # Revert exactly the permitted leaves and prove the rest of the parsed
    # source, including order, all parameters and every pass, is unchanged.
    reverted = copy.deepcopy(result)
    for index, process in enumerate(processes):
        reverted['process_array'][index]['enable'] = process['enable']
    if reverted != original:
        raise AssertionError('Unexpected native configuration modification')
    target = next(item for item in processes if item['name'] == effect)
    return result, target, {'source_file': str(path), 'source_sha256': sha256(original_bytes),
                            'changed_paths': changes, 'process_names': names,
                            'render_order': original.get('render_order'),
                            'parameters': target.get('paras'), 'pass_array': target.get('pass_array')}


def _native_sources(project, game_exe, target_processes):
    native_root = game_exe.parent/'data/resource_packs/vanilla_netease'
    path = native_root/'materials/postprocess.material'
    content = path.read_bytes()
    definitions = json.loads(content.decode('utf-8-sig'))
    materials = sorted({item['material'].split('.')[0]
                        for process in target_processes for item in process['pass_array']})
    if any(name not in definitions for name in materials):
        raise ValueError('Native post material definitions do not contain every original pass')
    local_path = project/'resource_pack/materials/postprocess.material'
    for candidate in sorted((project/'resource_pack/materials').glob('*.material')):
        local = read_json(candidate)
        local = local.get('materials', local)
        if any(key.split(':', 1)[0].split('.')[0] in materials for key in local):
            raise ValueError('Probe overrides an original target native post material: '+str(candidate))
    shaders = sorted({definitions[name][field] for name in materials
                      for field in ('vertexShader', 'fragmentShader')})
    shader_sources = {}
    for shader in shaders:
        # The installed native post material uses the engine's shaders/foo
        # alias; the GLSL source lives at shaders/glsl/foo in both source roots.
        if not shader.startswith('shaders/') or '..' in Path(shader).parts:
            raise ValueError('Unexpected native shader path: '+shader)
        relative = Path('shaders/glsl')/Path(shader).relative_to('shaders')
        if shader.startswith('shaders/glsl/'):
            relative = Path(shader)
        if (project/'resource_pack'/relative).exists() or (project/'resource_pack'/shader).exists():
            raise ValueError('Probe overrides an original target native shader: '+shader)
        candidates = (native_root/relative, game_exe.parent/'data'/relative)
        if not all(candidate.is_file() for candidate in candidates):
            raise ValueError('Installed native GLSL source is incomplete: '+shader)
        shader_sources[shader] = [{'source_file': str(candidate),
                                   'sha256': sha256(candidate.read_bytes())} for candidate in candidates]
    return {'source_file': str(path), 'sha256': sha256(content),
            'pass_material_names': materials,
            'pass_materials': {name: definitions[name] for name in materials},
            'project_post_material_sha256': sha256(local_path.read_bytes()),
            'project_overrides_original_pass_materials': False}, shader_sources


def _manifests(project, effect):
    values, receipt, mapping = {}, {}, {}
    for folder in ('behavior_pack', 'resource_pack'):
        relative = folder+'/manifest.json'
        path = project/relative
        original_bytes = path.read_bytes()
        value = json.loads(original_bytes.decode('utf-8-sig'))
        old = value['header']['uuid']
        new = str(uuid.uuid5(NAMESPACE, effect+'/'+folder+'/header'))
        mapping[old] = new
        value['header']['uuid'] = new
        value['header']['name'] = 'Native stencil original '+effect+' '+folder
        for index, item in enumerate(value['modules']):
            old = item['uuid']
            new = str(uuid.uuid5(NAMESPACE, effect+'/'+folder+'/module/'+str(index)))
            mapping[old] = new
            item['uuid'] = new
        values[relative] = value
        receipt[relative] = {'before_sha256': sha256(original_bytes)}
    for relative, value in values.items():
        for dependency in value.get('dependencies', []):
            if dependency.get('uuid') in mapping:
                dependency['uuid'] = mapping[dependency['uuid']]
        receipt[relative].update(after_sha256=sha256(json_bytes(value)),
                                 header_uuid=value['header']['uuid'],
                                 module_uuids=[item['uuid'] for item in value['modules']])
    return values, receipt


def _existing(project, effect, game_exe):
    path = project/RECEIPT
    if not path.exists():
        return None
    receipt = read_json(path)
    if (receipt.get('schema') != SCHEMA or receipt.get('effect') != effect
            or receipt.get('project') != str(project)
            or receipt.get('game_executable_path') != str(game_exe)):
        raise ValueError('An existing startup variant differs; build a fresh project for the next effect')
    for relative, expected in receipt['installed_files'].items():
        if sha256((project/relative).read_bytes()) != expected:
            raise ValueError('Installed startup fixture was modified: '+relative)
    for relative, expected in (('probe_resources.json', receipt['probe_resources_sha256']),
                               ('.mcdev.json', receipt['mcdev_settings_sha256']),
                               ('resource_pack/materials/postprocess.material',
                                receipt['native_material']['project_post_material_sha256'])):
        if sha256((project/relative).read_bytes()) != expected:
            raise ValueError('Frozen startup input was modified: '+relative)
    for value in receipt['config_outputs'].values():
        if sha256(Path(value['source_file']).read_bytes()) != value['source_sha256']:
            raise ValueError('Installed native configuration source changed since fixture installation')
    material = receipt['native_material']
    if sha256(Path(material['source_file']).read_bytes()) != material['sha256']:
        raise ValueError('Installed native material source changed since fixture installation')
    for records in receipt['native_shader_sources'].values():
        for record in records:
            if sha256(Path(record['source_file']).read_bytes()) != record['sha256']:
                raise ValueError('Installed native shader source changed since fixture installation')
    _native_sources(project, game_exe, [value for value in receipt['config_outputs'].values()])
    return receipt


def install_startup(project, effect, game_exe=None):
    """Install one isolated original native effect before the first launch.

    Both native configuration routes are written.  Their parsed content differs
    from the installed native originals only at process enable flags.  Pack
    identity is deterministically scoped by effect.  Repeating the same install
    validates and returns the previous receipt; changing effect requires a fresh
    generated carrier project.  This function does not launch or contact a game.
    """
    effect = effect_name(effect)
    project, game_exe, probe_path, settings_path = _project(project, game_exe)
    existing = _existing(project, effect, game_exe)
    if existing is not None:
        return existing
    checked_launch_receipts = _prelaunch(project)
    native_root = game_exe.parent/'data/resource_packs/vanilla_netease'
    files, configs, targets = {}, {}, []
    for name in CONFIG_NAMES:
        value, target, source = _config(native_root, name, effect)
        relative = 'resource_pack/graphics_settings/'+name
        output = json_bytes(value)
        source.update(output_sha256=sha256(output),
                      previous_project_sha256=(sha256((project/relative).read_bytes())
                                               if (project/relative).exists() else None))
        files[relative], configs[relative] = output, source
        targets.append(target)
    native_material, shader_sources = _native_sources(project, game_exe, targets)
    manifests, manifest_receipt = _manifests(project, effect)
    files.update({relative: json_bytes(value) for relative, value in manifests.items()})
    receipt = {'schema': SCHEMA, 'effect': effect, 'project': str(project),
               'game_executable_path': str(game_exe),
               'startup_enabled_effects': [effect], 'original_native_math': True,
               'original_pass_arrays': True, 'native_execution_verified': False,
               'host_only_offline_install': True, 'runtime_file_writes': False,
               'prelaunch_local_receipts_checked': checked_launch_receipts,
               'external_session_absence_not_inferred': True,
               'probe_resources_sha256': sha256(probe_path.read_bytes()),
               'mcdev_settings_sha256': sha256(settings_path.read_bytes()),
               'installer_source_sha256': sha256(Path(__file__).read_bytes()),
               'config_outputs': configs, 'manifests': manifest_receipt,
               'native_material': native_material, 'native_shader_sources': shader_sources,
               'installed_files': {name: sha256(content) for name, content in files.items()}}
    # Everything, including all native input files, has been validated before
    # the first write.  The receipt is last, so an interrupted install cannot
    # masquerade as a completed, authenticated variant.
    for relative, content in files.items():
        destination = project/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    (project/RECEIPT).write_bytes(json_bytes(receipt))
    return receipt


def validate_startup(project, effect, game_exe=None):
    """Read-only validation of an already installed native startup fixture.

    This may run after launch: it checks the same project, installed-file,
    native-source and override invariants as an idempotent install, without
    checking prelaunch receipts or writing files.  The original receipt is
    returned unchanged.  A missing installation is an error.
    """
    effect = effect_name(effect)
    project, game_exe, _, _ = _project(project, game_exe)
    receipt = _existing(project, effect, game_exe)
    if receipt is None:
        raise ValueError('Native startup fixture is not installed; install it before launch')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--effect', choices=('bloom', 'depthoffield', 'dof'), required=True)
    parser.add_argument('--game-exe', type=Path)
    arguments = parser.parse_args()
    print(json.dumps(install_startup(arguments.project, arguments.effect, arguments.game_exe),
                     ensure_ascii=False, indent=2))
