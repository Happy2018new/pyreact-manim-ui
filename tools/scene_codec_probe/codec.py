"""CPU oracle for RGB transport and fixed 32-alpha blocks; no SDK or file IO.

The blend oracle assumes exact linear UNORM8 arithmetic. It does not establish
the native attachment format, material ordering, coverage, or blend precision.
All bit streams are little endian, including the RGB channel order R,G,B.
"""

import math


BLOCK_PIXELS = 32
HEADER_BYTES = 8
ALPHA_PAYLOAD_BYTES = 24


def _byte(value):
    if int(value) != value or not 0 <= value <= 255:
        raise ValueError('Expected an integer byte')
    return int(value)


def _bits(bits):
    if bits not in (1, 2):
        raise ValueError('This probe supports RGB k=1 or k=2 only')
    return int(bits)


def nearest_ratio(numerator, denominator):
    return (2 * numerator + denominator) // (2 * denominator)


def encode_rgb_channel(original, payload, bits):
    """Ideal SourceAlpha/OneMinusSrcAlpha blend followed by UNORM8 storage."""
    bits = _bits(bits)
    original = _byte(original)
    if int(payload) != payload or not 0 <= payload < (1 << bits):
        raise ValueError('Payload exceeds its RGB symbol')
    levels = 1 << (8 - bits)
    return nearest_ratio((levels - 1) * original, 255) + levels * int(payload)


def decode_rgb_channel(encoded, bits):
    bits = _bits(bits)
    levels = 1 << (8 - bits)
    payload, quantized = divmod(_byte(encoded), levels)
    return payload, nearest_ratio(quantized * 255, levels - 1)


def payload_to_symbols(values, bits):
    """Pack bytes into 3*k-bit geometry records; zero-pad the final record."""
    width = 3 * _bits(bits)
    buffer_value = 0
    available = 0
    result = bytearray()
    for value in bytearray(values):
        buffer_value |= value << available
        available += 8
        while available >= width:
            result.append(buffer_value & ((1 << width) - 1))
            buffer_value >>= width
            available -= width
    if available:
        result.append(buffer_value)
    return result


def symbols_to_payload(symbols, bits, byte_count=None):
    width = 3 * _bits(bits)
    buffer_value = 0
    available = 0
    result = bytearray()
    for symbol in symbols:
        if int(symbol) != symbol or not 0 <= symbol < (1 << width):
            raise ValueError('Geometry record exceeds 3*k bits')
        buffer_value |= int(symbol) << available
        available += width
        while available >= 8:
            result.append(buffer_value & 255)
            buffer_value >>= 8
            available -= 8
    if byte_count is None:
        return result
    if int(byte_count) != byte_count or not 0 <= byte_count <= len(result):
        raise ValueError('Requested byte count exceeds the symbol stream')
    return result[:int(byte_count)]


def payload_oracle(byte_index, salt=29):
    """Fixture byte function; bounded intermediates also fit float32 shaders."""
    return ((byte_index % 256) * 73 + ((byte_index // 251) % 256) * 19 + salt) % 256


def fixture_rgb(index):
    value = index % 256
    return value, (value * 73 + 19) % 256, (value * 151 + 47) % 256


def fixture_alpha(index, mode=1, base=255):
    base = _byte(base)
    local = index % BLOCK_PIXELS
    if mode == 0:
        return base
    if mode == 1:
        positions = (0, 7, 16, 31)
        return (base + positions.index(local) + 1) % 256 if local in positions else base
    if mode == 2:
        return (base + local + 1) % 256 if local < 5 else base
    if mode == 3:
        return index % 256
    raise ValueError('Unknown alpha fixture mode')


def fixture_rgba(index, bits, mode=1, base=255, salt=29):
    """Shader fixture oracle; calculated encoding is not a native blend test."""
    bits = _bits(bits)
    symbol = 0
    for shift in range(3 * bits):
        address = index * 3 * bits + shift
        value = payload_oracle(address // 8, salt)
        symbol |= ((value >> (address % 8)) & 1) << shift
    rgb = fixture_rgb(index)
    return tuple(encode_rgb_channel(value, (symbol >> (channel * bits)) & ((1 << bits) - 1), bits)
                 for channel, value in enumerate(rgb)) + (fixture_alpha(index, mode, base),)


def encode_alpha_block(alpha, payload=(), base=255):
    """32 bytes -> 4 mask bytes + 4 exceptions + 24 payload bytes.

    The baseline is an external uniform, not an unstated ninth header byte.
    Overflow is rejected. No truncated block is returned as a valid encoding.
    """
    alpha = bytearray(alpha)
    payload = bytearray(payload)
    base = _byte(base)
    if len(alpha) != BLOCK_PIXELS or len(payload) > ALPHA_PAYLOAD_BYTES:
        raise ValueError('Expected 32 alpha bytes and at most 24 payload bytes')
    mask = 0
    exceptions = bytearray()
    for index, value in enumerate(alpha):
        if value != base:
            mask |= 1 << index
            exceptions.append(value)
    result = {'overflow': len(exceptions) > 4,
              'exception_count': len(exceptions), 'mask': mask,
              'base': base, 'encoded': None}
    if result['overflow']:
        return result
    encoded = bytearray((mask >> (8 * index)) & 255 for index in range(4))
    encoded.extend(exceptions)
    encoded.extend(bytearray(4 - len(exceptions)))
    encoded.extend(payload)
    encoded.extend(bytearray(ALPHA_PAYLOAD_BYTES - len(payload)))
    result['encoded'] = encoded
    return result


def decode_alpha_block(encoded, base=255):
    encoded = bytearray(encoded)
    base = _byte(base)
    if len(encoded) != BLOCK_PIXELS:
        raise ValueError('Encoded alpha block must have 32 bytes')
    mask = sum(encoded[index] << (8 * index) for index in range(4))
    if bin(mask).count('1') > 4:
        raise ValueError('Overflow alpha block cannot be decoded independently')
    result = bytearray()
    rank = 0
    for index in range(BLOCK_PIXELS):
        is_exception = (mask >> index) & 1
        result.append(encoded[4 + rank] if is_exception else base)
        rank += is_exception
    return {'alpha': result, 'payload': encoded[HEADER_BYTES:], 'mask': mask}


def encode_combined_block(rgb, alpha, payload, bits, base=255):
    """Model geometry RGB transport -> simultaneous RGB restore/alpha pack.

    This moves the RGB input payload into alpha slots; capacities do not add.
    k=1 carries 12 bytes/block, k=2 carries 24 bytes/block.
    """
    bits = _bits(bits)
    payload = bytearray(payload)
    if len(rgb) != BLOCK_PIXELS or len(payload) != 12 * bits:
        raise ValueError('Combined fixture requires 32 RGB pixels and 12*k bytes')
    symbols = payload_to_symbols(payload, bits)
    coded_rgb = []
    restored_rgb = []
    recovered_symbols = []
    channel_mask = (1 << bits) - 1
    for original, symbol in zip(rgb, symbols):
        if len(original) != 3:
            raise ValueError('Expected RGB triples')
        coded = tuple(encode_rgb_channel(value, (symbol >> (channel * bits)) & channel_mask,
                                         bits) for channel, value in enumerate(original))
        decoded = [decode_rgb_channel(value, bits) for value in coded]
        coded_rgb.append(coded)
        restored_rgb.append(tuple(value[1] for value in decoded))
        recovered_symbols.append(sum(value[0] << (channel * bits)
                                     for channel, value in enumerate(decoded)))
    transported = symbols_to_payload(recovered_symbols, bits, len(payload))
    result = encode_alpha_block(alpha, transported, base)
    result.update({'coded_rgb': coded_rgb, 'restored_rgb': restored_rgb,
                   'transported_payload': transported, 'rgb_bits': bits,
                   'logical_payload_bytes': len(payload)})
    return result


def alpha_distribution(samples, base=255, grid_tolerance=0.0001):
    """Report observed precision and fixed-baseline block compressibility.

    Quantization is diagnosed, not declared lossless for non-UNORM8 inputs.
    A partial final block contributes to the histogram but not capacity.
    """
    base = _byte(base)
    quantized = bytearray()
    histogram = [0] * 256
    max_residual = 0.0
    off_grid = 0
    for sample in samples:
        if math.isnan(sample) or math.isinf(sample) or not 0.0 <= sample <= 1.0:
            raise ValueError('Alpha sample must be finite and normalized')
        code = int(sample * 255.0 + 0.5)
        residual = abs(sample * 255.0 - code)
        max_residual = max(max_residual, residual)
        off_grid += residual > grid_tolerance
        quantized.append(code)
        histogram[code] += 1
    counts = [sum(value != base for value in quantized[start:start + BLOCK_PIXELS])
              for start in range(0, len(quantized) - BLOCK_PIXELS + 1, BLOCK_PIXELS)]
    valid = sum(count <= 4 for count in counts)
    modal_byte = max(range(256), key=lambda value: histogram[value])
    return {'sample_count': len(quantized), 'histogram': histogram,
            'distinct_quantized_values': sum(bool(count) for count in histogram),
            'modal_byte': modal_byte, 'modal_count': histogram[modal_byte],
            'base': base, 'off_grid_count': off_grid,
            'max_subbyte_residual': max_residual, 'complete_blocks': len(counts),
            'incomplete_pixels': len(quantized) % BLOCK_PIXELS,
            'valid_blocks': valid, 'overflow_blocks': len(counts) - valid,
            'conditional_alpha_payload_bytes': valid * ALPHA_PAYLOAD_BYTES,
            'unorm8_exact_at_tolerance': off_grid == 0}
