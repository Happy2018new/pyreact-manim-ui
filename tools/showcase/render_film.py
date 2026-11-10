"""Export the actual showcase shader through desktop GL, with an original score.

The exported MP4 is an offline render of the same shader and atlas deployed in
Minecraft. It is deliberately labelled as such, not represented as game capture.
Frames stream directly to ffmpeg; a full movie never accumulates as PNG files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from pyreact_manim.compiler.desktop import VERTEX, desktop_fragment
from score import write_score

DEFAULT_TIMES = (1.5, 4.0, 6.5, 9.2, 12.0, 16.0, 20.5, 24.8, 28.5, 32.0, 35.5, 39.0)


class FilmRenderer:
    """One context, one program, one atlas for every frame of the film."""

    def __init__(self, shader: Path, texture: Path, width: int, height: int):
        import moderngl
        self.gl = moderngl
        self.width, self.height = width, height
        self.resources = []
        self.context = moderngl.create_standalone_context(require=330)
        try:
            self.program = self.context.program(
                vertex_shader=VERTEX,
                fragment_shader=desktop_fragment(shader.read_text(encoding="utf-8")),
            )
            self.resources.append(self.program)
            vertices = self.context.buffer(struct.pack("8f", -1, -1, 1, -1, -1, 1, 1, 1))
            self.resources.append(vertices)
            self.vertex_array = self.context.simple_vertex_array(self.program, vertices, "position")
            self.resources.append(self.vertex_array)
            with Image.open(texture) as source:
                pixels = source.convert("RGBA")
            atlas = self.context.texture(pixels.size, 4, pixels.tobytes())
            self.resources.append(atlas)
            atlas.filter = (moderngl.NEAREST, moderngl.NEAREST)
            atlas.repeat_x = atlas.repeat_y = False
            atlas.use(2)
            background = self.context.texture((1, 1), 4, bytes((0, 0, 0, 255)))
            self.resources.append(background)
            background.use(0)
            for name, value in (("TEXTURE_2", 2), ("TEXTURE_0", 0),
                                ("EXTRA_VECTOR2", (0.0, 0.0, 1.0, 0.0))):
                if name in self.program:
                    self.program[name].value = value
            if "EXTRA_VECTOR1" not in self.program:
                raise ValueError("Showcase shader must expose EXTRA_VECTOR1 playback input")
            self.framebuffer = self.context.simple_framebuffer((width, height), components=4)
            self.resources.append(self.framebuffer)
            self.framebuffer.use()
            self.driver = {name: self.context.info.get(name)
                           for name in ("GL_VENDOR", "GL_RENDERER", "GL_VERSION")}
        except BaseException:
            self.close()
            raise

    def frame(self, timestamp: float) -> bytes:
        """Return tightly packed RGB in OpenGL bottom-up order."""
        self.program["EXTRA_VECTOR1"].value = (
            timestamp, self.width / self.height, float(self.height), 1.0)
        self.vertex_array.render(self.gl.TRIANGLE_STRIP)
        return self.framebuffer.read(components=3, alignment=1)

    def image(self, timestamp: float) -> Image.Image:
        return Image.frombytes("RGB", (self.width, self.height), self.frame(timestamp)).transpose(
            Image.Transpose.FLIP_TOP_BOTTOM)

    def close(self):
        for resource in reversed(self.resources):
            resource.release()
        self.resources = []
        self.context.release()


def ffmpeg_path(explicit: str | None) -> str:
    path = explicit or shutil.which("ffmpeg")
    if not path and Path("C:/Sharing/ffmpeg/bin/ffmpeg.exe").is_file():
        path = "C:/Sharing/ffmpeg/bin/ffmpeg.exe"
    if not path or not Path(path).is_file():
        raise FileNotFoundError("Install ffmpeg or supply --ffmpeg <executable>")
    return str(path)


def save_contact(renderer: FilmRenderer, times: list[float], output: Path):
    tile_width = 480
    tile_height = round(tile_width * renderer.height / renderer.width)
    columns = min(4, len(times))
    rows = math.ceil(len(times) / columns)
    padding, caption = 12, 26
    image = Image.new("RGB", (columns * (tile_width + padding) + padding,
                              rows * (tile_height + caption + padding) + padding), (9, 14, 23))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=15)
    for index, timestamp in enumerate(times):
        x = padding + index % columns * (tile_width + padding)
        y = padding + index // columns * (tile_height + caption + padding)
        frame = renderer.image(timestamp).resize((tile_width, tile_height), Image.Resampling.LANCZOS)
        image.paste(frame, (x, y))
        draw.text((x + 4, y + tile_height + 5), "%05.2f s" % timestamp,
                  fill=(158, 181, 193), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def render_video(renderer, args, score_path: Path | None) -> dict:
    output = args.output.resolve()
    if output.exists() and not args.overwrite:
        raise FileExistsError("Use --overwrite to replace the previous film: " + str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.stem + ".partial.mp4")
    log_path = output.with_suffix(".ffmpeg.log")
    command = [ffmpeg_path(args.ffmpeg), "-hide_banner", "-y", "-loglevel", "warning",
               "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size",
               "%dx%d" % (args.width, args.height), "-framerate", str(args.fps), "-i", "pipe:0"]
    if score_path:
        command += ["-i", str(score_path), "-map", "0:v:0", "-map", "1:a:0"]
    command += ["-vf", "vflip,scale=in_range=pc:out_range=tv:out_color_matrix=bt709",
                "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf),
                "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709",
                "-colorspace", "bt709", "-color_range", "tv", "-movflags", "+faststart", "-metadata",
                "title=Let ideas be seen", "-metadata",
                "comment=Offline render of the Minecraft showcase shader; original synthesized score"]
    if score_path:
        command += ["-c:a", "aac", "-b:a", "256k", "-ar", "48000"]
    command += ["-t", str(args.duration), str(partial)]
    frame_count = round(args.duration * args.fps)
    started = time.perf_counter()
    with log_path.open("wb") as log:
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                   stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            for index in range(frame_count):
                encoder.stdin.write(renderer.frame(index / args.fps))
                if index % max(1, args.fps * 2) == 0:
                    print(json.dumps({"rendered": index, "frames": frame_count,
                                      "seconds": round(time.perf_counter() - started, 2)}), flush=True)
            encoder.stdin.close()
            code = encoder.wait(timeout=180)
            if code:
                raise RuntimeError("ffmpeg failed (%d); inspect %s" % (code, log_path))
        except BaseException:
            if encoder.poll() is None:
                encoder.kill()
            encoder.wait(timeout=15)
            raise
    partial.replace(output)
    return {"path": str(output), "frames": frame_count, "fps": args.fps,
            "duration": frame_count / args.fps, "width": args.width, "height": args.height,
            "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "render_seconds": round(time.perf_counter() - started, 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shader", type=Path,
                        default=ROOT / "resource_pack/shaders/glsl/client_showcase.fragment")
    parser.add_argument("--texture", type=Path,
                        default=ROOT / "resource_pack/textures/manim/client_showcase.png")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "dist/client-showcase/let-ideas-be-seen.mp4")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--duration", type=float, default=41.0)
    parser.add_argument("--contact", type=Path)
    parser.add_argument("--poster", type=Path)
    parser.add_argument("--poster-time", type=float, default=37.0)
    parser.add_argument("--times", help="Comma-separated contact-sheet timestamps")
    parser.add_argument("--frame", type=float, help="Export one PNG at this time")
    parser.add_argument("--frame-output", type=Path)
    parser.add_argument("--stills-only", action="store_true")
    parser.add_argument("--silent", action="store_true", help="Omit the original soundtrack")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if not 2 <= args.width <= 7680 or not 2 <= args.height <= 4320:
        parser.error("Invalid output dimensions")
    if args.width % 2 or args.height % 2:
        parser.error("H.264 yuv420p output dimensions must be even")
    if not 1 <= args.fps <= 120 or not math.isfinite(args.duration) or not 1 <= args.duration <= 300:
        parser.error("Invalid duration or frame rate")
    times = ([float(value) for value in args.times.split(",") if value.strip()]
             if args.times is not None else [value for value in DEFAULT_TIMES if value <= args.duration])
    if not times and args.times is None:
        times = [args.duration * 0.5]
    if not times or any(not math.isfinite(value) or not 0 <= value <= args.duration for value in times):
        parser.error("Contact times must be finite and within the film")
    if args.frame is not None and (not math.isfinite(args.frame) or not 0 <= args.frame <= args.duration):
        parser.error("Frame time must be within the film")
    if not 0 <= args.poster_time <= args.duration:
        # Short encode smoke tests should not need a separate poster timestamp.
        args.poster_time = args.duration * 0.8
    if args.frame is not None and args.frame_output is None:
        parser.error("--frame requires --frame-output")
    report = {"kind": "offline_desktop_gl_shader_export", "game_capture": False,
              "shader": str(args.shader.resolve()), "texture": str(args.texture.resolve()),
              "shader_sha256": hashlib.sha256(args.shader.read_bytes()).hexdigest(),
              "texture_sha256": hashlib.sha256(args.texture.read_bytes()).hexdigest()}
    renderer = FilmRenderer(args.shader, args.texture, args.width, args.height)
    try:
        report["driver"] = renderer.driver
        if args.contact:
            save_contact(renderer, times, args.contact)
            report["contact"] = str(args.contact.resolve())
        if args.poster:
            args.poster.parent.mkdir(parents=True, exist_ok=True)
            renderer.image(args.poster_time).save(args.poster)
            report["poster"] = str(args.poster.resolve())
        if args.frame is not None:
            args.frame_output.parent.mkdir(parents=True, exist_ok=True)
            renderer.image(args.frame).save(args.frame_output)
            report["frame"] = {"time": args.frame, "path": str(args.frame_output.resolve())}
        if not args.stills_only:
            score_path = None
            if not args.silent:
                score_path = ROOT / ".runtime/showcase-export/score.wav"
                report["audio"] = write_score(score_path, args.duration)
            report["video"] = render_video(renderer, args, score_path)
    finally:
        renderer.close()
    report_path = args.output.with_suffix(".stills.json" if args.stills_only else ".render.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
