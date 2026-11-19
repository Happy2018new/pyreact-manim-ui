"""Host-only native shadow witnesses with predeclared geometry and payload binding."""
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


_PAYLOAD_SPEC = importlib.util.spec_from_file_location('shadow_complete_payload_verifier',
    Path(__file__).resolve().parents[1] / 'weather_stencil_large_probe/verify.py')
_PAYLOAD_VERIFY = importlib.util.module_from_spec(_PAYLOAD_SPEC)
_PAYLOAD_SPEC.loader.exec_module(_PAYLOAD_VERIFY)


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest()


def _polygon(shape, points):
    height, width = shape
    if len(points) < 3 or any(len(point) != 2 or not np.isfinite(point).all() for point in points):
        raise ValueError('Predeclared screen polygons need at least three finite xy points')
    image = Image.new('1', (width, height))
    ImageDraw.Draw(image).polygon([tuple(point) for point in points], fill=1)
    return np.array(image, dtype=bool)


def _rectangle(shape, bounds):
    left, top, right, bottom = bounds
    return _polygon(shape, [[left, top], [right, top], [right, bottom], [left, bottom]])


def _masks(plan):
    width, height = plan['viewport']
    shape = (height, width)
    receiver = _polygon(shape, plan['receiver_polygon'])
    left, top, right, bottom = plan['body_bounds']
    receiver &= ~_rectangle(shape, [left - 3, top - 3, right + 3, bottom + 3])
    dx, dy = (right - left) * .3, (bottom - top) * .3
    body = _rectangle(shape, [left + dx, top + dy, right - dx, bottom - dy])
    control = _polygon(shape, plan['control_polygon']) & ~receiver & ~body
    receiver[plan['output_y']:] = False
    body[plan['output_y']:] = False
    control[plan['output_y']:] = False
    x, y, rw, rh = plan['roi']
    inside = np.zeros(shape, dtype=bool)
    inside[y:y + rh, x:x + rw] = True
    boundary = np.zeros(shape, dtype=bool)
    boundary[max(0, y - 2):y + 3, x:x + rw] = True
    boundary[y + rh - 2:min(height, y + rh + 3), x:x + rw] = True
    boundary[y:y + rh, max(0, x - 2):x + 3] = True
    boundary[y:y + rh, x + rw - 2:min(width, x + rw + 3)] = True
    return receiver, body, control, inside, boundary


def make_plan(viewport, roi, receiver_polygon, body_bounds, control_polygon, output_y=650):
    """Freeze geometry before captures; polygons are projected from known world patches.

    The control polygon must be a separate unshadowed floor patch, outside the
    receiver polygon. All masks are geometry-derived, never selected from pixels.
    """
    viewport, roi = list(viewport), list(roi)
    if (len(viewport) != 2 or len(roi) != 4 or len(body_bounds) != 4
            or any(not isinstance(value, int) or isinstance(value, bool) for value in viewport + roi)
            or min(viewport) < 1 or output_y < 1 or output_y > viewport[1]):
        raise ValueError('Need integer viewport/ROI and valid reserved diagnostic origin')
    x, y, width, height = roi
    if min(x, y) < 0 or min(width, height) < 1 or x + width > viewport[0] or y + height > viewport[1]:
        raise ValueError('Source ROI lies outside viewport')
    if (not np.isfinite(body_bounds).all() or body_bounds[2] <= body_bounds[0]
            or body_bounds[3] <= body_bounds[1]):
        raise ValueError('Expected finite nonempty projected body bounds')
    plan = {'schema': 'native_shadow_predeclared_geometry_v1', 'viewport': list(viewport),
            'roi': list(roi), 'receiver_polygon': receiver_polygon, 'body_bounds': list(body_bounds),
            'control_polygon': control_polygon, 'output_y': output_y,
            'pixel_tolerance': 2, 'off_stability_channel_tolerance': 4,
            'maximum_changed_fraction': .01, 'minimum_shadow_pixels_each_side': 24,
            'minimum_darkening_mean': 8, 'minimum_darkening_each_channel': 4,
            'maximum_shadow_channel_ratio_spread': .12,
            'pixel_derived_masks': False, 'alignment_search': False}
    receiver, body, control, inside, _ = _masks(plan)
    counts = {'receiver': int(receiver.sum()), 'body_control': int(body.sum()),
              'floor_control': int(control.sum()), 'receiver_inside_roi': int((receiver & inside).sum()),
              'receiver_outside_roi': int((receiver & ~inside).sum())}
    if min(counts.values()) < 64:
        raise ValueError('Predeclared receiver must cross ROI, with at least64pixels per side/body/control')
    plan['mask_pixels'] = counts
    plan['plan_sha256'] = _sha(plan)
    return json.loads(json.dumps(plan))


def _validate_plan(plan):
    copy = dict(plan)
    expected = copy.pop('plan_sha256', None)
    if expected is None or expected != _sha(copy) or plan.get('pixel_derived_masks') is not False:
        raise ValueError('Shadow geometry plan changed after freezing')


def _rgb(frame, plan):
    value = np.asarray(frame)
    width, height = plan['viewport']
    if value.dtype != np.uint8 or value.ndim != 3 or value.shape[:2] != (height, width) or value.shape[2] < 3:
        raise ValueError('Expected native viewport uint8 RGB/RGBA capture')
    return value[:, :, :3].astype(np.int16)


def _change(before, after, mask, tolerance):
    delta = np.max(np.abs(before - after), axis=2)[mask]
    return {'pixels': int(delta.size), 'changed_pixels': int((delta > tolerance).sum()),
            'changed_fraction': float(np.mean(delta > tolerance)),
            'max_channel_delta': int(delta.max()), 'channel_tolerance': tolerance}


def compare_shadow(off_before, on, off_after, plan):
    """Require neutral darkening across ROI and stable floor, body and off replay."""
    _validate_plan(plan)
    before, active, after = [_rgb(frame, plan) for frame in (off_before, on, off_after)]
    receiver, body, control, inside, boundary = _masks(plan)
    dark = np.minimum(before - active, after - active)
    ratio = active.astype(float) / np.maximum((before.astype(float) + after) * .5, 1.)
    positive = (receiver & (np.minimum(before, after).min(axis=2) >= 24)
                & (dark.min(axis=2) >= plan['minimum_darkening_each_channel'])
                & (dark.mean(axis=2) >= plan['minimum_darkening_mean'])
                & (np.ptp(ratio, axis=2) <= plan['maximum_shadow_channel_ratio_spread']))
    counts = {'inside_roi': int((positive & inside).sum()),
              'outside_roi': int((positive & ~inside).sum()),
              'at_roi_boundary': int((positive & boundary).sum()), 'total': int(positive.sum())}
    metrics = {'receiver_off_replay': _change(before, after, receiver, 4),
               'floor_control_off_replay': _change(before, after, control, 4),
               'floor_control_on': _change(before, active, control, 4),
               'body_control_off_replay': _change(before, after, body, 4),
               'body_control_on': _change(before, active, body, 4)}
    errors = [name + ' changed: receiver/background/animation stability failed'
              for name, value in metrics.items() if value['changed_fraction'] > .01]
    if min(counts['inside_roi'], counts['outside_roi']) < plan['minimum_shadow_pixels_each_side']:
        errors.append('native dark shadow witness missing on one or both sides of source ROI')
    if counts['at_roi_boundary'] < 2:
        errors.append('native shadow witness does not cross source ROI boundary')
    return {'schema': 'native_shadow_visible_positive_control_v1', 'pass': not errors,
            'errors': errors, 'plan_sha256': plan['plan_sha256'], 'shadow_pixels': counts,
            'stability': metrics, 'native_data_compatibility_checked': False,
            'native_shadow_shader_route_authenticated_by_pixels': False}


def compare_snapshots(states):
    """Owner receipts bind toggles to one stationary entity and unchanged receiver."""
    if len(states) != 3:
        raise ValueError('Need off-before/on/off-after native receipts')
    errors = []
    if [state.get('shadow_requested') for state in states] != [False, True, False]:
        errors.append('shadow requested sequence is not off/on/off')
    for key in ('entity', 'native_position', 'camera', 'receiver_revision'):
        if states[0].get(key) is None or any(state.get(key) != states[0].get(key) for state in states[1:]):
            errors.append('native ' + key + ' missing or changed')
    if any(not (state.get('animation_frozen') or state.get('static_entity')) for state in states):
        errors.append('native entity pose is not frozen')
    return {'pass': not errors, 'errors': errors, 'setter_return_value_is_proof': False,
            'shadow_getter_available': False}


def _payload_gate(reports, roi):
    errors, hashes, by_mode = [], set(), {}
    for report in reports:
        mode = report.get('mode')
        if mode not in (1, 3):
            continue
        by_mode[mode] = report
        identity = report.get('state', {}).get('identity', {})
        state = report.get('state', {})
        expected_hash, observed_hash = identity.get('host_sha256'), report.get('payload_sha256')
        query_count = 65536 if mode == 1 else 262144
        if (report.get('logical_bytes') != 65536 or report.get('exact') is not True
                or report.get('error_pixels') != 0 or report.get('configuration') != 'all'
                or report.get('state', {}).get('payload_visible') is not True
                or report.get('source_roi') != roi or identity.get('byte_count') != 65536
                or report.get('query_count') != query_count
                or report.get('distinct_final_addresses') != 65536
                or not expected_hash or observed_hash != expected_hash):
            errors.append('64KiB active-carrier exact payload receipt failed for mode' + str(mode))
        if (state.get('state') != 'resident' or state.get('ready') is not True
                or not isinstance(state.get('generation'), int) or isinstance(state['generation'], bool) or state['generation'] < 1
                or not isinstance(state.get('active_pages'), list) or len(state['active_pages']) != 2
                or not isinstance(state.get('native_page_names'), list) or len(state['native_page_names']) != 3
                or len(set(state['active_pages'])) != 2 or len(set(state['native_page_names'])) != 3
                or any(not isinstance(name,str) or not name for name in state['native_page_names'])
                or not set(state['active_pages']).issubset(set(state['native_page_names']))
                or not isinstance(state.get('native_attempt_count'), int) or state['native_attempt_count'] < 3
                or state.get('native_records_reserved') != 131073):
            errors.append('explicit resident64KiB native page/record receipts missing for mode' + str(mode))
        hashes.add(expected_hash)
    if set(by_mode) != {1, 3} or len(hashes) != 1:
        errors.append('complete mode1 identity and mode3 raw-byte checks must share one64KiBidentity')
    reference = next(iter(by_mode.values())).get('state', {}) if by_mode else {}
    for report in by_mode.values():
        state = report.get('state', {})
        if any(state.get(key) != reference.get(key) for key in (
                'identity', 'active_pages', 'native_page_names', 'native_attempt_count',
                'native_records_reserved', 'generation')):
            errors.append('native payload identity/pages changed between exhaustive diagnostic frames')
    return {'pass': not errors, 'errors': errors, 'checked_modes': sorted(by_mode),
            'payload_sha256': next(iter(hashes)) if len(hashes) == 1 else None}


def _diagnostic_visuals(baseline_on, reports, plan, region, actual_payload):
    """Each exact data screenshot must simultaneously retain its native shadow."""
    comparisons = []
    baseline = _rgb(baseline_on, plan)
    if not isinstance(actual_payload, bytes) or len(actual_payload) != 65536:
        return [{'pass': False, 'error': 'actual host65536byte input is required for independent pixel decoding'}]
    for report in reports:
        if report.get('mode') not in (1, 3):
            continue
        path = Path(report.get('capture_file', ''))
        if not path.is_file() or report.get('output_origin') != [0, plan['output_y']]:
            comparisons.append({'label': report.get('label'), 'pass': False,
                                'error': 'same-frame diagnostic capture or reserved output origin missing'})
            continue
        with Image.open(path) as image:
            native_image = image.convert('RGB')
            pixels = _rgb(native_image, plan)
            decoded = _PAYLOAD_VERIFY.verify(native_image, report['mode'], actual_payload,
                plan['viewport'], plan['roi'], output_y=plan['output_y'])
        difference = _change(baseline, pixels, region, plan['pixel_tolerance'])
        identity = report.get('state', {}).get('identity', {})
        input_matches = decoded['payload_sha256'] == identity.get('host_sha256')
        comparisons.append({'label': report.get('label'),
                            'pass': difference['changed_pixels'] == 0 and decoded['exact'] and input_matches,
                            'whole_regions': difference,
                            'capture_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                            'independently_decoded_payload': decoded,
                            'actual_input_matches_native_identity': input_matches})
    return comparisons


def compare_coexistence(baseline_triplet, active_triplet, plan, payload_reports, actual_payload=None):
    """Compare every predeclared witness/control pixel; payload checks remain exact."""
    baseline = compare_shadow(*baseline_triplet, plan)
    active = compare_shadow(*active_triplet, plan)
    receiver, body, control, _, _ = _masks(plan)
    region = receiver | body | control
    comparisons = [_change(_rgb(first, plan), _rgb(second, plan), region, plan['pixel_tolerance'])
                   for first, second in zip(baseline_triplet, active_triplet)]
    payload = _payload_gate(payload_reports, plan['roi'])
    diagnostic_visuals = _diagnostic_visuals(baseline_triplet[1], payload_reports, plan, region, actual_payload)
    errors = []
    if not baseline['pass'] or not active['pass']:
        errors.append('both native-only and carrier-active shadow positive controls must pass')
    if any(row['changed_pixels'] for row in comparisons):
        errors.append('shadow/floor/body pixels changed beyond2channel quantization tolerance')
    if not payload['pass']:
        errors.extend(payload['errors'])
    if len(diagnostic_visuals) < 2 or any(not row['pass'] for row in diagnostic_visuals):
        errors.append('same screenshots must preserve native shadow while exposing exact complete payload')
    return {'schema': 'native_shadow_64kib_coexistence_v1', 'pass': not errors, 'errors': errors,
            'plan_sha256': plan['plan_sha256'], 'baseline': baseline, 'active': active,
            'native_vs_active_whole_regions': comparisons, 'visual_channel_tolerance': 2,
            'same_frame_shadow_and_payload_screenshots': diagnostic_visuals,
            'payload': payload, 'payload_is_byte_exact': payload['pass'] and all(
                row.get('independently_decoded_payload', {}).get('exact')
                and row.get('actual_input_matches_native_identity') for row in diagnostic_visuals),
            'pixel_derived_masks': False, 'separate_frame_visual_comparison': True}


def native_material_receipt(client_root):
    """Authenticate shipped source semantics; this is not proof of the engine route."""
    client = Path(client_root)
    path = client / 'data/resource_packs/vanilla/materials/shadows.material'
    data = path.read_bytes()
    materials = json.loads(data.decode('utf-8-sig'))['materials']
    front, back, overlay = [materials[name] for name in ('shadow_front', 'shadow_back', 'shadow_overlay')]
    if (front['stencilWriteMask'] != 1 or back['stencilWriteMask'] != 1
            or overlay['stencilRef'] != 1 or overlay['stencilReadMask'] != 255
            or overlay['stencilWriteMask'] != 0 or overlay['frontFace']['stencilFunc'] != 'Equal'
            or overlay['blendSrc'] != 'DestColor' or overlay['blendDst'] != 'Zero'):
        raise ValueError('Installed shadow stencil recipe differs from reviewed467018source')
    shader = client / 'data/shaders/glsl/shadow_stencil_overlay.fragment'
    return {'source_path': str(path), 'source_sha256': hashlib.sha256(data).hexdigest(),
            'shader_path': str(shader), 'shader_sha256': hashlib.sha256(shader.read_bytes()).hexdigest(),
            'materials': {name: materials[name] for name in ('shadow_front', 'shadow_back', 'shadow_overlay')},
            'transport_mask': 192, 'shadow_overlay_shared_read_bits': overlay['stencilReadMask'] & 192,
            'shadow_volume_shared_write_bits': back['stencilWriteMask'] & 192,
            'engine_route_proven': False, 'installed_resources_modified': False}
