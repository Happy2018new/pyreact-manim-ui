"""Independent exact oracle for geometry-backed texture gather screenshots.

Expected bytes and dependent addresses come only from integer seed/generation
arithmetic. Receipt payload copies and screenshot observations never supply an
expected byte or an indirection address. Every 3x3 RGBA patch must match.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image


SCHEMA = 'geometry_atlas_probe_v1'
SCREEN_SIZE = (720, 1080)
DISPLAY_RECT = [0, 64. / 1080., 1, 1000. / 1080.]
MAX_SLOTS = 524288
MAX_SALT = 65535
MAX_QUERY = 4096
MASK = (1 << 32) - 1
IDENTITY_FIELDS = ('schema', 'seed', 'generation', 'slot_count', 'geometry_name',
                   'geometry_build_serial', 'encoding')
LARGE_FIELDS = frozenset(('observed_bytes', 'expected_bytes', 'source_indices',
                          'verified_slot_indices', 'centers', 'failures'))


def _integer(value, name, minimum=0, maximum=MASK):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError('%s must be an integer in [%d,%d]' % (name, minimum, maximum))
    return value


def _vector(value, name, count):
    if (not isinstance(value, (tuple, list)) or len(value) != count or
            any(isinstance(item, bool) or not isinstance(item, (int, float)) or
                not math.isfinite(item) or int(item) != item for item in value)):
        raise ValueError(name + ' must contain finite integer-valued numbers')
    return list(map(int, value))


def expected_byte(seed, generation, index):
    seed = _integer(seed, 'seed')
    generation = _integer(generation, 'generation')
    index = _integer(index, 'index', maximum=MAX_SLOTS - 1)
    value = seed ^ ((generation * 0x9e3779b9) & MASK)
    value ^= (index * 0x85ebca6b) & MASK
    value ^= value >> 16
    value = (value * 0x7feb352d) & MASK
    value ^= value >> 15
    value = (value * 0x846ca68b) & MASK
    return (value ^ (value >> 16)) & 255


def expected_lookup(seed, generation, slots, ordinal, mode, salt=0, salt2=0):
    """Return (source index, byte), including independent dependent-gather math."""
    slots = _integer(slots, 'slots', 2, MAX_SLOTS)
    ordinal = _integer(ordinal, 'ordinal', maximum=slots - 1)
    mode = _integer(mode, 'mode', 0, 2)
    salt = _integer(salt, 'salt', maximum=MAX_SALT)
    salt2 = _integer(salt2, 'salt2', maximum=MAX_SALT)
    index = ordinal
    if mode:
        index = (131 * ordinal + salt) % slots
        if mode == 2:
            first = expected_byte(seed, generation, index)
            index = (index + 257 * first + salt2) % slots
    return index, expected_byte(seed, generation, index)


def _receipt(receipt, size):
    if not isinstance(receipt, dict) or receipt.get('schema') != SCHEMA:
        raise ValueError('Receipt schema must be ' + SCHEMA)
    for key in ('seed', 'generation'):
        _integer(receipt.get(key), key)
    slots = _integer(receipt.get('slot_count'), 'slot_count', 2, MAX_SLOTS)
    _integer(receipt.get('geometry_build_serial'), 'geometry_build_serial', 1)
    if not isinstance(receipt.get('geometry_name'), str) or not receipt['geometry_name']:
        raise ValueError('geometry_name must be nonempty')
    if receipt.get('encoding') != 'compact8':
        raise ValueError('Only compact8 is declared for the geometry atlas probe')
    if tuple(size) != SCREEN_SIZE or receipt.get('screen_size') != list(SCREEN_SIZE):
        raise ValueError('Receipt and capture must both be native 720x1080')
    if receipt.get('display_rect_norm') != DISPLAY_RECT:
        raise ValueError('Display rectangle must be the fixed native [0,64,720,1000] region')
    start, count, mode, salt = _vector(receipt.get('query'), 'query', 4)
    if not 0 <= start < slots or not 1 <= count <= MAX_QUERY or start + count > slots:
        raise ValueError('Query must fit all slots and contain 1..4096 bytes')
    if not 0 <= mode <= 2 or not 0 <= salt <= MAX_SALT:
        raise ValueError('Only byte-gather modes0..2 and bounded salts are payload evidence')
    layout = _vector(receipt.get('layout'), 'layout', 4)
    cell, width, height, salt2 = _vector(receipt.get('dimensions'), 'dimensions', 4)
    total, columns, left, top = layout
    if (total != slots or not 1 <= columns <= 720 or cell < 1 or
            (width, height) != SCREEN_SIZE or min(left, top) < 0 or
            left + columns * cell > width or top + ((slots + columns - 1) // columns) * cell > height or
            not 0 <= salt2 <= MAX_SALT):
        raise ValueError('Source atlas layout must fit the declared native render surface')
    orientation = _vector(receipt.get('orientation'), 'orientation', 4)
    flip_y, channel, reserved0, reserved1 = orientation
    if flip_y not in (0, 1) or channel not in (0, 1) or reserved0 or reserved1:
        raise ValueError('orientation must be [flipY0or1,channel0or1,0,0]')
    if not isinstance(receipt.get('direct_source'), bool):
        raise ValueError('direct_source must be explicit bool')
    packed = mode + 4 * flip_y + 8 * channel + 16 * int(receipt['direct_source'])
    if receipt.get('packed_mode') != packed:
        raise ValueError('packed_mode disagrees with recorded mode/orientation/source')
    if receipt.get('pipeline_ready') is not True:
        raise ValueError('A ready explicitly connected pipeline is required')
    if mode == 1 and math.gcd(131, slots) != 1:
        raise ValueError('Permutation mode requires slot count coprime with131')
    return start, count, mode, salt, salt2, channel


def compact_report(report):
    return {key: value for key, value in report.items() if key not in LARGE_FIELDS}


def verify_image(receipt, image):
    start, count, mode, salt, salt2, channel = _receipt(receipt, image.size)
    image = image.convert('RGBA')
    rows = (count + 63) // 64
    expected, observed, indices, centers, failures = [], [], [], [], []
    maximum = 0
    for ordinal in range(count):
        index, value = expected_lookup(receipt['seed'], receipt['generation'], receipt['slot_count'],
                                       start + ordinal, mode, salt, salt2)
        row, column = divmod(ordinal, 64)
        left, right = column * 720. / 64, (column + 1) * 720. / 64
        top, bottom = 64. + row * 1000. / rows, 64. + (row + 1) * 1000. / rows
        x, y = math.floor((left + right) / 2), math.floor((top + bottom) / 2)
        if not (left < x - .5 and x + 1.5 < right and top < y - .5 and y + 1.5 < bottom):
            raise ValueError('Every byte needs a complete interior native3x3 patch')
        pixels = [image.getpixel((x + dx, y + dy)) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
        rgb_error = max(abs(component - value) for pixel in pixels for component in pixel[:3])
        alpha_error = max(255 - pixel[3] for pixel in pixels)
        maximum = max(maximum, rgb_error, alpha_error)
        if rgb_error or alpha_error:
            failures.append({'ordinal': start + ordinal, 'source_index': index,
                             'rgb_error': rgb_error, 'alpha_error': alpha_error})
        expected.append(value)
        observed.append(image.getpixel((x, y))[0])
        indices.append(index)
        centers.append([x, y])
    identity = {key: receipt.get(key) for key in IDENTITY_FIELDS}
    return dict(identity, passed=not failures, exact_equal=not failures, query=[start, count, mode, salt],
                salt2=salt2, orientation=list(receipt['orientation']), direct_source=receipt['direct_source'],
                packed_mode=receipt['packed_mode'], payload_channel='alpha' if channel == 0 else 'red',
                alpha_channel_sampled=channel == 0, capture_size=list(image.size), rows=rows,
                sample_width=3, byte_tolerance=0, required_alpha=255,
                checked_cells=count, checked_pixels=count * 9, checked_channels=count * 36,
                failed_cells=len(failures), max_error=maximum, source_indices=indices,
                verified_slot_indices=list(range(start, start + count)), expected_bytes=expected,
                observed_bytes=observed, centers=centers, failures=failures,
                observed_payload_sha256=hashlib.sha256(bytes(observed)).hexdigest(),
                expected_payload_sha256=hashlib.sha256(bytes(expected)).hexdigest())


def verify_reports(pairs):
    identity, controls, seen, observed, expected = None, None, None, None, None
    reports = []
    for receipt, report in pairs:
        _receipt(receipt, SCREEN_SIZE)
        current = {key: receipt.get(key) for key in IDENTITY_FIELDS}
        query = list(map(int, receipt['query']))
        indices = list(range(query[0], query[0] + query[1]))
        lookup = [expected_lookup(receipt['seed'], receipt['generation'], receipt['slot_count'],
                                  index, query[2], query[3], int(receipt['dimensions'][3])) for index in indices]
        required = dict(current, query=query, verified_slot_indices=indices,
                        source_indices=[item[0] for item in lookup], expected_bytes=[item[1] for item in lookup],
                        checked_cells=len(indices), checked_pixels=len(indices) * 9,
                        checked_channels=len(indices) * 36, sample_width=3, required_alpha=255,
                        byte_tolerance=0, capture_size=list(SCREEN_SIZE),
                        orientation=list(receipt['orientation']), direct_source=receipt['direct_source'],
                        packed_mode=receipt['packed_mode'], salt2=int(receipt['dimensions'][3]))
        if not isinstance(report, dict) or any(report.get(key) != value for key, value in required.items()):
            raise ValueError('Report disagrees with the independent oracle or exact patch contract')
        levels = report.get('observed_bytes')
        if (not isinstance(levels, list) or len(levels) != len(indices) or
                any(type(value) is not int or not 0 <= value <= 255 for value in levels)):
            raise ValueError('Every observed query byte is required')
        failed = _integer(report.get('failed_cells'), 'failed_cells', 0, len(indices))
        error = _integer(report.get('max_error'), 'max_error', 0, 255)
        if (not isinstance(report.get('passed'), bool) or report['passed'] != (failed == 0) or
                (report['passed'] and (levels != required['expected_bytes'] or error))):
            raise ValueError('Report passing flag disagrees with exact pixel evidence')
        current_controls = (query[2], query[3], tuple(receipt['orientation']), receipt['direct_source'],
                            tuple(receipt['layout']), tuple(receipt['dimensions']))
        if identity is None:
            identity, controls = current, current_controls
            seen = bytearray(current['slot_count'])
            observed, expected = bytearray(current['slot_count']), bytearray(current['slot_count'])
        elif current != identity or current_controls != controls:
            raise ValueError('Geometry identity or gather controls changed within a capture series')
        for index, actual, oracle in zip(indices, levels, required['expected_bytes']):
            if seen[index]:
                raise ValueError('Duplicate query ordinal in full coverage')
            seen[index], observed[index], expected[index] = 1, actual, oracle
        reports.append(report)
    if not reports or 0 in seen:
        raise ValueError('Full coverage is missing query ordinals')
    if len(set(expected)) < 2:
        raise ValueError('A uniform control cannot establish payload delivery')
    passed = all(report['passed'] for report in reports)
    return dict(identity, passed=passed, exact_equal=passed, full_query_coverage=True,
                source_index_coverage=len(set(index for report in reports for index in report['source_indices'])),
                full_source_coverage=len(set(index for report in reports for index in report['source_indices'])) == len(seen),
                capture_count=len(reports), payload_bytes=len(seen), checked_cells=sum(r['checked_cells'] for r in reports),
                checked_pixels=sum(r['checked_pixels'] for r in reports), failed_cells=sum(r['failed_cells'] for r in reports),
                max_error=max(r['max_error'] for r in reports), mode=controls[0], salt=controls[1],
                salt2=controls[5][3], orientation=list(controls[2]), direct_source=controls[3],
                payload_channel='alpha' if controls[2][1] == 0 else 'red',
                observed_payload_sha256=hashlib.sha256(observed).hexdigest(),
                expected_payload_sha256=hashlib.sha256(expected).hexdigest())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt_raw, capture_raw = args.receipt.read_bytes(), args.capture.read_bytes()
        receipt = json.loads(receipt_raw.decode('utf-8-sig'))
        with Image.open(args.capture) as image:
            report = verify_image(receipt, image)
        report.update(receipt_sha256=hashlib.sha256(receipt_raw).hexdigest(),
                      capture_sha256=hashlib.sha256(capture_raw).hexdigest())
    except (OSError, ValueError, KeyError, TypeError) as error:
        report = {'passed': False, 'exact_equal': False, 'error': '%s: %s' % (type(error).__name__, error)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, separators=(',', ':')), encoding='utf-8')
    print(json.dumps(compact_report(report), separators=(',', ':')))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
