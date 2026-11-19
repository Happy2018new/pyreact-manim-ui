"""Build a fresh unchanged target carrier with host stage-diagnostic receipts."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
TARGET = HERE.parent/'native_stencil_dimension_target_diagnostics'
BOUND_SOURCES = ('runner.py', 'observations.py', 'routing.py', 'build_candidate.py')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def install(project):
    project = Path(project).resolve()
    receipt_path = project/'dimension_stage_receipt.json'
    if receipt_path.exists():
        raise ValueError('Annotate stage diagnostics once in a fresh unlaunched project')
    module('stage_target_verifier', TARGET/'runner.py').verify_install(project)
    receipt = {'schema': 'static_dimension_stage_fixture_v1', 'project': str(project),
        'room_dimensions': [0], 'default_dimension_sequence': [0, 2, 0],
        'maximum_transitions': 2, 'maximum_stage_captures': 21, 'manual_control_captures': 6,
        'maximum_routing_captures': 13,
        'runtime_candidate_modified': False, 'materials_or_shaders_modified': False,
        'runtime_file_writes': False, 'resident_payload_uploads': 1, 'native_verified': False,
        'source_sha256': {name: hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in BOUND_SOURCES}}
    receipt_path.write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    return receipt


def build(output, game_exe):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Build into a new absent directory; preserve prepared projects')
    project = module('stage_target_builder', TARGET/'build_candidate.py').build(output, game_exe)
    install(project)
    return project


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--game-exe', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.output, args.game_exe))
