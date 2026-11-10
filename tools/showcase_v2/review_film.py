"""Sample the actual film shader at transitions, boundaries and static holds.

This offline tool renders pixels, not SDK return values. It also derives an
isolated typography pass from the exact production shader so moving background
geometry cannot masquerade as unstable held text. Contact sheets require human
review; numeric checks are deliberately limited to final-frame finiteness,
unexpected black output, and explicitly declared static typography intervals.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/showcase"))
_spec = importlib.util.spec_from_file_location("_review_shared_renderer", ROOT / "tools/showcase/render_film.py")
shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shared)

DEFAULT_BOUNDARIES = (0.0, 2.4, 12.0, 28.0, 48.0, 66.0, 84.0, 102.0, 114.0, 120.0)
# Only a fallback for legacy manifests; new manifests supply the authored crop.
LEGACY_BOUNDS = {
    "opening": (-6.6, -1.2, 6.6, 1.7), "matrix": (3.6, -3.7, 7.6, -1.8),
    "algebra": (-6.5, -1.3, 6.5, 1.8), "complex": (-6.4, 1.65, 6.4, 3.25),
    "calculus": (-6.4, 1.55, 6.4, 3.3), "harmonics": (-7.1, 1.5, 7.1, 3.35),
    "finale": (-6.5, -1.0, 6.5, 1.4), "closing": (-6.6, -1.0, 6.6, 1.4),
}


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def isolate_typography(source):
    marker = "void main()"
    if source.count(marker) != 1 or "void typography(" not in source:
        raise ValueError("Expected exactly one film main and the production typography function")
    prefix = source.split(marker, 1)[0]
    return prefix + r"""
// Diagnostic only: use the production typography function without atmosphere.
void main() {
    vec2 v=uv;
    if(EXTRA_VECTOR2.x>0.5) v.y=1.0-v.y;
    float height=EXTRA_VECTOR2.z>0.0?EXTRA_VECTOR2.z:1.0;
    vec2 local=vec2(v.x,(v.y-EXTRA_VECTOR2.y)/height);
    float aspect=EXTRA_VECTOR1.y;
    float narrow=max(1.0,(16.0/9.0)/aspect);
    vec2 p=vec2((local.x-0.5)*aspect,0.5-local.y)*9.0*narrow;
    float aa=9.0/max(EXTRA_VECTOR1.z,1.0)*narrow;
    float t=clamp(EXTRA_VECTOR1.x,0.0,120.0);
    vec3 c=vec3(0.0);
    typography(c,p,t,aa);
    gl_FragColor=vec4(c,1.0);
}
"""


def world_crop(bounds, width, height):
    xmin, ymin, xmax, ymax = map(float, bounds)
    if not xmin < xmax or not ymin < ymax:
        raise ValueError("review_bounds must be [xmin, ymin, xmax, ymax]")
    aspect = width / height
    narrow = max(1.0, (16.0 / 9.0) / aspect)
    xscale, yscale = width / (9 * aspect * narrow), height / (9 * narrow)
    box = (math.floor(width / 2 + xmin * xscale), math.floor(height / 2 - ymax * yscale),
           math.ceil(width / 2 + xmax * xscale), math.ceil(height / 2 - ymin * yscale))
    return (max(0, box[0]), max(0, box[1]), min(width, box[2]), min(height, box[3]))


def event_timing(event):
    if "transition_start" in event and "transition_end" in event:
        return float(event["transition_start"]), float(event["transition_end"]), "explicit"
    begin, end = float(event["start"]), float(event["end"])
    if event["chapter"] == "closing":
        return begin, end, "legacy_inferred"
    return begin + min(0.8, (end - begin) * 0.25), end - 0.3, "legacy_inferred"


def sample_plan(manifest, fps):
    duration = float(manifest["duration"])
    step = 1 / fps
    events, plans = [], []
    for index, original in enumerate(manifest["glyph_transitions"]):
        event = dict(original)
        begin, end, mode = event_timing(event)
        if not 0 <= begin <= end <= duration:
            raise ValueError("Invalid transition timing: " + repr(event))
        event.update(index=index, review_transition_start=begin, review_transition_end=end,
                     timing_contract=mode)
        events.append(event)
        for phase, timestamp in (("before", begin - step), ("middle", (begin + end) / 2),
                                 ("after", end), ("after_200ms", end + 0.2)):
            plans.append({"kind": "transition", "event": index, "chapter": event["chapter"],
                          "phase": phase, "time": max(0.0, min(duration, timestamp))})
    boundaries = set(DEFAULT_BOUNDARIES)
    for value in manifest.get("chapter_boundaries", []):
        boundaries.add(float(value["time"] if isinstance(value, dict) else value))
    for event in events:
        boundaries.add(float(event["start"]))
        boundaries.add(float(event["end"]))
    for boundary in sorted(boundaries):
        if not 0 <= boundary <= duration:
            continue
        for phase, offset in (("before", -step), ("at", 0.0), ("after", step)):
            timestamp = max(0.0, min(duration, boundary + offset))
            plans.append({"kind": "boundary", "boundary": boundary, "phase": phase, "time": timestamp})
    holds = []
    for event in events:
        end = event["review_transition_end"]
        hold_until = event.get("hold_until")
        if hold_until is None:
            # Legacy event end is not proof of the next hold duration. Export
            # transition frames but do not invent a stability acceptance result.
            continue
        hold_until = min(float(hold_until), duration)
        first, last = end + 0.08, min(end + 0.45, hold_until - step)
        if last <= first + step:
            continue
        hold = {"event": event["index"], "chapter": event["chapter"],
                "times": [first, last], "declared_hold_until": hold_until}
        holds.append(hold)
        for phase, timestamp in zip(("hold_a", "hold_b"), hold["times"]):
            plans.append({"kind": "hold", "event": event["index"], "chapter": event["chapter"],
                          "phase": phase, "time": timestamp})
    return events, plans, holds


def float_framebuffer(renderer):
    """Retain HDR values for checking actual final shader output, including NaN."""
    texture = renderer.context.texture((renderer.width, renderer.height), 4, dtype="f4")
    renderer.resources.append(texture)
    framebuffer = renderer.context.framebuffer(color_attachments=[texture])
    renderer.resources.append(framebuffer)
    renderer.framebuffer = framebuffer
    framebuffer.use()


def render_sample(renderer, timestamp):
    renderer.program["EXTRA_VECTOR1"].value = (
        timestamp, renderer.width / renderer.height, float(renderer.height), 1.0)
    renderer.vertex_array.render(renderer.gl.TRIANGLE_STRIP)
    raw = renderer.framebuffer.read(components=3, dtype="f4", alignment=1)
    pixels = np.frombuffer(raw, dtype=np.float32).reshape(renderer.height, renderer.width, 3)[::-1]
    finite = np.isfinite(pixels)
    valid = bool(finite.all())
    safe = np.where(finite, pixels, 0)
    normalized = np.clip(safe, 0, 1)
    image = Image.fromarray(np.rint(normalized * 255).astype(np.uint8))
    metric = {"finite_output": valid, "nonfinite_components": int((~finite).sum()),
              "min": float(safe.min()), "max": float(safe.max()),
              "mean_rgb": [float(x) for x in normalized.mean(axis=(0, 1))],
              "lit_pixel_fraction": float(np.any(normalized > 0.06, axis=2).mean()),
              "unexpected_full_black": bool(timestamp > 0.7 and normalized.max() < 0.008)}
    return image, metric


def contact_sheet(rows, destination, caption, thumb_width=480):
    """Each row is (description, [(image_path, label, crop_or_none), ...])."""
    thumb_height = 270
    columns = max(len(row[1]) for row in rows)
    header, label_height, row_title, gap = 52, 24, 27, 10
    width = columns * (thumb_width + gap) + gap
    row_height = row_title + thumb_height + label_height + gap
    canvas = Image.new("RGB", (width, header + len(rows) * row_height), (8, 14, 24))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=15)
    title_font = ImageFont.load_default(size=19)
    draw.text((12, 14), caption, fill=(223, 235, 244), font=title_font)
    for row_index, (title, frames) in enumerate(rows):
        y = header + row_index * row_height
        draw.text((12, y + 3), title, fill=(95, 215, 236), font=font)
        y += row_title
        for column, (path, label, crop) in enumerate(frames):
            with Image.open(path) as source:
                picture = source.convert("RGB")
            if crop is not None:
                picture = picture.crop(crop)
            picture.thumbnail((thumb_width, thumb_height), Image.Resampling.LANCZOS)
            x = gap + column * (thumb_width + gap)
            canvas.paste(picture, (x + (thumb_width - picture.width) // 2,
                                   y + (thumb_height - picture.height) // 2))
            draw.text((x + 4, y + thumb_height + 3), label, fill=(166, 185, 201), font=font)
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "tools/showcase_v2/film.json")
    parser.add_argument("--shader", type=Path, default=ROOT / "resource_pack/shaders/glsl/client_showcase.fragment")
    parser.add_argument("--texture", type=Path, default=ROOT / "resource_pack/textures/manim/client_showcase.png")
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/showcase-v3-review/final")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--offline-only", action="store_true",
                        help="Export full/isolated references and contacts without numeric pass/fail")
    parser.add_argument("--allow-legacy-timing", action="store_true")
    args = parser.parse_args()
    if not 16 <= args.width <= 7680 or not 16 <= args.height <= 4320 or not 1 <= args.fps <= 120:
        parser.error("Invalid dimensions/frame rate")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if checksum(args.shader) != manifest["shader_sha256"] or checksum(args.texture) != manifest["texture_sha256"]:
        raise ValueError("Manifest and shader/texture hashes do not match")
    events, plans, holds = sample_plan(manifest, args.fps)
    if any(event["timing_contract"] != "explicit" for event in events) and not args.allow_legacy_timing:
        raise ValueError("Manifest needs explicit transition_start/transition_end (or --allow-legacy-timing for baseline)")
    args.output.mkdir(parents=True, exist_ok=True)
    isolated = args.output / "isolated-typography.fragment"
    isolated.write_text(isolate_typography(args.shader.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    timestamps = sorted({round(item["time"], 9) for item in plans})
    captures, metrics = {}, []
    for kind, shader in (("full", args.shader), ("type", isolated)):
        renderer = shared.FilmRenderer(shader, args.texture, args.width, args.height)
        float_framebuffer(renderer)
        try:
            for index, timestamp in enumerate(timestamps):
                image, metric = render_sample(renderer, timestamp)
                path = args.output / "frames" / ("%s-%010.6f.png" % (kind, timestamp))
                path.parent.mkdir(parents=True, exist_ok=True)
                image.save(path)
                captures[(kind, timestamp)] = path
                metric.update(kind=kind, time=timestamp, image=str(path.resolve()), sha256=checksum(path))
                metrics.append(metric)
                if index % 20 == 0:
                    print(json.dumps({"pass": kind, "sample": index, "total": len(timestamps)}), flush=True)
        finally:
            renderer.close()
    def capture(kind, timestamp):
        return captures[(kind, round(timestamp, 9))]
    sheets = []
    for chapter in dict.fromkeys(event["chapter"] for event in events):
        rows, crop_rows = [], []
        for event in (item for item in events if item["chapter"] == chapter):
            selected = [item for item in plans if item["kind"] == "transition" and item["event"] == event["index"]]
            description = "%02d %s -> %s | %.3f..%.3fs" % (
                event["index"], event["source"], event["target"],
                event["review_transition_start"], event["review_transition_end"])
            bounds = event.get("review_bounds", LEGACY_BOUNDS.get(chapter, (-8, -4.5, 8, 4.5)))
            crop = world_crop(bounds, args.width, args.height)
            rows.append((description, [(capture("full", item["time"]),
                                       "%s %.6f" % (item["phase"], item["time"]), None) for item in selected]))
            crop_rows.append((description, [(capture("type", item["time"]),
                                            "%s %.6f" % (item["phase"], item["time"]), crop) for item in selected]))
        for kind, content in (("full", rows), ("type", crop_rows)):
            path = args.output / ("contact-%s-%s.png" % (chapter, kind))
            contact_sheet(content, path, "%s / %s / production shader samples" % (chapter.upper(), kind))
            sheets.append(str(path.resolve()))
    boundary_groups = defaultdict(list)
    for plan in plans:
        if plan["kind"] == "boundary":
            boundary_groups[plan["boundary"]].append(plan)
    for page in range(math.ceil(len(boundary_groups) / 8)):
        rows = []
        for boundary, selected in list(boundary_groups.items())[page * 8:(page + 1) * 8]:
            rows.append(("boundary %.6f s" % boundary,
                         [(capture("full", item["time"]), "%s %.6f" % (item["phase"], item["time"]), None)
                          for item in selected]))
        path = args.output / ("contact-boundaries-%02d.png" % page)
        contact_sheet(rows, path, "Boundary continuity: one frame before / at / after")
        sheets.append(str(path.resolve()))
    hold_checks = []
    for hold in holds:
        event = events[hold["event"]]
        bounds = event.get("review_bounds", LEGACY_BOUNDS.get(event["chapter"], (-8, -4.5, 8, 4.5)))
        crop = world_crop(bounds, args.width, args.height)
        arrays = []
        for timestamp in hold["times"]:
            with Image.open(capture("type", timestamp)) as source:
                arrays.append(np.asarray(source.crop(crop), dtype=np.int16))
        difference = np.abs(arrays[0] - arrays[1])
        hold_checks.append(dict(hold, crop=list(crop), review_bounds=list(bounds),
                                identical=bool(not difference.any()),
                                max_channel_delta=int(difference.max()),
                                changed_pixels=int(np.any(difference, axis=2).sum()),
                                target_nonempty=bool(arrays[0].max() > 24),
                                comparison="isolated production typography, 8-bit displayed pixels"))
    critical_continuity = []
    for boundary in (2.4, 114.0):
        selected = boundary_groups.get(boundary, [])
        crop = world_crop((-6.6, -1.25, 6.6, 1.8), args.width, args.height)
        coverage = []
        for item in selected:
            with Image.open(capture("type", item["time"])) as source:
                pixels = np.asarray(source.crop(crop), dtype=np.float32) / 255
            coverage.append({"phase": item["phase"], "time": item["time"],
                             "mean_max_channel": float(pixels.max(axis=2).mean()),
                             "lit_pixels": int(np.any(pixels > 0.1, axis=2).sum())})
        values = [item["mean_max_channel"] for item in coverage]
        largest = max(values, default=0.0)
        relative_change = (largest - min(values)) / largest if largest else 0.0
        critical_continuity.append({"boundary": boundary, "samples": coverage,
                                    "crop": list(crop), "relative_coverage_change": relative_change,
                                    "needs_attention": bool(largest > 0.001 and relative_change > 0.5),
                                    "interpretation": "Large one-frame brightness/coverage jump needs visual review; not a full-image equality test."})
    failures = []
    if not args.offline_only:
        failures += ["nonfinite %s %.6f" % (row["kind"], row["time"]) for row in metrics if not row["finite_output"]]
        failures += ["black full frame %.6f" % row["time"] for row in metrics
                     if row["kind"] == "full" and row["unexpected_full_black"]]
        failures += ["unstable held typography event %d" % row["event"] for row in hold_checks if not row["identical"]]
        failures += ["empty held typography event %d" % row["event"] for row in hold_checks if not row["target_nonempty"]]
        failures += ["critical one-frame typography discontinuity at %.6f" % row["boundary"]
                     for row in critical_continuity if row["needs_attention"]]
    report = {"kind": "actual_shader_offline_frame_review", "game_tested": False,
              "offline_only": args.offline_only, "visual_acceptance": "requires human contact-sheet review",
              "shader_sha256": checksum(args.shader), "texture_sha256": checksum(args.texture),
              "width": args.width, "height": args.height, "fps": args.fps,
              "unique_timestamps": len(timestamps), "rendered_frames": len(metrics),
              "events": events, "sample_plan": plans, "frame_metrics": metrics,
              "hold_checks": hold_checks, "contact_sheets": sheets, "numeric_failures": failures,
              "critical_continuity": critical_continuity,
              "numeric_passed": None if args.offline_only else not failures,
              "limits": ["Held text checks use declared static intervals and exclude dynamic backgrounds.",
                         "Final output finiteness does not prove every intermediate shader expression is finite.",
                         "Numeric checks do not judge shape correspondence, legibility or artistic quality."]}
    target = args.output / "review.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(target.resolve()), "frames": len(metrics), "holds": len(hold_checks),
                      "numeric_passed": report["numeric_passed"], "failures": failures}, indent=2), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
