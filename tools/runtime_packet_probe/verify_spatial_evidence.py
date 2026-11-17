"""Offline independent LCG/PNG audit of v1/v2 spatial packet case evidence.

No production verifier is imported. Receipts supply geometry and seed metadata;
expected bytes come from the independently evaluated LCG, never receipt words.
Every declared cell uses its fixed center and, when wholly interior, 3x3 patch.
Failed original cases remain excluded even if a later named rerun succeeds.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load(path, root, artifacts):
    raw = path.read_bytes()
    artifacts[str(path.relative_to(root)).replace("\\", "/")] = digest(raw)
    return json.loads(raw.decode("utf-8-sig"))


def independent_pages(seed, count):
    require(type(seed) is int and type(count) is int and count > 0, "Invalid seed/page count")
    value, rows, words = seed % 16777216, [], []
    for page in range(count):
        row, word_row = bytearray(), []
        for unused in range(8):
            value = (1664525 * value + 1013904223) % 16777216
            high, remainder = divmod(value, 65536)
            middle, low = divmod(remainder, 256)
            row.extend((high, middle, low))
            word_row.append(value)
        rows.append(bytes(row))
        words.append(word_row)
    return rows, words


def declared_groups(state, source):
    pages = len(source)
    if state["transport"] == "atlas2d":
        query = state["aggregate"]["query"]
        require(isinstance(query, list) and len(query) == 4 and
                all(type(value) in (int, float) and math.isfinite(value) and int(value) == value
                    for value in query), "Invalid atlas query")
        total, start, count, shift = map(int, query)
        require(total == pages and 0 <= start < pages and 1 <= count <= pages, "Query exceeds atlas")
        x, y, width, height = state["aggregate"]["display_rect_norm"]
        for row, page in enumerate(range(start, start + count)):
            if page < pages:
                rotation = 3 * (shift % 8)
                expected = source[page][rotation:] + source[page][:rotation]
            else:
                expected = bytes(24)
            yield page, (x, y + row * height / count, width, height / count), expected
    else:
        require(state["transport"] in ("uniform_ui", "uniform_split"), "Unknown transport")
        rectangles = state["rectangles_norm"]
        require(len(rectangles) == pages, "Uniform tile rectangles omit pages")
        for page, rectangle in enumerate(rectangles):
            yield page, rectangle, source[page]


def sample_cell(image, rectangle, cell):
    require(isinstance(rectangle, (list, tuple)) and len(rectangle) == 4 and
            all(type(value) in (int, float) and math.isfinite(value) for value in rectangle),
            "Invalid cell rectangle")
    x, y, width, height = rectangle
    require(min(x, y) >= 0 and min(width, height) > 0 and
            x + width <= 1.00000001 and y + height <= 1.00000001, "Rectangle leaves image")
    x, y, width, height = x * image.width, y * image.height, width * image.width, height * image.height
    left, right = x + cell * width / 24, x + (cell + 1) * width / 24
    top, bottom = y, y + height
    require(right - left >= 1 and bottom - top >= 1, "Cell must cover one pixel per axis")
    cx, cy = math.floor((left + right) / 2), math.floor((top + bottom) / 2)
    require(0 <= cx < image.width and 0 <= cy < image.height and
            left <= cx + .5 < right and top <= cy + .5 < bottom, "Invalid interior center")
    radius = int(left <= cx - .5 and cx + 1.5 < right and top <= cy - .5 and cy + 1.5 < bottom)
    pixels = [((cx + dx, cy + dy), image.getpixel((cx + dx, cy + dy)))
              for dy in range(-radius, radius + 1) for dx in range(-radius, radius + 1)]
    return image.getpixel((cx, cy)), pixels


def diagnose_failed_tiles(image, groups):
    """Scan tile-interior pixel centers only to explain a failed uniform case."""
    mismatches = {}
    for page, (x, y, width, height), expected in groups:
        x, y, width, height = x * image.width, y * image.height, width * image.width, height * image.height
        for py in range(max(0, math.ceil(y - .5)), min(image.height, math.ceil(y + height - .5))):
            for px in range(max(0, math.ceil(x - .5)), min(image.width, math.ceil(x + width - .5))):
                cell = min(23, int((px + .5 - x) * 24 / width))
                value, pixel = expected[cell], image.getpixel((px, py))
                if pixel != (value, value, value, 255):
                    mismatches[(px, py)] = pixel == (255 - value,) * 3 + (255,)
    coordinates = sorted(mismatches)
    return {"mismatched_pixels": len(coordinates), "rgb_inverted_pixels": sum(mismatches.values()),
            "bounding_box": ([min(x for x, y in coordinates), min(y for x, y in coordinates),
                              max(x for x, y in coordinates), max(y for x, y in coordinates)]
                             if coordinates else None),
            "pixel_coordinates": [list(point) for point in coordinates[:32]],
            "used_for_pass_decision": False}


def verify_window(directory, label, source, seed, case, root, artifacts):
    require(Path(label).name == label, "Window label is not a basename")
    state = load(directory / (label + ".state.json"), root, artifacts)
    report = load(directory / (label + ".verify.json"), root, artifacts)
    capture = load(directory / (label + ".json"), root, artifacts)
    png = directory / (label + ".png")
    png_hash = digest(png.read_bytes())
    artifacts[str(png.relative_to(root)).replace("\\", "/")] = png_hash
    state_hash = artifacts[str((directory / (label + ".state.json")).relative_to(root)).replace("\\", "/")]
    require(report["receipt_sha256"] == state_hash and report["capture_sha256"] == png_hash,
            "Window source hashes disagree")
    require(capture["ok"] is True and capture["backend"] == "Windows.Graphics.Capture" and
            capture["frame_qpc_100ns"] >= capture["request_qpc_100ns"] and
            capture["background_only"] is True and
            all(capture[key]["background_safe"] is True for key in ("background_before", "background_after")),
            "Capture is not a fresh protected WGC frame")
    require(state["transport"] == case["transport"] and state["expected_seed"] == seed and
            state["aggregate"]["pages"] == len(source) and state["aggregate"]["words_per_page"] == 8,
            "Window metadata changed the frozen payload")
    require(state.get("runner_running", False) is False and state["ready"] is True and
            state["enabled"] is True and state["error"] is None, "Payload was not frozen and ready")
    # This is an additional consistency check, never the source of pixel expectations.
    unused, expected_words = independent_pages(seed, len(source))
    require(state["aggregate"]["words"] == expected_words, "Receipt words disagree with independent seed")
    groups = list(declared_groups(state, source))
    require(len(report["results"]) == len(groups), "Report omitted display rows")
    payloads, failed_cells, maximum, checked, pixels_checked = {}, 0, 0, 0, 0
    mismatches, padding_cells, center_digest, diagnostic = {}, 0, hashlib.sha256(), None
    with Image.open(png) as opened:
        image = opened.convert("RGBA")
        require(list(image.size) == state["screen_size"] == report["capture_size"] ==
                [capture["width"], capture["height"]] == case["screen_size"], "Native capture size changed")
        for (page, rectangle, expected), recorded in zip(groups, report["results"]):
            payload = page < len(source)
            require(recorded["index"] == page and recorded["payload"] is payload and
                    len(recorded["observed"]) == 24, "Report row coverage disagrees")
            observed, errors = bytearray(), []
            for cell, value in enumerate(expected):
                center, patch = sample_cell(image, rectangle, cell)
                require(recorded["observed"][cell] == list(center[:3]), "Observed RGB differs from PNG")
                error = max(abs(channel - value) for unused, pixel in patch for channel in pixel[:3])
                failed = error != 0 or any(pixel[3] != 255 for unused, pixel in patch)
                for (px, py), pixel in patch:
                    pixels_checked += 1
                    if pixel != (value, value, value, 255):
                        mismatches[(px, py)] = {"pixel": [px, py], "page": page, "cell": cell,
                                               "expected": value, "observed": list(pixel),
                                               "rgb_inverted": pixel == (255 - value,) * 3 + (255,)}
                checked += 1
                failed_cells += int(failed)
                maximum = max(maximum, error)
                observed.append(center[0])
                errors.append(error)
                center_digest.update(bytes(center[:3]))
            require(recorded["errors"] == errors, "Report inner-patch errors disagree")
            if payload:
                require(page not in payloads, "Duplicate page within window")
                payloads[page] = (bytes(observed), expected)
            else:
                padding_cells += 24
        if failed_cells and state["transport"] in ("uniform_split", "uniform_ui"):
            diagnostic = diagnose_failed_tiles(image, groups)
    passed = failed_cells == 0
    require(report["passed"] is passed and report["exact_equal"] is passed and
            report["checked_cells"] == checked and report["failed_cells"] == failed_cells and
            report["max_error"] == maximum, "Independent pixel result disagrees with existing report")
    ordered = sorted(payloads)
    observed_digest = digest(b"".join(payloads[page][0] for page in ordered))
    expected_digest = digest(b"".join(payloads[page][1] for page in ordered))
    require(report["observed_payload_sha256"] == observed_digest and
            report["expected_payload_sha256"] == expected_digest, "Window payload digest mismatch")
    details = {"label": label, "exact_equal": passed, "checked_cells": checked,
               "sampled_pixels": pixels_checked, "padding_cells": padding_cells,
               "failed_cells": failed_cells, "max_error": maximum,
               "mismatched_pixels": len(mismatches), "inverted_pixels": sum(item["rgb_inverted"] for item in mismatches.values()),
               "observed_payload_sha256": observed_digest, "expected_payload_sha256": expected_digest,
               "observed_rgb_sha256": center_digest.hexdigest()}
    if mismatches:
        details["mismatch_details"] = list(mismatches.values())[:32]
    if diagnostic is not None:
        details["tile_interior_diagnostic"] = diagnostic
    return details, payloads


def verify_case(path, root):
    artifacts = {}
    case = load(path, root, artifacts)
    pages, seed = case["pages"], case["final_seed"]
    source, unused = independent_pages(seed, pages)
    if case.get("run") is not None:
        run = case["run"]
        require(run["success"] is True and run["dynamic"] is case["dynamic"], "Benchmark metadata disagrees")
        require(seed == run["seed"] + (run["frames"] * 97 if case["dynamic"] else 0), "Final seed/frame mismatch")
    rows, coverage = [], {}
    for window in case["windows"]:
        detail, payloads = verify_window(path.parent, window["label"], source, seed, case, root, artifacts)
        rows.append(detail)
        for page, values in payloads.items():
            require(page not in coverage, "Duplicate page across windows")
            coverage[page] = values
    complete = set(coverage) == set(range(pages))
    observed = digest(b"".join(coverage[page][0] for page in sorted(coverage)))
    expected = digest(b"".join(coverage[page][1] for page in sorted(coverage)))
    exact = complete and bool(rows) and all(row["exact_equal"] for row in rows) and observed == expected
    declared_success = case.get("status") != "failed" and case.get("error") is None and case["exact_equal"] is True
    if declared_success:
        require(case["verified_pages"] == pages and case["all_resident_bytes_verified"] is True and
                case["observed_payload_sha256"] == observed and case["expected_payload_sha256"] == expected,
                "Case coverage or digest disagrees with independent windows")
    return {"case": str(path.relative_to(root)).replace("\\", "/"), "declared_success": declared_success,
            "independent_exact": exact, "counted_as_pass": declared_success and exact,
            "transport": case["transport"], "shader_mode": case["shader_mode"], "pages": pages,
            "seed": seed, "covered_pages": len(coverage), "coverage_complete": complete,
            "payload_bytes": pages * 24, "checked_cells": sum(row["checked_cells"] for row in rows),
            "padding_cells": sum(row["padding_cells"] for row in rows), "observed_payload_sha256": observed,
            "expected_payload_sha256": expected, "recorded_failure": case.get("error"), "windows": rows,
            "artifact_hashes": artifacts}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.evidence.resolve()
    paths = sorted(path for version in ("v1", "v2") for path in (root / version).glob("*.case.json"))
    results = []
    for path in paths:
        try:
            results.append(verify_case(path, root))
        except (ValueError, OSError, KeyError, TypeError, IndexError) as error:
            results.append({"case": str(path.relative_to(root)).replace("\\", "/"),
                            "counted_as_pass": False, "audit_error": str(error)})
    successes = [case for case in results if case["counted_as_pass"]]
    failed = [case for case in results if not case["counted_as_pass"]]
    manifest = {name: value for case in results for name, value in case.get("artifact_hashes", {}).items()}
    report = {"audit_passed": bool(results) and not any(case.get("audit_error") or
              (case.get("declared_success") and not case.get("independent_exact")) for case in results),
              "scope": "fixed_center_and_all_interior_patch_pixels_of_frozen_resident_payloads",
              "expected_source": "independent_uint24_LCG_seed_then_divmod_byte_groups",
              "state_words_used_as_expected": False, "production_verifier_imported": False,
              "all_render_frames_verified": False, "actual_mobile_hardware": False,
              "case_count": len(results), "passed_cases": len(successes), "excluded_cases": len(failed),
              "passed_payload_bytes": sum(case["payload_bytes"] for case in successes),
              "passed_checked_cells": sum(case["checked_cells"] for case in successes),
              "source_snapshot_sha256": digest(json.dumps(manifest, sort_keys=True).encode("utf-8")),
              "artifact_count": len(manifest), "verifier_sha256": digest(Path(__file__).read_bytes()),
              "historical_failure_policy": "Keep distinct1024_static as a failed original; later hidden-crosshair reruns are separate cases.",
              "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("audit_passed", "case_count", "passed_cases", "excluded_cases", "passed_payload_bytes")}))
    return 0 if report["audit_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
