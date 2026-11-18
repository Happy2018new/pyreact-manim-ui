"""Independent host verifier for the bounded arbitrary64B stencil probe.

This module imports no original probe runner, builder, runtime, or verifier.
It reads supplied native images and does not operate a game or write files.

Layout, also implemented by packed_post.fragment:
  * Native image: 720x1080. Source ROI: (96,192,128,128).
  * Source: 16x16 records, each replicated over an 8x8 cell. Record r carries
    (payload[r//4] >> (2*(r%4))) & 3 in its red byte's upper two bits.
  * Diagnostic output ROI: (0,600,720,256), flattened in row-major order.
  * Mode0: first 32768 output pixels are adjacent rawRGB / alpha-gray pairs,
    covering all 16384 source pixels. Remaining output pixels are GUARD.
  * Mode1: every output pixel queries i=ordinal%64 and displays marker(byte).
  * Mode2: i=ordinal%64; j=(13*i+7)%64; b=payload[j]; k=(j+3*b+5)%64;
    every output pixel displays marker(payload[k]). No payload seed is used.
  * Mode3: first 16384 output pixels contain restored source RGB, flattened
    from the source ROI. Remaining pixels are GUARD. This mode requires the
    known native background fixture: R=r,G=(73*r+19)%256,B=(151*r+47)%256.

marker(b)=(b,(71*b+43)%256,(131*b+17)%256). Mode3 accepts at most two byte
units of error per RGB channel. Modes1/2 and guards require exact RGB.
Mode0 fixture=True validates the unencoded known native background. Default
sunny mode0 validates exact hardware-blend bytes against that background.
Mode0 raining=True validates payload symbols and lower-six-bit green/blue
range without assigning an RGB oracle to a changing natural rain frame.
All mode0 cases check every alpha-gray triple and guard.
Screenshot alpha is never used to infer intermediate alpha preservation.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from PIL import Image


SCREEN_SIZE = (720, 1080)
SOURCE_ROI = (96, 192, 128, 128)
OUTPUT_ROI = (0, 600, 720, 256)
CELL_SIZE = 8
RECORD_COLUMNS = 16
RECORD_COUNT = 256
SOURCE_PIXELS = 16384
PAYLOAD_BYTES = 64
GUARD = (17, 53, 97)
RESTORE_TOLERANCE = 2


def _payload(values):
    if not isinstance(values, (list, tuple, bytes, bytearray)) or len(values) != PAYLOAD_BYTES:
        raise ValueError('Expected exactly 64 independently supplied bytes')
    result = list(values)
    if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255 for value in result):
        raise ValueError('Payload values must be integer bytes, excluding bool')
    return result


def _rgb_image(image):
    if isinstance(image, Image.Image):
        result = image.convert('RGB')
    else:
        with Image.open(Path(image)) as source:
            result = source.convert('RGB')
    if result.size != SCREEN_SIZE:
        raise ValueError('Expected a native 720x1080 image without resizing or cropping')
    return result


def _record(source_index):
    x = source_index % SOURCE_ROI[2]
    y = source_index // SOURCE_ROI[2]
    return (y // CELL_SIZE) * RECORD_COLUMNS + x // CELL_SIZE


def _symbol(values, record):
    return (values[record // 4] >> (2 * (record % 4))) & 3


def _marker(value):
    return value, (71 * value + 43) % 256, (131 * value + 17) % 256


def _fixture(record):
    return record, (73 * record + 19) % 256, (151 * record + 47) % 256


def _quantized_base(value):
    # Nearest integer to value*63/255, with explicit integer arithmetic.
    return (2 * value * 63 + 255) // 510


def _location(ordinal):
    return OUTPUT_ROI[0] + ordinal % OUTPUT_ROI[2], OUTPUT_ROI[1] + ordinal // OUTPUT_ROI[2]


def verify(image, mode, payload, slot, fixture=False, raining=False):
    """Return full intended-output verification; slot records T0/T1 selection.

Modes0/3 cover all source pixels and all guard pixels. Modes1/2 compare the
    entire 720x256 output, with every logical query repeated 2880 times.
    Alpha-gray values are observations in mode0; no all-255 assumption is made.
    fixture=True is only for mode0 with the raw native background visible and
    all SFX encoding hidden. Default sunny mode0 expects the encoded native
    background. rainy mode0 does not compare against a historical RGB frame.
    """
    if isinstance(mode, bool) or mode not in (0, 1, 2, 3):
        raise ValueError('Mode must be 0, 1, 2, or 3')
    if isinstance(slot, bool) or slot not in (0, 1):
        raise ValueError('Slot must be 0 or 1')
    if not isinstance(fixture, bool) or not isinstance(raining, bool):
        raise ValueError('Fixture and raining flags must be bool')
    if fixture and (mode != 0 or raining):
        raise ValueError('The raw native fixture control requires sunny mode0')
    if mode == 3 and raining:
        raise ValueError('RGB restoration has an oracle only for the sunny native fixture')
    values = _payload(payload)
    pixels = _rgb_image(image)
    total = OUTPUT_ROI[2] * OUTPUT_ROI[3]
    errors = guard_errors = source_errors = alpha_gray_errors = range_errors = 0
    symbol_errors = rgb_oracle_errors = 0
    rgb_channel_errors = [0, 0, 0]
    maximum_error = [0, 0, 0]
    alpha_codes = Counter()
    symbol_codes = Counter()
    query_codes = Counter()
    first_errors = []
    query_addresses = list(range(PAYLOAD_BYTES))
    if mode == 2:
        query_addresses = []
        for query in range(PAYLOAD_BYTES):
            first_address = (13 * query + 7) % PAYLOAD_BYTES
            query_addresses.append((first_address + 3 * values[first_address] + 5) % PAYLOAD_BYTES)
    data_pixels = SOURCE_PIXELS * (2 if mode == 0 else 1) if mode in (0, 3) else total
    for ordinal in range(total):
        location = _location(ordinal)
        actual = pixels.getpixel(location)
        category = 'guard'
        expected = None
        wrong = False
        if ordinal >= data_pixels:
            expected = GUARD
            wrong = actual != expected
            guard_errors += wrong
        elif mode == 0:
            source_index = ordinal // 2
            if ordinal % 2:
                category = 'alpha_gray'
                wrong = not (actual[0] == actual[1] == actual[2])
                alpha_gray_errors += wrong
                alpha_codes[actual[0]] += 1
            else:
                category = 'source_symbol'
                record = _record(source_index)
                symbol = _symbol(values, record)
                got = actual[0] // 64
                symbol_codes[got] += 1
                symbol_wrong = not fixture and got != symbol
                range_wrong = not fixture and (actual[1] > 63 or actual[2] > 63)
                oracle_wrong = False
                if fixture or not raining:
                    original = _fixture(record)
                    expected = original if fixture else tuple(_quantized_base(value) + (64 * symbol if channel == 0 else 0)
                        for channel, value in enumerate(original))
                    differences = [abs(a - b) for a, b in zip(actual, expected)]
                    for channel, difference in enumerate(differences):
                        maximum_error[channel] = max(maximum_error[channel], difference)
                        rgb_channel_errors[channel] += difference != 0
                    oracle_wrong = actual != expected
                else:
                    expected = symbol
                symbol_errors += symbol_wrong
                range_errors += range_wrong
                rgb_oracle_errors += oracle_wrong
                wrong = symbol_wrong or range_wrong or oracle_wrong
                source_errors += wrong
        elif mode in (1, 2):
            category = 'query_marker'
            query = ordinal % PAYLOAD_BYTES
            address = query_addresses[query]
            expected = _marker(values[address])
            wrong = actual != expected
            source_errors += wrong
            query_codes[query] += 1
        else:
            category = 'restored_rgb'
            expected = _fixture(_record(ordinal))
            differences = [abs(a - b) for a, b in zip(actual, expected)]
            for channel, difference in enumerate(differences):
                maximum_error[channel] = max(maximum_error[channel], difference)
                rgb_channel_errors[channel] += difference > RESTORE_TOLERANCE
            wrong = any(difference > RESTORE_TOLERANCE for difference in differences)
            source_errors += wrong
        errors += wrong
        if wrong and len(first_errors) < 12:
            first_errors.append({'output_xy': list(location), 'category': category,
                'actual_rgb': list(actual), 'expected_rgb_or_symbol': expected})
    result = {
        'schema': 'weather_stencil_packed64_post_verify_v1', 'mode': int(mode), 'slot': int(slot),
        'source_texture': 'TEXTURE_' + str(slot), 'source_roi': list(SOURCE_ROI), 'output_roi': list(OUTPUT_ROI),
        'payload_bytes': PAYLOAD_BYTES, 'geometry_records': RECORD_COUNT,
        'fixture_unencoded': fixture, 'raining': raining,
        'checked_output_pixels': total, 'data_output_pixels': data_pixels,
        'checked_guard_pixels': total - data_pixels, 'error_pixels': errors,
        'source_error_pixels': source_errors, 'guard_error_pixels': guard_errors,
        'exact': errors == 0, 'first_errors': first_errors,
        'native_image_size_verified': True, 'original_verifier_imported': False,
        'screenshot_alpha_used_for_intermediate_alpha_claim': False,
        'intermediate_alpha_preservation_verified': False,
    }
    if mode == 0:
        result.update({'source_pixels': SOURCE_PIXELS, 'same_scene_texel_rgb_alpha_pairs': SOURCE_PIXELS,
            'payload_symbol_error_pixels': symbol_errors, 'payload_symbol_validation_performed': not fixture,
            'green_blue_outside_low6_range_pixels': range_errors,
            'raw_rgb_oracle_applied': fixture or not raining, 'raw_rgb_oracle_error_pixels': rgb_oracle_errors,
            'maximum_rgb_oracle_error': maximum_error, 'rgb_oracle_channel_errors': rgb_channel_errors,
            'alpha_pair_not_gray_pixels': alpha_gray_errors,
            'alpha_not255_pixels': sum(count for code, count in alpha_codes.items() if code != 255),
            'alpha_min': min(alpha_codes), 'alpha_max': max(alpha_codes),
            'alpha_histogram': dict(sorted(alpha_codes.items())), 'symbol_histogram': dict(sorted(symbol_codes.items())),
            'alpha_values_are_observations': True,
            'comparison_scope': ('Exact raw native fixture RGB, all alpha-gray triples, and guards.' if fixture else
                ('Exact encoded native fixture RGB, payload symbols, alpha-gray triples, and guards.' if not raining else
                 'All source high-red payload symbols, green/blue range, alpha-gray triples, and guards; changing rain RGB lower bits have no oracle.'))})
    elif mode in (1, 2):
        result.update({'logical_queries': PAYLOAD_BYTES, 'query_executions': total,
            'query_repetitions': dict(sorted(query_codes.items())), 'query_final_addresses': query_addresses,
            'distinct_final_addresses': len(set(query_addresses)),
            'expected_query_bytes': [values[address] for address in query_addresses],
            'comparison_scope': 'Exact RGB marker comparison across the entire intended output.'})
    else:
        result.update({'source_pixels': SOURCE_PIXELS, 'fixture_color_records': RECORD_COUNT,
            'restore_tolerance_per_channel': RESTORE_TOLERANCE, 'maximum_rgb_error': maximum_error,
            'maximum_channel_error': max(maximum_error), 'rgb_channel_errors': rgb_channel_errors,
            'rgb_byte_exact': max(maximum_error) == 0,
            'rgb_within_tolerance': source_errors == 0,
            'comparison_scope': 'All source RGB against the known native fixture with tolerance2, plus exact guards; output alpha is not a preservation oracle.'})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--mode', type=int, choices=(0, 1, 2, 3), required=True)
    parser.add_argument('--slot', type=int, choices=(0, 1), required=True)
    parser.add_argument('--payload-json', type=Path, required=True,
                        help='JSON array of64 bytes or an object containing payload')
    parser.add_argument('--fixture', action='store_true', help='Unencoded known native background, mode0 only')
    parser.add_argument('--raining', action='store_true', help='Skip historical RGB oracle in rainy mode0')
    args = parser.parse_args()
    payload = json.loads(args.payload_json.read_text(encoding='utf-8-sig'))
    if isinstance(payload, dict):
        payload = payload['payload']
    report = verify(args.image, args.mode, payload, args.slot, fixture=args.fixture, raining=args.raining)
    print(json.dumps(report, indent=2))
    return 0 if report['exact'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
