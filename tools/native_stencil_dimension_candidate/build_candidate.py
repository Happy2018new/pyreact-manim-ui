"""Compose a separate static dimension candidate into a fresh carrier project."""
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLASS = 'stencil_large.dimension_candidate.ProbeSystem'
ORIGINAL = b'stencil_large.integrated_runtime.ProbeSystem'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def install(project):
    project = Path(project).resolve()
    package = project/'behavior_pack/stencil_large'
    receipt_path = project/'probe_resources.json'
    entry = package/'modMain.py'
    target = package/'dimension_candidate.py'
    output = project/'dimension_candidate_receipt.json'
    if target.exists() or output.exists():
        raise ValueError('Install the dimension candidate once in a fresh generated carrier project')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if (receipt.get('native_compatibility', {}).get('variant') != 'carrier' or
            receipt.get('runtime', {}).get('class') != ORIGINAL.decode('ascii')):
        raise ValueError('Expected the unchanged integrated native compatibility carrier')
    before = {p.relative_to(project).as_posix(): digest(p.read_bytes())
              for folder in ('behavior_pack', 'resource_pack')
              for p in (project/folder).rglob('*') if p.is_file()}
    original_entry = entry.read_bytes()
    if original_entry.count(ORIGINAL) != 1:
        raise ValueError('Expected exactly one original integrated system registration')
    source = (HERE/'runtime.py').read_bytes()
    target.write_bytes(source)
    entry.write_bytes(original_entry.replace(ORIGINAL, CLASS.encode('ascii')))
    receipt['runtime']['class'] = CLASS
    receipt['dimension_candidate'] = {'schema': 'static_dimension_reattach_candidate_v1',
        'runtime_source_sha256': digest(source), 'static_only': True,
        'geometry_cache_survival_assumed_for_attempt_only': True,
        'native_pixel_verification_required': True, 'native_verified': False}
    receipt_path.write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    unchanged = {name: sha for name, sha in before.items() if name != 'behavior_pack/stencil_large/modMain.py'}
    if any(digest((project/name).read_bytes()) != sha for name, sha in unchanged.items()):
        raise RuntimeError('Candidate install changed a frozen runtime or resource')
    result = {'schema': 'static_dimension_candidate_install_v1',
        'project': str(project), 'runtime_class': CLASS, 'runtime_sha256': digest(source),
        'entry_original_sha256': digest(original_entry), 'entry_sha256': digest(entry.read_bytes()),
        'original_entry_ascii': original_entry.decode('utf-8'),
        'frozen_file_hashes': unchanged, 'frozen_files_unchanged': True,
        'materials_or_shaders_modified': False, 'runtime_file_writes': False,
        'native_verified': False}
    output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    print(json.dumps(install(parser.parse_args().project), indent=2))
