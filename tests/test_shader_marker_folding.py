"""Constant marker folding must preserve atlas bytes and interpolated activity."""
import copy
import importlib.util
import itertools
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pyreact_manim.compiler import compile_scene, validate_scene
from pyreact_manim.compiler.codec import build_atlas
from pyreact_manim.compiler.desktop import render_compiled
from pyreact_manim.compiler.preview import sample_frame
from pyreact_manim.compiler.shader import _curve_activity, generate_shader
from test_compiler_v2 import fan_scene


def mixed_marker_scene():
    scene = fan_scene()
    middle = copy.deepcopy(scene["frames"][0])
    middle["time"] = 0.7  # Nonuniform spacing must keep its exact time tree.
    scene["frames"].insert(1, middle)
    for frame in scene["frames"]:
        path = frame["paths"][0]
        path["curves"][1]["skip_marker"] = True
        path["curves"][2]["skip_marker"] = frame["time"] != 0.7
        path["fill"] = [0.25, 0.5, 1, 0.5]
        path["fill_border_width"] = 0.12
    return scene


def compile_pair(scene, root):
    """Compare folding with the legacy all-dynamic generation over one input."""
    optimized = compile_scene(scene, root / "optimized")
    with patch("pyreact_manim.compiler.shader._curve_activity",
               side_effect=lambda source, index: [None] * len(source["frames"][0]["paths"][index]["curves"])):
        baseline = compile_scene(scene, root / "baseline")
    return optimized, baseline


class MarkerFoldingTests(unittest.TestCase):
    def test_all_three_frame_marker_patterns_match_interpolated_activity(self):
        # In particular, equal endpoints do not imply a constant interior.
        for pattern in itertools.product((False, True), repeat=3):
            scene = mixed_marker_scene()
            for frame, skipped in zip(scene["frames"], pattern):
                frame["paths"][0]["curves"][0]["skip_marker"] = skipped
            activity = _curve_activity(scene, 0)[0]
            expected = not pattern[0] if len(set(pattern)) == 1 else None
            self.assertIs(activity, expected)
            for timestamp in (-1, 0, 0.2, 0.7, 1.0, 2, 3):
                active = not sample_frame(scene, timestamp)["paths"][0]["curves"][0]["skip_marker"]
                if activity is not None:
                    self.assertIs(active, activity)

    def test_folding_changes_only_shader_and_keeps_mixed_marker_dynamic(self):
        source = mixed_marker_scene()
        untouched = copy.deepcopy(source)
        with tempfile.TemporaryDirectory() as temporary:
            optimized, baseline = compile_pair(source, Path(temporary))
            manifests = [json.loads(path.read_text(encoding="utf-8")) for path in (optimized, baseline)]
            for path, manifest in zip((optimized, baseline), manifests):
                self.assertEqual(manifest["texture"]["curve_count"], 4)
                self.assertEqual(manifest["vertex_count"], 9)
            images = [(path.parent / manifest["texture"]["path"]).read_bytes()
                      for path, manifest in zip((optimized, baseline), manifests)]
            self.assertEqual(images[0], images[1])
            shaders = [(path.parent / manifest.pop("shader")["path"]).read_text(encoding="utf-8")
                       for path, manifest in zip((optimized, baseline), manifests)]
            self.assertEqual(manifests[0], manifests[1])
            optimized_code, baseline_code = shaders
            self.assertEqual(optimized_code.count("if (sampleScalar("), 1)
            self.assertEqual(baseline_code.count("if (sampleScalar("), 4)
            self.assertEqual(optimized_code.count("for (int i = 1;"), 3)
            self.assertEqual(baseline_code.count("for (int i = 1;"), 4)
            curves = manifests[0]["paths"][0]["curves"]
            self.assertNotIn("vec2 a = samplePoint(%s.0, frames);" % curves[1]["start"], optimized_code)
            self.assertIn("if (sampleScalar(%s.0, frames) > 0.0)" % curves[2]["active_offset"], optimized_code)
            # Coordinate math, time selection, signed-alpha accumulation and
            # border blending remain byte-identical outside curve emission.
            self.assertEqual(optimized_code.split("// Native fixed curve slots;")[0],
                             baseline_code.split("// Native fixed curve slots;")[0])
            self.assertEqual(optimized_code.split("        vec4 fill =", 1)[1],
                             baseline_code.split("        vec4 fill =", 1)[1])
        self.assertEqual(source, untouched)

    def test_degenerate_active_geometry_is_kept_and_different_paths_are_independent(self):
        source = fan_scene()
        for frame in source["frames"]:
            first = frame["paths"][0]
            first["curves"][0]["points"] = [[0, 0], [0, 0]]
            second = copy.deepcopy(first)
            second["id"] = "other"
            second["curves"][0]["skip_marker"] = True
            frame["paths"].append(second)
        normalized = validate_scene(source)
        _, layout = build_atlas(normalized)
        code = generate_shader(normalized, layout)
        active_start = layout["paths"][0]["curves"][0]["start"]
        skipped_start = layout["paths"][1]["curves"][0]["start"]
        self.assertIn("vec2 a = samplePoint(%s.0, frames);" % active_start, code)
        self.assertNotIn("vec2 a = samplePoint(%s.0, frames);" % skipped_start, code)
        self.assertEqual(code.count("for (int i = 1;"), 7)

    def test_all_skipped_curves_emit_no_loops_without_mutating_layout(self):
        source = fan_scene()
        for frame in source["frames"]:
            for curve in frame["paths"][0]["curves"]:
                curve["skip_marker"] = True
        normalized = validate_scene(source)
        _, layout = build_atlas(normalized)
        original_layout = copy.deepcopy(layout)
        code = generate_shader(normalized, layout)
        self.assertNotIn("for (int i = 1;", code)
        self.assertNotIn("if (sampleScalar(", code)
        self.assertEqual(layout, original_layout)


@unittest.skipUnless(importlib.util.find_spec("moderngl"), "Optional desktop OpenGL diagnostic requires moderngl")
class MarkerFoldingDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import moderngl
        try:
            context = moderngl.create_standalone_context(require=330)
        except (moderngl.Error, OSError) as error:
            raise unittest.SkipTest("Desktop OpenGL context unavailable: " + str(error))
        context.release()

    def test_real_shader_pixels_match_legacy_at_endpoints_and_marker_transitions(self):
        scene = mixed_marker_scene()
        with tempfile.TemporaryDirectory() as temporary:
            optimized, baseline = compile_pair(scene, Path(temporary))
            images = []
            for timestamp in (0, 0.2, 0.7, 1.0, 2):
                folded, _ = render_compiled(optimized, timestamp, 64, 64)
                original, _ = render_compiled(baseline, timestamp, 64, 64)
                self.assertEqual(folded.tobytes(), original.tobytes(), "timestamp=%s" % timestamp)
                images.append(folded.tobytes())
            # This fixture actually changes when its dynamic marker toggles.
            self.assertNotEqual(images[0], images[1])
            self.assertNotEqual(images[-2], images[-1])


if __name__ == "__main__":
    unittest.main()
