"""Independently replay large-alpha native PNGs without importing probe code.

Only host files are read/written. This program neither contacts MC nor runs a
GPU. Expected bytes use uint32 wraparound, checked against scalar integers;
addresses use integer arithmetic and a separate float32 shader simulation.
"""

import argparse
from fractions import Fraction
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image


SCREEN = (2560, 1440)
PAGE = 65536
LIMIT = 2097152
SCHEMA = 'geometry_atlas_large_probe_v1'
REQUIRED = ('calibration_64k_identity', 'calibration_64k_hidden', 'calibration_64k_restored') + tuple(
    'resident_%d_%s' % (size, mode) for size in (1048576, 1572864, 2097152)
    for mode in ('identity', 'dependent'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scalar_byte(seed, generation, position):
    mask = (1 << 32) - 1
    word = seed ^ ((generation * 2654435769) & mask) ^ ((position * 2246822507) & mask)
    word = (word ^ (word >> 16)) * 2146121005 & mask
    word = (word ^ (word >> 15)) * 2221713035 & mask
    return (word ^ (word >> 16)) & 255


def payload_bytes(seed, generation, count):
    # uint32 multiplication itself supplies wraparound, unlike the original
    # verifier's uint64 products followed by explicit masks.
    positions = np.arange(count, dtype=np.uint32)
    word = np.multiply(positions, np.uint32(2246822507), dtype=np.uint32)
    word ^= np.uint32(seed ^ ((generation * 2654435769) % (1 << 32)))
    word ^= word >> 16
    word = np.multiply(word, np.uint32(2146121005), dtype=np.uint32)
    word ^= word >> 15
    word = np.multiply(word, np.uint32(2221713035), dtype=np.uint32)
    word ^= word >> 16
    result = (word & 255).astype(np.uint8)
    probes = {0, count - 1}
    probes.update(range(0, count, PAGE))
    probes.update(range(PAGE - 1, count, PAGE))
    for position in probes:
        require(int(result[position]) == scalar_byte(seed, generation, position),
                'Vector/scalar PRNG implementations disagree at %d' % position)
    return result


def addresses(count, mode, salt, salt2, values):
    result = np.arange(count, dtype=np.int64)
    if mode >= 1:
        result = (result * 131 + salt) % count
    if mode >= 2:
        result = (result + values[result].astype(np.int64) * 257 + salt2) % count
    return result


def float32_address_check(count, salt, salt2, values):
    original = np.arange(count, dtype=np.float32)
    divisor = np.float32(count)
    intermediate = original.copy()
    for unused in range(7):
        doubled = intermediate * np.float32(2)
        intermediate = doubled - divisor * np.floor(doubled / divisor)
    summed = intermediate + np.float32(3) * original + np.float32(salt)
    indexed = summed - divisor * np.floor(summed / divisor)
    exact_indexed = addresses(count, 1, salt, salt2, values)
    indexed_failures = int(np.count_nonzero(indexed != exact_indexed))
    first = values[exact_indexed].astype(np.float32)
    summed = indexed + np.float32(257) * first + np.float32(salt2)
    dependent = summed - divisor * np.floor(summed / divisor)
    exact_dependent = addresses(count, 2, salt, salt2, values)
    dependent_failures = int(np.count_nonzero(dependent != exact_dependent))
    return {'indices_checked_per_mode': count, 'indexed_failures': indexed_failures,
            'dependent_failures': dependent_failures,
            'maximum_pre_modulus_sum_bound': 4 * (count - 1) + salt,
            'exact_integer_limit_exclusive': 1 << 24,
            'native_precision_proof': False}


def identity(state):
    return {'seed': state['seed'], 'generation': state['generation'], 'slot_count': state['slot_count'],
            'geometry_build_serial': state['geometry_build_serial'],
            'native_attempt_serial': state['native_attempt_serial'],
            'pages': [{key: page[key] for key in ('base', 'count', 'name', 'entity', 'seed', 'generation',
                'payload_fingerprint', 'upload_serial')} for page in state['pages']]}


def display_layout(state):
    layout = state.get('diagnostic_layout', [16, 64, 2048, 1])
    require(len(layout) == 4 and all(type(value) is int for value in layout), 'Invalid diagnostic layout')
    left, top, columns, cell = layout
    rows = state['slot_count'] // 2048
    require(columns == 2048 and cell == 1 and 0 <= left and 0 <= top and
            left + columns <= SCREEN[0] and top + rows <= SCREEN[1], 'Diagnostic data region exceeds native screen')
    policy = state.get('diagnostic_border_policy', 'whole_screen')
    if policy == 'whole_screen':
        guard = [0, 0, SCREEN[0], SCREEN[1]]
    else:
        require(policy == 'declared_guard_rect_excluding_native_debug_UI', 'Unknown border exclusion policy')
        guard = state.get('border_guard_rect_native')
        require(guard == [0, 128, 2560, 1408] and layout == [16, 128, 2048, 1],
                'Only the explicitly reviewed debug-UI guard rectangle is accepted')
    require(guard[0] <= left and guard[1] <= top and left + columns <= guard[2] and top + rows <= guard[3],
            'Every queried data pixel must remain inside the audited guard')
    return layout, policy, guard


def validate_receipt(state):
    require(state.get('schema') == SCHEMA, 'Unexpected receipt schema')
    require(state.get('screen_size') == list(SCREEN), 'Physical screen must be native2560x1440')
    size = state.get('slot_count')
    require(type(size) is int and PAGE <= size <= LIMIT and size % PAGE == 0,
            'Logical prefix must contain whole64KiB pages through2MiB')
    require(state.get('loaded_bytes') == size and state.get('error') is None,
            'All logical bytes must be loaded without runtime error')
    require(all(state.get(key) is True for key in ('pipeline_ready', 'pipeline_installed', 'connection')),
            'Pipeline and explicit private-texture connection must be ready')
    require(state.get('runtime_payload_files') is False, 'Runtime payload-file claim must be explicit')
    require(state.get('layout') == [size, 2048, 8, 32] and
            state.get('dimensions', [])[:3] == [1, 2560, 1440], 'Unexpected source atlas layout')
    require(state.get('query', [])[:2] == [0, size] and state['query'][2] in (0, 1, 2),
            'Capture must query the complete array in a diagnostic mode')
    require(type(state.get('flip_y')) is bool and type(state.get('writer_visible')) is bool,
            'Orientation and visibility must be explicit')
    for key in ('seed', 'generation'):
        require(type(state.get(key)) is int and 0 <= state[key] < 1 << 32, 'Invalid unsigned '+key)
    require(0 <= state['query'][3] <= 65535 and 0 <= state['dimensions'][3] <= 65535,
            'Query salts exceed the reviewed float32 bounds')
    pages = state.get('pages', [])
    require(len(pages) == size // PAGE, 'Page count disagrees with logical length')
    require(state.get('geometry_build_serial') == len(pages) and
            state.get('native_attempt_serial') == len(pages), 'Native/build serials must equal page count')
    names = []
    entities = []
    for number, page in enumerate(pages):
        require(page.get('base') == number * PAGE and page.get('count') == PAGE, 'Page range has a gap or overlap')
        require(all(page.get(key) is True for key in ('loaded', 'ready', 'attempted')),
                'Page was not fully ready/resident/attempted')
        require(page.get('seed') == state['seed'] and page.get('generation') == state['generation'],
                'Page generation does not match the logical array')
        require(page.get('upload_serial') == number + 1, 'Unexpected per-page upload serial')
        require(bool(page.get('name')) and bool(page.get('entity')), 'Page geometry/anchor identity missing')
        fingerprint = page.get('payload_fingerprint', {})
        require(fingerprint.get('algorithm') == 'sum_u8_mod2^32' and type(fingerprint.get('value')) is int,
                'Require explicitly named in-memory fingerprint algorithm')
        names.append(page['name'])
        entities.append(page['entity'])
        timings = page.get('timings', {})
        require(timings and all(math.isfinite(value) and value >= 0 for value in timings.values()),
                'Invalid upload timing')
        parts = ('generation_ms', 'fingerprint_ms', 'encode_ms', 'deserialize_ms', 'combine_ms', 'attach_ms')
        require(abs(sum(timings[key] for key in parts) - timings['total_ms']) < 0.001,
                'Per-page timing components disagree with total')
    require(len(set(names)) == len(names) and len(set(entities)) == len(entities), 'Duplicated page identity')
    require(state.get('geometry_names') == names, 'Recorded geometry order disagrees with pages')
    for key, recorded in state.get('cumulative_timings', {}).items():
        require(abs(sum(page['timings'][key] for page in pages) - recorded) < 0.001,
                'Cumulative timing mismatch: '+key)
    display_layout(state)
    return size


def replay_pixels(image_path, state, values):
    with Image.open(image_path) as image:
        require(image.size == SCREEN, 'Screenshot was scaled or has a different native size')
        rgba = np.array(image.convert('RGBA'), dtype=np.uint8)
    size = state['slot_count']
    rows = size // 2048
    (left, top, columns, cell), policy, guard = display_layout(state)
    # Build an expected RGBA image, then check every query and every nonquery
    # pixel inside the declared guard. No data pixel is excluded as UI.
    indices = addresses(size, state['query'][2], state['query'][3], state['dimensions'][3], values)
    expected_bytes = values[indices]
    expected_image = np.empty_like(rgba)
    expected_image[:] = (8, 16, 32, 255)
    expected_image[top:top + rows, left:left + columns, :3] = expected_bytes.reshape(rows, 2048, 1)
    query = rgba[top:top + rows, left:left + columns]
    channel_failure = rgba != expected_image
    failed_pixels = np.any(channel_failure, axis=2)
    failed_queries = np.any(query[:, :, :3] != expected_bytes.reshape(rows, 2048, 1), axis=2) | (query[:, :, 3] != 255)
    query_count = int(np.count_nonzero(failed_queries))
    guarded_failure = failed_pixels[guard[1]:guard[3], guard[0]:guard[2]]
    outside_count = int(np.count_nonzero(guarded_failure)) - query_count
    guarded_pixels = (guard[2] - guard[0]) * (guard[3] - guard[1])
    rgb_difference = np.abs(query[:, :, :3].astype(np.int16) - expected_bytes.reshape(rows, 2048, 1).astype(np.int16))
    positions = np.flatnonzero(failed_queries)[:12]
    flat = query.reshape(size, 4)
    return {'passed': query_count == 0 and outside_count == 0,
            'native_pixels_checked': guarded_pixels, 'query_pixels_checked': size,
            'outside_pixels_checked': guarded_pixels - size,
            'excluded_native_UI_pixels': SCREEN[0] * SCREEN[1] - guarded_pixels,
            'diagnostic_layout': [left, top, columns, cell],
            'diagnostic_border_policy': policy, 'border_guard_rect_native': guard,
            'failed_queries': query_count, 'border_failures': outside_count,
            'alpha_failures': int(np.count_nonzero(query[:, :, 3] != 255)),
            'maximum_rgb_error': int(rgb_difference.max()), 'byte_tolerance': 0,
            'observed_query_sha256': hashlib.sha256(flat[:, 0].tobytes()).hexdigest(),
            'expected_query_sha256': hashlib.sha256(expected_bytes.tobytes()).hexdigest(),
            'failures_first12': [{'ordinal': int(position), 'address': int(indices[position]),
                'expected': int(expected_bytes[position]), 'observed': flat[position].tolist()} for position in positions]}


def audit_page_oracles(evidence, state, values, oracle_fallback=None):
    reports = []
    for number, page in enumerate(state['pages']):
        source = evidence / ('page_%03d.host-oracle.json' % number)
        if not source.is_file() and oracle_fallback is not None:
            source = Path(oracle_fallback) / source.name
        require(source.is_file(), 'Missing host page oracle: '+str(source))
        recorded = read_json(source)
        page_values = values[page['base']:page['base'] + PAGE]
        checksum = int(page_values.astype(np.uint64).sum()) % (1 << 32)
        sha = hashlib.sha256(page_values.tobytes()).hexdigest()
        for key in ('base', 'count', 'seed', 'generation'):
            require(recorded.get(key) == page[key], 'Host page oracle disagrees: '+key)
        require(recorded.get('sha256') == sha and recorded.get('sum_u8_mod2^32') == checksum,
                'Independent page SHA256/sum check failed')
        require(recorded.get('runtime_fingerprint') == page['payload_fingerprint'] and
                page['payload_fingerprint']['value'] == checksum, 'Runtime page fingerprint mismatch')
        reports.append({'page': number, 'base': page['base'], 'count': PAGE, 'sha256': sha,
                        'sum_u8_mod2^32': checksum, 'host_oracle': str(source.resolve()),
                        'host_oracle_sha256': digest_file(source)})
    return reports


def exact_layout_check():
    checks = []
    for index in (0, PAGE - 1, PAGE, LIMIT - 1):
        row, column = divmod(index, 2048)
        u = Fraction(2 * (8 + column) + 1, 2 * SCREEN[0])
        v = Fraction(2 * (32 + row) + 1, 2 * SCREEN[1])
        require(int(u * SCREEN[0]) == 8 + column and int(v * SCREEN[1]) == 32 + row,
                'Texel-center arithmetic failed')
        checks.append({'global_index': index, 'source_pixel': [8 + column, 32 + row],
                       'u': str(u), 'v_top': str(v)})
    return {'physical_source_bounds_half_open': [8, 32, 2056, 1056],
            'supported_query_bounds_at_2mib_half_open': {
                'legacy': [16, 64, 2064, 1088], 'declared_UI_guard': [16, 128, 2064, 1152]},
            'point_texel_centers': checks, 'one_byte_per_native_pixel': True}


def audit(evidence, oracle_fallback=None):
    evidence = Path(evidence).resolve()
    summary_path = evidence / 'large_case.summary.json'
    summary = read_json(summary_path) if summary_path.is_file() else None
    observations = []
    previous = None
    page_reports = {}
    float_reports = {}
    cache = {}
    completed = []
    for label in REQUIRED:
        image = evidence / (label + '.png')
        receipts = sorted(evidence.glob('*_' + label + '_settled.state.json'))
        if not image.is_file() or not receipts:
            continue
        require(len(receipts) == 1, 'Ambiguous settled receipts: '+label)
        receipt = receipts[0]
        state = read_json(receipt)
        size = validate_receipt(state)
        require(size == (PAGE if label.startswith('calibration') else int(label.split('_')[1])),
                'Label/receipt logical length disagree')
        require(state['query'][2] == (2 if label.endswith('dependent') else 0), 'Label/query mode disagree')
        frozen = identity(state)
        if previous is not None:
            require(frozen['seed'] == previous['seed'] and frozen['generation'] == previous['generation'],
                    'Resident prefix seed/generation changed across captures')
            common = min(len(frozen['pages']), len(previous['pages']))
            require(frozen['pages'][:common] == previous['pages'][:common], 'Frozen page identities mutated')
            if size == previous['slot_count']:
                require(frozen == previous, 'Frozen build/attempt serials changed between queries')
        previous = frozen
        key = (state['seed'], state['generation'], size)
        if key not in cache:
            cache[key] = payload_bytes(*key)
        values = cache[key]
        if str(size) not in page_reports:
            page_reports[str(size)] = audit_page_oracles(evidence, state, values, oracle_fallback)
            float_reports[str(size)] = float32_address_check(size, state['query'][3], state['dimensions'][3], values)
            require(float_reports[str(size)]['indexed_failures'] == 0 and
                    float_reports[str(size)]['dependent_failures'] == 0, 'Float32 address replay failed')
        result = replay_pixels(image, state, values)
        hidden = label == 'calibration_64k_hidden'
        require(state['writer_visible'] is not hidden, 'Negative-control writer visibility is wrong')
        require(result['border_failures'] == 0, 'Native display border differs: '+label)
        if hidden:
            require(result['failed_queries'] > size * 0.9, 'Hidden writer did not reject most input bytes')
        else:
            require(result['passed'], 'Independent whole-frame replay failed: '+label)
        original_report_path = evidence / (label + '.verify.json')
        require(original_report_path.is_file(), 'Original verification record missing')
        original_report = read_json(original_report_path)
        require(original_report.get('capture_sha256') == digest_file(image) and
                original_report.get('receipt_sha256') == digest_file(receipt), 'Recorded evidence file hash mismatch')
        require(original_report.get('passed') == result['passed'] and
                original_report.get('failed_queries') == result['failed_queries'] and
                original_report.get('border_failures') == result['border_failures'],
                'Original and independent replay disagree')
        wrong_generation = None
        if not hidden:
            altered = dict(state, generation=(state['generation'] + 1) % (1 << 32))
            wrong_values = payload_bytes(altered['seed'], altered['generation'], size)
            wrong_generation = replay_pixels(image, altered, wrong_values)
            require(not wrong_generation['passed'] and wrong_generation['failed_queries'] > size * 0.9,
                    'Wrong generation did not reject the native capture')
            recorded_negative = evidence / (label + '.wrong-generation.verify.json')
            require(recorded_negative.is_file() and read_json(recorded_negative).get('passed') is False,
                    'Missing or accepted recorded wrong-generation negative')
        observations.append({'label': label, 'receipt': str(receipt), 'capture': str(image),
            'receipt_sha256': digest_file(receipt), 'capture_sha256': digest_file(image),
            'slot_count': size, 'mode': state['query'][2], 'writer_visible': state['writer_visible'],
            'frozen_identity_sha256': hashlib.sha256(json.dumps(frozen, sort_keys=True).encode('utf-8')).hexdigest(),
            'independent_replay': result,
            'wrong_generation_failed_queries': None if wrong_generation is None else wrong_generation['failed_queries']})
        completed.append(label)
    missing = [label for label in REQUIRED if label not in completed]
    if summary is not None:
        recorded_labels = {entry['label'] for entry in summary.get('results', [])}
        require(set(completed) <= recorded_labels, 'Summary omits completed captures')
        require(all(event.get('returncode') == 0 for event in summary.get('events', [])), 'Host command failed')
    complete = not missing and summary is not None and summary.get('status') == 'passed'
    return {'schema': 'independent_large_alpha_audit_v1', 'passed': complete, 'complete': complete,
            'evidence': str(evidence), 'missing_captures': missing, 'observations': observations,
            'page_oracles_by_logical_size': page_reports, 'float32_address_replay': float_reports,
            'layout': exact_layout_check(), 'all_available_captures_passed_their_expected_outcome': True,
            'probe_verifier_imported': False, 'mc_or_gpu_accessed': False,
            'runtime_fingerprint_is_cryptographic': False,
            'source_capture_is_a_gpu_fence': False,
            'formal_fps_measured': False if summary is None else summary.get('formal_fps_measured', False),
            'timing_interpretation': 'SDK return latency and render-event intervals, not GPU completion time',
            'summary_sha256': digest_file(summary_path) if summary_path.is_file() else None}


def self_test():
    for count in (PAGE, 1048576, 1572864, LIMIT):
        values = payload_bytes(54321, 1, count)
        for position in (0, 1, 255, PAGE - 1, count - 1):
            require(int(values[position]) == scalar_byte(54321, 1, position), 'Scalar PRNG self-test failed')
        for salt, salt2 in ((37, 91), (65535, 65535)):
            check = float32_address_check(count, salt, salt2, values)
            require(check['indexed_failures'] == 0 and check['dependent_failures'] == 0,
                    'Float32 boundary self-test failed')
    exact_layout_check()
    values = payload_bytes(54321, 1, PAGE)
    state = {'slot_count': PAGE, 'query': [0, PAGE, 0, 37], 'dimensions': [1, 2560, 1440, 91],
             'diagnostic_layout': [16, 128, 2048, 1],
             'diagnostic_border_policy': 'declared_guard_rect_excluding_native_debug_UI',
             'border_guard_rect_native': [0, 128, 2560, 1408]}
    pixels = np.empty((1440, 2560, 4), dtype=np.uint8)
    pixels[:] = (8, 16, 32, 255)
    pixels[128:160, 16:2064, :3] = values.reshape(32, 2048, 1)
    pixels[4:20, :1000] = (255, 255, 255, 255)  # Excluded native UI.

    def replay_memory():
        buffer = BytesIO()
        Image.fromarray(pixels).save(buffer, format='PNG')
        buffer.seek(0)
        return replay_pixels(buffer, state, values)

    require(replay_memory()['passed'], 'Guarded synthetic PNG self-test failed')
    pixels[159, 2063, 0] ^= 1  # Last logical byte, one channel.
    broken = replay_memory()
    require(broken['failed_queries'] == 1 and broken['border_failures'] == 0,
            'Final1px data boundary mutation was not detected independently')
    pixels[159, 2063, 0] ^= 1
    pixels[128, 15, 0] ^= 1  # Immediately outside the data rectangle.
    broken = replay_memory()
    require(broken['failed_queries'] == 0 and broken['border_failures'] == 1,
            'Adjacent1px guard mutation was not detected independently')
    return {'self_test': 'passed', 'sizes': [PAGE, 1048576, 1572864, LIMIT],
            'salts': [[37, 91], [65535, 65535]], 'synthetic_PNG_checks': 3, 'native_validation': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--allow-incomplete', action='store_true')
    parser.add_argument('--page-oracle-fallback', type=Path,
                        help='Explicit earlier host-oracle directory for an already-resident prefix page')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    require(args.evidence is not None and args.output is not None, 'Provide --evidence and --output')
    require(not args.output.exists(), 'Preserve existing audit output; choose a new path')
    try:
        result = audit(args.evidence, args.page_oracle_fallback)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {'schema': 'independent_large_alpha_audit_v1', 'passed': False, 'complete': False,
                  'evidence': str(args.evidence.resolve()),
                  'error': '%s: %s' % (type(error).__name__, error),
                  'probe_verifier_imported': False, 'mc_or_gpu_accessed': False}
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
        return 1
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'complete': result['complete'],
        'captures': len(result['observations']), 'missing': result['missing_captures'],
        'output': str(args.output.resolve())}, indent=2))
    return 0 if result['complete'] or args.allow_incomplete else 2


if __name__ == '__main__':
    raise SystemExit(main())
