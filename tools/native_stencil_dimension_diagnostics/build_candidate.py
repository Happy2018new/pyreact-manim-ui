"""Build a fresh unchanged dimension candidate for a positive-altitude host fixture."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parent/'native_stencil_dimension_candidate'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest()


def install(project):
    """Annotate a fresh carrier; never patch the reviewed candidate source."""
    project = Path(project).resolve()
    output = project/'dimension_positive_pose_receipt.json'
    if output.exists():
        raise ValueError('Install the positive pose fixture once in a fresh unlaunched project')
    config_path = project/'.mcdev.json'
    config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    if (project/'level.dat').exists() or config.get('world_source_path') not in (None, '', 'auto'):
        raise ValueError('Positive pose requires an independent generated development world')
    candidate_builder = module('positive_pose_candidate_builder', CANDIDATE/'build_candidate.py')
    if not (project/'dimension_candidate_receipt.json').exists():
        candidate_builder.install(project)
    runtime = project/'behavior_pack/stencil_large/dimension_candidate.py'
    installed = json.loads((project/'dimension_candidate_receipt.json').read_text(encoding='utf-8'))
    source = (CANDIDATE/'runtime.py').read_bytes()
    resources = json.loads((project/'probe_resources.json').read_text(encoding='utf-8'))
    if (runtime.read_bytes() != source or installed.get('runtime_sha256') != digest(source) or
            digest((project/'behavior_pack/stencil_large/modMain.py').read_bytes()) != installed['entry_sha256'] or
            resources.get('runtime', {}).get('class') != candidate_builder.CLASS or
            resources.get('native_compatibility', {}).get('variant') != 'carrier'):
        raise ValueError('Expected the exact reviewed static dimension carrier')
    for name, sha in installed['frozen_file_hashes'].items():
        if digest((project/name).read_bytes()) != sha:
            raise ValueError('Frozen carrier file changed: '+name)
    # instances.prepare_config generates PYR_<fresh instance UUID>; an explicit
    # empty source prevents an accidental inherited/copied world at launch.
    config['world_source_path'] = ''
    config_path.write_text(json.dumps(config, indent=2)+'\n', encoding='utf-8')
    result = {'schema': 'positive_pose_dimension_fixture_v3',
        'project': str(project), 'candidate_runtime_sha256': digest(source),
        'candidate_runtime_modified': False, 'materials_or_shaders_modified': False,
        'pose_source_sha256': digest((HERE/'pose.py').read_bytes()),
        'runner_source_sha256': digest((HERE/'runner.py').read_bytes()),
        'camera': [8., 72., 5.], 'player_feet': [8.5, 70., 8.5],
        'dimension_target': [8, 72, 8], 'room_dimensions': [0, 1],
        'supported_room_modes': {'controlled': [0, 1], 'nether_natural': [0]},
        'room_minimum': [4, 69, 3], 'room_maximum': [12, 78, 13],
        'room_pipeline': 'sequential_single_chunk_later_verification_v2',
        'maximum_room_write_attempts': 3,
        'independent_world_source': '', 'existing_level_dat': False,
        'launcher_world_name': 'PYR_<fresh instance UUID>',
        'runtime_file_writes': False, 'continuous_update_tested': False,
        'native_verified': False}
    output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result


def build(output, game_exe):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Build into a new absent directory; never reuse a prepared or launched project')
    compat = module('positive_pose_compat_builder', HERE.parent/'native_stencil_compat_probe/build_probe.py')
    project = compat.build(output, game_exe, 'carrier')
    install(project)
    return project


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output', type=Path)
    mode.add_argument('--project', type=Path, help='Fresh unlaunched generated carrier only')
    parser.add_argument('--game-exe', type=Path)
    args = parser.parse_args()
    if args.output is not None:
        if args.game_exe is None:
            parser.error('--game-exe is required with --output')
        print(build(args.output, args.game_exe))
    else:
        print(json.dumps(install(args.project), indent=2))
