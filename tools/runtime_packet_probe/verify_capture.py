"""Fixed-coordinate screenshot oracle for the isolated runtime packet probe.

Receipt records use logical, top-left ``rect=[x,y,w,h]`` coordinates and three
uint24 words. Each word is displayed as high/middle/low byte grayscale cells.
An aggregate receipt has ``pages``, ``words_per_page`` (8 or 12), and a top-left
``display_rect_norm``; its display has one row per page and three grayscale
columns per word. Missing ``words_per_page`` means 12 for older receipts.
Optional ``query=[pages,row_shift,word_shift,byte_shift]`` selects cyclic source
indices, exactly as the display shader does. Omission means no shifts. Query
values must be integral; integer-valued JSON floats from game Python are valid.
All declared cells are checked. This tool never searches offsets or subsets.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image


BYTE_TOLERANCE = 2
UINT24_LIMIT = 1 << 24


def word_bytes(value):
    """Independent integer oracle; do not decode using shader float math."""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < UINT24_LIMIT:
        raise ValueError("Packet words must be integers in [0, 2**24)")
    return (value >> 16, (value >> 8) & 255, value & 255)


def _numbers(value, length, name):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError("%s must contain %d numbers" % (name, length))
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) or
           not math.isfinite(item) for item in value):
        raise ValueError("%s must contain finite numbers" % name)
    return tuple(float(item) for item in value)


def _rect(value, width, height, name):
    x, y, w, h = _numbers(value, 4, name)
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
        raise ValueError("%s must fit wholly inside the declared viewport" % name)
    return x, y, w, h


def _words(value, count, name):
    if not isinstance(value, (list, tuple)) or len(value) != count:
        raise ValueError("%s must contain exactly %d uint24 words" % (name, count))
    return [byte for word in value for byte in word_bytes(word)]


def _aggregate_query(aggregate, pages, words_per_page):
    query = _numbers(aggregate.get("query", [pages, 0, 0, 0]), 4, "aggregate query")
    if any(not value.is_integer() for value in query):
        raise ValueError("aggregate query must contain integer-valued numbers")
    query = tuple(int(value) for value in query)
    if query[0] != pages:
        raise ValueError("aggregate query page count must match aggregate pages")
    # Keep index additions and GLSL mod's divisor * floor(x / divisor)
    # exactly representable in the shader's float32, including negative shifts.
    # Reject large ambiguous queries instead of normalizing them before checking.
    for shift, largest_index, divisor in zip(
            query[1:], (pages - 1, words_per_page - 1, 3 * words_per_page - 1),
            (pages, words_per_page, 3)):
        if not -UINT24_LIMIT + divisor < shift < UINT24_LIMIT - largest_index:
            raise ValueError("aggregate query shifts exceed exact float32 index arithmetic")
    return query


def _groups(receipt, size):
    if not isinstance(receipt, dict):
        raise ValueError("Receipt must be a JSON object")
    image_width, image_height = size
    groups = []
    scale = None
    query = None
    if "records" in receipt:
        width, height = _numbers(receipt.get("screen"), 2, "screen")
        if width <= 0 or height <= 0:
            raise ValueError("Logical screen dimensions must be positive")
        scale = (image_width / width, image_height / height)
        records = receipt["records"]
        if not isinstance(records, list) or not records:
            raise ValueError("records must be a nonempty list")
        if "count" in receipt and receipt["count"] != len(records):
            raise ValueError("Declared count does not match all receipt records")
        indices = set()
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("Every record must be an object")
            index = record.get("index")
            if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index in indices:
                raise ValueError("Record indices must be unique nonnegative integers")
            indices.add(index)
            expected = _words(record.get("values"), 3, "record values")
            x, y, w, h = _rect(record.get("rect"), width, height, "record rect")
            groups.append(("record", index, expected,
                           (x * scale[0], y * scale[1], w * scale[0], h * scale[1])))
    if "aggregate" in receipt:
        aggregate = receipt["aggregate"]
        if not isinstance(aggregate, dict):
            raise ValueError("aggregate must be an object")
        pages = aggregate.get("pages")
        words = aggregate.get("words")
        words_per_page = aggregate.get("words_per_page", 12)
        if isinstance(pages, bool) or not isinstance(pages, int) or pages <= 0:
            raise ValueError("aggregate pages must be a positive integer")
        if (isinstance(words_per_page, bool) or not isinstance(words_per_page, int) or
                words_per_page not in (8, 12)):
            raise ValueError("aggregate words_per_page must be 8 or 12")
        if not isinstance(words, list) or len(words) != pages:
            raise ValueError("aggregate words must include every declared page")
        # This old placeholder field has no defined shader mapping.
        if aggregate.get("query_offset", 0) != 0:
            raise ValueError("Nonzero aggregate query_offset is not supported")
        query = _aggregate_query(aggregate, pages, words_per_page)
        _, row_shift, word_shift, byte_shift = query
        source_rows = [_words(row, words_per_page, "aggregate page words") for row in words]
        x, y, w, h = _rect(aggregate.get("display_rect_norm"), 1, 1,
                           "aggregate display_rect_norm")
        for page in range(pages):
            source = source_rows[(page + row_shift) % pages]
            # Positive integer divisors make Python % match GLSL mod for the
            # accepted signed integer indices, including negative shifts.
            expected = [source[3 * ((cell // 3 + word_shift) % words_per_page) +
                               (cell + byte_shift) % 3]
                        for cell in range(3 * words_per_page)]
            groups.append(("aggregate", page, expected,
                           (x * image_width, (y + page * h / pages) * image_height,
                            w * image_width, h * image_height / pages)))
    if not groups:
        raise ValueError("Receipt must declare records or aggregate")
    return groups, scale, query


def _sample(image, rect, cell, columns, flip_y):
    x, y, w, h = rect
    left, right = x + cell * w / columns, x + (cell + 1) * w / columns
    top, bottom = y, y + h
    if flip_y:
        top, bottom = image.height - bottom, image.height - top
    if right - left < 1 or bottom - top < 1:
        raise ValueError("Every declared cell must cover at least one physical pixel per axis")
    center_x, center_y = math.floor((left + right) / 2), math.floor((top + bottom) / 2)
    if not (0 <= center_x < image.width and 0 <= center_y < image.height and
            left <= center_x + .5 < right and top <= center_y + .5 < bottom):
        raise ValueError("Declared cell center does not address an interior capture pixel")
    # Use 3x3 only when every pixel center lies strictly within this cell.
    radius = int(left <= center_x - .5 and center_x + 1.5 < right and
                 top <= center_y - .5 and center_y + 1.5 < bottom)
    pixels = [image.getpixel((center_x + dx, center_y + dy))
              for dy in range(-radius, radius + 1) for dx in range(-radius, radius + 1)]
    return [center_x, center_y], pixels, 2 * radius + 1


def verify_image(receipt, image, flip_y=False):
    """Check all RGB channels of all cell-center pixels, with byte tolerance 2.

    Transparent pixels always fail. A uniform expected payload cannot establish
    that a carrier rendered instead of a blank background, so also fails.
    ``all_equal`` means within the declared tolerance; ``exact_equal`` is strict.
    """
    image = image.convert("RGBA")
    groups, scale, query = _groups(receipt, image.size)
    results, failed_cells, checked_cells, maximum_error = [], 0, 0, 0
    expected_levels, observed_levels = [], []
    for source, index, expected, rect in groups:
        row = {"source": source, "index": index, "expected": expected,
               "observed": [], "centers": [], "sample_widths": [],
               "errors": [], "alpha_min": [], "failed": []}
        expected_levels.extend(expected)
        for cell, value in enumerate(expected):
            center, pixels, sample_width = _sample(image, rect, cell, len(expected), flip_y)
            error = max(abs(pixel[channel] - value) for pixel in pixels for channel in range(3))
            alpha_min = min(pixel[3] for pixel in pixels)
            observed = list(image.getpixel(tuple(center))[:3])
            observed_levels.extend(observed)
            row["observed"].append(observed)
            row["centers"].append(center)
            row["sample_widths"].append(sample_width)
            row["errors"].append(error)
            row["alpha_min"].append(alpha_min)
            if error > BYTE_TOLERANCE or alpha_min != 255:
                row["failed"].append(cell)
                failed_cells += 1
            maximum_error = max(maximum_error, error)
            checked_cells += 1
        row["passed"] = not row["failed"]
        results.append(row)
    reasons = []
    if max(expected_levels) - min(expected_levels) <= 2 * BYTE_TOLERANCE:
        reasons.append("expected_payload_cannot_distinguish_a_uniform_background")
    if max(observed_levels) - min(observed_levels) <= 2 * BYTE_TOLERANCE:
        reasons.append("capture_has_no_distinguishable_payload_variation")
    passed = failed_cells == 0 and not reasons
    return {"passed": passed, "all_equal": passed,
            "exact_equal": passed and maximum_error == 0,
            "byte_tolerance": BYTE_TOLERANCE, "required_alpha": 255,
            "capture_size": list(image.size), "logical_to_physical_scale": scale,
            "aggregate_query": query,
            "flip_y": bool(flip_y), "checked_cells": checked_cells,
            "failed_cells": failed_cells, "max_error": maximum_error,
            "failure_reasons": reasons, "results": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--flip-y", action="store_true",
                        help="Explicitly mirror declared coordinates vertically; never inferred")
    args = parser.parse_args(argv)
    try:
        receipt_bytes = args.receipt.read_bytes()
        capture_bytes = args.capture.read_bytes()
        receipt = json.loads(receipt_bytes.decode("utf-8-sig"))
        with Image.open(args.capture) as image:
            report = verify_image(receipt, image, flip_y=args.flip_y)
        report["receipt_sha256"] = hashlib.sha256(receipt_bytes).hexdigest()
        report["capture_sha256"] = hashlib.sha256(capture_bytes).hexdigest()
    except (ValueError, OSError, TypeError) as error:
        report = {"passed": False, "all_equal": False, "error": str(error),
                  "flip_y": args.flip_y, "byte_tolerance": BYTE_TOLERANCE}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, separators=(",", ":"), ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({key: report[key] for key in
                      ("passed", "checked_cells", "failed_cells", "max_error", "error")
                      if key in report}, separators=(",", ":")))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
