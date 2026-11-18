"""Host-only positive control for native outline; payload correctness stays separate."""
import math

import numpy as np


def _rgb(frame):
    value = np.asarray(frame)
    if value.dtype != np.uint8 or value.ndim != 3 or value.shape[2] < 3:
        raise ValueError('Native outline captures must be uint8 RGB or RGBA images')
    return value[:, :, :3].astype(np.int16)


def compare_snapshots(off_before, on, off_after):
    """Native receipts prove frozen placement and query state, never rendered pixels."""
    states = (off_before, on, off_after)
    errors = []
    if any(not state.get('entity') for state in states):
        errors.append('native fixture entity is missing')
    if len(set(state.get('entity') for state in states)) != 1:
        errors.append('fixture entity changed across captures')
    if [state.get('native_query') for state in states] != [0., 1., 0.]:
        errors.append('native query sequence must be off/on/off')
    if any(not state.get('registered') or not state.get('position_matches_requested')
           or not state.get('camera_matches_initial') or not state.get('projection_all_visible')
           or not state.get('native_material_recipe_present')
           or not state.get('native_render_controllers_present')
           for state in states):
        errors.append('native recipe, registration, position, camera or visible projection was not frozen')
    for key in ('requested_position', 'native_position', 'camera', 'roi', 'viewport',
                'projected_corners', 'projected_bounds'):
        if any(state.get(key) != states[0].get(key) for state in states[1:]):
            errors.append(key + ' changed across captures')
    return {'pass': not errors, 'errors': errors, 'rendered_outline_proven': False}


def _rectangle(shape, bounds):
    height, width = shape
    left, top, right, bottom = bounds
    mask = np.zeros(shape, dtype=bool)
    mask[max(0, min(height, int(math.floor(top)))):max(0, min(height, int(math.ceil(bottom)))),
         max(0, min(width, int(math.floor(left)))):max(0, min(width, int(math.ceil(right))))] = True
    return mask


def _roi_masks(shape, roi):
    x, y, width, height = roi
    inside = _rectangle(shape, [x, y, x + width, y + height])
    boundary = _rectangle(shape, [x - 2, y, x + 3, y + height])
    boundary |= _rectangle(shape, [x + width - 2, y, x + width + 3, y + height])
    boundary |= _rectangle(shape, [x, y - 2, x + width, y + 3])
    boundary |= _rectangle(shape, [x, y + height - 2, x + width, y + height + 3])
    return inside, boundary


def _new_magenta(before, active, after):
    magenta = ((active[:, :, 0] >= 80) & (active[:, :, 2] >= 80)
               & (active[:, :, 0] - active[:, :, 1] >= 40)
               & (active[:, :, 2] - active[:, :, 1] >= 40)
               & (np.abs(active[:, :, 0] - active[:, :, 2]) <= 70))
    changed = np.minimum(np.max(np.abs(active - before), axis=2),
                         np.max(np.abs(active - after), axis=2)) >= 12
    return magenta & changed


def _body_core(before, active, bounds):
    left, top, right, bottom = bounds
    dx, dy = (right - left) * .3, (bottom - top) * .3
    core = _rectangle(before.shape[:2], [left + dx, top + dy, right - dx, bottom - dy])
    gray = (np.max(before, axis=2) >= 60) & (np.ptp(before, axis=2) <= 35)
    unchanged = np.max(np.abs(active - before), axis=2) <= 8
    pixels = int(np.count_nonzero(core & gray & unchanged))
    return pixels, int(np.count_nonzero(core))


def _pixel_metrics(before, active, after, roi, bounds):
    height, width = active.shape[:2]
    left, top, right, bottom = bounds
    margin = max(12, int(math.ceil(max(right - left, bottom - top) * .25)))
    region = [max(0, int(math.floor(left)) - margin), max(0, int(math.floor(top)) - margin),
              min(width, int(math.ceil(right)) + margin), min(height, int(math.ceil(bottom)) + margin)]
    window = _rectangle((height, width), region)
    inside, boundary = _roi_masks(window.shape, roi)
    positive = window & _new_magenta(before, active, after)
    shell = window & ~_rectangle(window.shape, bounds)
    stable_delta = np.max(np.abs(before - after), axis=2)[window]
    body_pixels, core_pixels = _body_core(before, active, bounds)
    return {'positive_pixels': {
        'inside_roi': int(np.count_nonzero(positive & inside)),
        'outside_roi': int(np.count_nonzero(positive & ~inside)),
        'at_roi_boundary': int(np.count_nonzero(positive & boundary)),
        'outside_projected_body': int(np.count_nonzero(positive & shell)),
        'total': int(np.count_nonzero(positive))}, 'fixture_window': region,
        'unchanged_neutral_body_core_pixels': body_pixels, 'body_core_pixels': core_pixels,
        'off_replay_changed_fraction_over_4': float(np.mean(stable_delta > 4)),
        'off_replay_max_channel_delta': int(np.max(stable_delta))}


def compare_outline(off_before, on, off_after, roi, bounds=None, minimum_pixels=24):
    """Require new magenta pixels on both sides of an ROI boundary and stable off frames.

    Supply the native snapshot's projected_bounds; an unrelated magenta scene pixel
    cannot satisfy a whole-screen color test. Capture with native transport disabled
    for this positive control, then verify payload separately under the same fixture.
    """
    before, active, after = (_rgb(frame) for frame in (off_before, on, off_after))
    if before.shape != active.shape or before.shape != after.shape:
        raise ValueError('Outline captures must use the same viewport')
    if len(roi) != 4 or minimum_pixels < 1:
        raise ValueError('Expected ROI x/y/width/height and positive pixel threshold')
    height, width = active.shape[:2]
    x, y, rw, rh = [int(value) for value in roi]
    if x < 0 or y < 0 or rw <= 0 or rh <= 0 or x + rw > width or y + rh > height:
        raise ValueError('Outline ROI is outside captured viewport')
    result = {'kind': 'native_outline_visible_positive_control_v1', 'pass': False,
              'native_data_compatibility': None, 'native_data_compatibility_checked': False,
              'roi': list(roi), 'projected_bounds': bounds, 'errors': []}
    if bounds is None or len(bounds) != 4 or any(not math.isfinite(value) for value in bounds):
        result['errors'].append('native projected fixture bounds are required')
        return result
    left, top, right, bottom = bounds
    if right <= left or bottom <= top or left < 0 or top < 0 or right > width or bottom > height:
        result['errors'].append('projected fixture must be fully inside capture')
        return result
    result.update(_pixel_metrics(before, active, after, roi, bounds))
    counts = result['positive_pixels']
    unstable_fraction = result['off_replay_changed_fraction_over_4']
    result.update({'off_replay_stable': unstable_fraction <= .01,
                   'minimum_pixels_each_side': minimum_pixels})
    if unstable_fraction > .01:
        result['errors'].append('off-before/off-after fixture window changed')
    if counts['inside_roi'] < minimum_pixels or counts['outside_roi'] < minimum_pixels:
        result['errors'].append('new visible magenta outline must exist inside and outside ROI')
    if counts['at_roi_boundary'] < 2:
        result['errors'].append('visible outline did not cross an ROI boundary')
    if counts['outside_projected_body'] < minimum_pixels:
        result['errors'].append('magenta shell outside projected body is missing')
    if result['unchanged_neutral_body_core_pixels'] < max(minimum_pixels, result['body_core_pixels'] * .25):
        result['errors'].append('visible neutral body did not remain present under outline')
    result['pass'] = not result['errors']
    return result
