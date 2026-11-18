"""Independently compare the two historical RGB failures without codec imports."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


FILES = {
    'baseline': 'native64k2_native_k2_bytes65536_baseline.png',
    'first_restored': 'native64k2_native_k2_bytes65536_restored.png',
    'later_off': 'k2_rgb_steady_off_after.png',
    'followup_before': 'k2_rgb_followup_off_before.png',
    'steady_on': 'k2_rgb_steady_on.png',
}


def describe(mask, baseline, candidate, xs, ys):
    selected = np.flatnonzero(mask)
    result = {'count': int(len(selected))}
    if not len(selected):
        return result
    def common(values):
        return [{'rgb': list(color), 'count': count}
                for color, count in Counter(map(tuple, values.tolist())).most_common(5)]
    result.update({
        'display_bbox_inclusive': [int(xs[selected].min()), int(ys[selected].min()),
                                   int(xs[selected].max()), int(ys[selected].max())],
        'ordinal_min_max': [int(selected.min()), int(selected.max())],
        'rows': {str(int(y)): int(count) for y, count in
                 zip(*np.unique(ys[selected], return_counts=True))},
        'max_rgb_error': int(np.abs(candidate[selected] - baseline[selected]).max()),
        'baseline_common': common(baseline[selected]),
        'candidate_common': common(candidate[selected]),
        'delta_common': common(candidate[selected] - baseline[selected]),
        'ordinal_mask_sha256': hashlib.sha256(mask.astype(np.uint8).tobytes()).hexdigest(),
    })
    source_x = 8 + selected % 128
    source_y = 32 + selected // 128
    result['source_bbox_inclusive'] = [int(source_x.min()), int(source_y.min()),
                                       int(source_x.max()), int(source_y.max())]
    result['source_rows'] = {str(int(y)): int(count) for y, count in
                             zip(*np.unique(source_y, return_counts=True))}
    return result


def analyze(directory, count=87424):
    directory = Path(directory).resolve()
    indices = np.arange(count)
    xs, ys = indices % 720, 128 + indices // 720
    colors, sources = {}, {}
    for name, filename in FILES.items():
        path = directory / filename
        if name == 'steady_on' and not path.exists():
            continue
        with Image.open(path) as image:
            pixels = np.asarray(image.convert('RGB'), dtype=np.int16)
        if pixels.shape[:2] != (1080, 720):
            raise ValueError('Expected 720x1080 capture: ' + str(path))
        colors[name] = pixels[ys, xs]
        sources[name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    baseline = colors['baseline']
    first_mask = np.any(np.abs(colors['first_restored'] - baseline) > 2, axis=1)
    later_mask = np.any(colors['later_off'] != baseline, axis=1)
    result = {
        'kind': 'historical_rgb_disjoint_failure_audit_v1',
        'independent_of_probe_codec': True,
        'sources': sources,
        'layout': {'source_roi': [8, 32, 128, 683], 'count': count,
                   'display_x': 'ordinal % 720', 'display_y': '128 + ordinal // 720'},
        'first_restored_error_gt_2': describe(first_mask, baseline, colors['first_restored'], xs, ys),
        'later_off_error_gt_0': describe(later_mask, baseline, colors['later_off'], xs, ys),
        'intersection_count': int(np.count_nonzero(first_mask & later_mask)),
        'baseline_equals_followup_before': bool(np.array_equal(baseline, colors['followup_before'])),
        'first_failure_pixels_matching_later_off_within_2': int(np.count_nonzero(
            first_mask & np.all(np.abs(colors['first_restored'] - colors['later_off']) <= 2, axis=1))),
        'causal_attribution': None,
        'conclusion': 'Compare locations and colors; later scene variation is not an explanation '
                      'for the first anomaly when the failure masks are disjoint. No object or engine cause is inferred.',
    }
    if 'steady_on' in colors:
        result['first_failure_pixels_matching_steady_on_exactly'] = int(np.count_nonzero(
            first_mask & np.all(colors['first_restored'] == colors['steady_on'], axis=1)))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Refusing to overwrite an existing historical audit')
    result = analyze(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('intersection_count', 'baseline_equals_followup_before')}))
