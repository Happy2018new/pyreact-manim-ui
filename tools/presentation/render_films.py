"""Stream both deployed films to MP4 with the exact game music/foley masters."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/showcase"))
spec = importlib.util.spec_from_file_location("_presentation_renderer", ROOT / "tools/showcase/render_film.py")
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)

FILMS = {
    "client_showcase": {"title": "Metamorphosis | Light unfolds", "folder": "client-showcase-v5",
                        "filename": "metamorphosis-cinematic-120s.mp4", "poster": 107.0,
                        "times": (3.6, 9, 14, 21, 29.2, 38.2, 49.2, 67.2, 85.2, 103, 108, 117)},
    "story_showcase": {"title": "The star borrowed by the wind", "folder": "storybook-wind-v1",
                       "filename": "the-star-borrowed-by-the-wind-120s.mp4", "poster": 101.0,
                       "times": (4, 12, 22, 31, 40, 50, 62, 72, 82, 92, 102, 116)},
}


def render(scene, args):
    film = FILMS[scene]
    shader = ROOT / "resource_pack/shaders/glsl" / (scene + ".fragment")
    texture = ROOT / "resource_pack/textures/manim" / (scene + ".png")
    audio = args.masters / (scene + ".wav")
    output = ROOT / "dist" / film["folder"] / film["filename"]
    if output.exists() and not args.overwrite:
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    config = SimpleNamespace(output=output, overwrite=args.overwrite, width=1920, height=1080,
                             fps=60, duration=120.0, crf=18, ffmpeg=args.ffmpeg)
    renderer = shared.FilmRenderer(shader, texture, config.width, config.height)
    try:
        renderer.image(film["poster"]).save(output.parent / "poster.png")
        shared.save_contact(renderer, film["times"], output.parent / "contact.png")
        video = shared.render_video(renderer, config, audio)
        driver = renderer.driver
    finally:
        renderer.close()
    retitled = output.with_name(output.stem + ".metadata.mp4")
    subprocess.run([shared.ffmpeg_path(args.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(output), "-map", "0", "-c", "copy", "-movflags", "+faststart",
                    "-metadata", "title=" + film["title"], "-metadata",
                    "comment=Offline export of game shader; original synthesized music and foley",
                    str(retitled)], check=True, timeout=60,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    retitled.replace(output)
    video.update(bytes=output.stat().st_size, sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    report = {"scene": scene, "kind": "offline_desktop_gl_shader_export", "game_capture": False,
              "shader_sha256": hashlib.sha256(shader.read_bytes()).hexdigest(),
              "texture_sha256": hashlib.sha256(texture.read_bytes()).hexdigest(),
              "audio_master_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
              "audio": {"original_synthesis": True, "external_samples": False,
                        "sample_rate": 48000, "channels": 2},
              "video": video, "driver": driver,
              "acceptance": "Not performed, per user request; delivered for user review."}
    output.with_suffix(".render.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", choices=tuple(FILMS) + ("all",), default="all")
    parser.add_argument("--masters", type=Path, default=ROOT / ".runtime/presentation-audio")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    for scene in FILMS if args.scene == "all" else (args.scene,):
        render(scene, args)
