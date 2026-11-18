"""Host-only exhaustive RGB oracle for byte-record stencil diagnostics."""
import argparse
import hashlib
import json

import numpy as np


GUARD = (17, 53, 97)
OUTPUT_Y = 64
PAYLOAD_FORMULA = 'SHA256(stencil-bulk-v1/ + ASCII(N) + / + ASCII(blockIndex)), concatenated and truncated'


def payload_bytes(count):
    """Generate actual host input; neither the game nor GLSL receives this rule."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError('Payload count must be a positive integer')
    prefix = b'stencil-bulk-v1/' + str(count).encode('ascii') + b'/'
    return b''.join(hashlib.sha256(prefix + str(index).encode('ascii')).digest()
                    for index in range((count + 31) // 32))[:count]


def _payload_array(payload):
    if isinstance(payload, (bytes, bytearray, memoryview)):
        values = np.frombuffer(payload, dtype=np.uint8)
    else:
        source = np.asarray(payload)
        if (source.ndim != 1 or source.dtype.kind not in 'iu'
                or np.any(source < 0) or np.any(source > 255)):
            raise ValueError('Expected a one-dimensional integer byte payload')
        values = source.astype(np.uint8)
    if values.ndim != 1 or not values.size:
        raise ValueError('Expected a nonempty byte payload')
    return values


def _markers(values):
    wide = values.astype(np.uint16)
    return np.column_stack((wide, (71 * wide + 43) % 256,
                            (131 * wide + 17) % 256)).astype(np.uint8)


def verify(image, mode, payload, viewport, roi, output_y=OUTPUT_Y):
    """Verify every diagnostic/guard pixel below Y64 in oracle modes1,2,3.

    Mode3 asserts the two-bit symbol and the compressed G/B range flag. Its
    output green channel is the same fetched texel's raw alpha, an observation
    rather than an expected constant. Source RGB low bits are likewise free.
    """
    if isinstance(mode, bool) or mode not in (1, 2, 3):
        raise ValueError('Exhaustive diagnostic verification requires mode1,2or3')
    if len(viewport) != 2 or len(roi) != 4:
        raise ValueError('Expected viewport[W,H] and source ROI[X,Y,W,H]')
    width, height = (int(value) for value in viewport)
    x, y, roi_width, roi_height = (int(value) for value in roi)
    values = _payload_array(payload)
    count = int(values.size)
    if (isinstance(output_y, bool) or not isinstance(output_y, int) or output_y < 0
            or width < 1 or height <= output_y or roi_width < 4 or roi_width % 4
            or roi_height < 1 or x < 0 or y < 0 or x + roi_width > width
            or y + roi_height > height or roi_width * roi_height != count * 4):
        raise ValueError('Invalid viewport or four-source-pixels-per-byte ROI')
    rgb = np.asarray(image)
    if (rgb.ndim != 3 or rgb.shape[:2] != (height, width)
            or rgb.shape[2] < 3 or rgb.dtype != np.uint8):
        raise ValueError('Expected a native-size uint8 RGB/RGBA image')
    output = rgb[output_y:, :, :3].reshape(-1, 3)
    data_count = count * 4 if mode == 3 else count
    if output.shape[0] < data_count:
        raise ValueError('Diagnostic output does not expose the complete payload')
    actual_data, actual_guard = output[:data_count], output[data_count:]
    guard_bad = np.any(actual_guard != np.asarray(GUARD, dtype=np.uint8), axis=1)
    result = {
        'mode': int(mode), 'logical_bytes': count, 'source_pixels': count * 4,
        'viewport': [width, height], 'source_roi': [x, y, roi_width, roi_height],
        'output_origin': [0, output_y], 'output_pixels': int(output.shape[0]),
        'data_pixels': data_count, 'guard_pixels': int(actual_guard.shape[0]),
        'guard_error_pixels': int(np.count_nonzero(guard_bad)),
        'payload_sha256': hashlib.sha256(values.tobytes()).hexdigest(),
        'same_texture_same_fetch_rgb_alpha': mode == 3,
    }
    expected_data = None
    if mode == 3:
        symbols = ((values[:, None] >> np.arange(0, 8, 2, dtype=np.uint8)) & 3).reshape(-1)
        symbol_bad = (actual_data[:, 0] // 64) != symbols
        range_bad = actual_data[:, 2] != 0
        data_bad = symbol_bad | range_bad
        alpha = actual_data[:, 1]
        codes, frequencies = np.unique(alpha, return_counts=True)
        alpha_changed = alpha != 255
        result.update(
            symbol_error_pixels=int(np.count_nonzero(symbol_bad)),
            range_error_pixels=int(np.count_nonzero(range_bad)),
            alpha_not255_pixels=int(np.count_nonzero(alpha_changed)),
            intact_symbol_and_alpha_not255_pixels=int(np.count_nonzero(alpha_changed & ~data_bad)),
            corrupt_symbol_or_range_and_alpha_not255_pixels=int(np.count_nonzero(alpha_changed & data_bad)),
            alpha_histogram={str(int(code)): int(frequency) for code, frequency in zip(codes, frequencies)},
            asserted_data_components='red byte quotient64 and blue rangeflag; green is raw alpha',
            query_count=data_count, distinct_final_addresses=count,
        )
    else:
        addresses = np.arange(count, dtype=np.int64)
        if mode == 2:
            first_addresses = (13 * addresses + 7) % count
            addresses = (first_addresses + 3 * values[first_addresses].astype(np.int64) + 5) % count
            result['distinct_first_addresses'] = int(np.unique(first_addresses).size)
        expected_data = _markers(values[addresses])
        data_bad = np.any(actual_data != expected_data, axis=1)
        result.update(query_count=count, distinct_final_addresses=int(np.unique(addresses).size),
                      asserted_data_components='all RGB marker channels')
    result['data_error_pixels'] = int(np.count_nonzero(data_bad))
    result['error_pixels'] = result['data_error_pixels'] + result['guard_error_pixels']
    result['exact'] = result['error_pixels'] == 0
    first = []
    for ordinal in np.flatnonzero(data_bad)[:10]:
        index = int(ordinal)
        failure = {'output_ordinal': index, 'pixel': [index % width, output_y + index // width],
                   'actual_rgb': [int(value) for value in actual_data[index]]}
        if mode == 3:
            failure.update(expected_symbol=int(symbols[index]), expected_range_flag=0,
                           actual_symbol=int(actual_data[index, 0] // 64))
        else:
            failure['expected_rgb'] = [int(value) for value in expected_data[index]]
        first.append(failure)
    for guard_index in np.flatnonzero(guard_bad)[:max(0, 10 - len(first))]:
        index = data_count + int(guard_index)
        first.append({'output_ordinal': index, 'pixel': [index % width, output_y + index // width],
                      'actual_rgb': [int(value) for value in output[index]], 'expected_rgb': list(GUARD)})
    result['first_errors'] = first
    return result


def self_test():
    """Exercise exact paths and independent data, range, and guard mutations."""
    payload = payload_bytes(64)
    values = np.frombuffer(payload, dtype=np.uint8)
    viewport, roi = (32, 80), (0, 0, 32, 8)
    checked = []
    for mode in (1, 2, 3):
        image = np.zeros((80, 32, 3), dtype=np.uint8)
        output = image[OUTPUT_Y:].reshape(-1, 3)
        output[:] = GUARD
        length = len(payload) * (4 if mode == 3 else 1)
        if mode == 3:
            for i in range(length):
                output[i] = (((payload[i // 4] >> (2 * (i % 4))) & 3) * 64 + i % 64,
                             127 if i % 7 == 0 else 255, 0)
        else:
            for i in range(length):
                address = i
                if mode == 2:
                    j = (13 * i + 7) % len(payload)
                    address = (j + 3 * payload[j] + 5) % len(payload)
                value = payload[address]
                output[i] = (value, (71 * value + 43) % 256, (131 * value + 17) % 256)
        report = verify(image, mode, payload, viewport, roi)
        assert report['exact'] and report['data_pixels'] == length
        if mode == 3:
            assert report['alpha_not255_pixels'] == (length + 6) // 7
            output[1, 1] = 29
            assert verify(image, mode, payload, viewport, roi)['exact']
            output[0, 2] = 1
            assert verify(image, mode, payload, viewport, roi)['range_error_pixels'] == 1
            output[0, 2] = 0
            output[0, 0] ^= 64
            assert verify(image, mode, payload, viewport, roi)['symbol_error_pixels'] == 1
            output[0, 0] ^= 64
        else:
            output[0, 2] ^= 1
            assert verify(image, mode, payload, viewport, roi)['data_error_pixels'] == 1
            output[0, 2] ^= 1
        output[length, 0] ^= 1
        mutated = verify(image, mode, payload, viewport, roi)
        assert not mutated['exact'] and mutated['guard_error_pixels'] == 1
        checked.append({'mode': mode, 'exact_pixels': report['output_pixels'],
                        'distinct_final_addresses': report['distinct_final_addresses'],
                        'data_and_guard_mutations_rejected': True})
    return {'passed': True, 'cases': checked, 'payload_sha256': hashlib.sha256(payload).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true', required=True)
    parser.parse_args()
    print(json.dumps(self_test(), indent=2))
