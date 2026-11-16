"""Float32 numeric packet contract and malformed-input controls; CPU only."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import struct
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "runtime_packet_numeric", ROOT / "tools/runtime_packet_probe/numeric_payload.py")
CODEC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CODEC)
PACKAGE_NAME = "_runtime_packet_numeric_test"
PACKAGE = types.ModuleType(PACKAGE_NAME)
PACKAGE.__path__ = [str(ROOT / "tools/runtime_packet_probe")]
RUNTIME_SPEC = importlib.util.spec_from_file_location(
    PACKAGE_NAME + ".numeric_runtime", ROOT / "tools/runtime_packet_probe/numeric_runtime.py")
NUMERIC_RUNTIME = importlib.util.module_from_spec(RUNTIME_SPEC)
with patch.dict(sys.modules, {PACKAGE_NAME: PACKAGE, PACKAGE_NAME + ".numeric_payload": CODEC}):
    RUNTIME_SPEC.loader.exec_module(NUMERIC_RUNTIME)
STREAM_SPEC = importlib.util.spec_from_file_location(
    "runtime_packet_numeric_stream", ROOT / "tools/runtime_packet_probe/run_numeric_stream.py")
NUMERIC_STREAM = importlib.util.module_from_spec(STREAM_SPEC)
sys.path.insert(0, str(ROOT / "tools/runtime_packet_probe"))
try:
    STREAM_SPEC.loader.exec_module(NUMERIC_STREAM)
finally:
    sys.path.pop(0)


def scalar_bytes(values):
    """Independent reference keeps each scalar's explicit little-endian bytes."""
    return b"".join(struct.pack("<f", value) for value in values)


def wire_from_words(packet):
    """Extract word bytes with divmod, independently from production shifts."""
    result = bytearray()
    for page in packet["words"]:
        for word in page:
            high, remainder = divmod(word, 65536)
            middle, low = divmod(remainder, 256)
            result.extend((high, middle, low))
    return bytes(result)


def header_and_words(packet):
    return {key: copy.deepcopy(packet[key]) for key in
            ("scalar_count", "byte_count", "words_per_page", "pages", "padding_bytes", "words")}


def words_from_wire(wire):
    words = [int.from_bytes(wire[index:index + 3], "big") for index in range(0, len(wire), 3)]
    return [words[index:index + 8] for index in range(0, len(words), 8)]


def stream_fixture(start, count, generation, capacity):
    values = [((index * 73) % 2001 - 1000) / 37. for index in range(start, start + count)]
    expected = struct.pack("<4I", 0x504D4E31, count, 4 * count, generation) + scalar_bytes(values)
    expected += b"\x00" * (capacity - len(expected))
    return {"exact_equal": True, "results": [
        {"observed": [[value, value, value] for value in expected[index:index + 24]]}
        for index in range(0, capacity, 24)]}, expected[16:16 + count * 4]


class FakeClock:
    def __init__(self):
        self.now = 0.

    def clock(self):
        self.now += .001
        return self.now


class FakePost:
    def __init__(self):
        self.calls = []
        self.failure_index = None
        self.failure = False

    def SetParameter(self, name, parameter, values):
        self.calls.append((name, parameter, values))
        if len(self.calls) == self.failure_index:
            if isinstance(self.failure, Exception):
                raise self.failure
            return False
        return True


class FakeAggregation:
    def __init__(self, pages=64):
        self.config = {"pages": pages,
                       "producer_names": ["numeric_page_%03d" % index for index in range(pages)]}
        self.ready = True
        self.enabled = True
        self.error = None
        self.post = FakePost()
        self.words = []

    def snapshot(self):
        return {"aggregate": {"pages": self.config["pages"], "words": self.words,
                              "words_per_page": 8},
                "ready": self.ready, "enabled": self.enabled, "error": self.error}

    def _failed(self, error):
        self.error = str(error)
        self.ready = False
        self.enabled = False


class RuntimePacketNumericTests(unittest.TestCase):
    def assert_roundtrip(self, values, capacity_pages):
        packet = CODEC.encode(values, capacity_pages)
        expected = scalar_bytes(values)
        decoded = CODEC.decode(packet)
        self.assertEqual(expected, packet["wire_bytes"])
        self.assertEqual(expected, scalar_bytes(packet["values"]))
        self.assertEqual(expected, scalar_bytes(decoded))
        self.assertEqual(len(values), packet["scalar_count"])
        self.assertEqual(4 * len(values), packet["byte_count"])
        self.assertEqual(8, packet["words_per_page"])
        self.assertEqual((len(expected) + 23) // 24, packet["pages"])
        self.assertEqual(24 * packet["pages"] - len(expected), packet["padding_bytes"])
        self.assertEqual(expected + b"\x00" * packet["padding_bytes"], wire_from_words(packet))
        self.assertEqual([8] * packet["pages"], [len(page) for page in packet["words"]])
        self.assertEqual(expected, scalar_bytes(CODEC.decode(header_and_words(packet))))
        return packet

    def test_signed_fractional_values_and_word_byte_order(self):
        packet = self.assert_roundtrip([1., -2.5, .125, -123.75, 0., -0., 42], 2)
        # float32(1) bytes are 00 00 80 3f: word zero must be 0x000080.
        self.assertEqual(0x000080, packet["words"][0][0])
        decoded = CODEC.decode(packet)
        self.assertEqual(-1., math.copysign(1., decoded[5]))
        self.assertEqual(1., math.copysign(1., decoded[4]))
        self.assertIsInstance(decoded[6], float)

    def test_float32_rounding_boundaries_subnormals_and_signed_underflow(self):
        values = [1. + 2. ** -24, 1. + 3. * 2. ** -24,
                  (1 << 24) + 1, (1 << 24) + 3,
                  2. ** -149, -(2. ** -149), -(2. ** -150),
                  struct.unpack("<f", b"\xff\xff\x7f\x7f")[0]]
        packet = self.assert_roundtrip(values, 2)
        decoded = CODEC.decode(packet)
        self.assertEqual([1., 1. + 2. ** -22, float(1 << 24), float((1 << 24) + 4)], decoded[:4])
        self.assertEqual(b"\x00\x00\x00\x80", struct.pack("<f", decoded[6]))
        self.assertTrue(all(math.isfinite(value) for value in decoded))

    def test_near_maximum_values_follow_struct_rounding_and_overflow_is_rejected(self):
        largest_roundable = math.nextafter(CODEC.FLOAT32_OVERFLOW, 0.)
        self.assert_roundtrip([largest_roundable, -largest_roundable], 1)
        for value in (CODEC.FLOAT32_OVERFLOW, -CODEC.FLOAT32_OVERFLOW,
                      int(CODEC.FLOAT32_OVERFLOW) - 1, -int(CODEC.FLOAT32_OVERFLOW) + 1):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "overflow"):
                CODEC.encode([value], 1)

    def test_lengths_change_without_stale_words_or_implicit_capacity_padding(self):
        for count in (0, 1, 5, 6, 7, 12, 11, 2, 0, 7):
            with self.subTest(count=count):
                packet = self.assert_roundtrip([(-1.) ** index * (index + .25)
                                               for index in range(count)], 2)
                self.assertEqual((count + 5) // 6, len(packet["words"]))
        self.assert_roundtrip([], 0)
        self.assert_roundtrip((.5, -.5), 1)
        with self.assertRaisesRegex(ValueError, "capacity_pages"):
            CODEC.encode([0.] * 13, 2)
        with self.assertRaisesRegex(ValueError, "capacity_pages"):
            CODEC.encode([0.], 0)

    def test_encode_rejects_invalid_shapes_and_values_without_mutating_input(self):
        invalid = (None, 1, "1", b"1", {}, {1, 2}, iter([1.]),
                   [[1.]], [1., [2.]], [True], [False], [None], ["1"], [1j],
                   [float("nan")], [float("inf")], [-float("inf")],
                   [2. ** 128], [-(2. ** 128)], [10 ** 1000])
        for values in invalid:
            with self.subTest(values=repr(values)), self.assertRaises(ValueError):
                CODEC.encode(values, 2)
        values = [1., 2., object()]
        original = list(values)
        with self.assertRaises(ValueError):
            CODEC.encode(values, 1)
        self.assertEqual(original, values)
        for capacity in (None, True, False, -1, .5, 1., "2", [], {}):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                CODEC.encode([], capacity)

    def test_decode_rejects_missing_and_inconsistent_header_metadata(self):
        original = header_and_words(CODEC.encode([1., -2.5, .125, 4., 5., 6., 7.], 2))
        for name in ("scalar_count", "byte_count", "words_per_page", "pages", "padding_bytes", "words"):
            packet = copy.deepcopy(original)
            del packet[name]
            with self.subTest(missing=name), self.assertRaises(ValueError):
                CODEC.decode(packet)
        for name in ("scalar_count", "byte_count", "words_per_page", "pages", "padding_bytes"):
            for value in (None, True, False, -1, 1., "1", [], {}):
                packet = copy.deepcopy(original)
                packet[name] = value
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    CODEC.decode(packet)
        for name, value in (("scalar_count", 6), ("byte_count", 27), ("words_per_page", 12),
                            ("pages", 3), ("padding_bytes", 19)):
            packet = copy.deepcopy(original)
            packet[name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                CODEC.decode(packet)
        for invalid in (None, [], "packet"):
            with self.subTest(packet=invalid), self.assertRaises(ValueError):
                CODEC.decode(invalid)

    def test_decode_rejects_short_long_malformed_word_pages_and_nonzero_padding(self):
        original = header_and_words(CODEC.encode([-.5] * 7, 2))
        malformed_words = (None, {}, original["words"][:1], original["words"] + [[0] * 8],
                           [None, [0] * 8], [[0] * 7, [0] * 8], [[0] * 9, [0] * 8])
        for words in malformed_words:
            packet = copy.deepcopy(original)
            packet["words"] = words
            with self.subTest(words=words), self.assertRaises(ValueError):
                CODEC.decode(packet)
        for word in (True, -1, 1 << 24, 0., "0", None, []):
            packet = copy.deepcopy(original)
            packet["words"][1][7] = word
            with self.subTest(word=word), self.assertRaises(ValueError):
                CODEC.decode(packet)
        packet = copy.deepcopy(original)
        packet["words"][-1][-1] = 1
        with self.assertRaisesRegex(ValueError, "padding"):
            CODEC.decode(packet)
        empty = header_and_words(CODEC.encode([], 2))
        empty.update(pages=1, padding_bytes=24, words=[[0] * 8])
        with self.assertRaisesRegex(ValueError, "minimum page count"):
            CODEC.decode(empty)

    def test_decode_rejects_nonfinite_wire_values_and_inconsistent_optional_copies(self):
        for bits in (b"\x00\x00\x80\x7f", b"\x00\x00\x80\xff", b"\x00\x00\xc0\x7f"):
            packet = header_and_words(CODEC.encode([0.], 1))
            packet["words"][0][0] = bits[0] * 65536 + bits[1] * 256 + bits[2]
            packet["words"][0][1] = bits[3] * 65536
            with self.subTest(bits=bits), self.assertRaisesRegex(ValueError, "finite"):
                CODEC.decode(packet)
        for key, value in (("values", []), ("values", [1.]), ("wire_bytes", b""),
                           ("wire_bytes", [0, 0, 0, 128]), ("values", [0.])):
            packet = CODEC.encode([-0.], 1)
            packet[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                CODEC.decode(packet)

    def test_header_words_survive_json_and_decode_rejects_stale_extra_data(self):
        packet = self.assert_roundtrip([-.25, 2.75, 3.125, 4.5, 5.625], 3)
        encoded = json.loads(json.dumps(header_and_words(packet)))
        self.assertEqual(scalar_bytes(packet["values"]), scalar_bytes(CODEC.decode(encoded)))
        # A prior longer message cannot be silently interpreted using a shorter header.
        shorter = header_and_words(CODEC.encode([-.25], 1))
        shorter["words"] = packet["words"]
        with self.assertRaisesRegex(ValueError, "padding"):
            CODEC.decode(shorter)


class RuntimePacketNumericIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.clock_patch = patch.object(NUMERIC_RUNTIME, "time", FakeClock())
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)

    def test_length_changes_upload_complete_bits_header_generation_and_clear_unused_capacity(self):
        aggregation = FakeAggregation()
        cases = (-0., -.5, .125, 2. ** -149, -(2. ** -150),
                 1. + 2. ** -24, (1 << 24) + 1, -123.75)
        for generation, count in enumerate((0, 1, 5, 6, 7, 380, 3, 0, 7)):
            with self.subTest(count=count, generation=generation):
                values = [cases[index % len(cases)] for index in range(count)]
                aggregation.post.calls = []
                result = NUMERIC_RUNTIME.write_numbers(aggregation, values, generation)
                header = result["numeric_header"]
                wire = wire_from_words({"words": aggregation.words})
                decoded = NUMERIC_RUNTIME.decode_numbers(aggregation.words)
                self.assertEqual((NUMERIC_RUNTIME.MAGIC, count, count * 4, generation),
                                 struct.unpack("<4I", wire[:16]))
                self.assertEqual(scalar_bytes(values), wire[16:16 + count * 4])
                self.assertEqual(b"\x00" * (1536 - 16 - count * 4), wire[16 + count * 4:])
                self.assertEqual(scalar_bytes(values), scalar_bytes(decoded["values"]))
                self.assertEqual(scalar_bytes(values), decoded["wire_bytes"])
                self.assertEqual((count, count * 4, generation),
                                 (decoded["scalar_count"], decoded["byte_count"], decoded["generation"]))
                self.assertEqual(64, len(aggregation.words))
                self.assertEqual([8] * 64, [len(row) for row in aggregation.words])
                self.assertEqual(128, len(aggregation.post.calls))
                self.assertEqual(128, header["sdk_payload_calls"])
                self.assertEqual(1536, header["capacity_bytes"])
                self.assertEqual(16, header["header_bytes"])
                self.assertEqual(1536 - 16 - count * 4, header["cleared_bytes"])
                self.assertAlmostEqual(1., header["generation_ms"])
                self.assertAlmostEqual(1., header["upload_ms"])
                for page, name in enumerate(aggregation.config["producer_names"]):
                    for packet_index in (0, 1):
                        call_name, parameter, uploaded = aggregation.post.calls[page * 2 + packet_index]
                        expected_words = aggregation.words[page][packet_index * 4:packet_index * 4 + 4]
                        self.assertEqual((name, "packet%d" % packet_index), (call_name, parameter))
                        self.assertEqual(expected_words, [int(value * (1 << 24)) for value in uploaded])

    def test_header_reserves_sixteen_bytes_and_generation_accepts_uint32_maximum(self):
        aggregation = FakeAggregation(pages=1)
        result = NUMERIC_RUNTIME.write_numbers(aggregation, [-0., .25], 0xffffffff)
        self.assertEqual(0, result["numeric_header"]["cleared_bytes"])
        decoded = NUMERIC_RUNTIME.decode_numbers(aggregation.words)
        self.assertEqual(0xffffffff, decoded["generation"])
        self.assertEqual(scalar_bytes([-0., .25]), decoded["wire_bytes"])
        aggregation.post.calls = []
        with self.assertRaisesRegex(ValueError, "header.*capacity"):
            NUMERIC_RUNTIME.write_numbers(aggregation, [1., 2., 3.])
        self.assertEqual([], aggregation.post.calls)

    def test_invalid_payload_generation_and_capacity_fail_before_any_sdk_call(self):
        for values in (None, [[1.]], [1., None], [True], [float("nan")],
                       [float("inf")], [2. ** 128], [0.] * 381, [0.] * 385):
            aggregation = FakeAggregation()
            with self.subTest(values=repr(values)), self.assertRaises(ValueError):
                NUMERIC_RUNTIME.write_numbers(aggregation, values)
            self.assertEqual([], aggregation.post.calls)
            self.assertEqual([], aggregation.words)
            self.assertFalse(hasattr(aggregation, "numeric_header"))
        for generation in (-1, 1 << 32, True, None, 1., "1"):
            aggregation = FakeAggregation()
            with self.subTest(generation=generation), self.assertRaises(ValueError):
                NUMERIC_RUNTIME.write_numbers(aggregation, [1.], generation)
            self.assertEqual([], aggregation.post.calls)

    def test_unready_disabled_or_failed_atlas_cannot_upload(self):
        for field, value in (("ready", False), ("enabled", False),
                             ("enabled", None), ("error", "prior upload failed")):
            aggregation = FakeAggregation()
            setattr(aggregation, field, value)
            with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                NUMERIC_RUNTIME.write_numbers(aggregation, [1.])
            self.assertEqual([], aggregation.post.calls)

    def test_failed_sdk_upload_raises_and_does_not_commit_success_header_or_words(self):
        for failure_index, failure in ((1, False), (2, False), (95, RuntimeError("injected failure"))):
            aggregation = FakeAggregation()
            NUMERIC_RUNTIME.write_numbers(aggregation, [1., -2.5], generation=7)
            previous_words = copy.deepcopy(aggregation.words)
            previous_header = copy.deepcopy(aggregation.numeric_header)
            aggregation.post.calls = []
            aggregation.post.failure_index = failure_index
            aggregation.post.failure = failure
            with self.subTest(failure_index=failure_index), self.assertRaises(RuntimeError):
                NUMERIC_RUNTIME.write_numbers(aggregation, [3., 4., 5.], generation=8)
            self.assertEqual(failure_index, len(aggregation.post.calls))
            self.assertEqual(previous_words, aggregation.words)
            self.assertEqual(previous_header, aggregation.numeric_header)
            self.assertFalse(aggregation.ready)
            self.assertFalse(aggregation.enabled)
            self.assertIsNotNone(aggregation.error)
            with self.assertRaisesRegex(RuntimeError, "ready enabled"):
                NUMERIC_RUNTIME.write_numbers(aggregation, [6.], generation=9)
            self.assertEqual(failure_index, len(aggregation.post.calls))

    def test_runtime_decoder_rejects_malformed_word_containers_without_truncation(self):
        aggregation = FakeAggregation()
        NUMERIC_RUNTIME.write_numbers(aggregation, [1., -2.5], generation=12)
        original = aggregation.words
        for words in (None, [], {}, [[0] * 7], [[0] * 9],
                      [original[0][:4], original[0][4:]] + original[1:]):
            with self.subTest(words=repr(words)[:100]), self.assertRaises(ValueError):
                NUMERIC_RUNTIME.decode_numbers(words)
        for invalid_word in (True, -1, 1 << 24, 0., "0", None):
            words = copy.deepcopy(original)
            words[0][0] = invalid_word
            with self.subTest(word=invalid_word), self.assertRaises(ValueError):
                NUMERIC_RUNTIME.decode_numbers(words)

    def test_runtime_decoder_rejects_invalid_header_nonfinite_scalars_and_stale_tail(self):
        aggregation = FakeAggregation()
        NUMERIC_RUNTIME.write_numbers(aggregation, [0.], generation=2)
        wire = wire_from_words({"words": aggregation.words})
        invalid_headers = ((0, 1, 4, 2), (NUMERIC_RUNTIME.MAGIC, 2, 4, 2),
                           (NUMERIC_RUNTIME.MAGIC, 381, 1524, 2))
        for header in invalid_headers:
            words = words_from_wire(struct.pack("<4I", *header) + wire[16:])
            with self.subTest(header=header), self.assertRaisesRegex(ValueError, "header"):
                NUMERIC_RUNTIME.decode_numbers(words)
        for bits in (b"\x00\x00\x80\x7f", b"\x00\x00\x80\xff", b"\x00\x00\xc0\x7f"):
            words = words_from_wire(wire[:16] + bits + wire[20:])
            with self.subTest(bits=bits), self.assertRaisesRegex(ValueError, "nonfinite"):
                NUMERIC_RUNTIME.decode_numbers(words)
        words = words_from_wire(wire[:-1] + b"\x01")
        with self.assertRaisesRegex(ValueError, "not cleared"):
            NUMERIC_RUNTIME.decode_numbers(words)


class RuntimePacketNumericStreamTests(unittest.TestCase):
    def test_seventeen_chunks_reassemble_one_hundred_thousand_independent_float32_values(self):
        capacity, resident_scalars, total = 24576, 6140, 100000
        observed_stream, counts = [], []
        checked_bytes = 0
        for index, start in enumerate(range(0, total, resident_scalars)):
            count = min(resident_scalars, total - start)
            verification, expected_data = stream_fixture(start, count, index + 100, capacity)
            # These bogus CPU expected fields must never supply the independent oracle.
            verification["results"][0]["expected"] = [255] * 24
            observed = NUMERIC_STREAM.verify_chunk(verification, start, count, index + 100, capacity)
            self.assertEqual(expected_data, observed)
            observed_stream.append(observed)
            counts.append(count)
            checked_bytes += capacity
        self.assertEqual([6140] * 16 + [1760], counts)
        self.assertEqual(17, len(observed_stream))
        self.assertEqual(417792, checked_bytes)
        independent = scalar_bytes([((index * 73) % 2001 - 1000) / 37. for index in range(total)])
        self.assertEqual(400000, len(independent))
        self.assertEqual(independent, b"".join(observed_stream))
        self.assertGreater(total, resident_scalars)

    def test_chunk_rejects_stale_start_generation_missing_bytes_and_nonzero_tail(self):
        start, count, generation, capacity = 6140, 7, 101, 24576
        verification, unused = stream_fixture(start, count, generation, capacity)
        for changed_start, changed_count, changed_generation in (
                (0, count, generation), (start, count + 1, generation), (start, count, generation + 1)):
            with self.subTest(start=changed_start, count=changed_count, generation=changed_generation):
                with self.assertRaisesRegex(ValueError, "independent"):
                    NUMERIC_STREAM.verify_chunk(verification, changed_start, changed_count,
                                                changed_generation, capacity)
        missing = copy.deepcopy(verification)
        missing["results"].pop()
        with self.assertRaisesRegex(ValueError, "independent"):
            NUMERIC_STREAM.verify_chunk(missing, start, count, generation, capacity)
        tail = copy.deepcopy(verification)
        tail["results"][-1]["observed"][-1] = [1, 1, 1]
        with self.assertRaisesRegex(ValueError, "independent"):
            NUMERIC_STREAM.verify_chunk(tail, start, count, generation, capacity)
        with self.assertRaisesRegex(ValueError, "capacity"):
            NUMERIC_STREAM.verify_chunk(verification, start, count, generation, 16)

    def test_chunk_requires_exact_grayscale_observations(self):
        verification, unused = stream_fixture(0, 5, 100, 48)
        verification["exact_equal"] = False
        with self.assertRaisesRegex(ValueError, "not exact"):
            NUMERIC_STREAM.verify_chunk(verification, 0, 5, 100, 48)
        verification["exact_equal"] = True
        verification["results"][0]["observed"][0] = [49, 50, 49]
        with self.assertRaisesRegex(ValueError, "grayscale"):
            NUMERIC_STREAM.verify_chunk(verification, 0, 5, 100, 48)


if __name__ == "__main__":
    unittest.main()
