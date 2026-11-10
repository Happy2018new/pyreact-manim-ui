"""Export the two-minute Metamorphosis film using the shared shader renderer.

Reuse the original persistent GL context, contact sheet and streaming encoder.
This file supplies only v2 orchestration, score and delivery metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from score import write_score

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_showcase_renderer_shared", ROOT / "tools/showcase/render_film.py")
shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shared)

DEFAULT_TIMES = (3, 7, 10, 15, 21, 26, 31, 37, 44, 51, 58, 64,
                 69, 75, 81, 87, 93, 100, 105, 109, 112, 115, 117, 119)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shader", type=Path, default=ROOT / "resource_pack/shaders/glsl/client_showcase.fragment")
    parser.add_argument("--texture", type=Path, default=ROOT / "resource_pack/textures/manim/client_showcase.png")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/client-showcase-v2/metamorphosis-120s.mp4")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--contact", type=Path)
    parser.add_argument("--poster", type=Path)
    parser.add_argument("--poster-time", type=float, default=117.0)
    parser.add_argument("--times")
    parser.add_argument("--frame", type=float)
    parser.add_argument("--frame-output", type=Path)
    parser.add_argument("--stills-only", action="store_true")
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if not 2 <= args.width <= 7680 or not 2 <= args.height <= 4320 or args.width % 2 or args.height % 2:
        parser.error("Output dimensions must be even and within 2..7680 by 2..4320")
    if not 1 <= args.fps <= 120 or not math.isfinite(args.duration) or not 1 <= args.duration <= 300:
        parser.error("Invalid frame rate or duration")
    times = ([float(value) for value in args.times.split(",") if value.strip()]
             if args.times is not None else [value for value in DEFAULT_TIMES if value <= args.duration])
    if not times and args.times is None:
        times = [args.duration / 2]
    if not times or any(not math.isfinite(value) or not 0 <= value <= args.duration for value in times):
        parser.error("Contact times must be within the film")
    if args.frame is not None and (not math.isfinite(args.frame) or not 0 <= args.frame <= args.duration or args.frame_output is None):
        parser.error("--frame requires a valid timestamp and --frame-output")
    if not math.isfinite(args.poster_time) or not 0 <= args.poster_time <= args.duration:
        args.poster_time = args.duration * 0.8
    report = {"kind": "offline_desktop_gl_shader_export", "game_capture": False,
              "film": "Metamorphosis", "shader": str(args.shader.resolve()),
              "texture": str(args.texture.resolve()),
              "shader_sha256": hashlib.sha256(args.shader.read_bytes()).hexdigest(),
              "texture_sha256": hashlib.sha256(args.texture.read_bytes()).hexdigest()}
    renderer = shared.FilmRenderer(args.shader, args.texture, args.width, args.height)
    try:
        report["driver"] = renderer.driver
        if args.contact:
            shared.save_contact(renderer, times, args.contact)
            report["contact"] = str(args.contact.resolve())
        for timestamp, output in ((args.poster_time, args.poster), (args.frame, args.frame_output)):
            if timestamp is not None and output is not None:
                output.parent.mkdir(parents=True, exist_ok=True)
                renderer.image(timestamp).save(output)
        if args.poster:
            report["poster"] = str(args.poster.resolve())
        if not args.stills_only:
            score = None
            if not args.silent:
                score = ROOT / ".runtime/showcase-v2-export" / (args.output.stem + "-score.wav")
                report["audio"] = write_score(score, args.duration)
            report["video"] = shared.render_video(renderer, args, score)
            # Keep the shared encoder untouched; replace only the v1 container
            # title with a fast stream-copy pass, preserving faststart and pixels.
            started = time.perf_counter()
            retitled = args.output.with_name(args.output.stem + ".metadata.mp4")
            subprocess.run([shared.ffmpeg_path(args.ffmpeg), "-v", "error", "-y", "-i", str(args.output),
                            "-map", "0", "-c", "copy", "-movflags", "+faststart", "-metadata",
                            "title=Metamorphosis | A visual language", "-metadata",
                            "comment=Offline shader film; original synthesized electronic score; not game capture",
                            str(retitled)], check=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            retitled.replace(args.output)
            report["video"].update(bytes=args.output.stat().st_size,
                                   sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),
                                   metadata_seconds=round(time.perf_counter() - started, 3))
    finally:
        renderer.close()
    target = args.output.with_suffix(".stills.json" if args.stills_only else ".render.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
