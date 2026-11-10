"""Compare captured MC glyphs with the generated desktop shader, excluding UI."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pyreact_manim.compiler.desktop import render_compiled


def bounds(mask):
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise ValueError("Compiled glyph has no visible pixels")
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def make_sheet(tiles, output):
    cell_width, cell_height = 340, 380
    rows = max(1, (len(tiles) + 2) // 3)
    sheet = Image.new("RGB", (3 * cell_width, rows * cell_height), (15, 18, 24))
    draw = ImageDraw.Draw(sheet)
    for index, (label, crop) in enumerate(tiles):
        x, y = index % 3 * cell_width, index // 3 * cell_height
        draw.text((x + 12, y + 10), label, fill=(220, 230, 240))
        crop = crop.copy()
        crop.thumbnail((cell_width - 24, cell_height - 48), Image.Resampling.LANCZOS)
        sheet.paste(crop, (x + (cell_width - crop.width) // 2, y + 36 + (cell_height - 48 - crop.height) // 2))
    sheet.save(output)


def analyze(report_path, output, scene_prefix="manimgl_"):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    viewport = report["viewport"]["used"]
    canvas_viewport = report["viewport"].get("canvas", [0.0, 1.0])
    output.mkdir(parents=True, exist_ok=True)
    frames, tiles = [], []
    for entry in report["frames"]:
        state = entry["state"]
        if not state["scene"].startswith(scene_prefix):
            continue
        capture_path = ROOT / entry["capture"].replace("\\", "/")
        manifest_path = ROOT / ".runtime/compiled" / state["scene"] / "scene.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for kind, deployed in (("shader", ROOT / "resource_pack/shaders/glsl" / (state["scene"] + ".fragment")),
                               ("texture", ROOT / "resource_pack/textures/manim" / (state["scene"] + ".png"))):
            if hashlib.sha256(deployed.read_bytes()).hexdigest() != manifest[kind]["sha256"]:
                raise ValueError("Deployed artifact differs from the compiled manifest")
        with Image.open(capture_path) as image:
            captured = image.convert("RGB")
        expected, driver = render_compiled(manifest_path, state["position"], *captured.size,
                                           viewport_uniform=viewport, canvas_viewport=canvas_viewport)
        expected_array = np.asarray(expected)
        foreground = np.max(expected_array, axis=2) > 16
        box = bounds(foreground)
        roi = [max(0, box[0] - 2), max(0, box[1] - 2), min(captured.width, box[2] + 2),
               min(captured.height, box[3] + 2)]
        actual_roi = np.asarray(captured.crop(roi)).astype(np.int16)
        expected_roi = np.asarray(expected.crop(roi)).astype(np.int16)
        colored = np.max(actual_roi, axis=2) - np.min(actual_roi, axis=2) > 12
        # The sample glyphs are white; player's time text is blue-grey.
        # Do not silently count an overlapping control as shader error.
        ui_pixels = int(np.count_nonzero(colored))
        delta = np.abs(actual_roi - expected_roi)
        actual_mask = np.max(actual_roi, axis=2) > 16
        expected_mask = np.max(expected_roi, axis=2) > 16
        union = actual_mask | expected_mask
        union_count = int(np.count_nonzero(union))
        frame = {"scene": state["scene"], "time": state["position"], "capture_size": list(captured.size),
                 "viewport_uniform": viewport, "canvas_viewport": canvas_viewport,
                 "roi": roi, "compiled_foreground_bbox": box,
                 "roi_rule": "compiled foreground bbox at threshold 16, expanded by 2 pixels",
                 "colored_ui_pixels_in_roi": ui_pixels, "roi_clear_of_colored_ui": ui_pixels == 0,
                 "capture_sha256": hashlib.sha256(capture_path.read_bytes()).hexdigest(),
                 "shader_sha256": manifest["shader"]["sha256"], "texture_sha256": manifest["texture"]["sha256"],
                 "pixel_exact_in_roi": bool(np.array_equal(actual_roi, expected_roi)),
                 "foreground_iou": float(np.count_nonzero(actual_mask & expected_mask) / union_count),
                 "mean_channel_error_255": float(delta.mean()), "maximum_channel_error_255": int(delta.max()),
                 "foreground_mean_channel_error_255": float(delta[union].mean()), "driver": driver}
        frames.append(frame)
        tiles.append(("%s  t=%.1fs" % (state["scene"].replace("manimgl_", ""), state["position"]), captured.crop(roi)))
        expected.save(capture_path.with_name(capture_path.stem + "_desktop.png"))
    if not frames:
        raise ValueError("No captured scenes match the requested prefix")
    result = {"kind": "minecraft_vs_generated_shader", "manim_reference_comparison": False,
              "scene_prefix": scene_prefix,
              "text_one_to_one_accepted": False, "frames": frames,
              "all_rois_clear_of_colored_ui": all(frame["roi_clear_of_colored_ui"] for frame in frames),
              "foreground_iou_range": [min(f["foreground_iou"] for f in frames), max(f["foreground_iou"] for f in frames)],
              "foreground_mean_error_255_range": [min(f["foreground_mean_channel_error_255"] for f in frames),
                                                    max(f["foreground_mean_channel_error_255"] for f in frames)],
              "limitations": ["Only the captured static states on this PC are compared.",
                              "Game viewport uniforms and capture dimensions may differ; both are recorded per frame.",
                              "Both sides use our generated shader; this checks MC transport/rendering, not Manim fidelity.",
                              "UI contamination check is scoped to these white glyph scenes and blue-grey player controls.",
                              "Original Manim comparison remains separate and has nonzero pixel differences."],
              "reproduction": "python tools/compare_game_captures.py --report " + str(report_path.relative_to(ROOT))}
    (output / "game_vs_compiled_summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    make_sheet(tiles, output / "game-contact-sheet.png")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/initial-text")
    parser.add_argument("--scene-prefix", default="manimgl_",
                        help="Only compare this prefix; UI-color detection assumes white text")
    args = parser.parse_args()
    result = analyze(args.report.resolve(), args.output.resolve(), args.scene_prefix)
    print(json.dumps({key: value for key, value in result.items() if key != "frames"}, indent=2))


if __name__ == "__main__":
    main()
