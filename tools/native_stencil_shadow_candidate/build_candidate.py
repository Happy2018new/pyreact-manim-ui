"""Host-only, diagnostic shadow read-mask candidates for fresh carrier projects.

No installed resources or production packages are written. Native execution and
engine material resolution remain unproven until the separate owner-run matrix.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import uuid


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MASKS = (255, 191, 63)
RECEIPT = 'native_shadow_candidate.json'
ORIGINAL = 'native_shadow_candidate_original.material'
MATERIAL = 'resource_pack/materials/shadows.material'
FIELD = '/materials/shadow_overlay/stencilReadMask'
NAMESPACE = uuid.UUID('97469c4b-a1b0-44c9-87b4-f20fe90ddad7')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _mask(value):
    if not isinstance(value, int) or isinstance(value, bool) or value not in MASKS:
        raise ValueError('Choose diagnostic mask255,191or63')
    return value


def _object_end(data, start):
    depth, quoted, escaped = 0, False, False
    for index in range(start, len(data)):
        character = data[index]
        if quoted:
            if escaped:
                escaped = False
            elif character == 92:
                escaped = True
            elif character == 34:
                quoted = False
        elif character == 34:
            quoted = True
        elif character == 123:
            depth += 1
        elif character == 125:
            depth -= 1
            if depth == 0:
                return index + 1
    raise ValueError('Unterminated native shadow_overlay object')


def patch_material(original, mask):
    """Splice one scoped numeric token, retaining every other original byte."""
    _mask(mask)
    parsed = json.loads(original.decode('utf-8-sig'))
    materials = parsed['materials']
    overlay = materials['shadow_overlay']
    if (overlay.get('stencilReadMask') != 255 or overlay.get('stencilRef') != 1
            or overlay.get('stencilWriteMask') != 0
            or overlay.get('frontFace', {}).get('stencilFunc') != 'Equal'
            or overlay.get('backFace', {}).get('stencilFunc') != 'Equal'
            or overlay.get('blendSrc') != 'DestColor' or overlay.get('blendDst') != 'Zero'
            or any(materials[name].get('stencilWriteMask') != 1
                   for name in ('shadow_front', 'shadow_back'))):
        raise ValueError('Installed native shadow recipe differs from reviewed source')
    objects = list(re.finditer(rb'"shadow_overlay"\s*:\s*\{', original))
    if len(objects) != 1:
        raise ValueError('Native shadow_overlay object must occur exactly once')
    start = objects[0].end() - 1
    end = _object_end(original, start)
    fields = list(re.finditer(rb'"stencilReadMask"\s*:\s*(255)(?![0-9])', original[start:end]))
    if len(fields) != 1:
        raise ValueError('Only one original overlay read-mask token is allowed')
    left, right = (start + value for value in fields[0].span(1))
    token = str(mask).encode('ascii')
    result = original[:left] + token + original[right:]
    reverted = result[:left] + b'255' + result[left + len(token):]
    patched = json.loads(result.decode('utf-8-sig'))
    reset = copy.deepcopy(patched)
    reset['materials']['shadow_overlay']['stencilReadMask'] = 255
    if reverted != original or reset != parsed:
        raise AssertionError('Candidate altered bytes or fields outside the one numeric token')
    return result, {'json_path': FIELD, 'before': 255, 'after': mask,
                    'original_byte_span': [left, right], 'candidate_byte_span': [left, left + len(token)],
                    'prefix_byte_exact': result[:left] == original[:left],
                    'suffix_byte_exact': result[left + len(token):] == original[right:],
                    'restored_original_byte_exact': reverted == original,
                    'all_other_parsed_fields_equal': reset == parsed,
                    'changed_json_paths': [] if mask == 255 else [FIELD]}


def mask_model(mask):
    """A synthetic Equal/ref1 truth table, never a native acceptance prediction."""
    _mask(mask)
    return {'synthetic_stencil': '1 | (symbol << 6)', 'reference': 1,
            'symbol_bit_order': 'bit128:bit64', 'native_acceptance_gate': False,
            'rows': [{'symbol': format(symbol, '02b'), 'stencil': 1 | (symbol << 6),
                      'equal_pass': ((1 | (symbol << 6)) & mask) == (1 & mask)}
                     for symbol in range(4)]}


def _packaged_files(project):
    return {path.relative_to(project).as_posix(): sha(path.read_bytes())
            for folder in ('behavior_pack', 'resource_pack')
            for path in sorted((project / folder).rglob('*')) if path.is_file()}


def _manifest_plans(project, mask):
    plans, mapping = {}, {}
    for folder in ('behavior_pack', 'resource_pack'):
        path = project / folder / 'manifest.json'
        value = read_json(path)
        mapping[value['header']['uuid']] = str(uuid.uuid5(NAMESPACE, '%d/%s/header' % (mask, folder)))
        plans[folder] = value
    for folder, value in plans.items():
        value['header']['uuid'] = mapping[value['header']['uuid']]
        value['header']['name'] = 'DIAGNOSTIC ONLY shadow mask%d %s' % (mask, folder)
        for index, item in enumerate(value['modules']):
            item['uuid'] = str(uuid.uuid5(NAMESPACE, '%d/%s/module%d' % (mask, folder, index)))
        for item in value.get('dependencies', []):
            if item.get('uuid') in mapping:
                item['uuid'] = mapping[item['uuid']]
    return plans


def install(project, game_exe, mask):
    """Install into one fresh, offline, isolated comparison carrier project.

    Local receipt checks do not discover external live sessions. The lifecycle
    owner must ensure this project has never been launched before calling.
    """
    mask = _mask(mask)
    project, game_exe = Path(project).resolve(strict=True), Path(game_exe).resolve(strict=True)
    if (ROOT / '.runtime').resolve() not in project.parents or not game_exe.is_file():
        raise ValueError('Only fresh diagnostic projects under repository.runtime are supported')
    probe = read_json(project / 'probe_resources.json')
    settings = read_json(project / '.mcdev.json')
    if probe.get('native_compatibility', {}).get('variant') != 'carrier':
        raise ValueError('Use a fresh unchanged native compatibility carrier build')
    if Path(settings['game_executable_path']).resolve() != game_exe:
        raise ValueError('Installed source executable must match generated project settings')
    if settings.get('included_mod_dirs', ['./']) != ['./'] or any(settings.get(key) is not False for key in (
            'auto_hot_reload_mods', 'auto_hot_reload_ui', 'auto_hot_reload_shaders', 'auto_hot_reload_materials')):
        raise ValueError('Candidate must be isolated with all generated hot reload settings disabled')
    checks = [project / 'launch.json', project / 'evidence/launch.json',
              project.parent / 'evidence/launch.json', project.parent / 'launch-evidence/launch.json']
    if any(path.exists() for path in checks):
        raise ValueError('Install candidate before the first launch')
    targets = [project / RECEIPT, project / ORIGINAL, project / MATERIAL]
    if any(path.exists() for path in targets):
        raise ValueError('Fresh project required; never overwrite an existing shadow candidate')
    source = game_exe.parent / 'data/resource_packs/vanilla/materials/shadows.material'
    original = source.read_bytes()
    candidate, patch = patch_material(original, mask)
    manifests = _manifest_plans(project, mask)
    before = _packaged_files(project)
    # All validation and planning above is read-only. These are only generated
    # host-side project files, never installed resources or game runtime writes.
    (project / MATERIAL).write_bytes(candidate)
    (project / ORIGINAL).write_bytes(original)
    for folder, manifest in manifests.items():
        (project / folder / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    after = _packaged_files(project)
    changed = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
    allowed = sorted([MATERIAL, 'behavior_pack/manifest.json', 'resource_pack/manifest.json'])
    if changed != allowed:
        raise AssertionError('Unexpected packaged diagnostic changes')
    unchanged = {key: value for key, value in before.items() if key not in allowed}
    receipt = {'schema': 'native_shadow_read_mask_candidate_v1', 'diagnostic_only': True,
               'project': str(project), 'game_executable': str(game_exe), 'mask': mask,
               'hex_mask': '0x%02X' % mask, 'transport_read_bits': mask & 192,
               'excluded_transport_bits': 192 & ~mask, 'source_file': str(source),
               'source_sha256': sha(original), 'original_backup': ORIGINAL,
               'candidate_material': MATERIAL, 'candidate_sha256': sha(candidate),
               'patch': patch, 'static_equal_model': mask_model(mask),
               'installed_resources_modified': False, 'production_resources_modified': False,
               'shader_changes': False, 'runtime_file_writes': False, 'native_execution_verified': False,
               'engine_material_resolution_verified': False, 'external_session_absence_not_inferred': True,
               'prelaunch_local_receipts_checked': [str(path) for path in checks],
               'builder_sha256': sha(Path(__file__).read_bytes()),
               'settings_sha256': sha((project / '.mcdev.json').read_bytes()),
               'probe_receipt_sha256': sha((project / 'probe_resources.json').read_bytes()),
               'packaged_changed_files': changed, 'packaged_before_sha256': before,
               'packaged_after_sha256': after, 'unchanged_packaged_sha256': unchanged,
               'manifest_identities': {folder: {'header': value['header'], 'modules': value['modules']}
                                       for folder, value in manifests.items()}}
    (project / RECEIPT).write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    validate(project, mask)
    return receipt


def validate(project, mask=None):
    """Read-only recheck of the entire frozen candidate package before a run."""
    project = Path(project).resolve(strict=True)
    receipt = read_json(project / RECEIPT)
    actual_mask = _mask(receipt['mask'])
    if mask is not None and _mask(mask) != actual_mask:
        raise ValueError('Requested mask does not match isolated candidate receipt')
    if Path(receipt['project']).resolve() != project or receipt.get('diagnostic_only') is not True:
        raise ValueError('Candidate identity or diagnostic scope mismatch')
    original = (project / ORIGINAL).read_bytes()
    candidate, patch = patch_material(original, actual_mask)
    if (sha(original) != receipt['source_sha256']
            or sha(Path(receipt['source_file']).read_bytes()) != receipt['source_sha256']
            or (project / MATERIAL).read_bytes() != candidate or sha(candidate) != receipt['candidate_sha256']
            or patch != receipt['patch'] or _packaged_files(project) != receipt['packaged_after_sha256']
            or sha((project / '.mcdev.json').read_bytes()) != receipt['settings_sha256']
            or sha((project / 'probe_resources.json').read_bytes()) != receipt['probe_receipt_sha256']):
        raise ValueError('Candidate source, single-field patch, settings or packaged bytes changed')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--game-exe', type=Path)
    parser.add_argument('--mask', type=int, choices=MASKS, required=True)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    if args.validate_only:
        receipt = validate(args.project, args.mask)
    else:
        if args.game_exe is None:
            parser.error('--game-exe is required for offline installation')
        receipt = install(args.project, args.game_exe, args.mask)
    print(json.dumps({'project': receipt['project'], 'mask': receipt['mask'],
                      'candidate_sha256': receipt['candidate_sha256'], 'diagnostic_only': True,
                      'native_execution_verified': False}))


if __name__ == '__main__':
    main()
