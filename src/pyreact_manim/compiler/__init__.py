"""Compile frozen vector animation data into a Minecraft shader and data atlas."""

import hashlib
import json
from pathlib import Path

from .codec import build_atlas
from .shader import generate_shader
from .validation import SceneError, validate_scene


def compile_scene(scene, output_dir):
    """Build artifacts and return the path of the runtime-only manifest.

    This is a compiler for exported geometry, not an arbitrary Python-to-GLSL
    translator. Intermediate geometry is linearly interpolated between samples.
    """
    normalized = validate_scene(scene)
    image, layout = build_atlas(normalized)
    shader = generate_shader(normalized, layout)
    output = Path(output_dir)
    texture_relative = "textures/%s.png" % normalized["name"]
    shader_relative = "shaders/%s.fragment" % normalized["name"]
    texture_path = output / texture_relative
    shader_path = output / shader_relative
    texture_path.parent.mkdir(parents=True, exist_ok=True)
    shader_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(texture_path, format="PNG", optimize=True)
    shader_path.write_text(shader, encoding="utf-8", newline="\n")
    manifest = {
        "schema_version": normalized["schema_version"], "name": normalized["name"], "duration": normalized["duration"],
        "geometry_kind": "directed_curve_fans" if normalized["schema_version"] == 2 else "closed_contours",
        "canvas": {key: normalized[key] for key in ("width", "height", "background")},
        "frame_times": [frame["time"] for frame in normalized["frames"]],
        "frame_count": len(normalized["frames"]), "path_count": len(layout["paths"]),
        "vertex_count": layout["vertex_count"], "paths": layout["paths"],
        "texture": {
            "path": texture_relative, "width": layout["width"], "height": layout["height"],
            "sampler": 2, "filter": "Point", "encoding": "rg16_unorm",
            "frame_stride": layout["frame_stride"], "point_offset": 0,
            "style_offset": layout["style_offset"], "style_scalars_per_path": 9,
            "marker_offset": layout["marker_offset"], "curve_count": layout["curve_count"],
            "sha256": hashlib.sha256(texture_path.read_bytes()).hexdigest(),
        },
        "coordinate_bounds": layout["coordinate_bounds"],
        "stroke_width_scale": layout["stroke_width_scale"],
        "shader": {
            "path": shader_relative,
            "sha256": hashlib.sha256(shader.encode("utf-8")).hexdigest(),
            "uniforms": {
                "EXTRA_VECTOR1": ["time_seconds", "viewport_aspect", "pixel_height", "opacity"],
                "EXTRA_VECTOR2": ["flip_y", "canvas_top_ratio", "canvas_height_ratio", "reserved"],
            },
        },
        "precision": {
            "coordinate_absolute_error_bound": layout["coordinate_error_bound"],
            "color_absolute_error_bound": 0.5 / 65535,
            "between_frames": "linear interpolation of exported geometry and styles",
            "fill_rule": "nonzero",
            "marker_rule": "at keyframe use native active flag; between keys active when either endpoint is active"
                           if normalized["schema_version"] == 2 else None,
            "coverage": "2x2 signed native alpha, per-sample border MAX, filtered negative recovery"
                        if normalized["schema_version"] == 2 else "nearest edge winding coverage",
            "native_fill_approximations": ["curve chains and round segment caps replace native analytic fill and stroke strips",
                                            "float32 signed alpha replaces ordered native FP16 blending",
                                            "signed-alpha exponent beyond +/-80 is saturated for float32 safety"]
                                           if normalized["schema_version"] == 2 else None,
            "reference_pixel_parity_verified": False,
        },
        "source_sha256": hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":"),
                                                     allow_nan=False).encode("utf-8")).hexdigest(),
    }
    manifest_path = output / "scene.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                             encoding="utf-8", newline="\n")
    return manifest_path


__all__ = ["SceneError", "compile_scene", "validate_scene"]
