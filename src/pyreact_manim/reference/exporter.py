"""Run real, pinned ManimGL Text/Transform and export its aligned outlines.

This is deliberately an adapter for one supported scene, not a reimplementation
of glyph matching, contour alignment, or Manim's interpolation semantics.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from importlib import metadata
import json
import math
from pathlib import Path
import platform
import sys

from .sampling import (choose_subdivisions, chord_error_bound, contour_curves,
                       sample_contour, signed_area)


PINNED_MANIMGL = "1.7.2"
UPSTREAM_COMMIT = "f427fc67df75513be0cd3f3329e327a9a19401c3"
UPSTREAM_WHEEL_SHA256 = "e2644c93cffd93ea56ddded9c9752b9371f7d2d19e99da5693dd03b2e0d658e4"
REPOSITORY = Path(__file__).resolve().parents[3]
DEFAULT_FONT = REPOSITORY / "tools/reference/fonts/DejaVuSerif.ttf"


@dataclass(frozen=True)
class ExportSettings:
    source: str = "O"
    target: str = "B"
    name: str = "manimgl_o_to_b"
    font: str = "DejaVu Serif"
    font_file: Path | None = DEFAULT_FONT
    glyph_height: float = 4.0
    duration: float = 2.0
    frame_count: int = 61
    width: float = 128.0 / 9.0
    height: float = 8.0
    tolerance: float = 0.003
    render_reference: bool = False
    reference_resolution: tuple[int, int] = (1280, 720)
    geometry_mode: str = "contours"
    allow_marker_approximation: bool = False
    input_kind: str = "text"
    tex_template: str = "basic"


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@contextmanager
def _upstream_import_arguments():
    # ManimGL 1.7.2 parses the process CLI in config.py at import time.
    # Our exporter owns its CLI; never let Manim interpret those arguments.
    arguments = sys.argv
    try:
        sys.argv = arguments[:1]
        yield
    finally:
        sys.argv = arguments


def _reference_environment():
    version = metadata.version("manimgl")
    if version != PINNED_MANIMGL:
        raise RuntimeError("Expected official ManimGL %s, found %s" % (PINNED_MANIMGL, version))
    with _upstream_import_arguments():
        import manimlib
    root = Path(manimlib.__file__).resolve().parent
    source_files = ["animation/animation.py", "animation/transform.py", "mobject/mobject.py",
                    "mobject/types/vectorized_mobject.py", "mobject/svg/text_mobject.py", "mobject/svg/string_mobject.py",
                    "mobject/svg/tex_mobject.py", "utils/tex_file_writing.py", "tex_templates.yml",
                    "camera/camera.py", "shader_wrapper.py", "utils/rate_functions.py", "utils/paths.py",
                    "shaders/quadratic_bezier/fill/geom.glsl", "shaders/quadratic_bezier/fill/frag.glsl"]
    packages = ["manimgl", "ManimPango", "numpy", "Pillow", "moderngl", "glcontext",
                "fonttools", "scipy", "setuptools", "audioop-lts"]
    versions = {}
    for package in packages:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    return {
        "python": platform.python_version(), "platform": platform.platform(),
        "upstream": {"distribution": "manimgl", "version": version,
                     "repository": "https://github.com/3b1b/manim", "tag": "v1.7.2",
                     "commit": UPSTREAM_COMMIT, "wheel_sha256": UPSTREAM_WHEEL_SHA256,
                     "source_sha256": {p: _sha256(root / p) for p in source_files}},
        "dependencies": versions,
    }


def _spans(mob):
    spans = []
    offset = 0
    for contour in mob.get_subpaths():
        if len(contour) < 3 or len(contour) % 2 != 1:
            raise ValueError("Unsupported degenerate Manim contour control-point count")
        if max(abs(float(a - b)) for a, b in zip(contour[0], contour[-1])) > 1e-5:
            raise ValueError("This reference adapter only exports closed text contours")
        spans.append((offset, offset + len(contour)))
        # Upstream align_points inserts one extra anchor between contours.
        offset += len(contour) + 1
    if offset - 1 != len(mob.get_points()):
        raise ValueError("Upstream contour separators do not match the pinned data layout")
    return spans


def _snapshot(mobject, topology):
    members = mobject.family_members_with_points()
    if len(members) != len(topology):
        raise ValueError("Upstream Transform changed the number of aligned glyph objects")
    paths = []
    for mob, expected in zip(members, topology):
        if "spans" in expected and _spans(mob) != expected["spans"]:
            raise ValueError("Upstream contour topology changed during Transform")
        points = mob.get_points().tolist()
        if "point_count" in expected and len(points) != expected["point_count"]:
            raise ValueError("Upstream Transform changed the aligned curve slot count")
        if any(abs(point[2]) > 1e-5 for point in points):
            raise ValueError("Only planar XY text is supported by this reference exporter")
        # Uniform solid styles only. Reject gradients rather than silently flattening.
        for field in ["fill_rgba", "stroke_rgba", "stroke_width", "fill_border_width"]:
            rows = mob.data[field]
            if abs(rows - rows[0]).max() > 1e-6:
                raise ValueError("Per-point style gradients are not supported: " + field)
        width = float(mob.data["stroke_width"][0][0])
        if width != 0:
            raise ValueError("Native Manim stroke width conversion is not yet supported; use fill-only text")
        paths.append({"id": expected["id"], "points": points,
                      "fill": mob.data["fill_rgba"][0].tolist(),
                      "stroke": mob.data["stroke_rgba"][0].tolist(), "stroke_width": width,
                      "native_fill_border_width": float(mob.data["fill_border_width"][0][0]),
                      "native_anti_alias_width": float(mob.uniforms["anti_alias_width"]),
                      "native_unit_normal": mob.get_unit_normal().tolist()})
    return paths


def export_text_transform(output, settings=ExportSettings()):
    """Write scene.json, untouched upstream control points, provenance and PNGs.

    Alignment and interpolation are performed exclusively by real ManimGL.
    Only the final quadratic-to-polygon approximation is implemented here.
    """
    if settings.geometry_mode == "curve_slots":
        from .curve_export import export_curve_text_transform
        return export_curve_text_transform(output, settings)
    if settings.geometry_mode != "contours":
        raise ValueError("geometry_mode must be contours or curve_slots")
    if not settings.source or not settings.target:
        raise ValueError("source and target must both contain visible text")
    if not 2 <= settings.frame_count <= 256:
        raise ValueError("frame_count must be between 2 and 256")
    if any(not math.isfinite(v) or v <= 0 for v in
           (settings.duration, settings.width, settings.height, settings.glyph_height, settings.tolerance)):
        raise ValueError("All geometric/time settings and tolerance must be finite and positive")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = _reference_environment()
    from manimlib import Transform
    from manimlib.config import manim_config
    from .mobject_source import create_source_pair

    cache = output.parent / "manim-cache"
    cache.mkdir(parents=True, exist_ok=True)
    manim_config.directories.cache = str(cache)
    with create_source_pair(settings, output) as (source, target, source_metadata):
        animation = Transform(source, target, run_time=settings.duration)
        animation.begin()
        start_members = animation.starting_mobject.family_members_with_points()
        end_members = animation.target_copy.family_members_with_points()
        if not start_members or len(start_members) != len(end_members):
            raise ValueError("No stable, visible upstream glyph family to export")
        topology = []
        for index, (start, end) in enumerate(zip(start_members, end_members)):
            spans = _spans(start)
            if spans != _spans(end):
                raise ValueError("Aligned endpoint contour spans differ; this case needs a separate adapter")
            topology.append({"id": "glyph-%d" % index, "spans": spans})
        raw_frames = []
        for index in range(settings.frame_count):
            alpha = index / (settings.frame_count - 1)
            animation.interpolate(alpha)
            raw_frames.append({"time": alpha * settings.duration,
                               "paths": _snapshot(source, topology)})

        # One fixed count per aligned curve across ALL frames; no contour matching,
        # resampling, simplification, winding correction or endpoint de-duplication.
        all_counts = []
        bound = 0.0
        for path_index, info in enumerate(topology):
            path_counts = []
            for lo, hi in info["spans"]:
                count = (hi - lo - 1) // 2
                counts = [1] * count
                for frame in raw_frames:
                    curves = contour_curves(frame["paths"][path_index]["points"][lo:hi])
                    for index, curve in enumerate(curves):
                        counts[index] = max(counts[index], choose_subdivisions(curve, settings.tolerance))
                for frame in raw_frames:
                    curves = contour_curves(frame["paths"][path_index]["points"][lo:hi])
                    bound = max(bound, *(chord_error_bound(c, n) for c, n in zip(curves, counts)))
                path_counts.append(counts)
            all_counts.append(path_counts)
        frames = []
        for raw in raw_frames:
            paths = []
            for path_index, (path, info) in enumerate(zip(raw["paths"], topology)):
                contours = [sample_contour(path["points"][lo:hi], counts)
                            for (lo, hi), counts in zip(info["spans"], all_counts[path_index])]
                paths.append({"id": path["id"], "contours": contours, "closed": True,
                              "fill": path["fill"], "stroke": path["stroke"], "stroke_width": 0.0})
            frames.append({"time": raw["time"], "paths": paths})
        scene = {"schema_version": 1, "name": settings.name, "duration": settings.duration,
                 "width": settings.width, "height": settings.height, "background": [0, 0, 0],
                 "frames": frames}
        raw_reference = {"schema_version": 1, "coordinate_system": "XY, Y up",
                         "data_layout": "ManimGL quadratic shared-anchor 2*n+1; extra anchor between subpaths",
                         "topology": topology, "frames": raw_frames}
        scene_path = output / "scene.json"
        raw_path = output / "upstream_control_points.json"
        _write_json(scene_path, scene)
        _write_json(raw_path, raw_reference)

        # Independent probes of the upstream time function at 3 interior times in
        # EVERY interval. This is a measured interpolation error, not a proof over
        # continuous time and not a raster/pixel parity claim.
        time_error = 0.0
        for index in range(len(raw_frames) - 1):
            for fraction in (0.25, 0.5, 0.75):
                alpha = (index + fraction) / (settings.frame_count - 1)
                animation.interpolate(alpha)
                actual = _snapshot(source, topology)
                for path_index, path in enumerate(actual):
                    before = raw_frames[index]["paths"][path_index]["points"]
                    after = raw_frames[index + 1]["paths"][path_index]["points"]
                    for point, a, b in zip(path["points"], before, after):
                        delta = [point[k] - (a[k] + (b[k] - a[k]) * fraction) for k in (0, 1)]
                        time_error = max(time_error, math.hypot(*delta))

        report = {
            "schema_version": 1, "environment": environment,
            "input": {"source": settings.source, "target": settings.target, **source_metadata,
                      "per_text_height": settings.glyph_height,
                      "duration": settings.duration, "canvas": [settings.width, settings.height]},
            "upstream_execution": {"classes": [source_metadata["mobject_class"], "manimlib.Transform"],
                                   "calls": ["Transform.begin", "Transform.interpolate"],
                                   "rate_func": animation.rate_func.__module__ + "." + animation.rate_func.__name__,
                                   "path_func": animation.path_func.__module__ + "." + animation.path_func.__name__,
                                   "matching": "upstream Mobject.align_data_and_family / VMobject.align_points"},
            "sampling": {"frame_count": settings.frame_count,
                         "requested_chord_tolerance_scene_units": settings.tolerance,
                         "max_chord_error_bound_scene_units_at_exported_frames": bound,
                         "time_interpolation_probe_count": 3 * (settings.frame_count - 1),
                         "measured_time_interpolation_max_control_error_scene_units": time_error,
                         "subdivisions": all_counts,
                         "vertices_per_path": [sum(sum(c) for c in p) for p in all_counts],
                         "contour_vertex_counts": [[sum(c) for c in p] for p in all_counts],
                         "endpoint_contour_signed_areas": [
                             [[signed_area(c) for c in p["contours"]] for p in frame["paths"]]
                             for frame in (frames[0], frames[-1])]},
            "artifacts": {"scene": {"file": scene_path.name, "sha256": _sha256(scene_path)},
                          "raw_upstream": {"file": raw_path.name, "sha256": _sha256(raw_path)}},
            "verification": {"real_upstream_execution": True, "native_reference_rendered": False,
                             "minecraft_pixel_parity_verified": False,
                             "notes": ["Polygon sampling is an approximation to upstream quadratic curves.",
                                       "Time interpolation error is measured at probes; it is not a continuous-time bound.",
                                       "This adapter supports fill-only planar Text/Tex and Transform, not arbitrary Manim scripts."]},
        }
        _write_json(output / "reference_report.json", report)
        if settings.render_reference:
            report["native_render"] = _render_native_reference(output, settings, source, animation)
            report["verification"]["native_reference_rendered"] = True
            _write_json(output / "reference_report.json", report)
        return {"scene": scene_path, "raw_reference": raw_path,
                "report": output / "reference_report.json", "data": report}


def _render_native_reference(output, settings, source, animation):
    from manimlib.camera.camera import Camera
    from manimlib.config import manim_config
    from manimlib.shader_wrapper import VShaderWrapper
    from PIL import Image, ImageDraw

    width, height = settings.reference_resolution
    if abs(width / height - settings.width / settings.height) > 1e-6:
        raise ValueError("Native reference resolution must match the exported canvas aspect ratio")
    # Upstream's shared fill canvas reads global camera configuration, rather
    # than this Camera's resolution. Pin both, so supersampling is reproducible.
    manim_config.camera.resolution = settings.reference_resolution
    camera = Camera(resolution=settings.reference_resolution,
                    frame_config={"frame_shape": (settings.width, settings.height)})
    frames = []
    images = []
    for alpha in (0.0, 0.25, 0.5, 0.75, 1.0):
        animation.interpolate(alpha)
        camera.capture(source)
        image = camera.get_image()
        filename = "manimgl_%03d.png" % round(alpha * 100)
        image.save(output / filename)
        frames.append({"alpha": alpha, "time": alpha * settings.duration,
                       "file": filename, "sha256": _sha256(output / filename)})
        images.append(image.convert("RGB"))
    thumbnail_width = 384
    thumbnail_height = round(thumbnail_width * height / width)
    contact = Image.new("RGB", (thumbnail_width * len(images), thumbnail_height + 24), "#111111")
    draw = ImageDraw.Draw(contact)
    for index, (image, frame) in enumerate(zip(images, frames)):
        contact.paste(image.resize((thumbnail_width, thumbnail_height)), (index * thumbnail_width, 24))
        draw.text((index * thumbnail_width + 8, 6), "ManimGL alpha=%g" % frame["alpha"], fill="white")
    contact.save(output / "manimgl_contact_sheet.png")
    result = {"implementation": "unmodified manimlib.camera.camera.Camera.capture/get_image",
              "context": "standalone OpenGL, no application window",
              "resolution": list(settings.reference_resolution),
              "camera_frame_shape": [float(v) for v in camera.get_frame_shape()],
              "native_fill_canvas_resolution": list(VShaderWrapper.get_fill_canvas(camera.ctx)[0].size),
              "renderer": camera.ctx.info.get("GL_RENDERER"),
              "gl_version": camera.ctx.info.get("GL_VERSION"),
              "frames": frames, "contact_sheet": "manimgl_contact_sheet.png"}
    camera.ctx.release()
    return result
