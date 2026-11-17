"""Offline false-positive controls for the geometry packet native-pixel oracle."""
import copy
import ctypes
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "geometry_packet_verify", ROOT / "tools/geometry_packet_probe/verify_capture.py")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def fixture_bytes(seed, generation, count):
    """Fixture wraps through uint32 storage, independently of host oracle masks."""
    values = []
    wrap = lambda value: ctypes.c_uint32(value).value
    for index in range(count):
        value = seed ^ wrap(generation * 0x9e3779b9) ^ wrap(index * 0x85ebca6b)
        for shift, multiplier in ((16, 0x7feb352d), (15, 0x846ca68b)):
            value = wrap((value ^ (value >> shift)) * multiplier)
        values.append((value ^ (value >> 16)) % 256)
    return bytes(values)


def fixture(slot_count=137, start=0, count=None, generation=7, serial=1):
    count = min(slot_count - start, 4096) if count is None else count
    receipt = {"schema": "geometry_packet_probe_v1", "seed": 123456789,
               "generation": generation, "slot_count": slot_count,
               "geometry_name": "geometry_probe_%d" % generation,
               "geometry_build_serial": serial, "screen_size": [720, 1080],
               "query": [start, count, 64], "display_rect_norm": [0, 0, 1, 1]}
    payload = fixture_bytes(receipt["seed"], generation, slot_count)
    image = Image.new("RGBA", (720, 1080), (17, 53, 97, 255))
    draw = ImageDraw.Draw(image)
    rows = math.ceil(count / 64)
    for ordinal, value in enumerate(payload[start:start + count]):
        row, column = divmod(ordinal, 64)
        left = math.ceil(column * 720 / 64 - .5)
        right = math.ceil((column + 1) * 720 / 64 - .5) - 1
        top = math.ceil(row * 1080 / rows - .5)
        bottom = math.ceil((row + 1) * 1080 / rows - .5) - 1
        draw.rectangle((left, top, right, bottom), fill=(value, value, value, 255))
    return receipt, image


class GeometryPacketProbeTests(unittest.TestCase):
    def test_prng_golden_vector_and_uint32_boundaries(self):
        golden = bytes((40, 41, 77, 92, 72, 53, 92, 99, 122, 200, 171, 159))
        self.assertEqual(golden, VERIFY.expected_bytes(123456789, 7, 12))
        self.assertEqual(golden, fixture_bytes(123456789, 7, 12))
        for seed, generation in ((0, 0), (0xffffffff, 0xffffffff), (1, 0xffffffff)):
            with self.subTest(seed=seed, generation=generation):
                reference = fixture_bytes(seed, generation, 513)
                self.assertEqual(reference, VERIFY.expected_bytes(seed, generation, 513))
                self.assertEqual(reference[-1], VERIFY.expected_byte(seed, generation, 512))
        for invalid in (-1, 1 << 32, True, 2.0, "1", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                VERIFY.expected_byte(invalid, 0, 0)

    def test_full_4096_window_checks_every_slot_and_all_patch_channels(self):
        receipt, image = fixture(4096)
        report = VERIFY.verify_image(receipt, image)
        self.assertTrue(report["passed"])
        self.assertTrue(report["exact_equal"])
        self.assertEqual(4096, report["checked_cells"])
        self.assertEqual(4096 * 9 * 4, report["checked_channels"])
        self.assertEqual(list(range(4096)), report["verified_slot_indices"])
        self.assertEqual(list(fixture_bytes(receipt["seed"], 7, 4096)), report["observed_bytes"])
        # Last-slot, off-center single-channel corruption must fail with error 1.
        x, y = report["centers"][-1]
        pixel = image.getpixel((x + 1, y - 1))
        image.putpixel((x + 1, y - 1), (pixel[0], pixel[1] ^ 1, pixel[2], 255))
        failed = VERIFY.verify_image(receipt, image)
        self.assertFalse(failed["passed"])
        self.assertEqual(1, failed["failed_cells"])
        self.assertEqual(1, failed["max_error"])
        self.assertEqual(4095, failed["failures"][0]["index"])

    def test_matching_rgb_with_one_transparent_patch_pixel_fails(self):
        receipt, image = fixture()
        report = VERIFY.verify_image(receipt, image)
        x, y = report["centers"][63]
        pixel = image.getpixel((x - 1, y + 1))
        image.putpixel((x - 1, y + 1), pixel[:3] + (254,))
        failed = VERIFY.verify_image(receipt, image)
        self.assertFalse(failed["passed"])
        self.assertEqual([{"index": 63, "rgb_error": 0, "alpha_error": 1}], failed["failures"])

    def test_wrong_generation_and_stale_query_frames_fail(self):
        first, first_image = fixture(512, 0, 256)
        second, second_image = fixture(512, 256, 256)
        changed, changed_image = fixture(512, 0, 256, generation=8, serial=2)
        self.assertTrue(VERIFY.verify_image(second, second_image)["passed"])
        self.assertTrue(VERIFY.verify_image(changed, changed_image)["passed"])
        self.assertFalse(VERIFY.verify_image(second, first_image)["passed"])
        self.assertFalse(VERIFY.verify_image(changed, first_image)["passed"])
        self.assertFalse(VERIFY.verify_image(first, changed_image)["passed"])

    def test_partial_last_row_and_reverse_query_order_preserve_source_order_hash(self):
        last = fixture(137, 128, 9)
        middle = fixture(137, 64, 64)
        first = fixture(137, 0, 64)
        report = VERIFY.verify_series((last, middle, first))
        payload = fixture_bytes(first[0]["seed"], 7, 137)
        self.assertTrue(report["passed"])
        self.assertTrue(report["full_slot_coverage"])
        self.assertEqual(137, report["payload_bytes"])
        self.assertEqual(list(payload), report["observed_bytes"])
        self.assertEqual(hashlib.sha256(payload).hexdigest(), report["observed_payload_sha256"])
        self.assertEqual(report["expected_payload_sha256"], report["observed_payload_sha256"])

    def test_stream_reports_equal_image_series_and_refuse_inconsistent_reports(self):
        pairs = (fixture(137, 0, 64), fixture(137, 64, 73))
        evidence = [(receipt, VERIFY.verify_image(receipt, image)) for receipt, image in pairs]
        self.assertEqual(VERIFY.verify_series(pairs), VERIFY.verify_reports(evidence))
        for field, value in (("observed_bytes", [1]), ("expected_bytes", [1]),
                             ("checked_pixels", 1), ("generation", 8), ("passed", True)):
            bad = copy.deepcopy(evidence)
            if field == "passed":
                bad[0][1]["observed_bytes"][0] ^= 1
            bad[0][1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                VERIFY.verify_reports(bad)

    def test_missing_duplicate_and_generation_or_rebuild_changes_are_rejected(self):
        first, second = fixture(128, 0, 64), fixture(128, 64, 64)
        with self.assertRaisesRegex(ValueError, "missing"):
            VERIFY.verify_series((first,))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            VERIFY.verify_series((first, first, second))
        for key, value in (("generation", 8), ("seed", 42), ("geometry_build_serial", 2),
                           ("geometry_name", "rebuilt"), ("slot_count", 129)):
            receipt, image = second
            altered = copy.deepcopy(receipt)
            altered[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "identity"):
                VERIFY.verify_series((first, (altered, image)))
        with self.assertRaisesRegex(ValueError, "nonempty"):
            VERIFY.verify_series(())

    def test_geometry_freeze_ignores_cpu_payload_copies_but_update_needs_new_pixels(self):
        old_receipt, old_image = fixture(137)
        before = VERIFY.verify_series(((old_receipt, old_image),))
        frozen = copy.deepcopy(old_receipt)
        frozen.update(source_generation=99, payload=[255] * 137, expected_bytes=[255] * 137)
        frozen_report = VERIFY.verify_series(((frozen, old_image),))
        self.assertTrue(VERIFY.verify_transition(before, frozen_report, False)["passed"])
        updated = fixture(137, generation=8, serial=2)
        after = VERIFY.verify_series((updated,))
        self.assertTrue(VERIFY.verify_transition(before, after, True)["passed"])
        self.assertFalse(VERIFY.verify_transition(before, after, False)["passed"])
        self.assertFalse(VERIFY.verify_transition(before, frozen_report, True)["passed"])
        stale = VERIFY.verify_series(((updated[0], old_image),))
        self.assertFalse(stale["passed"])
        with self.assertRaisesRegex(ValueError, "passing"):
            VERIFY.verify_transition(before, stale, True)

    def test_native_size_orientation_background_and_fixed_patch_are_enforced(self):
        receipt, image = fixture()
        for wrong in (image.resize((721, 1080)), image.resize((720, 1079))):
            with self.assertRaisesRegex(ValueError, "720x1080"):
                VERIFY.verify_image(receipt, wrong)
        self.assertFalse(VERIFY.verify_image(receipt, ImageOps.flip(image))["passed"])
        for color in ((17, 53, 97), (0, 0, 0), (127, 127, 127), (255, 255, 255)):
            self.assertFalse(VERIFY.verify_image(receipt, Image.new("RGB", image.size, color))["passed"])
        # Tiny viewport cannot silently drop the patch to one pixel.
        receipt["display_rect_norm"] = [0, 0, .1, .1]
        with self.assertRaisesRegex(ValueError, "3x3"):
            VERIFY.verify_image(receipt, image)

    def test_invalid_queries_headers_and_rects_are_not_clipped_or_coerced(self):
        receipt, image = fixture()
        mutations = {"query": ([0, 0, 64], [-1, 1, 64], [0, 138, 64], [0, 4097, 64],
                               [0, 10, 63], [0, 10], [0, True, 64], [0, 1.5, 64],
                               [float("nan"), 1, 64]),
                     "seed": (-1, 1 << 32, True, "1"),
                     "generation": (-1, True, 1.0), "slot_count": (0, True, 1 << 25),
                     "geometry_build_serial": (0, True), "geometry_name": ("", None),
                     "query_mode": (True, 1, 2, 3),
                     "schema": ("other",), "screen_size": ([720, 1081], [720., 1080]),
                     "display_rect_norm": ([0, 0, 2, 1], [0, 0, 0, 1],
                                           [0, float("inf"), 1, 1])}
        for key, values in mutations.items():
            for value in values:
                altered = copy.deepcopy(receipt)
                altered[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    VERIFY.verify_image(altered, image)
        receipt["query"] = [0., 137., 64.]
        self.assertTrue(VERIFY.verify_image(receipt, image)["passed"])

    def test_cli_hashes_source_artifacts_and_returns_nonzero_for_pixel_failure(self):
        receipt, image = fixture()
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            state, capture, result = folder / "state.json", folder / "capture.png", folder / "out.json"
            state.write_text(json.dumps(receipt), encoding="utf-8")
            image.save(capture)
            args = ["--receipt", str(state), "--capture", str(capture), "--output", str(result)]
            self.assertEqual(0, VERIFY.main(args))
            report = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(hashlib.sha256(capture.read_bytes()).hexdigest(), report["capture_sha256"])
            self.assertEqual(hashlib.sha256(state.read_bytes()).hexdigest(), report["receipt_sha256"])
            Image.new("RGB", image.size, (17, 53, 97)).save(capture)
            self.assertEqual(1, VERIFY.main(args))
            self.assertFalse(json.loads(result.read_text(encoding="utf-8"))["passed"])


if __name__ == "__main__":
    unittest.main()
