"""Independent, exact native-pixel oracle for geometry packet screenshots.

Only seed, uploaded generation and slot indices define the expected payload.
CPU payload/expected copies in receipts are deliberately never read. Each
query displays consecutive slots as 64 columns, top-left first, with enough
rows for its count. All nine RGB+alpha pixels in each center patch must match.
No scaling, offset search, tolerance, or smaller-patch fallback is permitted.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image


SCHEMA = "geometry_packet_probe_v1"
SCREEN_SIZE = (720, 1080)
COLUMNS = 64
MAX_QUERY_COUNT = 4096
UINT32_MASK = (1 << 32) - 1
MAX_SLOT_COUNT = 1 << 24


def _integer(value, name, minimum=0, maximum=UINT32_MASK):
    if (isinstance(value, bool) or not isinstance(value, int) or
            not minimum <= value <= maximum):
        raise ValueError("%s must be an integer in [%d, %d]" % (name, minimum, maximum))
    return value


def _byte_at(seed, generation, index):
    mixed = seed ^ ((generation * 0x9e3779b9) & UINT32_MASK)
    mixed ^= (index * 0x85ebca6b) & UINT32_MASK
    mixed ^= mixed >> 16
    mixed = (mixed * 0x7feb352d) & UINT32_MASK
    mixed ^= mixed >> 15
    mixed = (mixed * 0x846ca68b) & UINT32_MASK
    return (mixed ^ (mixed >> 16)) & 255


def expected_byte(seed, generation, index):
    """Integer reference independent of palette construction and shader math."""
    seed = _integer(seed, "seed")
    generation = _integer(generation, "generation")
    index = _integer(index, "index", maximum=MAX_SLOT_COUNT - 1)
    return _byte_at(seed, generation, index)


def expected_bytes(seed, generation, slot_count):
    seed = _integer(seed, "seed")
    generation = _integer(generation, "generation")
    count = _integer(slot_count, "slot_count", 1, MAX_SLOT_COUNT)
    return bytes(_byte_at(seed, generation, index) for index in range(count))


def _receipt(receipt, size):
    if not isinstance(receipt, dict) or receipt.get("schema") != SCHEMA:
        raise ValueError("receipt schema must be %s" % SCHEMA)
    for field in ("seed", "generation"):
        _integer(receipt.get(field), field)
    _integer(receipt.get("slot_count"), "slot_count", 1, MAX_SLOT_COUNT)
    _integer(receipt.get("geometry_build_serial"), "geometry_build_serial", 1)
    _integer(receipt.get("query_mode", 0), "query_mode", 0, 0)
    if not isinstance(receipt.get("geometry_name"), str) or not receipt["geometry_name"]:
        raise ValueError("geometry_name must be a nonempty string")
    screen = receipt.get("screen_size")
    if (not isinstance(screen, (list, tuple)) or len(screen) != 2 or
            any(isinstance(value, bool) or not isinstance(value, int) for value in screen) or
            tuple(screen) != SCREEN_SIZE or tuple(size) != SCREEN_SIZE):
        raise ValueError("receipt and native capture must both be exactly 720x1080")
    query = receipt.get("query")
    if (not isinstance(query, (list, tuple)) or len(query) != 3 or
            any(isinstance(value, bool) or not isinstance(value, (int, float)) or
                (isinstance(value, float) and not math.isfinite(value)) or
                int(value) != value for value in query)):
        raise ValueError("query must contain integer-valued [start, count, columns]")
    start, count, columns = map(int, query)
    if (columns != COLUMNS or not 1 <= count <= MAX_QUERY_COUNT or start < 0 or
            start + count > receipt["slot_count"]):
        raise ValueError("query must fit all declared slots, use 64 columns and count 1..4096")
    rect = receipt.get("display_rect_norm", [0, 0, 1, 1])
    if (not isinstance(rect, (list, tuple)) or len(rect) != 4 or
            any(isinstance(value, bool) or not isinstance(value, (int, float)) or
                (isinstance(value, float) and not math.isfinite(value)) for value in rect)):
        raise ValueError("display_rect_norm must contain four finite numbers")
    x, y, width, height = rect
    if (x < 0 or y < 0 or width <= 0 or height <= 0 or
            x + width > 1 or y + height > 1):
        raise ValueError("display_rect_norm must fit wholly inside the native capture")
    return (start, count, columns), (x * size[0], y * size[1],
                                    width * size[0], height * size[1])


def _identity(receipt):
    return {key: receipt.get(key) for key in ("schema", "seed", "generation", "slot_count",
                                             "geometry_name", "geometry_build_serial")}


def _patch(image, rect, ordinal, columns, rows):
    x, y, width, height = rect
    row, column = divmod(ordinal, columns)
    left, right = x + column * width / columns, x + (column + 1) * width / columns
    top, bottom = y + row * height / rows, y + (row + 1) * height / rows
    cx, cy = math.floor((left + right) / 2), math.floor((top + bottom) / 2)
    if not (0 <= cx - 1 and cx + 1 < image.width and 0 <= cy - 1 and
            cy + 1 < image.height and left < cx - .5 and cx + 1.5 < right and
            top < cy - .5 and cy + 1.5 < bottom):
        raise ValueError("every slot must contain a full interior 3x3 native-pixel patch")
    pixels = [image.getpixel((cx + dx, cy + dy))
              for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
    return [cx, cy], pixels


def verify_image(receipt, image):
    """Verify one query, returning byte lists for an external streaming runner.

    A passing query does not claim full-dataset coverage. Use verify_series or
    independently enforce every slot exactly once when streaming many images.
    generation identifies the uploaded geometry even if a CPU producer advances
    while the geometry is frozen; source_generation is not an oracle input.
    """
    query, rect = _receipt(receipt, image.size)
    image = image.convert("RGBA")
    start, count, columns = query
    rows = (count + columns - 1) // columns
    indices = list(range(start, start + count))
    expected = [_byte_at(receipt["seed"], receipt["generation"], index) for index in indices]
    observed, centers, failures = [], [], []
    maximum_error = 0
    for ordinal, (index, level) in enumerate(zip(indices, expected)):
        center, pixels = _patch(image, rect, ordinal, columns, rows)
        error = max(abs(channel - level) for pixel in pixels for channel in pixel[:3])
        alpha_error = max(255 - pixel[3] for pixel in pixels)
        maximum_error = max(maximum_error, error, alpha_error)
        centers.append(center)
        observed.append(image.getpixel(tuple(center))[0])
        if error or alpha_error:
            failures.append({"index": index, "rgb_error": error,
                             "alpha_error": alpha_error})
    passed = not failures
    return dict(_identity(receipt), passed=passed, exact_equal=passed,
                byte_tolerance=0, required_alpha=255, sample_width=3,
                capture_size=list(image.size), query=list(query), rows=rows,
                checked_cells=count, checked_pixels=count * 9,
                checked_channels=count * 9 * 4, failed_cells=len(failures),
                max_error=maximum_error, verified_slot_indices=indices,
                observed_bytes=observed, expected_bytes=expected, centers=centers,
                observed_payload_sha256=hashlib.sha256(bytes(observed)).hexdigest(),
                expected_payload_sha256=hashlib.sha256(bytes(expected)).hexdigest(),
                failures=failures)


def verify_series(captures):
    """Check (receipt, PIL image) pairs: one unchanged geometry, every slot once.

    Missing or duplicated slots and changed identities are malformed evidence,
    rejected with ValueError even if all provided pixels happen to match.
    Hashes are always in source slot order, independent of query order.
    """
    return verify_reports((receipt, verify_image(receipt, image)) for receipt, image in captures)


def verify_reports(captures):
    """Aggregate (receipt, verify_image report) pairs without keeping images.

    Reports are evidence returned by verify_image, not a substitute for image
    validation. Their metadata, byte lengths, and expected bytes are checked
    again; independent expected values never come from a receipt payload copy.
    """
    reports, identity, observed, expected, covered, rect = [], None, None, None, None, None
    for receipt, report in captures:
        query, _ = _receipt(receipt, SCREEN_SIZE)
        current = _identity(receipt)
        count = query[1]
        indices = list(range(query[0], query[0] + count))
        levels = report.get("observed_bytes") if isinstance(report, dict) else None
        if (not isinstance(report, dict) or _identity(report) != current or
                report.get("query") != list(query) or
                report.get("verified_slot_indices") != indices or
                report.get("checked_cells") != count or
                report.get("checked_pixels") != count * 9 or
                report.get("checked_channels") != count * 36 or
                report.get("capture_size") != list(SCREEN_SIZE) or
                report.get("sample_width") != 3 or report.get("byte_tolerance") != 0 or
                report.get("required_alpha") != 255):
            raise ValueError("report metadata disagrees with its receipt or exact patch contract")
        if (not isinstance(levels, list) or len(levels) != count or
                any(isinstance(value, bool) or not isinstance(value, int) or
                    not 0 <= value <= 255 for value in levels)):
            raise ValueError("report must contain every observed byte")
        oracle = [_byte_at(current["seed"], current["generation"], index) for index in indices]
        if report.get("expected_bytes") != oracle:
            raise ValueError("report expected bytes disagree with independent seed oracle")
        failed_cells = _integer(report.get("failed_cells"), "failed_cells", 0, count)
        _integer(report.get("max_error"), "max_error", 0, 255)
        if (not isinstance(report.get("passed"), bool) or
                report["passed"] != (failed_cells == 0) or
                (report["passed"] and (levels != oracle or report["max_error"] != 0))):
            raise ValueError("report passing status disagrees with its pixel evidence")
        current_rect = tuple(receipt.get("display_rect_norm", [0, 0, 1, 1]))
        if identity is None:
            identity, rect = current, current_rect
            observed = bytearray(identity["slot_count"])
            expected = expected_bytes(identity["seed"], identity["generation"], identity["slot_count"])
            covered = bytearray(identity["slot_count"])
        elif current != identity or current_rect != rect:
            raise ValueError("capture series changed geometry identity, generation or display rectangle")
        for index, value in zip(report["verified_slot_indices"], report["observed_bytes"]):
            if covered[index]:
                raise ValueError("duplicate slot %d in capture series" % index)
            covered[index], observed[index] = 1, value
        reports.append(report)
    if not reports:
        raise ValueError("capture series must be nonempty")
    missing = covered.count(0)
    if missing:
        raise ValueError("capture series is missing %d slots" % missing)
    if len(set(expected)) < 2:
        raise ValueError("payload cannot distinguish delivery from a uniform background")
    passed = all(report["passed"] for report in reports)
    return dict(identity, passed=passed, exact_equal=passed, full_slot_coverage=True,
                capture_count=len(reports), payload_bytes=len(observed),
                checked_cells=sum(report["checked_cells"] for report in reports),
                checked_pixels=sum(report["checked_pixels"] for report in reports),
                failed_cells=sum(report["failed_cells"] for report in reports),
                max_error=max(report["max_error"] for report in reports),
                observed_bytes=list(observed), expected_bytes=list(expected),
                observed_payload_sha256=hashlib.sha256(observed).hexdigest(),
                expected_payload_sha256=hashlib.sha256(expected).hexdigest(),
                queries=[report["query"] for report in reports])


def verify_transition(before, after, expect_changed):
    """Check full-coverage reports for an uploaded change or a frozen geometry.

    For freeze, uploaded identity and bytes must stay equal. For an update,
    generation must change, build serial must increase, and bytes must change.
    The caller still records the CPU producer's change separately during freeze.
    """
    if not isinstance(expect_changed, bool):
        raise ValueError("expect_changed must be bool")
    if any(not report.get("passed") or not report.get("full_slot_coverage")
           for report in (before, after)):
        raise ValueError("transition requires two passing full-slot reports")
    if any(before[key] != after[key] for key in ("schema", "seed", "slot_count")):
        raise ValueError("transition must preserve schema, seed and slot_count")
    changed = before["observed_payload_sha256"] != after["observed_payload_sha256"]
    if expect_changed:
        passed = (changed and before["generation"] != after["generation"] and
                  before["geometry_build_serial"] < after["geometry_build_serial"])
    else:
        passed = not changed and _identity(before) == _identity(after)
    return {"passed": passed, "expect_changed": expect_changed, "payload_changed": changed,
            "before_generation": before["generation"], "after_generation": after["generation"],
            "before_sha256": before["observed_payload_sha256"],
            "after_sha256": after["observed_payload_sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw_receipt, raw_capture = args.receipt.read_bytes(), args.capture.read_bytes()
        receipt = json.loads(raw_receipt.decode("utf-8-sig"))
        with Image.open(args.capture) as image:
            report = verify_image(receipt, image)
        report.update(receipt_sha256=hashlib.sha256(raw_receipt).hexdigest(),
                      capture_sha256=hashlib.sha256(raw_capture).hexdigest())
    except (ValueError, OSError, TypeError) as error:
        report = {"passed": False, "exact_equal": False, "error": str(error)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in
                      ("passed", "checked_cells", "failed_cells", "max_error", "error")
                      if key in report}, separators=(",", ":")))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
