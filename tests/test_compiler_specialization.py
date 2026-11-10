"""Source/numeric checks for safe compiler work reduction, without rendering."""
import copy
import json
import math
from pathlib import Path
import random
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pyreact_manim.compiler import compile_scene, validate_scene
from pyreact_manim.compiler.codec import build_atlas, decode_unit, encode_unit, path_points
from pyreact_manim.compiler.shader import _curve_bounds, _path_invariants, generate_shader
from test_compiler import donut_scene
from test_compiler_v2 import fan_scene


def float32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


def decoded_point(point, layout):
    result = []
    for axis in (0, 1):
        lower = layout["coordinate_bounds"]["min"][axis]
        span = layout["coordinate_bounds"]["max"][axis] - lower
        unit = decode_unit(encode_unit(min(1., max(0., (point[axis] - lower) / span))))
        result.append(float32(float32(lower) + float32(float32(unit) * float32(span))))
    return result


def winding(point, polygon):
    total = 0
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        side = (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])
        if a[1] <= point[1] < b[1] and side > 0:
            total += 1
        elif b[1] <= point[1] < a[1] and side < 0:
            total -= 1
    return total


def segment_distance(point, a, b):
    direction = [b[axis] - a[axis] for axis in (0, 1)]
    relative = [point[axis] - a[axis] for axis in (0, 1)]
    ratio = min(1., max(0., sum(x * y for x, y in zip(direction, relative)) /
                       max(sum(x * x for x in direction), 1e-20)))
    return math.hypot(*(relative[axis] - ratio * direction[axis] for axis in (0, 1)))


class CompilerSpecializationTests(unittest.TestCase):
    def test_invariants_check_interior_frames_and_each_style_independently(self):
        scene = fan_scene()
        middle = copy.deepcopy(scene["frames"][0])
        middle["time"] = .7
        scene["frames"].insert(1, middle)
        self.assertTrue(all(_path_invariants(scene, 0).values()))
        middle["paths"][0]["curves"][0]["skip_marker"] = True
        self.assertTrue(_path_invariants(scene, 0)["geometry"])
        middle["paths"][0]["curves"][0]["points"][0][0] += .25
        middle["paths"][0]["fill"][3] = .5
        actual = _path_invariants(scene, 0)
        self.assertEqual(actual, {"geometry": False, "fill": False, "stroke": True, "stroke_width": True})

    def test_static_geometry_and_style_remove_second_frame_reads_for_both_schemas(self):
        for factory in (donut_scene, fan_scene):
            scene = factory()
            scene["frames"][1]["paths"] = copy.deepcopy(scene["frames"][0]["paths"])
            normalized = validate_scene(scene)
            _, layout = build_atlas(normalized)
            code = generate_shader(normalized, layout).split("void main() {", 1)[1]
            self.assertIn("staticPoint(", code)
            self.assertIn("staticColor(", code)
            self.assertNotIn("samplePoint(", code)
            self.assertNotIn("sampleColor(", code)
            self.assertNotIn("sampleScalar(", code)
        moving = validate_scene(donut_scene())
        _, layout = build_atlas(moving)
        code = generate_shader(moving, layout).split("void main() {", 1)[1]
        self.assertIn("samplePoint(", code)
        self.assertIn("staticColor(", code)

    def test_specialization_preserves_atlas_manifest_contract_and_input(self):
        scene = fan_scene()
        before = copy.deepcopy(scene)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [compile_scene(scene, root / "optimized")]
            with patch("pyreact_manim.compiler.shader._path_invariants", return_value={
                    "geometry": False, "fill": False, "stroke": False, "stroke_width": False}):
                paths.append(compile_scene(scene, root / "dynamic"))
            manifests = [json.loads(path.read_text(encoding="utf8")) for path in paths]
            atlases = [(path.parent / manifest["texture"]["path"]).read_bytes()
                       for path, manifest in zip(paths, manifests)]
            self.assertEqual(atlases[0], atlases[1])
            self.assertEqual(manifests[0]["shader"]["generator_revision"], 2)
            for manifest in manifests:
                manifest.pop("shader")
            self.assertEqual(manifests[0], manifests[1])
        self.assertEqual(scene, before)

    def test_curve_bounds_include_base_quantization_and_float32_interpolation(self):
        rng = random.Random(304)
        for origin, size in ((0., 4.), (500000., .03), (-400000., 800000.)):
            scene = fan_scene()
            for frame_index, frame in enumerate(scene["frames"]):
                path = frame["paths"][0]
                path["base"] = [origin - size * .49, origin + size * .46]
                for curve in path["curves"]:
                    curve["points"] = [[origin + rng.uniform(-.45, .45) * size,
                                        origin + rng.uniform(-.45, .45) * size] for _ in range(5)]
            normalized = validate_scene(scene)
            _, layout = build_atlas(normalized)
            for curve_index in range(4):
                bounds = _curve_bounds(normalized, 0, curve_index, layout)
                # Exercise the same decimal constants that the shader sees.
                bounds = {key: [float32(float(format(x, ".10g"))) for x in value]
                          for key, value in bounds.items()}
                endpoints = []
                for frame in normalized["frames"]:
                    path = frame["paths"][0]
                    endpoints.append([decoded_point(p, layout) for p in
                                      [path["base"]] + path["curves"][curve_index]["points"]])
                for amount in (0., .001, .25, .5, .999, 1.):
                    for a, b in zip(*endpoints):
                        for axis in (0, 1):
                            value = float32(float32(a[axis] * float32(1 - amount)) +
                                            float32(b[axis] * float32(amount)))
                            self.assertGreaterEqual(value, bounds["min"][axis])
                            self.assertLessEqual(value, bounds["max"][axis])

    def test_culled_fans_have_zero_winding_and_no_border_at_all_four_subpixels(self):
        rng = random.Random(851)
        scene = fan_scene()
        for frame in scene["frames"]:
            path = frame["paths"][0]
            # Shared base outside the real chains catches unsafe chain-only culling.
            path["base"] = [-3.5 + rng.random(), 2.5 + rng.random()]
            path["fill_border_width"] = .17
            for curve in path["curves"]:
                curve["points"] = [[rng.uniform(-2, 2), rng.uniform(-2, 2)] for _ in range(5)]
        normalized = validate_scene(scene)
        _, layout = build_atlas(normalized)
        rejected = 0
        for curve_index in range(4):
            bounds = _curve_bounds(normalized, 0, curve_index, layout)
            endpoints = []
            for frame in normalized["frames"]:
                path = frame["paths"][0]
                endpoints.append([decoded_point(p, layout) for p in
                                  [path["base"]] + path["curves"][curve_index]["points"]])
            for amount in (0., .01, .25, .5, .75, .99, 1.):
                polygon = [[a[k] * (1 - amount) + b[k] * amount for k in (0, 1)]
                           for a, b in zip(*endpoints)]
                for pixel_size in (.001, .05, .5):
                    border_extent = .17 / 2 + pixel_size * 1.5 / 2
                    margin = border_extent + pixel_size * .25
                    for _ in range(100):
                        p = [rng.uniform(-5, 5), rng.uniform(-5, 5)]
                        if all(bounds["min"][k] - margin <= p[k] <= bounds["max"][k] + margin
                               for k in (0, 1)):
                            continue
                        rejected += 1
                        for x, y in ((-.25, -.25), (.25, -.25), (-.25, .25), (.25, .25)):
                            sample = [p[0] + x * pixel_size, p[1] + y * pixel_size]
                            self.assertEqual(winding(sample, polygon), 0)
                            distance = min(segment_distance(sample, a, b)
                                           for a, b in zip(polygon[1:], polygon[2:]))
                            self.assertGreaterEqual(distance, border_extent)
        self.assertGreater(rejected, 3000)

    def test_fan_guards_preserve_signed_fill_holes_and_canvas_conversion(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        from build_canvas import transparent_fragment
        for factory in (donut_scene, fan_scene):
            normalized = validate_scene(factory())
            _, layout = build_atlas(normalized)
            code = generate_shader(normalized, layout)
            canvas = transparent_fragment(code)
            self.assertIn("canvasOver(canvasPremultiplied, canvasAlpha, fill.rgb,", canvas)
            self.assertNotIn("color = mix", canvas)
            if normalized["schema_version"] == 2:
                self.assertEqual(code.count("// Cull the complete fan"), 4)
                self.assertIn("signedExponent", canvas)
                self.assertIn("if (coverage < 0.0)", canvas)
                self.assertIn("borderHalfAA + pixelSize * 0.25", canvas)


if __name__ == "__main__":
    unittest.main()
