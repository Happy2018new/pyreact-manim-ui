"""Offline numerical and false-positive controls for the runtime packet oracle."""
import importlib.util
from collections import deque
import json
from pathlib import Path
import struct
import tempfile
import unittest

from PIL import Image, ImageDraw, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "runtime_packet_verify", ROOT / "tools/runtime_packet_probe/verify_capture.py")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def draw_row(image, values, rect):
    """Fixture encoder deliberately uses divmod rather than verifier helpers."""
    levels = []
    for value in values:
        high, remainder = divmod(value, 65536)
        middle, low = divmod(remainder, 256)
        levels.extend((high, middle, low))
    x, y, width, height = rect
    draw = ImageDraw.Draw(image)
    for column, level in enumerate(levels):
        left = x + column * width / len(levels)
        right = x + (column + 1) * width / len(levels)
        draw.rectangle((left, y, right - 1, y + height - 1), fill=(level, level, level, 255))


def record_fixture():
    receipt = {"screen": [200, 100], "count": 2, "records": [
        {"index": 0, "values": [0, 1, (1 << 23) - 1], "rect": [10, 10, 180, 20]},
        {"index": 1, "values": [1 << 23, (1 << 23) + 1, (1 << 24) - 1],
         "rect": [10, 40, 180, 20]}]}
    # Unequal X/Y scaling catches accidental use of a single DPI ratio.
    image = Image.new("RGBA", (400, 300), (31, 57, 89, 255))
    for row in receipt["records"]:
        x, y, width, height = row["rect"]
        draw_row(image, row["values"], (x * 2, y * 3, width * 2, height * 3))
    return receipt, image


def aggregate_fixture(query=None, words_per_page=None):
    count = 12 if words_per_page is None else words_per_page
    words = [[((20 + page * 60 + word) * 65536 + (100 + word * 3) * 256 +
               220 - page * 10 - word) for word in range(count)] for page in range(3)]
    aggregate = {"pages": 3, "words": words, "display_rect_norm": [.05, .05, .9, .9]}
    if words_per_page is not None:
        aggregate["words_per_page"] = words_per_page
    if query is not None:
        aggregate["query"] = query
    # Create the display with independent list rotations, not oracle indices.
    _, row_shift, word_shift, byte_shift = query or [3, 0, 0, 0]
    rows = deque(words)
    rows.rotate(-int(row_shift))
    image = Image.new("RGBA", (800, 400), (71, 35, 91, 255))
    for page, source_row in enumerate(rows):
        row = deque(source_row)
        row.rotate(-int(word_shift))
        display_words = []
        for word in row:
            high, remainder = divmod(word, 65536)
            middle, low = divmod(remainder, 256)
            channels = deque((high, middle, low))
            channels.rotate(-int(byte_shift))
            display_words.append(channels[0] * 65536 + channels[1] * 256 + channels[2])
        draw_row(image, display_words, (40, 20 + 120 * page, 720, 120))
    return {"aggregate": aggregate}, image


class RuntimePacketProbeTests(unittest.TestCase):
    def test_uint24_boundaries_and_float32_carrier_precision(self):
        cases = [(0, (0, 0, 0)), (1, (0, 0, 1)),
                 ((1 << 23) - 1, (127, 255, 255)), (1 << 23, (128, 0, 0)),
                 ((1 << 23) + 1, (128, 0, 1)), ((1 << 24) - 1, (255, 255, 255))]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(expected, VERIFY.word_bytes(value))
                packed_float = struct.unpack("f", struct.pack("f", value / float(1 << 24)))[0]
                self.assertEqual(value, int(packed_float * (1 << 24)))
        for invalid in (-1, 1 << 24, 1.0, True, "1"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                VERIFY.word_bytes(invalid)

    def test_all_boundary_cells_pass_with_independent_physical_scales(self):
        receipt, image = record_fixture()
        result = VERIFY.verify_image(receipt, image)
        self.assertTrue(result["passed"])
        self.assertTrue(result["exact_equal"])
        self.assertEqual((2, 3), result["logical_to_physical_scale"])
        self.assertEqual(18, result["checked_cells"])
        self.assertEqual(0, result["max_error"])
        self.assertEqual([3] * 9, result["results"][0]["sample_widths"])

    def test_tolerance_checks_every_rgb_channel_in_the_entire_inner_patch(self):
        receipt, image = record_fixture()
        # First cell is zero; its physical center is (40,60).
        image.putpixel((39, 59), (0, 2, 0, 255))
        within = VERIFY.verify_image(receipt, image)
        self.assertTrue(within["passed"])
        self.assertFalse(within["exact_equal"])
        image.putpixel((39, 59), (0, 3, 0, 255))
        failed = VERIFY.verify_image(receipt, image)
        self.assertFalse(failed["passed"])
        self.assertEqual(1, failed["failed_cells"])
        self.assertEqual(3, failed["max_error"])

    def test_transparent_matching_rgb_and_solid_backgrounds_fail(self):
        receipt, correct = record_fixture()
        transparent = correct.copy()
        transparent.putalpha(0)
        for image in (transparent, Image.new("RGB", correct.size, "black"),
                      Image.new("RGB", correct.size, "white"),
                      Image.new("RGB", correct.size, (127, 127, 127))):
            with self.subTest(mode=image.mode, pixel=image.getpixel((0, 0))):
                result = VERIFY.verify_image(receipt, image)
                self.assertFalse(result["passed"])
                self.assertGreater(result["failed_cells"], 0)
        for row in receipt["records"]:
            row["values"] = [0, 0, 0]
        result = VERIFY.verify_image(receipt, Image.new("RGB", correct.size, "black"))
        self.assertEqual(0, result["failed_cells"])
        self.assertFalse(result["passed"])
        self.assertIn("expected_payload_cannot_distinguish_a_uniform_background",
                      result["failure_reasons"])

    def test_vertical_flip_requires_explicit_option_and_does_not_search(self):
        receipt, image = record_fixture()
        flipped = ImageOps.flip(image)
        self.assertFalse(VERIFY.verify_image(receipt, flipped)["passed"])
        self.assertTrue(VERIFY.verify_image(receipt, flipped, flip_y=True)["passed"])
        shifted = Image.new("RGBA", image.size, (31, 57, 89, 255))
        shifted.paste(image, (40, 0))
        self.assertFalse(VERIFY.verify_image(receipt, shifted)["passed"])

    def test_aggregate_visits_all_pages_words_and_high_middle_low_bytes(self):
        words = [[((page + 1) * 919921 + word * 129979) & 0xffffff
                  for word in range(12)] for page in range(3)]
        receipt = {"aggregate": {"pages": 3, "words": words,
                                  "display_rect_norm": [.05, .05, .9, .9]}}
        image = Image.new("RGBA", (800, 400), (71, 35, 91, 255))
        for page, row in enumerate(words):
            draw_row(image, row, (40, 20 + 120 * page, 720, 120))
        result = VERIFY.verify_image(receipt, image)
        self.assertTrue(result["passed"])
        self.assertEqual(108, result["checked_cells"])
        self.assertEqual([0, 1, 2], [row["index"] for row in result["results"]])
        # A last-page/last-word fault must not disappear in a passing subset.
        image.putpixel((750, 320), (255, 0, 255, 255))
        result = VERIFY.verify_image(receipt, image)
        self.assertFalse(result["passed"])
        self.assertEqual([35], result["results"][2]["failed"])

    def test_aggregate_query_applies_each_shift_and_cyclic_signed_wrap(self):
        queries = ([3, 1, 0, 0], [3, 0, 2, 0], [3, 0, 0, 1],
                   [3., 1., 2., 1.], [3, -1, -2, -1], [3, 7, 26, 4])
        for query in queries:
            with self.subTest(query=query):
                receipt, image = aggregate_fixture(query)
                result = VERIFY.verify_image(receipt, image)
                self.assertTrue(result["exact_equal"])
                self.assertEqual(108, result["checked_cells"])
                self.assertEqual(tuple(query), result["aggregate_query"])
        receipt, image = aggregate_fixture([3, 1, 2, 1])
        result = VERIFY.verify_image(receipt, image)
        self.assertEqual([106, 208, 82], result["results"][0]["expected"][:3])
        self.assertEqual(21, result["results"][2]["expected"][-1])
        # Coordinates still denote display rows, regardless of source row shift.
        self.assertEqual([50, 80], result["results"][0]["centers"][0])

    def test_eight_word_aggregate_checks_all_cells_and_last_word_corruption(self):
        receipt, image = aggregate_fixture(words_per_page=8)
        result = VERIFY.verify_image(receipt, image)
        self.assertTrue(result["exact_equal"])
        self.assertEqual(72, result["checked_cells"])
        self.assertEqual([24] * 3, [len(row["expected"]) for row in result["results"]])
        self.assertEqual([0, 1, 2], [row["index"] for row in result["results"]])
        self.assertEqual([55, 80], result["results"][0]["centers"][0])
        self.assertEqual([745, 320], result["results"][-1]["centers"][-1])
        image.putpixel((745, 320), (255, 0, 255, 255))
        failed = VERIFY.verify_image(receipt, image)
        self.assertFalse(failed["passed"])
        self.assertEqual(72, failed["checked_cells"])
        self.assertEqual(1, failed["failed_cells"])
        self.assertEqual([23], failed["results"][2]["failed"])

    def test_eight_word_aggregate_queries_wrap_words_modulo_eight_and_bytes_modulo_three(self):
        identity, original = aggregate_fixture(words_per_page=8)
        queries = ([3, 1, 0, 0], [3, 0, 2, 0], [3, 0, 0, 1],
                   [3., 1., 2., 1.], [3, -1, -2, -1], [3, 7, 18, 4],
                   [3, 0, 8, 3])
        for query in queries:
            with self.subTest(query=query):
                receipt, shifted = aggregate_fixture(query, words_per_page=8)
                result = VERIFY.verify_image(receipt, shifted)
                self.assertTrue(result["exact_equal"])
                self.assertEqual(72, result["checked_cells"])
                self.assertEqual(tuple(query), result["aggregate_query"])
                if query == [3, 0, 8, 3]:
                    self.assertTrue(VERIFY.verify_image(receipt, original)["exact_equal"])
                else:
                    self.assertFalse(VERIFY.verify_image(receipt, original)["passed"])
                    self.assertFalse(VERIFY.verify_image(identity, shifted)["passed"])
        receipt, image = aggregate_fixture([3, 1, 2, 1], words_per_page=8)
        result = VERIFY.verify_image(receipt, image)
        self.assertEqual([106, 208, 82], result["results"][0]["expected"][:3])
        self.assertEqual(21, result["results"][2]["expected"][-1])
        self.assertEqual([55, 80], result["results"][0]["centers"][0])

    def test_explicit_twelve_word_aggregate_remains_supported(self):
        receipt, image = aggregate_fixture(words_per_page=12)
        result = VERIFY.verify_image(receipt, image)
        self.assertTrue(result["exact_equal"])
        self.assertEqual(108, result["checked_cells"])

    def test_eight_word_query_float32_bounds_follow_twenty_four_columns(self):
        limit = 1 << 24
        valid = ([3, 0, limit - 8, 0], [3, 0, -limit + 9, 0],
                 [3, 0, 0, limit - 24], [3, 0, 0, -limit + 4])
        for query in valid:
            with self.subTest(query=query):
                receipt, image = aggregate_fixture(query, words_per_page=8)
                self.assertTrue(VERIFY.verify_image(receipt, image)["exact_equal"])
        receipt, image = aggregate_fixture(words_per_page=8)
        invalid = ([3, 0, limit - 7, 0], [3, 0, -limit + 8, 0],
                   [3, 0, 0, limit - 23], [3, 0, 0, -limit + 3])
        for query in invalid:
            with self.subTest(query=query), self.assertRaisesRegex(
                    ValueError, "aggregate query shifts"):
                receipt["aggregate"]["query"] = query
                VERIFY.verify_image(receipt, image)

    def test_invalid_aggregate_words_per_page_and_mismatched_rows_are_rejected(self):
        receipt, image = aggregate_fixture(words_per_page=8)
        for invalid in (None, True, False, 0, -8, 1, 4, 9, 13, 8., "8", [], {}):
            with self.subTest(words_per_page=invalid), self.assertRaisesRegex(
                    ValueError, "aggregate words_per_page"):
                receipt["aggregate"]["words_per_page"] = invalid
                VERIFY.verify_image(receipt, image)
        for declared in (None, 12):
            with self.subTest(declared=declared), self.assertRaisesRegex(
                    ValueError, "exactly 12 uint24 words"):
                if declared is None:
                    del receipt["aggregate"]["words_per_page"]
                else:
                    receipt["aggregate"]["words_per_page"] = declared
                VERIFY.verify_image(receipt, image)
        receipt, image = aggregate_fixture(words_per_page=12)
        receipt["aggregate"]["words_per_page"] = 8
        with self.assertRaisesRegex(ValueError, "exactly 8 uint24 words"):
            VERIFY.verify_image(receipt, image)

    def test_aggregate_query_does_not_accept_stale_unshifted_capture(self):
        identity, original = aggregate_fixture()
        for query in ([3, 1, 0, 0], [3, 0, 2, 0], [3, 0, 0, 1], [3, -1, -2, -1]):
            with self.subTest(query=query):
                receipt, shifted = aggregate_fixture(query)
                self.assertFalse(VERIFY.verify_image(receipt, original)["passed"])
                self.assertFalse(VERIFY.verify_image(identity, shifted)["passed"])
        result = VERIFY.verify_image(identity, original)
        self.assertEqual((3, 0, 0, 0), result["aggregate_query"])

    def test_invalid_aggregate_queries_are_rejected(self):
        receipt, image = aggregate_fixture()
        for query in (None, {}, [3, 0, 0], [3, 0, 0, 0, 0], [2, 0, 0, 0],
                      [3, .5, 0, 0], [3, 0, .5, 0], [3, 0, 0, .5],
                      [3, float("nan"), 0, 0], [3, 0, float("inf"), 0],
                      [3, 0, 0, True], [3, "1", 0, 0], [3, 1 << 24, 0, 0]):
            with self.subTest(query=query), self.assertRaisesRegex(ValueError, "aggregate query"):
                receipt["aggregate"]["query"] = query
                VERIFY.verify_image(receipt, image)
        receipt["aggregate"]["query"] = [3, 0, 0, 0]
        receipt["aggregate"]["query_offset"] = 1
        with self.assertRaisesRegex(ValueError, "query_offset"):
            VERIFY.verify_image(receipt, image)

    def test_invalid_receipts_are_rejected_instead_of_clipped(self):
        receipt, image = record_fixture()
        receipt["records"][1]["rect"] = [199, 10, 180, 20]
        with self.assertRaisesRegex(ValueError, "fit wholly"):
            VERIFY.verify_image(receipt, image)
        receipt, image = record_fixture()
        receipt["records"].pop()
        with self.assertRaisesRegex(ValueError, "count"):
            VERIFY.verify_image(receipt, image)
        with self.assertRaisesRegex(ValueError, "nonempty"):
            VERIFY.verify_image({"screen": [200, 100], "records": []}, image)
        aggregate = {"aggregate": {"pages": 2, "words": [[0] * 12],
                                    "display_rect_norm": [0, 0, 1, 1]}}
        with self.assertRaisesRegex(ValueError, "every declared page"):
            VERIFY.verify_image(aggregate, image)

    def test_cli_saves_compact_report_and_failure_returns_nonzero(self):
        receipt, image = record_fixture()
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            state, capture, output = folder / "state.json", folder / "capture.png", folder / "result.json"
            state.write_text(json.dumps(receipt), encoding="utf-8")
            image.save(capture)
            args = ["--receipt", str(state), "--capture", str(capture), "--output", str(output)]
            self.assertEqual(0, VERIFY.main(args))
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(report["passed"])
            self.assertEqual(64, len(report["capture_sha256"]))
            self.assertEqual(1, len(output.read_text(encoding="utf-8").splitlines()))
            Image.new("RGB", image.size, "black").save(capture)
            self.assertEqual(1, VERIFY.main(args))
            self.assertFalse(json.loads(output.read_text(encoding="utf-8"))["passed"])


if __name__ == "__main__":
    unittest.main()
