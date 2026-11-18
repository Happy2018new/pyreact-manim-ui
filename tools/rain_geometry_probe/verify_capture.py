"""Independent integer oracles over every native query and guard pixel."""
import hashlib
import numpy as np
from PIL import Image


def payload(indices):
    values = np.asarray(indices, dtype=np.uint64)
    result = ((values % 256)*73 + ((values//251) % 256)*19 + 29) % 256
    return np.where(values < 65536, result, 0).astype(np.uint8)


def symbols(count):
    bits = np.arange(count*6, dtype=np.uint64)
    values = payload(bits//8)
    return (((values.astype(np.uint64) >> (bits % 8)) & 1).reshape(count, 6)
            * (1 << np.arange(6, dtype=np.uint64))).sum(axis=1).astype(np.uint8)


def expected_query(kind, count):
    address = np.arange(count, dtype=np.uint64)
    if kind == 'dependent':
        address = (131*address+29) % 65536
        address = (address+257*payload(address).astype(np.uint64)+113) % 65536
    return np.repeat(payload(address)[:, None], 3, axis=1)


def domain(kind, count=16384):
    index = np.arange(count, dtype=np.uint64)
    value = index % 256
    original = np.column_stack((value, (value*73+19) % 256, (value*151+47) % 256))
    q = index//256
    digits = (q[:, None] >> np.array([0, 2, 4], dtype=np.uint64)) & 3
    encoded = 64*digits + (2*63*original+255)//510
    restored = (2*(encoded % 64)*255+63)//126
    return {'domain_original': original, 'domain_encoded': encoded,
            'domain_restored': restored}[kind].astype(np.uint8)


def verify(path, kind, count):
    with Image.open(path) as image:
        if image.size != (720, 1080):
            raise ValueError('Native image must be720x1080')
        pixels = np.array(image.convert('RGBA'))
    guard = pixels[128:1064].reshape(-1, 4)
    queries = guard[:count]
    remainder = guard[count:]
    report = {'kind': kind, 'checked_query_pixels': count, 'checked_guard_pixels': len(remainder),
              'guard_errors': int(np.count_nonzero(np.any(remainder != [0, 0, 0, 255], axis=1))),
              'query_alpha_not255': int(np.count_nonzero(queries[:, 3] != 255)),
              'observed_rgba_sha256': hashlib.sha256(queries.tobytes()).hexdigest()}
    expected = None
    if kind in ('identity', 'dependent'):
        expected = expected_query(kind, count)
    elif kind.startswith('domain_'):
        expected = domain(kind, count)
    elif kind == 'alpha_error':
        expected = np.zeros((count, 3), dtype=np.uint8)
    elif kind == 'q_alpha':
        observed = queries[:, 0]
        expected_q = symbols(count)
        bad = observed != expected_q
        alpha = queries[:, 1]
        report.update(bad_q=int(bad.sum()), alpha_not255=int(np.count_nonzero(alpha != 255)),
                      bad_q_alpha_not255=int(np.count_nonzero(bad & (alpha != 255))),
                      bad_q_alpha255=int(np.count_nonzero(bad & (alpha == 255))),
                      alpha_offgrid=int(np.count_nonzero(queries[:, 2])),
                      alpha_histogram={str(v): int(n) for v, n in zip(*np.unique(alpha, return_counts=True))},
                      q_histogram={str(v): int(n) for v, n in zip(*np.unique(observed, return_counts=True))})
        report['query_errors'] = int(np.count_nonzero(bad | (queries[:, 2] != 0)))
    elif kind == 'block_alpha':
        counts = queries[:, 0]
        repeated = counts.reshape(-1, 32)
        report.update(max_block_exceptions=int(counts.max()),
                      overflow_source_pixels=int(np.count_nonzero(queries[:, 1])),
                      alpha_restore_error_pixels=int(np.count_nonzero(queries[:, 2])),
                      block_count=int(len(repeated)),
                      inconsistent_block_count_pixels=int(np.count_nonzero(repeated != repeated[:, :1])),
                      exception_count_histogram={str(v): int(n) for v, n in zip(*np.unique(repeated[:, 0], return_counts=True))})
        report['query_errors'] = int(np.count_nonzero((queries[:, 1] != 0) | (queries[:, 2] != 0)))
    else:
        raise ValueError('Unknown verification kind '+kind)
    if expected is not None:
        errors = np.max(np.abs(queries[:, :3].astype(np.int16)-expected.astype(np.int16)), axis=1)
        report.update(query_errors=int(np.count_nonzero(errors)), maximum_channel_error=int(errors.max()))
        failures = np.flatnonzero(errors)[:16]
        report['failures_first16'] = [{'ordinal': int(i), 'expected': expected[i].tolist(),
                                      'observed': queries[i].tolist()} for i in failures]
    report['passed'] = report['query_errors'] == report['guard_errors'] == report['query_alpha_not255'] == 0
    return report
