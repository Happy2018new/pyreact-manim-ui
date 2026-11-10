"""Verify 256 diagnostic texels in an owner-captured screenshot, offline."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import zlib

from PIL import Image, ImageStat


def host_fingerprints(receipt, data_png):
    """Hash captured runtime bytes on host; reject stale/changed data files."""
    png = Path(data_png).read_bytes()
    with Image.open(io.BytesIO(png)) as image:
        if image.size != (16, 16) or image.mode != "RGBA":
            raise ValueError("Runtime PNG must be 16x16 RGBA")
        rgba = image.tobytes()
    for label, payload in (("png", png), ("rgba", rgba)):
        crc = "%08x" % (zlib.crc32(payload) & 0xffffffff)
        if receipt.get(label + "_crc32") != crc:
            raise ValueError("Runtime " + label + " bytes no longer match the receipt CRC32")
    return {"host_png_sha256": hashlib.sha256(png).hexdigest(),
            "host_rgba_sha256": hashlib.sha256(rgba).hexdigest()}


def compare_capture(capture, receipt, rectangle=None, flip_y=False, tolerance=2):
    if receipt.get("probe") != "pmanim_runtime_data_v1" or len(receipt.get("values", [])) != 256:
        raise ValueError("Not a complete runtime probe data receipt")
    if not 0 <= tolerance <= 4:
        raise ValueError("Diagnostic tolerance must remain between 0 and 4 byte values")
    image = capture.convert("RGB")
    left, top, width, height = rectangle or (0, 0, image.width, image.height)
    if min(left, top) < 0 or min(width, height) < 16 or left + width > image.width or top + height > image.height:
        raise ValueError("Diagnostic rectangle falls outside the capture")
    samples = []
    matched = 0
    exact = 0
    maximum = 0
    total_error = 0
    for index, value in enumerate(receipt["values"]):
        column, row = index % 16, index // 16
        if flip_y:
            row = 15 - row
        x = min(image.width - 1, int(left + (column + 0.5) * width / 16.0))
        y = min(image.height - 1, int(top + (row + 0.5) * height / 16.0))
        # A single center texel is enough for a perfectly flat test grid;
        # average 3x3 only when each grid cell is large enough to contain it.
        radius = 1 if min(width, height) >= 64 else 0
        crop = image.crop((max(left, x - radius), max(top, y - radius),
                           min(left + width, x + radius + 1), min(top + height, y + radius + 1)))
        observed = [int(round(channel)) for channel in ImageStat.Stat(crop).median]
        expected = [value >> 8, value & 255, 0]
        errors = [abs(actual - want) for actual, want in zip(observed, expected)]
        largest = max(errors)
        maximum = max(maximum, largest)
        total_error += sum(errors)
        matched += int(largest <= tolerance)
        exact += int(observed == expected)
        samples.append({"index": index, "expected": expected, "observed": observed,
                        "decoded_uint16": observed[0] * 256 + observed[1], "max_byte_error": largest})
    return {"probe": receipt["probe"], "seed": receipt["seed"], "slot": receipt["slot"],
            "png_crc32": receipt["png_crc32"], "rgba_crc32": receipt["rgba_crc32"],
            "rectangle": [left, top, width, height],
            "flip_y": flip_y, "tolerance": tolerance, "matched_texels": matched,
            "exact_texels": exact, "total_texels": 256, "max_byte_error": maximum,
            "mean_byte_error": total_error / 768.0,
            "gpu_data_verified": matched == 256, "samples": samples}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--data-png", type=Path, help="Preserved runtime PNG; defaults to receipt absolute_png")
    parser.add_argument("--rect", type=int, nargs=4, metavar=("LEFT", "TOP", "WIDTH", "HEIGHT"))
    parser.add_argument("--flip-y", action="store_true")
    parser.add_argument("--tolerance", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    with Image.open(args.capture) as capture:
        result = compare_capture(capture, receipt, args.rect, args.flip_y, args.tolerance)
    result.update(host_fingerprints(receipt, args.data_png or receipt["absolute_png"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}, indent=2))
    raise SystemExit(0 if result["gpu_data_verified"] else 1)
