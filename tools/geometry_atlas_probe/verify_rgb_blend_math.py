"""Exhaustive CPU arithmetic only; does not import the SDK or launch a GPU.

The model assumes a linear UNORM8 attachment, exact blend arithmetic,
round-to-nearest after every draw, and exactly one full-coverage write
per stage. Its output is not evidence of a native rendering format.
"""

import json


def nearest_ratio(numerator, denominator):
    """Round a nonnegative rational, with half-way ties rounded upward."""
    return (2 * numerator + denominator) // (2 * denominator)


def check_high_bits(bits):
    levels = 1 << (8 - bits)
    pairs = 0
    payload_errors = 0
    max_error = 0
    for original in range(256):
        for payload in range(1 << bits):
            # Cs = levels*payload/(256-levels); As=(256-levels)/255.
            # RGB blend SourceAlpha / OneMinusSrcAlpha.
            quantized = nearest_ratio((levels - 1) * original, 255)
            encoded = quantized + levels * payload
            decoded_payload, decoded_color = divmod(encoded, levels)
            restored = nearest_ratio(decoded_color * 255, levels - 1)
            pairs += 1
            payload_errors += decoded_payload != payload
            max_error = max(max_error, abs(restored - original))
            if not 0 <= encoded <= 255:
                raise RuntimeError('High-bit model exceeded the attachment range')
    if payload_errors:
        raise RuntimeError('High-bit model lost payload')
    return {
        'bits_per_rgb_channel': bits,
        'tested_original_payload_pairs': pairs,
        'payload_errors': payload_errors,
        'max_restored_channel_error_byte': max_error,
        'source_alpha_fraction': [256 - levels, 255],
        'full_720x1080_capacity_bytes': 720 * 1080 * 3 * bits // 8,
        'one_pixel_records_for_64_kib': (65536 * 8 + 3 * bits - 1) // (3 * bits),
    }


def check_three_draw_low_bit():
    pairs = 0
    payload_errors = 0
    identity_errors = 0
    max_error = 0
    for original in range(256):
        for payload in range(2):
            # Draw 1: Cs=0, As=128/255, SrcAlpha/OneMinusSrcAlpha.
            first = nearest_ratio(127 * original, 255)
            # Draw 2: Cs=1, factors DestColor / SourceColor.
            second = 2 * first
            # Draw 3: Cs=payload/255, factors One / One.
            encoded = second + payload
            pairs += 1
            payload_errors += encoded % 2 != payload
            identity_errors += encoded != 2 * (original // 2) + payload
            max_error = max(max_error, abs(encoded - original))
    if payload_errors or identity_errors or max_error != 1:
        raise RuntimeError('Three-draw model failed the low-bit identity')
    return {
        'draws': 3,
        'tested_original_payload_pairs': pairs,
        'payload_errors': payload_errors,
        'lsb_replacement_identity_errors': identity_errors,
        'max_encoded_scene_channel_error_byte': max_error,
    }


def main():
    # The naive 50/50 blend has overlapping code intervals at byte 128.
    negative_control = [
        {'original': original, 'payload': payload}
        for original in range(256) for payload in range(2)
        if nearest_ratio(original + 255 * payload, 2) == 128
    ]
    if {entry['payload'] for entry in negative_control} != {0, 1}:
        raise RuntimeError('Naive blend negative control did not collide')
    print(json.dumps({
        'scope': 'CPU exact arithmetic; not a native GPU or performance result',
        'assumptions': [
            'linear UNORM8 attachment in the same encode/decode code space',
            'exact blend arithmetic and nearest quantization after every draw',
            'no dithering, sample mixing, later writes, or duplicate coverage',
        ],
        'high_bit_models': [check_high_bits(bits) for bits in range(1, 5)],
        'three_draw_low_bit_model': check_three_draw_low_bit(),
        'naive_half_blend_byte_128_collisions': negative_control,
    }, indent=2))


if __name__ == '__main__':
    main()
