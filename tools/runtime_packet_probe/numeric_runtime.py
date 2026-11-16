# -*- coding: utf-8 -*-
"""Variable-length float32 payloads on an already allocated packet atlas.

The first 16 bytes are four little-endian uint32 fields: magic, scalar count,
payload byte count, generation. Every upload clears unused capacity explicitly.
There is no hidden truncation or automatic native allocation.
"""
import struct
import time
import math
from .numeric_payload import encode


MAGIC = 0x504d4e31
HEADER_BYTES = 16


def write_numbers(aggregation, values, generation=0):
    """Validate the whole payload before the first SDK call, then upload it."""
    started = time.clock()
    if (not aggregation.ready or aggregation.enabled is not True or
            aggregation.error is not None):
        raise RuntimeError('Numeric upload requires a ready enabled atlas')
    if (isinstance(generation, bool) or not isinstance(generation, (int, type(1 << 64))) or
            not 0 <= generation <= 0xffffffff):
        raise ValueError('generation must be uint32')
    capacity = aggregation.config['pages'] * 24
    packet = encode(values, aggregation.config['pages'])
    if HEADER_BYTES + packet['byte_count'] > capacity:
        raise ValueError('Numeric payload plus its header exceeds allocated atlas capacity')
    header = struct.pack('<4I', MAGIC, packet['scalar_count'], packet['byte_count'], generation)
    wire = header + packet['wire_bytes']
    octets = bytearray(wire + b'\x00' * (capacity-len(wire)))
    flat = [(octets[i] << 16) | (octets[i+1] << 8) | octets[i+2]
            for i in range(0, capacity, 3)]
    words = [flat[i:i+8] for i in range(0, len(flat), 8)]
    packets = [[tuple(value/16777216. for value in row[i:i+4])
                for i in (0, 4)] for row in words]
    packed = time.clock()
    try:
        for name, page in zip(aggregation.config['producer_names'], packets):
            for index, values4 in enumerate(page):
                if not aggregation.post.SetParameter(name, 'packet%d' % index, values4):
                    raise RuntimeError('Numeric parameter upload failed: '+name)
    except Exception as error:
        # Earlier pages may already have changed. Disable the chain rather than
        # leave an apparently ready atlas containing mixed generations.
        aggregation._failed(error)
        raise
    uploaded = time.clock()
    aggregation.words = words
    aggregation.numeric_header = {
        'magic': MAGIC, 'scalar_count': packet['scalar_count'],
        'byte_count': packet['byte_count'], 'generation': generation,
        'header_bytes': HEADER_BYTES, 'capacity_bytes': capacity,
        'cleared_bytes': capacity-len(wire), 'format': 'float32_little_endian',
        'sdk_payload_calls': len(packets)*2,
        'generation_ms': (packed-started)*1000., 'upload_ms': (uploaded-packed)*1000.}
    result = aggregation.snapshot()
    result['numeric_header'] = dict(aggregation.numeric_header)
    return result


def decode_numbers(words):
    """Host/offline oracle for a complete capacity-sized word array."""
    integer_types = (int, type(1 << 64))
    if not isinstance(words, (list, tuple)) or not words:
        raise ValueError('Numeric atlas must contain word pages')
    for row in words:
        if not isinstance(row, (list, tuple)) or len(row) != 8:
            raise ValueError('Each numeric atlas page must contain eight words')
        if any(isinstance(value, bool) or not isinstance(value, integer_types) or
               not 0 <= value < 16777216 for value in row):
            raise ValueError('Numeric atlas words must be uint24')
    wire = b''.join(struct.pack('>I', value)[1:] for row in words for value in row)
    if len(wire) < HEADER_BYTES:
        raise ValueError('Numeric atlas has no complete header')
    magic, count, byte_count, generation = struct.unpack('<4I', wire[:HEADER_BYTES])
    if magic != MAGIC or byte_count != count*4 or HEADER_BYTES+byte_count > len(wire):
        raise ValueError('Invalid numeric atlas header')
    if any(bytearray(wire[HEADER_BYTES+byte_count:])):
        raise ValueError('Unused capacity was not cleared')
    data = wire[HEADER_BYTES:HEADER_BYTES+byte_count]
    values = list(struct.unpack('<%df' % count, data)) if count else []
    if any(math.isnan(value) or math.isinf(value) for value in values):
        raise ValueError('Numeric atlas contains nonfinite float32 values')
    return {'values': values, 'scalar_count': count, 'byte_count': byte_count,
            'generation': generation, 'wire_bytes': data}
