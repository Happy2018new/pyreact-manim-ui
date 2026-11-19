"""Build a fresh unchanged static carrier for one isolated End or Nether trip."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROUNDTRIP = HERE.parent/'native_stencil_dimension_roundtrip_diagnostics'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def install(project):
    project = Path(project).resolve()
    output = project/'dimension_target_receipt.json'
    if output.exists():
        raise ValueError('Annotate the isolated target diagnostic once in a fresh unlaunched project')
    reviewed = module('target_roundtrip_install_verifier', ROUNDTRIP/'runner.py')
    reviewed.verify_install(project)
    receipt = {'schema': 'static_target_dimension_fixture_v1', 'project': str(project),
        'runtime_candidate_modified': False, 'materials_or_shaders_modified': False,
        'runtime_file_writes': False, 'static_only': True, 'room_dimensions': [0],
        'target_head': [8, 72, 8], 'camera': [8., 72., 5.],
        'default_dimension_sequence': [0, 2, 0], 'maximum_planned_transitions': 2,
        'maximum_passive_followups': 3, 'terrain_sampling_read_only': True,
        'candidate_transition_limit': 8, 'native_verified': False,
        'source_sha256': {name: hashlib.sha256((HERE/name).read_bytes()).hexdigest()
                          for name in ('runner.py', 'build_candidate.py')}}
    output.write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    return receipt


def build(output, game_exe):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Build into a new absent directory; preserve prepared projects')
    builder = module('target_roundtrip_builder', ROUNDTRIP/'build_candidate.py')
    project = builder.build(output, game_exe)
    install(project)
    return project


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output', type=Path)
    mode.add_argument('--project', type=Path, help='Fresh unlaunched roundtrip diagnostic project')
    parser.add_argument('--game-exe', type=Path)
    args = parser.parse_args()
    if args.output is not None:
        if args.game_exe is None:
            parser.error('--game-exe is required with --output')
        print(build(args.output, args.game_exe))
    else:
        print(json.dumps(install(args.project), indent=2))
