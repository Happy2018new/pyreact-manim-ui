"""Host-only exhaustive shadow comparisons grouped by actual payload symbols."""
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('candidate_frozen_shadow_oracle',
    HERE.parent / 'integrated_shadow_fixture/verify.py')
shadow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(shadow)
MINIMUM_SHADOW_SAMPLES_PER_SYMBOL = 24
BUILD_SPEC = importlib.util.spec_from_file_location('saved_shadow_candidate_build_check', HERE / 'build_candidate.py')
build = importlib.util.module_from_spec(BUILD_SPEC)
BUILD_SPEC.loader.exec_module(build)


def images(paths):
    frames = []
    for path in paths:
        with Image.open(path) as image:
            frames.append(image.convert('RGB'))
    return frames


def symbol_map(payload, viewport, roi):
    """00/01/10/11 label bit128:bit64; source ordering is low pair first."""
    if not isinstance(payload, bytes) or len(payload) != 65536:
        raise ValueError('Actual65536byte host input required; no inferred seed is accepted')
    width, height = viewport
    x, y, rw, rh = roi
    if rw * rh != len(payload) * 4 or min(x, y) < 0 or x + rw > width or y + rh > height:
        raise ValueError('Invalid four-source-pixels-per-byte ROI')
    values = np.frombuffer(payload, dtype=np.uint8)
    symbols = ((values[:, None] >> np.arange(0, 8, 2, dtype=np.uint8)) & 3).reshape(rh, rw)
    result = np.full((height, width), -1, dtype=np.int16)
    result[y:y + rh, x:x + rw] = symbols
    return result


def _native_shadow_pixels(triplet, plan):
    """Descriptive baseline witness only; full geometry remains acceptance mask."""
    before, active, after = [shadow._rgb(frame, plan) for frame in triplet]
    receiver = shadow._masks(plan)[0]
    dark = np.minimum(before - active, after - active)
    ratio = active.astype(float) / np.maximum((before.astype(float) + after) * .5, 1.)
    return (receiver & (np.minimum(before, after).min(axis=2) >= 24)
            & (dark.min(axis=2) >= plan['minimum_darkening_each_channel'])
            & (dark.mean(axis=2) >= plan['minimum_darkening_mean'])
            & (np.ptp(ratio, axis=2) <= plan['maximum_shadow_channel_ratio_spread']))


def _difference(first, second, mask, tolerance):
    count = int(mask.sum())
    if not count:
        return {'pixels': 0, 'changed_pixels': 0, 'max_channel_delta': 0}
    delta = np.abs(first[mask] - second[mask])
    return {'pixels': count, 'changed_pixels': int(np.any(delta > tolerance, axis=1).sum()),
            'max_channel_delta': int(delta.max())}


def compare(native_triplet, active_triplet, plan, reports, actual_payload):
    """Unchanged full-region/data gates plus all four descriptive symbol groups.

    Baseline shadow pixels select only descriptive class samples, never the
    preservation acceptance region. Every geometry receiver/body/control pixel
    is still checked by the frozen predecessor, including same-PNG diagnostics.
    """
    if len(native_triplet) != 3 or len(active_triplet) != 3:
        raise ValueError('Need complete native and carrier off/on/off triplets')
    coexistence = shadow.compare_coexistence(native_triplet, active_triplet, plan, reports, actual_payload)
    symbols = symbol_map(actual_payload, plan['viewport'], plan['roi'])
    receiver, body, control, inside, boundary = shadow._masks(plan)
    region = receiver | body | control
    native_pixels = _native_shadow_pixels(native_triplet, plan)
    baseline = [shadow._rgb(frame, plan) for frame in native_triplet]
    active = [shadow._rgb(frame, plan) for frame in active_triplet]
    groups = []
    for symbol in range(4):
        group = symbols == symbol
        sample = native_pixels & group
        on = _difference(baseline[1], active[1], sample, plan['pixel_tolerance'])
        groups.append({'symbol': symbol, 'bits_bit128_bit64': format(symbol, '02b'),
                       'native_shadow_pixels': int(sample.sum()),
                       'native_shadow_at_roi_boundary': int((sample & boundary).sum()),
                       'retained_shadow_pixels': on['pixels'] - on['changed_pixels'],
                       'changed_shadow_pixels': on['changed_pixels'],
                       'shadow_max_channel_delta': on['max_channel_delta'],
                       'full_geometry_region': [_difference(first, second, region & group, plan['pixel_tolerance'])
                                                for first, second in zip(baseline, active)]})
    diagnostics = []
    for report in reports:
        if report.get('mode') not in (1, 3):
            continue
        path = Path(report['capture_file'])
        diagnostic = shadow._rgb(images([path])[0], plan)
        diagnostics.append({'label': report['label'], 'mode': report['mode'],
                            'capture_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                            'groups': [{'symbol': symbol, 'bits_bit128_bit64': format(symbol, '02b'),
                                        'native_shadow': _difference(baseline[1], diagnostic,
                                            native_pixels & (symbols == symbol), plan['pixel_tolerance']),
                                        'full_geometry_region': _difference(baseline[1], diagnostic,
                                            region & (symbols == symbol), plan['pixel_tolerance'])}
                                       for symbol in range(4)],
                            'outside_roi': _difference(baseline[1], diagnostic, region & ~inside,
                                                       plan['pixel_tolerance'])})
    coverage = all(row['native_shadow_pixels'] >= MINIMUM_SHADOW_SAMPLES_PER_SYMBOL for row in groups)
    errors = list(coexistence['errors'])
    if not coverage:
        errors.append('native shadow samples must cover00/01/10/11 at least24pixels each')
    return {'schema': 'native_shadow_four_symbol_comparison_v1', 'pass': coexistence['pass'] and coverage,
            'errors': errors, 'payload_sha256': hashlib.sha256(actual_payload).hexdigest(),
            'symbol_bit_order': 'bit128:bit64', 'source_pair_order': 'least-significant pair first',
            'minimum_native_shadow_pixels_per_symbol': MINIMUM_SHADOW_SAMPLES_PER_SYMBOL,
            'all_four_symbol_groups_covered': coverage, 'groups': groups,
            'outside_roi': [_difference(first, second, region & ~inside, plan['pixel_tolerance'])
                            for first, second in zip(baseline, active)],
            'same_png_symbol_comparisons': diagnostics, 'coexistence': coexistence,
            'acceptance_mask': 'entire predeclared geometric receiver/body/control regions',
            'pixel_derived_acceptance_mask': False,
            'baseline_positive_pixels_used_only_for_descriptive_symbol_samples': True,
            'active_pixels_used_to_select_samples': False, 'engine_route_proven': False}


def _saved_case(directory, mask):
    """Reopen inputs, all PNGs and raw receipts; never trust saved pass fields."""
    directory = Path(directory).resolve(strict=True)
    status = json.loads((directory / 'shadow-candidate-status.json').read_text(encoding='utf-8'))
    if status['mask'] != mask:
        raise ValueError('Matrix mask/evidence identity mismatch')
    receipt = build.validate(status['candidate']['project'], mask)
    if receipt != status['candidate']:
        raise ValueError('Saved run candidate differs from the frozen package receipt')
    payload = Path(status['actual_input_file']).read_bytes()
    if len(payload) != 65536 or hashlib.sha256(payload).hexdigest() != status['actual_payload_sha256']:
        raise ValueError('Saved actual input bytes/hash changed')
    results = json.loads((directory / 'results.json').read_text(encoding='utf-8'))
    if results['loads'][-1]['input_file'] != status['actual_input_file']:
        raise ValueError('Run load receipt and actual input file differ')
    session_bytes = (directory / 'assigned-session-snapshot.json').read_bytes()
    session = json.loads(session_bytes.decode('utf-8-sig'))
    if (hashlib.sha256(session_bytes).hexdigest() != status['assigned_session_sha256']
            or session['owner'] != 'manim-native-stencil-compat'
            or Path(session['project']).resolve() != Path(receipt['project']).resolve()):
        raise ValueError('Saved assigned-session identity changed')
    paths = status['native_captures'] + status['active_captures'] + status['payload_captures']
    normalized = [str(Path(path).resolve()) for path in paths]
    if len(paths) != 8 or len(set(normalized)) != 8 or set(normalized) != set(status['capture_sha256']):
        raise ValueError('Exactly eight unique native/active/data PNGs are required')
    reports = {str(Path(row['capture_file']).resolve()): row for row in results['reports']}
    last_frame = -1
    for path in paths:
        path = Path(path).resolve(strict=True)
        if path.parent != directory or hashlib.sha256(path.read_bytes()).hexdigest() != status['capture_sha256'][str(path)]:
            raise ValueError('Candidate capture bytes or evidence directory changed')
        report = reports[str(path)]
        capture = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        if (capture != report['capture_receipt'] or capture.get('ok') is not True
                or capture.get('backend') != 'Windows.Graphics.Capture'
                or [capture.get('width'), capture.get('height')] != status['plan']['viewport']
                or capture.get('pid') != session['game_pid']
                or capture.get('window', {}).get('pid') != session['game_pid']
                or capture.get('agent_activation_allowed') is not False
                or capture['frame_qpc_100ns'] < capture['request_qpc_100ns']
                or capture['frame_qpc_100ns'] <= last_frame
                or any(capture.get(key, {}).get('window_noactivate') is not True
                       for key in ('background_before', 'background_after'))):
            raise ValueError('Saved fresh native capture/owner/noactivation gate failed')
        last_frame = capture['frame_qpc_100ns']
    data_reports = [reports[str(Path(path).resolve())] for path in status['payload_captures']]
    recomputed = compare(images(status['native_captures']), images(status['active_captures']),
                         status['plan'], data_reports, payload)
    native_state = shadow.compare_snapshots(status['native_snapshots'])
    active_state = shadow.compare_snapshots(status['active_snapshots'])
    predecessor = json.loads((directory / 'shadow-recovery-status.json').read_text(encoding='utf-8'))
    floor_exact = predecessor.get('cleanup', {}).get('floor', {}).get('all_exact') is True
    pig = predecessor.get('pig_receipt')
    pig_gone = pig is None or predecessor.get('cleanup', {}).get('pig', {}).get('accepted') is True
    final = status.get('final_runtime_state', {})
    caster_gone = isinstance(final.get('outline'), dict) and final['outline'].get('entity') is None
    valid = (status.get('operational_complete') is True and status.get('failure') is None
             and status.get('candidate_package_unchanged') is True
             and status.get('frozen_hover_helper_unchanged') is True
             and native_state['pass'] and active_state['pass'] and floor_exact and pig_gone and caster_gone
             and recomputed['coexistence']['baseline']['pass'] and recomputed['all_four_symbol_groups_covered'])
    return status, recomputed, valid


def compare_matrix(evidence_by_mask):
    """Read saved evidence only; require equal native controls across candidates."""
    if set(evidence_by_mask) != {255, 191, 63}:
        raise ValueError('Provide separate255/191/63 evidence directories')
    cases, computed, valid_cases = {}, {}, {}
    for mask, directory in evidence_by_mask.items():
        cases[mask], computed[mask], valid_cases[mask] = _saved_case(directory, mask)
    original = cases[255]
    errors, controls = [], []
    for mask, status in cases.items():
        if not valid_cases[mask]:
            errors.append('mask%d did not finish required captures and cleanup' % mask)
        if (status.get('candidate', {}).get('source_sha256') != original['candidate']['source_sha256']
                or status['candidate']['unchanged_packaged_sha256'] != original['candidate']['unchanged_packaged_sha256']):
            errors.append('mask%d does not share exact native source and unchanged carrier package' % mask)
        if status.get('actual_payload_sha256') != original.get('actual_payload_sha256'):
            errors.append('mask%d actual input differs' % mask)
        if status.get('plan') != original.get('plan'):
            errors.append('mask%d predeclared geometry differs; cross-candidate pixel comparison rejected' % mask)
            continue
        if status.get('native_snapshots') is None or original.get('native_snapshots') is None:
            errors.append('native-only snapshots missing')
            continue
        # Entity IDs may be independently allocated; compare actual native pose,
        # camera and geometry, not engine allocation identities across sessions.
        for first, second in zip(original['native_snapshots'], status['native_snapshots']):
            if any(first.get(key) != second.get(key) for key in ('native_position', 'rotation', 'camera')):
                errors.append('mask%d native-only camera or caster pose differs' % mask)
        plan = original['plan']
        receiver, body, control, _, _ = shadow._masks(plan)
        region = receiver | body | control
        comparisons = [_difference(shadow._rgb(first, plan), shadow._rgb(second, plan), region, plan['pixel_tolerance'])
                       for first, second in zip(images(original['native_captures']), images(status['native_captures']))]
        if any(row['changed_pixels'] for row in comparisons):
            errors.append('mask%d altered native-only shadow/floor/body control' % mask)
        controls.append({'mask': mask, 'native_only_vs255': comparisons})
    reproduced = (valid_cases[255] and computed[255]['coexistence']['payload_is_byte_exact']
                  and computed[255]['all_four_symbol_groups_covered']
                  and any(row['changed_shadow_pixels'] for row in computed[255]['groups']))
    observed = [mask for mask in (191, 63) if not errors and valid_cases[mask] and computed[mask]['pass']]
    return {'schema': 'native_shadow_mask_comparative_matrix_v1', 'operational_complete': not errors,
            'classification': ('operational_or_cross_candidate_control_failure' if errors
                               else 'comparative_native_results_observed' if reproduced
                               else 'original_conflict_not_reproduced'),
            'errors': errors, 'native_only_cross_candidate_controls': controls,
            'cases': [{'mask': mask, 'classification': cases[mask].get('classification'),
                       'compatibility_recomputed': computed[mask]['pass'] if valid_cases[mask] else None,
                       'groups': computed[mask]['groups'],
                       'full_comparison_recomputed': computed[mask]}
                      for mask in (255, 191, 63)],
            'original_control_conflict_reproduced': reproduced,
            'observed_compatible_candidates': observed,
            'qualified_mask_repair_candidates': observed if reproduced else [],
            'production_fix_validated': False, 'engine_material_resolution_proven': False}
