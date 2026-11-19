"""Offline fixed-mask rain motion audit; observations never promote a native pass.

Reads saved WGC PNGs, raw alpha diagnostics and predeclared geometry only. No
Minecraft operations, mask fitting, alignment search or threshold adjustment.
"""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


THRESHOLDS = (2, 4, 8, 16, 32)
QUANTILES = (0, 50, 90, 95, 99, 100)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def polygon(shape, points):
    image = Image.new('1', (shape[1], shape[0]))
    ImageDraw.Draw(image).polygon([tuple(point) for point in points], fill=1)
    return np.array(image, dtype=bool)


def rectangle_polygon(shape, bounds):
    left, top, right, bottom = bounds
    return polygon(shape, [[left, top], [right, top], [right, bottom], [left, bottom]])


def masks(status, weather):
    """Reproduce the unchanged declared recipes, without examining image colors."""
    plan = status['shadow_plan']
    width, height = plan['viewport']
    shape = (height, width)
    receiver = polygon(shape, plan['receiver_polygon'])
    left, top, right, bottom = plan['body_bounds']
    receiver &= ~rectangle_polygon(shape, [left-3, top-3, right+3, bottom+3])
    dx, dy = (right-left)*.3, (bottom-top)*.3
    body = rectangle_polygon(shape, [left+dx, top+dy, right-dx, bottom-dy])
    control = polygon(shape, plan['control_polygon']) & ~receiver & ~body
    for mask in (receiver, body, control):
        mask[plan['output_y']:] = False
    target = status['target_plan']
    face = np.asarray(target['face_polygon'])
    center = face.mean(axis=0)
    highlight = polygon(shape, (center+(face-center)*.8).tolist())
    highlight[target['output_y']:] = False
    for x, y, w, h in target['ui_rectangles_excluded']:
        highlight[y:y+h, x:x+w] = False
    bounds = weather['roles']['outline']['result']['fixture_window']
    outline = np.zeros(shape, dtype=bool)
    left, top, right, bottom = bounds
    outline[max(0, math.floor(top)):min(height, math.ceil(bottom)),
            max(0, math.floor(left)):min(width, math.ceil(right))] = True
    x, y, w, h = plan['roi']
    roi = np.zeros(shape, dtype=bool)
    roi[y:y+h, x:x+w] = True
    return {'shadow': receiver|body|control, 'shadow_receiver': receiver,
            'shadow_body_control': body, 'shadow_floor_control': control,
            'outline': outline, 'highlight': highlight, 'source_roi': roi}


def distribution(values):
    return {'mean': float(values.mean()),
            'percentiles': {str(q): float(np.percentile(values, q)) for q in QUANTILES}}


def metrics(before, after, mask):
    difference = np.abs(after.astype(np.int16)-before.astype(np.int16))
    delta = difference.max(axis=2)
    values = delta[mask]
    result = {'pixels': int(mask.sum()), 'max_rgb_delta': distribution(values),
              'changed_pixels': {str(t): int((values > t).sum()) for t in THRESHOLDS},
              'changed_fraction': {str(t): float(np.mean(values > t)) for t in THRESHOLDS},
              'mean_absolute_channel_delta': difference[mask].mean(axis=0).tolist()}
    # Fixed 32x32 screen grid, clipped only by declared geometry. These tiles
    # quantify spatial density; they never select a revised acceptance region.
    densities, occupied, changed = [], 0, delta > 2
    for y in range(0, mask.shape[0], 32):
        for x in range(0, mask.shape[1], 32):
            tile = mask[y:y+32, x:x+32]
            count = int(tile.sum())
            if not count:
                continue
            bad = int((changed[y:y+32, x:x+32] & tile).sum())
            occupied += bad > 0
            densities.append(bad/count)
    result['fixed_grid_32px'] = {'eligible_tiles': len(densities), 'changed_tiles': occupied,
                                'density': distribution(np.asarray(densities))}
    return result


def audit(evidence):
    evidence = Path(evidence).resolve()
    status = read(evidence/'joint-status.json')
    results = read(evidence/'results.json')
    reports = {row['label']: row for row in results['reports']}
    cache, captures = {}, {}

    def image(label):
        if label not in cache:
            row = reports[label]
            path = Path(row['capture_file'])
            receipt = read(evidence/(label+'.json'))
            cache[label] = np.asarray(Image.open(path).convert('RGB'))
            if cache[label].shape != (1080, 720, 3):
                raise ValueError('Expected saved native 720x1080 RGB image')
            captures[label] = {'png_sha256': sha(path), 'receipt_sha256': sha(evidence/(label+'.json')),
                               'frame_qpc_100ns': receipt['frame_qpc_100ns'], 'pid': receipt['pid']}
        return cache[label]

    payload = (evidence/'n65536_actual_input.bin').read_bytes()
    values = np.frombuffer(payload, dtype=np.uint8).astype(np.int64)
    symbols = np.array([(byte>>shift)&3 for byte in payload for shift in (0, 2, 4, 6)])
    expected_markers = np.column_stack((values, (71*values+43)%256, (131*values+17)%256))
    output = {'schema': 'joint_fixed_mask_rain_motion_audit_v1', 'evidence': str(evidence),
              'audit_source_sha256': sha(__file__), 'joint_status_sha256': sha(evidence/'joint-status.json'),
              'results_sha256': sha(evidence/'results.json'), 'payload_sha256': hashlib.sha256(payload).hexdigest(),
              'thresholds_fixed': list(THRESHOLDS), 'tile_size_fixed': 32,
              'mask_adaptation': False, 'alignment_search': False, 'pass_promotion': False,
              'same_frame_alpha_is_correlation_not_causal_attribution': True, 'weather': []}

    def compare(label_a, label_b, geometry):
        a, b = image(label_a), image(label_b)
        return {'before': label_a, 'after': label_b,
                'gap_seconds': (captures[label_b]['frame_qpc_100ns']-captures[label_a]['frame_qpc_100ns'])/1e7,
                'regions': {name: metrics(a, b, mask) for name, mask in geometry.items()}}

    for weather in status['weather']:
        name = weather['weather']
        geometry = masks(status, weather)
        prefix = 'joint_'+name+'_'
        native = prefix+'all_on_native'
        active = prefix+'all_on_active'
        mode1, mode3 = prefix+'all_roles_payload_m1', prefix+'all_roles_payload_m3'
        native_repeats = [prefix+role+'_on' for role in ('shadow', 'outline', 'highlight')]+[native]
        carrier_repeats = [active, mode1, mode3]
        row = {'weather': name, 'geometry_pixels': {key: int(mask.sum()) for key, mask in geometry.items()},
               'off_replays': {}, 'native_all_on_repeats': [], 'carrier_all_on_repeats': [],
               'native_to_carrier': [], 'full_diagnostics': [], 'alpha_correlations': {}}
        for role in ('shadow', 'outline', 'highlight'):
            regions = ({key: geometry[key] for key in ('shadow', 'shadow_receiver', 'shadow_body_control', 'shadow_floor_control')}
                       if role == 'shadow' else {role: geometry[role]})
            row['off_replays'][role] = compare(prefix+role+'_off_before', prefix+role+'_off_after', regions)
        for a, b in zip(native_repeats, native_repeats[1:]):
            row['native_all_on_repeats'].append(compare(a, b, geometry))
        for a, b in itertools.combinations(carrier_repeats, 2):
            row['carrier_all_on_repeats'].append(compare(a, b, geometry))
        for label in carrier_repeats:
            row['native_to_carrier'].append(compare(native, label, geometry))

        alpha = np.full((1080, 720), 255, dtype=np.int16)
        x, y, w, h = status['shadow_plan']['roi']
        for mode, label in ((1, mode1), (3, mode3)):
            data = image(label)[650:].reshape(-1, 3).astype(np.int64)
            count = len(payload)*(4 if mode == 3 else 1)
            if mode == 1:
                bad = np.any(data[:count] != expected_markers, axis=1)
            else:
                bad = (data[:count, 0]//64 != symbols) | (data[:count, 2] != 0)
                alpha[y:y+h, x:x+w] = data[:count, 1].reshape(h, w)
            guards = np.any(data[count:] != [17, 53, 97], axis=1)
            row['full_diagnostics'].append({'mode': mode, 'data_pixels': count,
                                           'data_errors': int(bad.sum()), 'guard_pixels': len(data)-count,
                                           'guard_errors': int(guards.sum())})
        alpha_strata = {'lt192': alpha < 192, '192to254': (alpha >= 192)&(alpha < 255), 'eq255': alpha == 255}
        delta = np.abs(image(mode3).astype(np.int16)-image(native).astype(np.int16)).max(axis=2)
        for region_name, region in geometry.items():
            eligible = region & geometry['source_roi']
            if not eligible.any():
                continue
            strata = {}
            for stratum_name, stratum in alpha_strata.items():
                mask = eligible & stratum
                if mask.any():
                    strata[stratum_name] = {'pixels': int(mask.sum()),
                                           'delta': distribution(delta[mask]),
                                           'changed_gt2': int((delta[mask] > 2).sum()),
                                           'changed_gt2_fraction': float(np.mean(delta[mask] > 2))}
            deficit, error = 255-alpha[eligible].astype(float), delta[eligible].astype(float)
            correlation = (float(np.corrcoef(deficit, error)[0, 1])
                           if deficit.std() and error.std() else None)
            row['alpha_correlations'][region_name] = {'same_frame_m3_roi_pixels': int(eligible.sum()),
                'non255_alpha_pixels': int((alpha[eligible] < 255).sum()),
                'pearson_alpha_deficit_vs_native_to_m3_delta': correlation,
                'strata': strata}
        output['weather'].append(row)
    output['captures'] = captures
    output['limitation'] = ('RGB comparisons are separate-frame observations at recorded time gaps. '
        'Alpha is simultaneous only with mode3; alpha=255 can include rain visible in the older frame. '
        'The four native all-on samples and three carrier all-on samples have different capture gaps. '
        'These data quantify noise and association; they cannot establish an exact same-frame native/carrier difference.')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'output': str(args.output.resolve()), 'sha256': sha(args.output),
                      'weather': [row['weather'] for row in result['weather']]}))


if __name__ == '__main__':
    main()
