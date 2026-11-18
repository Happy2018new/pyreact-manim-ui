"""Independent bit/address checks for the scene codec's numerical boundaries."""

import importlib.util
from pathlib import Path
import random
import unittest


SPEC = importlib.util.spec_from_file_location('scene_codec_under_test',
    Path(__file__).resolve().parents[1] / 'codec.py')
CODEC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CODEC)


class SceneCodecTests(unittest.TestCase):
    def test_exhaustive_rgb_channel_transport_and_error(self):
        for bits, maximum in ((1, 1), (2, 2)):
            worst = 0
            for original in range(256):
                for payload in range(1 << bits):
                    encoded = CODEC.encode_rgb_channel(original, payload, bits)
                    decoded, restored = CODEC.decode_rgb_channel(encoded, bits)
                    self.assertEqual(decoded, payload)
                    self.assertTrue(0 <= encoded <= 255)
                    worst = max(worst, abs(restored - original))
            self.assertEqual(worst, maximum)

    def test_symbol_stream_against_independent_bit_list(self):
        for size in (0, 1, 2, 3, 12, 24, 257, 3072):
            payload = bytearray(CODEC.payload_oracle(index, 113) for index in range(size))
            raw_bits = [(value >> shift) & 1 for value in payload for shift in range(8)]
            for bits in (1, 2):
                width = 3 * bits
                expected = [sum(value << shift for shift, value in enumerate(raw_bits[start:start + width]))
                            for start in range(0, len(raw_bits), width)]
                symbols = CODEC.payload_to_symbols(payload, bits)
                self.assertEqual(list(symbols), expected)
                self.assertEqual(CODEC.symbols_to_payload(symbols, bits, size), payload)

    def test_alpha_masks_at_byte_boundaries_and_four_exceptions(self):
        payload = bytearray(range(24))
        for base in (0, 127, 255):
            for positions in ((), (0,), (31,), (0, 7, 8, 31), (8, 15, 16, 23)):
                alpha = bytearray([base] * 32)
                for rank, position in enumerate(positions):
                    alpha[position] = (base + rank + 1) % 256
                encoded = CODEC.encode_alpha_block(alpha, payload, base)
                self.assertFalse(encoded['overflow'])
                decoded = CODEC.decode_alpha_block(encoded['encoded'], base)
                self.assertEqual(decoded['alpha'], alpha)
                self.assertEqual(decoded['payload'], payload)
                expected_mask = sum(1 << position for position in positions)
                self.assertEqual(encoded['mask'], expected_mask)
                self.assertEqual(list(encoded['encoded'][:4]),
                                 [(expected_mask >> (8 * index)) & 255 for index in range(4)])

    def test_overflow_rejected_without_silent_truncation(self):
        alpha = bytearray([255] * 32)
        alpha[:5] = bytearray(range(5))
        result = CODEC.encode_alpha_block(alpha, bytearray(range(24)))
        self.assertTrue(result['overflow'])
        self.assertEqual(result['exception_count'], 5)
        self.assertIsNone(result['encoded'])
        invalid = bytearray(32)
        invalid[0] = 31
        with self.assertRaises(ValueError):
            CODEC.decode_alpha_block(invalid)

    def test_combined_geometry_transport_and_alpha_roundtrip(self):
        rng = random.Random(91823)
        for bits in (1, 2):
            for unused in range(32):
                rgb = [tuple(rng.randrange(256) for channel in range(3)) for pixel in range(32)]
                alpha = bytearray([255] * 32)
                for position in rng.sample(range(32), 4):
                    alpha[position] = rng.randrange(255)
                payload = bytearray(rng.randrange(256) for index in range(12 * bits))
                result = CODEC.encode_combined_block(rgb, alpha, payload, bits)
                self.assertFalse(result['overflow'])
                decoded = CODEC.decode_alpha_block(result['encoded'])
                self.assertEqual(decoded['alpha'], alpha)
                self.assertEqual(decoded['payload'][:12 * bits], payload)
                self.assertEqual(result['transported_payload'], payload)
                self.assertLessEqual(max(abs(a - b) for before, after in zip(rgb, result['restored_rgb'])
                                         for a, b in zip(before, after)), bits)

    def test_precision_and_capacity_are_conditional(self):
        samples = [1.0] * 64 + [0.5] * 32 + [1.0]
        stats = CODEC.alpha_distribution(samples)
        self.assertEqual(stats['sample_count'], 97)
        self.assertEqual(stats['complete_blocks'], 3)
        self.assertEqual(stats['incomplete_pixels'], 1)
        self.assertEqual(stats['valid_blocks'], 2)
        self.assertEqual(stats['overflow_blocks'], 1)
        self.assertEqual(stats['conditional_alpha_payload_bytes'], 48)
        self.assertEqual(stats['off_grid_count'], 32)
        self.assertFalse(stats['unorm8_exact_at_tolerance'])
        for sample in (-0.1, 1.1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                CODEC.alpha_distribution([sample])

    def test_shader_fixture_oracle_covers_all_rgb_codes_and_overflow(self):
        for bits in (1, 2):
            for mode, overflow in ((0, False), (1, False), (2, True), (3, True)):
                for block in range(8):
                    start = block * 32
                    expected_payload = bytearray(CODEC.payload_oracle(index, 113)
                        for index in range(block * 12 * bits, (block + 1) * 12 * bits))
                    pixels = [CODEC.fixture_rgba(index, bits, mode, 255, 113)
                              for index in range(start, start + 32)]
                    symbols = []
                    for pixel in pixels:
                        channel_payload = [CODEC.decode_rgb_channel(value, bits)[0] for value in pixel[:3]]
                        symbols.append(sum(value << (channel * bits)
                                           for channel, value in enumerate(channel_payload)))
                    recovered = CODEC.symbols_to_payload(symbols, bits, 12 * bits)
                    self.assertEqual(recovered, expected_payload)
                    encoded = CODEC.encode_alpha_block([pixel[3] for pixel in pixels], recovered)
                    self.assertEqual(encoded['overflow'], overflow)

    def test_input_rejection_and_payload_padding(self):
        for bits in (0, 3, 8):
            with self.assertRaises(ValueError):
                CODEC.payload_to_symbols([0], bits)
        with self.assertRaises(ValueError):
            CODEC.encode_alpha_block([255] * 31)
        with self.assertRaises(ValueError):
            CODEC.encode_alpha_block([255] * 32, [0] * 25)
        with self.assertRaises(ValueError):
            CODEC.symbols_to_payload([64], 2)
        decoded = CODEC.decode_alpha_block(CODEC.encode_alpha_block([255] * 32, [173])['encoded'])
        self.assertEqual(list(decoded['payload']), [173] + [0] * 23)


if __name__ == '__main__':
    unittest.main()
