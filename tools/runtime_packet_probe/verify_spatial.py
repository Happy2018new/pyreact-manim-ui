"""Fixed-coordinate all-byte oracle for phone-sized spatial packet probes."""
import hashlib
import math

from verify_capture import _sample, word_bytes


def expected_words(seed, pages):
    """Independent integer reference for the recorded runtime LCG dataset."""
    value = int(seed) & 0xffffff
    flat = []
    for index in range(pages * 8):
        value = (value * 1664525 + 1013904223) & 0xffffff
        flat.append(value)
    return [flat[index:index + 8] for index in range(0, len(flat), 8)]


def groups(receipt, size):
    if list(size) != receipt['screen_size']:
        raise ValueError('Native capture dimensions differ from requested phone profile')
    width, height = size
    aggregate = receipt['aggregate']
    pages, words = aggregate['pages'], aggregate['words']
    if (not isinstance(pages, int) or pages < 1 or len(words) != pages or
            aggregate['words_per_page'] != 8):
        raise ValueError('Spatial receipt must contain all eight-word pages')
    if 'expected_seed' in receipt and words != expected_words(receipt['expected_seed'], pages):
        raise ValueError('Runtime words disagree with independently generated expected seed')
    source = [[byte for word in row for byte in word_bytes(word)] for row in words
              if isinstance(row, list) and len(row) == 8]
    if len(source) != pages:
        raise ValueError('Malformed spatial word pages')
    if receipt['transport'] == 'atlas2d':
        query = aggregate['query']
        if len(query) != 4 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or
                                  not math.isfinite(x) or int(x) != x for x in query):
            raise ValueError('Invalid atlas display query')
        total, start, count, shift = map(int, query)
        if total != pages or not 0 <= start < pages or not 1 <= count <= pages:
            raise ValueError('Query is outside the allocated atlas')
        rect = aggregate['display_rect_norm']
        rectangles = [(rect[0], rect[1] + row * rect[3] / count, rect[2], rect[3] / count)
                      for row in range(count)]
        indices = list(range(start, start + count))
        expected = [[source[page][3 * ((cell // 3 + shift) % 8) + cell % 3]
                     if page < pages else 0 for cell in range(24)] for page in indices]
    elif receipt['transport'] in ('uniform_split', 'uniform_ui'):
        rectangles, indices, expected = receipt['rectangles_norm'], list(range(pages)), source
        if len(rectangles) != pages:
            raise ValueError('Uniform split receipt omitted tiles')
    else:
        raise ValueError('Unknown spatial transport')
    result = []
    for index, rect, values in zip(indices, rectangles, expected):
        if len(rect) != 4 or any(not math.isfinite(value) for value in rect):
            raise ValueError('Invalid tile rectangle')
        x, y, w, h = rect
        if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1.00000001 or y + h > 1.00000001:
            raise ValueError('Tile is outside the native capture')
        result.append((index, (x * width, y * height, w * width, h * height), values,
                       index < pages))
    return result


def verify_spatial(receipt, image):
    image = image.convert('RGBA')
    rows, failures, checked, maximum = [], 0, 0, 0
    observed_payload, expected_payload = bytearray(), bytearray()
    indices = []
    for index, rect, expected, payload in groups(receipt, image.size):
        observed, errors = [], []
        for cell, value in enumerate(expected):
            center, pixels, patch_width = _sample(image, rect, cell, 24, False)
            error = max(abs(channel - value) for pixel in pixels for channel in pixel[:3])
            alpha = min(pixel[3] for pixel in pixels)
            if error or alpha != 255:
                failures += 1
            checked += 1
            maximum = max(maximum, error)
            rgb = list(image.getpixel(tuple(center))[:3])
            observed.append(rgb)
            errors.append(error)
            if payload:
                observed_payload.append(rgb[0])
                expected_payload.append(value)
        if payload:
            indices.append(index)
        rows.append({'index': index, 'payload': payload, 'observed': observed,
                     'errors': errors})
    if len(set(expected_payload)) < 2:
        raise ValueError('Uniform background cannot establish data delivery')
    passed = failures == 0
    return {'passed': passed, 'exact_equal': passed, 'checked_cells': checked,
            'failed_cells': failures, 'max_error': maximum, 'capture_size': list(image.size),
            'payload_bytes': len(observed_payload), 'verified_page_indices': indices,
            'observed_payload_sha256': hashlib.sha256(observed_payload).hexdigest(),
            'expected_payload_sha256': hashlib.sha256(expected_payload).hexdigest(),
            'results': rows}
