"""Host-only complete diagnostics for explicit encoded/restored texture copies."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    'stencil_integrated_bulk_verify', HERE.parent / 'weather_stencil_large_probe/verify.py')
bulk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bulk)
payload_bytes = bulk.payload_bytes
GUARD = bulk.GUARD
OUTPUT_Y = 128
SHAPE_CLIP = (408, 704, 296, 304)


def fixture_rgba(roi):
    """Expected known fixture at every local integer source pixel, row major."""
    width, height = int(roi[2]), int(roi[3])
    ordinal = np.arange(width * height, dtype=np.int64)
    x, y = ordinal % width, ordinal // width
    return np.column_stack(((33*x + 17*y + 13) % 256,
                            (73*x + 19*y + 41) % 256,
                            (151*x + 47*y + 97) % 256,
                            (11*x + 31*y + 211) % 256)).astype(np.uint8)


def _rgb(image, viewport):
    rgb = np.asarray(image)
    width, height = (int(value) for value in viewport)
    if (rgb.ndim != 3 or rgb.shape[:2] != (height, width)
            or rgb.shape[2] < 3 or rgb.dtype != np.uint8):
        raise ValueError('Expected a native-size uint8 RGB/RGBA image')
    return rgb[:, :, :3]


def shape_bars(payload):
    """Exact16bars consumed from arbitrary actual bytes, without a GPU seed."""
    values = bulk._payload_array(payload)
    bars = []
    for index in range(16):
        address = (4093 * index + 17) % int(values.size)
        value = int(values[address])
        height = 4 + value
        bars.append({'index': index, 'address': address, 'value': value,
                     'height': height, 'rect': [412 + 18*index, 992 - height, 16, height],
                     'rgb': [value, (71*value + 43) % 256, (131*value + 17) % 256]})
    return bars


def verify_visible(image, payload, viewport, roi, fixture=False,
                   reference=None, reference_is_same_frame=False):
    """Assert every hard bar pixel; qualify separate-frame scene comparisons.

    A reference is optional. A same-frame restored reference can assert every
    passthrough pixel, while separate captures report drift without claiming
    exact preservation of a moving natural scene.
    """
    rgb = _rgb(image, viewport)
    width, height = (int(value) for value in viewport)
    if width < 704 or height < 1008:
        raise ValueError('The fixed visible shape requires a viewport containing its704x1008extent')
    values = bulk._payload_array(payload)
    bars = shape_bars(payload)
    mask = np.zeros((height, width), dtype=bool)
    errors, first = 0, []
    for bar in bars:
        x, y, bar_width, bar_height = bar['rect']
        mask[y:y+bar_height, x:x+bar_width] = True
        actual = rgb[y:y+bar_height, x:x+bar_width]
        bad = np.any(actual != np.asarray(bar['rgb'], dtype=np.uint8), axis=2)
        errors += int(np.count_nonzero(bad))
        for local_y, local_x in np.argwhere(bad)[:max(0, 10-len(first))]:
            first.append({'pixel': [x+int(local_x), y+int(local_y)],
                          'actual_rgb': [int(value) for value in actual[local_y, local_x]],
                          'expected_rgb': bar['rgb'], 'bar': bar['index']})
    result = {'mode': 4, 'logical_bytes': int(values.size), 'viewport': [width, height],
              'source_roi': [int(value) for value in roi], 'sampled_texture_slot': 3,
              'payload_sha256': hashlib.sha256(values.tobytes()).hexdigest(),
              'shape_clip': list(SHAPE_CLIP), 'shape_bars': bars,
              'shape_pixels': int(np.count_nonzero(mask)), 'shape_error_pixels': errors,
              'shape_exact': errors == 0, 'query_count': 16,
              'distinct_final_addresses': len({bar['address'] for bar in bars}),
              'outside_continuity_asserted': False,
              'separate_frame_scene_drift_qualification_required': reference is not None and not reference_is_same_frame,
              'first_errors': first, 'error_pixels': errors, 'exact': errors == 0}
    if fixture:
        x, y, roi_width, roi_height = (int(value) for value in roi)
        if (x < 0 or y < 0 or roi_width < 1 or roi_height < 1
                or x+roi_width > width or y+roi_height > height
                or roi_width*roi_height != int(values.size)*4):
            raise ValueError('Visible fixture check needs a valid complete sourceROI')
        actual_fixture = rgb[y:y+roi_height, x:x+roi_width].reshape(-1, 3)
        expected_fixture = fixture_rgba(roi)[:, :3]
        differences = np.abs(actual_fixture.astype(np.int16)-expected_fixture.astype(np.int16))
        eligible = ~mask[y:y+roi_height, x:x+roi_width].reshape(-1)
        fixture_bad = np.any(differences > 2, axis=1) & eligible
        fixture_errors = int(np.count_nonzero(fixture_bad))
        result.update(fixture_rgb_pixels=int(np.count_nonzero(eligible)),
                      fixture_rgb_error_pixels=fixture_errors,
                      fixture_max_rgb_error=(differences[eligible].max(axis=0).tolist()
                                             if np.any(eligible) else [0, 0, 0]),
                      fixture_rgb_per_channel_tolerance=2)
        result['error_pixels'] += fixture_errors
        result['exact'] = result['error_pixels'] == 0
        for ordinal in np.flatnonzero(fixture_bad)[:max(0, 10-len(first))]:
            index = int(ordinal)
            first.append({'pixel': [x+index % roi_width, y+index//roi_width],
                          'actual_rgb': [int(value) for value in actual_fixture[index]],
                          'expected_rgb': [int(value) for value in expected_fixture[index]],
                          'tolerance': 2, 'region': 'restored fixture outside bars'})
    if reference is not None:
        baseline = _rgb(reference, viewport)
        changed = np.any(rgb != baseline, axis=2)
        outside_clip = np.ones((height, width), dtype=bool)
        x, y, clip_width, clip_height = SHAPE_CLIP
        outside_clip[y:y+clip_height, x:x+clip_width] = False
        passthrough_errors = int(np.count_nonzero(changed & ~mask))
        result.update(outside_clip_changed_pixels=int(np.count_nonzero(changed & outside_clip)),
                      passthrough_changed_pixels=passthrough_errors,
                      outside_continuity_asserted=bool(reference_is_same_frame))
        if reference_is_same_frame:
            result['error_pixels'] += passthrough_errors
            result['exact'] = result['error_pixels'] == 0
    elif reference_is_same_frame:
        raise ValueError('A same-frame continuity assertion requires its reference image')
    return result


def verify(image, mode, payload, viewport, roi, output_y=OUTPUT_Y, fixture=True,
           reference=None, reference_is_same_frame=False):
    """Modes1/2/3 sample T3;5alpha pair,6restored fixtureRGB,7raw fixtureRGB."""
    if mode in (1, 2, 3):
        result = bulk.verify(image, mode, payload, viewport, roi, output_y=output_y)
        result.update(sampled_texture_slot=3, explicit_encoded_texture_copy=True)
        return result
    if mode == 4:
        return verify_visible(image, payload, viewport, roi, fixture, reference, reference_is_same_frame)
    if isinstance(mode, bool) or mode not in (5, 6, 7):
        raise ValueError('Integrated diagnostics require mode1..7')
    rgb = _rgb(image, viewport)
    values = bulk._payload_array(payload)
    width, height = (int(value) for value in viewport)
    x, y, source_width, source_height = (int(value) for value in roi)
    data_count = int(values.size) * 4
    if (not isinstance(output_y, int) or isinstance(output_y, bool) or output_y < 0
            or output_y >= height or x < 0 or y < 0 or source_width < 4
            or source_width % 4 or source_height < 1 or x+source_width > width
            or y+source_height > height or source_width*source_height != data_count):
        raise ValueError('Invalid full-source integrated diagnostic layout')
    output = rgb[output_y:].reshape(-1, 3)
    if output.shape[0] < data_count:
        raise ValueError('Diagnostic output does not expose the entire source')
    data, guard = output[:data_count], output[data_count:]
    expected_fixture = fixture_rgba(roi)
    if mode == 5:
        expected = (np.repeat(expected_fixture[:, 3:4], 3, axis=1) if fixture
                    else np.column_stack((data[:, 0], data[:, 0], data[:, 2])))
    else:
        expected = expected_fixture[:, :3]
    tolerance = 2 if mode == 6 else 0
    differences = np.abs(data.astype(np.int16) - expected.astype(np.int16))
    data_bad = np.any(differences > tolerance, axis=1)
    guard_bad = np.any(guard != np.asarray(GUARD, dtype=np.uint8), axis=1)
    data_errors, guard_errors = int(np.count_nonzero(data_bad)), int(np.count_nonzero(guard_bad))
    result = {'mode': int(mode), 'logical_bytes': int(values.size), 'source_pixels': data_count,
              'viewport': [width, height], 'source_roi': [x, y, source_width, source_height],
              'output_origin': [0, output_y], 'output_pixels': int(output.shape[0]),
              'data_pixels': data_count, 'guard_pixels': int(guard.shape[0]),
              'data_error_pixels': data_errors, 'guard_error_pixels': guard_errors,
              'error_pixels': data_errors+guard_errors, 'exact': data_errors+guard_errors == 0,
              'payload_sha256': hashlib.sha256(values.tobytes()).hexdigest(),
              'sampled_texture_slots': [3, 4] if mode == 5 else [4 if mode == 6 else 3],
              'fixture_formula': 'R33x+17y+13,G73x+19y+41,B151x+47y+97,A11x+31y+211; eachmod256',
              'max_rgb_error': differences.max(axis=0).tolist(), 'per_channel_tolerance': tolerance,
              'query_count': data_count, 'distinct_final_addresses': int(values.size)}
    if mode == 5:
        alpha_pair_bad = data[:, 0] != data[:, 1]
        alpha = data[:, 0]
        codes, frequencies = np.unique(alpha, return_counts=True)
        result.update(encoded_restored_alpha_mismatch_pixels=int(np.count_nonzero(alpha_pair_bad)),
                      alpha_not255_pixels=int(np.count_nonzero(alpha != 255)),
                      alpha_histogram={str(int(code)): int(frequency) for code, frequency in zip(codes, frequencies)},
                      same_frame_encoded_and_restored_alpha=True,
                      analytic_alpha_reference_asserted=bool(fixture), fixture_varying_alpha=bool(fixture),
                      max_encoded_restored_alpha_difference=int(np.abs(data[:, 0].astype(np.int16)-data[:, 1].astype(np.int16)).max()))
        if fixture:
            result.update(encoded_alpha_error_pixels=int(np.count_nonzero(differences[:, 0])),
                          restored_alpha_error_pixels=int(np.count_nonzero(differences[:, 1])),
                          analytic_alpha_error_pixels=int(np.count_nonzero(differences[:, 2])),
                          expected_alpha_not255_pixels=int(np.count_nonzero(expected_fixture[:, 3] != 255)))
    first = []
    for ordinal in np.flatnonzero(data_bad)[:10]:
        index = int(ordinal)
        first.append({'output_ordinal': index, 'pixel': [index % width, output_y+index//width],
                      'source_pixel': [x+index % source_width, y+index//source_width],
                      'actual_rgb': [int(value) for value in data[index]],
                      'expected_rgb': [int(value) for value in expected[index]], 'tolerance': tolerance})
    for guard_index in np.flatnonzero(guard_bad)[:max(0, 10-len(first))]:
        index = data_count+int(guard_index)
        first.append({'output_ordinal': index, 'pixel': [index % width, output_y+index//width],
                      'actual_rgb': [int(value) for value in output[index]], 'expected_rgb': list(GUARD)})
    result['first_errors'] = first
    return result


def self_test():
    payload = payload_bytes(64)
    viewport, roi = (32, 160), (0, 0, 32, 8)
    checked = []
    for mode in (1, 2, 3, 5, 6, 7):
        image = np.zeros((160, 32, 3), dtype=np.uint8)
        output = image[128:].reshape(-1, 3)
        output[:] = GUARD
        count = 64 if mode in (1, 2) else 256
        for i in range(count):
            if mode in (1, 2):
                address = i
                if mode == 2:
                    j = (13*i+7) % 64
                    address = (j+3*payload[j]+5) % 64
                byte = payload[address]
                output[i] = (byte, (71*byte+43) % 256, (131*byte+17) % 256)
            elif mode == 3:
                output[i] = (((payload[i//4] >> (2*(i % 4))) & 3)*64+i % 64, 131, 0)
            else:
                x, y = i % 32, i//32
                original = ((33*x+17*y+13) % 256, (73*x+19*y+41) % 256,
                            (151*x+47*y+97) % 256)
                alpha = (11*x+31*y+211) % 256
                output[i] = (alpha, alpha, alpha) if mode == 5 else original
        exact = verify(image, mode, payload, viewport, roi)
        assert exact['exact'] and exact['data_pixels'] == count
        if mode == 5:
            alpha = int(output[0, 1])
            output[0, 1] = 255-alpha
            negative = verify(image, mode, payload, viewport, roi)
            assert (negative['data_error_pixels'] == 1
                    and negative['restored_alpha_error_pixels'] == 1
                    and negative['encoded_alpha_error_pixels'] == 0
                    and negative['encoded_restored_alpha_mismatch_pixels'] == 1)
            output[0, 1] = alpha
            assert verify(image, mode, payload, viewport, roi)['exact']
        original = int(output[0, 0])
        if mode == 6:
            output[0, 0] = original+2
            assert verify(image, mode, payload, viewport, roi)['exact']
        output[0, 0] = (original + (3 if mode == 6 else 64)) % 256
        assert not verify(image, mode, payload, viewport, roi)['exact']
        output[0, 0] = original
        output[count, 0] ^= 1
        assert verify(image, mode, payload, viewport, roi)['guard_error_pixels'] == 1
        checked.append({'mode': mode, 'exact_pixels': exact['output_pixels'],
                        'data_and_guard_mutations_rejected': True})
    image = np.zeros((160, 32, 3), dtype=np.uint8)
    output = image[128:].reshape(-1, 3)
    output[:] = GUARD
    output[:256] = (131, 131, 23)
    natural = verify(image, 5, payload, viewport, roi, fixture=False)
    assert natural['exact'] and not natural['analytic_alpha_reference_asserted']
    output[0, 1] = 132
    assert verify(image, 5, payload, viewport, roi, fixture=False)['encoded_restored_alpha_mismatch_pixels'] == 1
    checked.append({'mode': 5, 'natural_same_frame_alpha_pair': True,
                    'unrelated_analytic_blue_unasserted': True, 'alpha_mismatch_rejected': True})
    reference = np.empty((1080, 720, 3), dtype=np.uint8)
    reference[:] = (31, 89, 147)
    image = reference.copy()
    for index in range(16):
        byte = payload[(4093*index+17) % 64]
        x, y, height = 412+18*index, 992-(4+byte), 4+byte
        image[y:y+height, x:x+16] = (byte, (71*byte+43) % 256, (131*byte+17) % 256)
    shape = verify_visible(image, payload, (720, 1080), (8, 128, 256, 1), reference=reference, reference_is_same_frame=True)
    assert shape['exact'] and shape['outside_clip_changed_pixels'] == 0
    first_bar = shape_bars(payload)[0]
    x, y = first_bar['rect'][:2]
    image[y, x, 0] ^= 1
    assert verify_visible(image, payload, (720, 1080), roi)['shape_error_pixels'] == 1
    image[y, x, 0] ^= 1
    image[0, 0, 0] ^= 1
    assert not verify_visible(image, payload, (720, 1080), roi, reference=reference, reference_is_same_frame=True)['exact']
    qualified = verify_visible(image, payload, (720, 1080), roi, reference=reference, reference_is_same_frame=False)
    assert qualified['exact'] and qualified['outside_clip_changed_pixels'] == 1
    checked.append({'mode': 4, 'shape_pixels': shape['shape_pixels'],
                    'same_frame_outside_mutation_rejected': True,
                    'separate_frame_scene_drift_qualified': True})
    fixture_roi = (8, 128, 256, 1)
    image[0, 0] = reference[0, 0]
    image[128:129, 8:264] = fixture_rgba(fixture_roi)[:, :3].reshape(1, 256, 3)
    assert verify_visible(image, payload, (720, 1080), fixture_roi, fixture=True)['exact']
    image[128, 8, 0] += 3
    assert verify_visible(image, payload, (720, 1080), fixture_roi, fixture=True)['fixture_rgb_error_pixels'] == 1
    checked.append({'mode': 4, 'analytic_fixture_outside_bars_checked': True,
                    'fixture_mutation_rejected': True})
    return {'passed': True, 'cases': checked}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true', required=True)
    parser.parse_args()
    print(json.dumps(self_test(), indent=2))
