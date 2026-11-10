"""Compare a native Manim reference PNG against the compiled desktop shader."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pyreact_manim.compiler.desktop import render_compiled


def _bounds(mask):
    rows, columns = np.nonzero(mask)
    if len(rows) == 0:
        return None
    return [int(columns.min()), int(rows.min()), int(columns.max()) + 1, int(rows.max()) + 1]


def compare(manifest_path, reference_path, timestamp, output, reference_kind="unspecified"):
    manifest_path, reference_path, output = map(Path, (manifest_path, reference_path, output))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with Image.open(reference_path) as source:
        reference = source.convert("RGB")
    rendered, driver = render_compiled(manifest_path, timestamp, *reference.size)
    a, b = np.asarray(reference).astype(np.int16), np.asarray(rendered).astype(np.int16)
    difference = np.abs(a - b)
    background = np.asarray(manifest["canvas"]["background"]) * 255
    mask_a = np.max(np.abs(a - background), axis=2) > 16
    mask_b = np.max(np.abs(b - background), axis=2) > 16
    union = mask_a | mask_b
    union_count = int(np.count_nonzero(union))
    intersection_count = int(np.count_nonzero(mask_a & mask_b))
    report = {
        "scope": "supplied reference PNG versus desktop GLSL adaptation of compiled MC shader",
        "reference_kind": reference_kind,
        "minecraft_verified": False,
        "pixel_exact": bool(np.array_equal(a, b)),
        "time": timestamp, "size": list(reference.size), "driver": driver,
        "maximum_channel_error_255": int(difference.max()),
        "mean_channel_error_255": float(difference.mean()),
        "foreground_mean_channel_error_255": float(difference[union].mean()) if union_count else 0,
        "foreground_iou": intersection_count / union_count if union_count else 1,
        "foreground_union_pixels": union_count,
        "reference_bounds": _bounds(mask_a), "compiled_bounds": _bounds(mask_b),
        "differing_pixels": int(np.count_nonzero(np.any(difference != 0, axis=2))),
        "reference_sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
        "compiled_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "compiled_shader_sha256": hashlib.sha256((manifest_path.parent / manifest["shader"]["path"]).read_bytes()).hexdigest(),
        "compiled_texture_sha256": hashlib.sha256((manifest_path.parent / manifest["texture"]["path"]).read_bytes()).hexdigest(),
        "compiled_coverage": manifest["precision"]["coverage"],
        "compiled_fill_approximations": manifest["precision"].get("native_fill_approximations"),
        "limitations": ["Different antialiasing rules may cause edge discrepancies.",
                        "Curves were sampled into closed polylines or shared-base directed fans by the exporter.",
                        "Intermediate times linearly interpolate exported samples.",
                        "This diagnostic does not declare the text 1:1 acceptance complete."],
    }
    output.mkdir(parents=True, exist_ok=True)
    rendered.save(output / "compiled.png")
    difference_image = Image.fromarray(np.uint8(np.clip(difference * 4, 0, 255)))
    difference_image.save(output / "difference-x4.png")
    width, height = reference.size
    comparison = Image.new("RGB", (width * 3, height + 28), (30, 30, 30))
    draw = ImageDraw.Draw(comparison)
    for index, (label, image) in enumerate((("Reference: " + reference_kind, reference),
                                          ("Compiled shader (desktop OpenGL)", rendered),
                                          ("Absolute difference x4", difference_image))):
        draw.text((index * width + 8, 8), label, fill="white")
        comparison.paste(image, (index * width, 28))
    comparison.save(output / "comparison.png")
    (output / "comparison.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiled-manifest", required=True, type=Path)
    parser.add_argument("--reference-image", required=True, type=Path)
    parser.add_argument("--time", required=True, type=float)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reference-kind", choices=("manim", "diagnostic", "unspecified"), default="unspecified")
    args = parser.parse_args()
    print(json.dumps(compare(args.compiled_manifest, args.reference_image, args.time, args.output,
                             args.reference_kind), indent=2))


if __name__ == "__main__":
    main()
