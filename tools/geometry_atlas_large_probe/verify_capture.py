"""Independent integer oracle: every valid native diagnostic pixel, plus all borders."""
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

SCHEMA = 'geometry_atlas_large_probe_v1'
SCREEN = (2560, 1440)
PAGE_BYTES = 65536
MAX_BYTES = 2097152


def expected_bytes(seed, generation, indices):
    index = np.asarray(indices, dtype=np.uint64)
    mask = np.uint64(0xffffffff)
    value = np.uint64(seed ^ ((generation * 0x9e3779b9) & 0xffffffff)) ^ ((index * np.uint64(0x85ebca6b)) & mask)
    value ^= value >> np.uint64(16)
    value = (value * np.uint64(0x7feb352d)) & mask
    value ^= value >> np.uint64(15)
    value = (value * np.uint64(0x846ca68b)) & mask
    return ((value ^ (value >> np.uint64(16))) & np.uint64(255)).astype(np.uint8)


def lookup_indices(seed, generation, count, mode, salt, salt2):
    indices = np.arange(count, dtype=np.uint64)
    if mode:
        indices = (131 * indices + salt) % count
        if mode == 2:
            first = expected_bytes(seed, generation, indices).astype(np.uint64)
            indices = (indices + 257 * first + salt2) % count
    return indices


def validate_receipt(state, size):
    if state.get('schema') != SCHEMA or tuple(size) != SCREEN or state.get('screen_size') != list(SCREEN):
        raise ValueError('Require the large-probe schema and unscaled native2560x1440 capture')
    n = state.get('slot_count')
    if isinstance(n, bool) or not isinstance(n, int) or not PAGE_BYTES <= n <= MAX_BYTES or n % PAGE_BYTES:
        raise ValueError('Require a complete64KiB-paged resident prefix through2MiB')
    if state.get('loaded_bytes') != n or not state.get('pipeline_ready') or not state.get('connection'):
        raise ValueError('All logical bytes and the explicit private-texture connection must be ready')
    if state.get('layout') != [n, 2048, 8, 32] or state.get('dimensions', [])[:3] != [1, 2560, 1440]:
        raise ValueError('Unexpected source atlas layout')
    if state.get('diagnostic_layout') != [16,128,2048,1] or state.get('border_guard_rect_native') != [0,128,2560,1408]:
        raise ValueError('Unexpected diagnostic layout or declared border guard')
    if state.get('query', [])[:2] != [0, n] or state['query'][2] not in (0, 1, 2):
        raise ValueError('Require a whole-array diagnostic query')
    if not isinstance(state.get('flip_y'), bool):
        raise ValueError('Sampling orientation must be explicit')
    pages = state.get('pages', [])
    if len(pages) != n // PAGE_BYTES:
        raise ValueError('Page count disagrees with logical byte count')
    names = []
    for i, page in enumerate(pages):
        if (page.get('base') != i * PAGE_BYTES or page.get('count') != PAGE_BYTES or
                page.get('loaded') is not True or page.get('ready') is not True or not page.get('name')):
            raise ValueError('Page bounds, identity or residency is incomplete')
        names.append(page['name'])
    if len(set(names)) != len(names) or state.get('geometry_names') != names:
        raise ValueError('Geometry identities must be unique and recorded in page order')
    return n


def verify_image(state, image):
    n = validate_receipt(state, image.size)
    pixels = np.asarray(image.convert('RGBA'), dtype=np.uint8)
    rows = n // 2048
    observed = pixels[128:128+rows, 16:2064].reshape(n, 4)
    mode, salt, salt2 = state['query'][2], state['query'][3], state['dimensions'][3]
    indices = lookup_indices(state['seed'], state['generation'], n, mode, salt, salt2)
    expected = expected_bytes(state['seed'], state['generation'], indices)
    difference = np.abs(observed[:, :3].astype(np.int16) - expected[:, None].astype(np.int16))
    failures = np.any(difference != 0, axis=1) | (observed[:, 3] != 255)
    border = np.zeros(pixels.shape[:2], dtype=bool)
    border[128:1408] = True
    border[128:128+rows, 16:2064] = False
    border_pixels = pixels[border]
    border_failures = np.any(border_pixels != np.array([8, 16, 32, 255], dtype=np.uint8), axis=1)
    failure_indices = np.flatnonzero(failures)
    return {'schema': SCHEMA, 'passed': not failures.any() and not border_failures.any(),
        'exact_equal': not failures.any(), 'slot_count': n, 'mode': mode, 'seed': state['seed'],
        'generation': state['generation'], 'query': state['query'], 'salt2': salt2,
        'native_size': list(image.size), 'logical_queries_checked': n,
        'query_pixels_checked': n, 'query_channels_checked': 4*n,
        'border_pixels_checked': int(border.sum()), 'border_failures': int(border_failures.sum()),
        'diagnostic_layout': state['diagnostic_layout'], 'border_guard_rect_native': state['border_guard_rect_native'],
        'border_policy': state['diagnostic_border_policy'],
        'failed_queries': int(failures.sum()), 'maximum_rgb_error': int(difference.max()),
        'alpha_failures': int((observed[:, 3] != 255).sum()), 'byte_tolerance': 0,
        'page_boundaries_checked': [value for i in range(n // PAGE_BYTES) for value in (i*PAGE_BYTES, (i+1)*PAGE_BYTES-1)],
        'failures_first32': [{'ordinal': int(i), 'source_index': int(indices[i]), 'expected': int(expected[i]),
            'observed_rgba': observed[i].tolist()} for i in failure_indices[:32]],
        'observed_payload_sha256': hashlib.sha256(observed[:, 0].tobytes()).hexdigest(),
        'expected_payload_sha256': hashlib.sha256(expected.tobytes()).hexdigest(),
        'oracle': 'independent_integer_seed_generation_and_dependent_addresses',
        'proof': 'every_valid_native_query_pixel_and_every_outside_pixel_in_declared_guard',
        'writer_visible': state['writer_visible'], 'runtime_payload_files': state['runtime_payload_files']}


def verify_files(receipt, capture, output):
    receipt, capture, output = map(Path, (receipt, capture, output))
    if output.exists():
        raise ValueError('Preserve existing verification output')
    state = json.loads(receipt.read_text(encoding='utf-8-sig'))
    with Image.open(capture) as image:
        result = verify_image(state, image)
    result['receipt_sha256'] = hashlib.sha256(receipt.read_bytes()).hexdigest()
    result['capture_sha256'] = hashlib.sha256(capture.read_bytes()).hexdigest()
    output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result
