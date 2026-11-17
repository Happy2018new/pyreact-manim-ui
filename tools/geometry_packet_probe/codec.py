# -*- coding: utf-8 -*-
"""Pure Python 2/3 byte-to-palette encoders for the isolated geometry probe.

legacy8 stores the byte in an integer block Y. compact8 stores its high
nibble in block Y and its low nibble in one of sixteen static model planes.
The latter keeps the native palette height at 16 instead of 256 blocks.
"""

MAX_BYTES = 1048576
DEFAULT_ENCODING = 'compact8'
ENCODINGS = ('legacy8', 'compact8')
ENCODING_LAYOUT_BIT = 2097152
LEGACY_IDENTIFIER = 'pmanim_geometry_packet:quad'
COMPACT_IDENTIFIERS = tuple('pmanim_geometry_packet:quad_compact8_%02d' % value
                            for value in range(16))

try:
    INTEGER_TYPES = (int, long)
except NameError:
    INTEGER_TYPES = (int,)


def template_identifier(encoding, template=0):
    """Return an existing static model identifier, rejecting invalid templates."""
    if encoding not in ENCODINGS:
        raise ValueError('Unknown geometry packet encoding: %s' % (encoding,))
    limit = 1 if encoding == 'legacy8' else 16
    if (isinstance(template, bool) or not isinstance(template, INTEGER_TYPES)
            or not 0 <= template < limit):
        raise ValueError('Invalid geometry packet template')
    return LEGACY_IDENTIFIER if encoding == 'legacy8' else COMPACT_IDENTIFIERS[template]


def _payload_bytes(values):
    # bytes is str in Python 2. Unicode strings are deliberately not accepted.
    if isinstance(values, (bytes, bytearray)):
        if not 1 <= len(values) <= MAX_BYTES:
            raise ValueError('Experimental byte count must be in [1,1048576]')
        return values if isinstance(values, bytearray) else bytearray(values)
    if not hasattr(values, '__iter__'):
        raise ValueError('Payload must contain integer bytes')
    payload = bytearray()
    for value in values:
        if len(payload) >= MAX_BYTES:
            raise ValueError('Experimental byte count must be in [1,1048576]')
        if (isinstance(value, bool) or not isinstance(value, INTEGER_TYPES)
                or not 0 <= value <= 255):
            raise ValueError('Payload must contain integer bytes in [0,255]')
        payload.append(value)
    if not payload:
        raise ValueError('Experimental byte count must be in [1,1048576]')
    return payload


def encode_values(values, encoding=DEFAULT_ENCODING):
    """Return native palette data and layout metadata without importing the SDK.

    Palette volume order is (z, x, y). Every input byte owns one X/Z record:
    record = x * stride + z, so its linear palette address is y * plane +
    record. Padding records are air, including the tail of non-square inputs.
    compact8 template t has local Y=(t+0.5)/16 blocks; the midpoint leaves
    a 1/32 block tolerance to either low-nibble decoding boundary.
    """
    if encoding not in ENCODINGS:
        raise ValueError('Unknown geometry packet encoding: %s' % (encoding,))
    payload = _payload_bytes(values)
    record_count = len(payload)
    stride = 2
    while stride * stride < record_count:
        stride *= 2
    plane = stride * stride
    if encoding == 'legacy8':
        height, template_count, encoding_id = 256, 1, 0
        common = {(LEGACY_IDENTIFIER, 0): [value * plane + index
                  for index, value in enumerate(payload)]}
    else:
        height, template_count, encoding_id = 16, 16, 1
        buckets = [[] for _ in range(16)]
        for index, value in enumerate(payload):
            buckets[value % 16].append((value // 16) * plane + index)
        common = {(COMPACT_IDENTIFIERS[template], 0): indices
                  for template, indices in enumerate(buckets) if indices}
    volume = (stride, stride, height)
    data = {'volume': volume, 'common': common,
            'extra': {}, 'actor': {}, 'states': {}, 'extraStates': {},
            'void': False, 'eliminateAir': True}
    return {'data': data, 'encoding': encoding, 'encoding_id': encoding_id,
            'record_count': record_count, 'stride': stride,
            'palette_height': height, 'template_count': template_count,
            'volume': volume, 'y_offset': height * 0.5}
