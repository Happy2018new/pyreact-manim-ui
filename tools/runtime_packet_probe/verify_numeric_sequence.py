"""Independently verify the nine v11 numeric captures against command formulas.

Read every observed grayscale byte back from the saved WGC PNG and its report.
Expected bytes come only from the recorded formula and stdlib struct, never
state.words, report.expected, numeric_payload, or numeric_runtime. This checks
nine frozen captures; it does not establish GPU arithmetic or all-frame delivery.
"""
import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import struct

from PIL import Image


MAGIC = 0x504D4E31
PAGES, COLUMNS, HEADER_BYTES = 256, 24, 16
CAPACITY_BYTES = PAGES * COLUMNS
SEQUENCE_COUNTS = (0, 1, 5, 6, 7, 1532, 3, 0)
SPECIAL_EXPRESSION = "[-0.0,1.0/3.0,-1.0/7.0,1e20,-1e-20,1.17549435e-38,3.402823466e38]"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def expected_case(index):
    if index < len(SEQUENCE_COUNTS):
        count = SEQUENCE_COUNTS[index]
        name = "numeric_sequence_%d_count%d" % (index, count)
        expression = "[((i*73)%%2001-1000)/37. for i in range(%d)]" % count
        values = [((i * 73) % 2001 - 1000) / 37. for i in range(count)]
    else:
        name, expression = "numeric_special", SPECIAL_EXPRESSION
        values = [-0.0, 1.0 / 3.0, -1.0 / 7.0, 1e20, -1e-20,
                  1.17549435e-38, 3.402823466e38]
    generation = index + 1
    command = ("from packet_probe.numeric_runtime import write_numbers\nvalues=%s\n"
               "_result=json.dumps(write_numbers(probe.aggregation,values,%d))\n" %
               (expression, generation))
    payload = b"".join(struct.pack("<f", value) for value in values)
    wire = struct.pack("<4I", MAGIC, len(values), len(payload), generation) + payload
    return name, command, values, wire + bytes(CAPACITY_BYTES - len(wire))


def observed_bytes(state, verification, image):
    """Validate all report RGBs against independently located PNG inner patches."""
    aggregate = state["aggregate"]
    require(aggregate["pages"] == PAGES and aggregate["words_per_page"] == 8,
            "Expected a complete 256-page eight-word atlas")
    require(aggregate["query"] == [PAGES, 0, 0, 0] and not verification["flip_y"],
            "This sequence requires the declared identity query and top-left coordinates")
    require(verification["capture_size"] == list(image.size), "PNG dimensions differ from report")
    require(verification["checked_cells"] == CAPACITY_BYTES, "Report omitted declared byte cells")
    rect = aggregate["display_rect_norm"]
    require(isinstance(rect, list) and len(rect) == 4 and
            all(type(value) in (int, float) and math.isfinite(value) for value in rect),
            "Invalid display rectangle")
    x, y, width, height = rect
    require(x >= 0 and y >= 0 and width > 0 and height > 0 and
            x + width <= 1 and y + height <= 1, "Display rectangle leaves the capture")
    rows = verification["results"]
    require(len(rows) == PAGES, "Report must contain every atlas page")
    image = image.convert("RGBA")
    result = bytearray()
    for page, row in enumerate(rows):
        require(row["source"] == "aggregate" and type(row["index"]) is int and row["index"] == page,
                "Report page order is incomplete or ambiguous")
        require(all(len(row[key]) == COLUMNS for key in ("observed", "centers", "sample_widths")),
                "Every page must report exactly 24 observed bytes")
        top = (y + page * height / PAGES) * image.height
        bottom = (y + (page + 1) * height / PAGES) * image.height
        for column, rgb in enumerate(row["observed"]):
            require(isinstance(rgb, list) and len(rgb) == 3 and
                    all(type(value) is int and 0 <= value <= 255 for value in rgb) and
                    rgb[0] == rgb[1] == rgb[2], "Observed byte must be exact grayscale RGB")
            left = (x + column * width / COLUMNS) * image.width
            right = (x + (column + 1) * width / COLUMNS) * image.width
            center_x, center_y = math.floor((left + right) / 2), math.floor((top + bottom) / 2)
            require(left <= center_x + .5 < right and top <= center_y + .5 < bottom,
                    "Cell has no interior center pixel")
            radius = int(left <= center_x - .5 and center_x + 1.5 < right and
                         top <= center_y - .5 and center_y + 1.5 < bottom)
            require(row["centers"][column] == [center_x, center_y] and
                    row["sample_widths"][column] == radius * 2 + 1,
                    "Report coordinates differ from the fixed declared rectangle")
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    require(image.getpixel((center_x + dx, center_y + dy)) == tuple(rgb) + (255,),
                            "PNG pixel or alpha differs from reported observed byte")
            result.append(rgb[0])
    require(len(result) == CAPACITY_BYTES, "Observed stream must cover all 6144 bytes")
    return bytes(result)


def verify_case(evidence, commands, index):
    name, expected_command, values, expected = expected_case(index)
    paths = {"state": evidence / (name + ".state.json"),
             "verification": evidence / (name + ".verify.json"),
             "capture": evidence / (name + ".png"),
             "capture_receipt": evidence / (name + ".json"),
             "command": commands / (name + ".py")}
    files = {key: path.read_bytes() for key, path in paths.items()}
    hashes = {key + "_sha256": sha256(data) for key, data in files.items()}
    state, verification, capture = [json.loads(files[key].decode("utf-8-sig"))
                                    for key in ("state", "verification", "capture_receipt")]
    require(ast.dump(ast.parse(files["command"].decode("utf-8-sig"))) ==
            ast.dump(ast.parse(expected_command)), "Command record differs from independent formula")
    require(verification["receipt_sha256"] == hashes["state_sha256"] and
            verification["capture_sha256"] == hashes["capture_sha256"], "Source hash mismatch")
    require(capture["ok"] is True and capture["backend"] == "Windows.Graphics.Capture" and
            capture["frame_qpc_100ns"] >= capture["request_qpc_100ns"] and
            capture["background_only"] is True and
            all(capture[key]["background_safe"] is True for key in ("background_before", "background_after")),
            "Capture receipt does not establish a fresh background WGC frame")
    with Image.open(paths["capture"]) as image:
        require([capture["width"], capture["height"]] == list(image.size), "WGC size mismatch")
        observed = observed_bytes(state, verification, image)
    mismatch = [offset for offset, (actual, wanted) in enumerate(zip(observed, expected)) if actual != wanted]
    count, generation = len(values), index + 1
    header = struct.unpack("<4I", observed[:HEADER_BYTES])
    payload = observed[HEADER_BYTES:HEADER_BYTES + count * 4]
    tail = observed[HEADER_BYTES + count * 4:]
    header_equal = header == (MAGIC, count, count * 4, generation)
    scalar_bits_equal = payload == expected[HEADER_BYTES:HEADER_BYTES + count * 4]
    zero_tail = not any(tail)
    receipt_header = state["numeric_header"]
    receipt_equal = all(receipt_header[key] == value for key, value in
                        (("magic", MAGIC), ("scalar_count", count), ("byte_count", count * 4),
                         ("generation", generation), ("header_bytes", HEADER_BYTES),
                         ("capacity_bytes", CAPACITY_BYTES), ("cleared_bytes", len(tail))))
    result = {"name": name, "passed": not mismatch and header_equal and scalar_bits_equal and
              zero_tail and receipt_equal, "checked_bytes": len(observed), "scalar_count": count,
              "generation": generation, "header": dict(zip(("magic", "scalar_count", "byte_count", "generation"), header)),
              "header_exact": header_equal, "float32_bits_exact": scalar_bits_equal,
              "cleared_tail_bytes": len(tail), "zero_tail": zero_tail,
              "state_header_agrees": receipt_equal, "mismatch_bytes": len(mismatch),
              "first_mismatch_offsets": mismatch[:12], "observed_wire_sha256": sha256(observed),
              "expected_wire_sha256": sha256(expected), "observed_payload_sha256": sha256(payload),
              "source_hashes": hashes}
    if name == "numeric_special":
        result["float32_bits_hex"] = [payload[offset:offset + 4].hex() for offset in range(0, len(payload), 4)]
        decoded = struct.unpack("<7f", payload)
        result["decoded_float32"] = [value if math.isfinite(value) else None for value in decoded]
        result["nonfinite_scalar_indices"] = [index for index, value in enumerate(decoded)
                                               if not math.isfinite(value)]
        result["negative_zero_preserved"] = payload[:4] == b"\x00\x00\x00\x80"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--commands", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    results = []
    for index in range(9):
        try:
            results.append(verify_case(args.evidence, args.commands, index))
        except (ValueError, OSError, KeyError, TypeError, IndexError, SyntaxError) as error:
            results.append({"name": expected_case(index)[0], "passed": False, "error": str(error)})
    report = {"passed": all(case["passed"] for case in results),
              "scope": "nine_frozen_WGC_captures_independent_float32_bit_transport",
              "expected_source": "AST-checked recorded commands plus independent stdlib struct formula",
              "state_words_used_as_expected": False, "report_expected_used": False,
              "png_pixels_rechecked": True, "all_frames_verified": False,
              "gpu_float_arithmetic_verified": False, "case_count": len(results),
              "checked_bytes": sum(case.get("checked_bytes", 0) for case in results),
              "verifier_sha256": sha256(Path(__file__).read_bytes()), "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("passed", "case_count", "checked_bytes")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
