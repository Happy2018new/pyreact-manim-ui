"""Native curve-slot markers and shared-base directed fan accumulation."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pyreact_manim.compiler import SceneError, compile_scene, validate_scene
from pyreact_manim.compiler.codec import path_points
from pyreact_manim.compiler.preview import decode_frame, render_preview, sample_frame
from pyreact_manim.compiler.validation import MAX_VERTICES


def fan_scene():
    corners = [[-2, -2], [2, -2], [2, 2], [-2, 2], [-2, -2]]
    path = {"id": "square", "base": [0, 0],
            "curves": [{"points": [a, b], "skip_marker": False}
                       for a, b in zip(corners, corners[1:])],
            "fill": [0.25, 0.5, 1, 1], "stroke": [0, 0, 0, 0], "stroke_width": 0}
    return {"schema_version": 2, "name": "fans", "duration": 2, "width": 8, "height": 8,
            "background": [0, 0, 0],
            "frames": [{"time": 0, "paths": [path]}, {"time": 2, "paths": [copy.deepcopy(path)]}]}


class CurveFanTests(unittest.TestCase):
    def test_schema_two_atlas_preserves_coordinates_styles_and_markers(self):
        source = fan_scene()
        source["frames"][1]["paths"][0]["curves"][1]["skip_marker"] = True
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = compile_scene(source, temporary)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["texture"]["curve_count"], 4)
            with Image.open(Path(temporary) / manifest["texture"]["path"]) as image:
                for index, frame in enumerate(source["frames"]):
                    expected = frame["paths"][0]
                    actual = decode_frame(manifest, image, index)["paths"][0]
                    for a, b in zip(path_points(expected), path_points(actual)):
                        for axis in (0, 1):
                            self.assertLessEqual(abs(a[axis] - b[axis]),
                                manifest["precision"]["coordinate_absolute_error_bound"][axis] + 1e-12)
                    self.assertEqual([c["skip_marker"] for c in expected["curves"]],
                                     [c["skip_marker"] for c in actual["curves"]])
                    for a, b in zip(expected["fill"], actual["fill"]):
                        self.assertLessEqual(abs(a - b), 0.5 / 65535 + 1e-12)

    def test_shared_fans_fill_square_without_artificial_diagonal_seams(self):
        image = render_preview(fan_scene(), 1, 128, 128)
        for coordinate in ((64, 64), (48, 48), (80, 80), (48, 80), (80, 48)):
            self.assertEqual(image.getpixel(coordinate), (64, 128, 255))
        self.assertEqual(image.getpixel((10, 10)), (0, 0, 0))

    def test_opposite_fans_cancel_instead_of_being_unioned(self):
        scene = fan_scene()
        for frame in scene["frames"]:
            path = frame["paths"][0]
            path["curves"] += [{"points": list(reversed(c["points"])), "skip_marker": False}
                               for c in path["curves"]]
        self.assertEqual(render_preview(scene, 1, 128, 128).getbbox(), None)

    def test_native_transparent_overlap_accumulates_before_alpha_recovery(self):
        scene = fan_scene()
        for frame in scene["frames"]:
            path = frame["paths"][0]
            path["fill"] = [1, 1, 1, 0.5]
            path["curves"] += copy.deepcopy(path["curves"])
        # Two native 0.95-scaled half-opacity contributions followed by 1.06 adjustment.
        expected = round((1 - (1 - 0.95 * 0.5) ** 2) * 1.06 * 255)
        self.assertEqual(render_preview(scene, 1, 64, 64).getpixel((32, 32)), (expected,) * 3)

    def test_reversed_curve_orientation_and_native_normal_preserve_fill(self):
        scene = fan_scene()
        for frame in scene["frames"]:
            path = frame["paths"][0]
            path["fill"] = [1, 1, 1, 0.5]
        before = render_preview(scene, 1, 64, 64)
        for frame in scene["frames"]:
            path = frame["paths"][0]
            path["fill_orientation"] = -1
            for curve in path["curves"]:
                curve["points"].reverse()
        self.assertEqual(before.tobytes(), render_preview(scene, 1, 64, 64).tobytes())
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = compile_scene(scene, temporary)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            with Image.open(Path(temporary) / manifest["texture"]["path"]) as image:
                self.assertEqual(decode_frame(manifest, image, 0)["paths"][0]["fill_orientation"], -1)

    def test_faint_multiple_windings_do_not_saturate_prematurely(self):
        scene = fan_scene()
        for frame in scene["frames"]:
            path = frame["paths"][0]
            path["fill"] = [1, 1, 1, 0.01]
            path["curves"] = path["curves"] * 20
        expected = round((1 - (1 - 0.95 * 0.01) ** 20) * 1.06 * 255)
        self.assertEqual(render_preview(scene, 1, 32, 32).getpixel((16, 16)), (expected,) * 3)

    def test_cjk_vertex_budget_accepts_2048_and_rejects_overflow(self):
        self.assertEqual(MAX_VERTICES, 2048)
        scene = fan_scene()
        for frame in scene["frames"]:
            frame["paths"][0]["curves"] = [
                {"points": [[0, 0], [1, 0]] * 1023 + [[0, 0]], "skip_marker": False}]
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = compile_scene(scene, temporary)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["vertex_count"], 2048)
            self.assertLessEqual(max(manifest["texture"]["width"], manifest["texture"]["height"]), 2048)
        for frame in scene["frames"]:
            frame["paths"][0]["curves"][0]["points"].append([1, 0])
        with self.assertRaisesRegex(SceneError, "2048 vertex"):
            validate_scene(scene)

    def test_native_fill_border_draws_real_curves_but_no_shared_base_spokes(self):
        scene = fan_scene()
        for frame in scene["frames"]:
            path = frame["paths"][0]
            path["fill_border_width"] = 0.1
            path["curves"] += [{"points": list(reversed(c["points"])), "skip_marker": False}
                               for c in path["curves"]]
        image = render_preview(scene, 1, 128, 128)
        self.assertNotEqual(image.getpixel((32, 64)), (0, 0, 0))
        self.assertEqual(image.getpixel((64, 64)), (0, 0, 0))
        self.assertEqual(image.getpixel((48, 48)), (0, 0, 0))

    def test_skip_marker_removes_fan_and_is_not_interpolated_opacity(self):
        scene = fan_scene()
        for curve in scene["frames"][0]["paths"][0]["curves"]:
            curve["skip_marker"] = True
        self.assertEqual(render_preview(scene, 0, 64, 64).getbbox(), None)
        self.assertTrue(all(not c["skip_marker"] for c in sample_frame(scene, 1e-8)["paths"][0]["curves"]))
        self.assertEqual(render_preview(scene, 1e-8, 64, 64).getpixel((32, 32)), (64, 128, 255))
        middle = copy.deepcopy(scene["frames"][0])
        middle["time"] = 1
        scene["frames"][0] = copy.deepcopy(scene["frames"][1])
        scene["frames"][0]["time"] = 0
        scene["frames"].insert(1, middle)
        self.assertEqual(render_preview(scene, 1, 64, 64).getbbox(), None)
        self.assertTrue(all(not c["skip_marker"] for c in sample_frame(scene, 1 - 1e-8)["paths"][0]["curves"]))
        self.assertTrue(all(not c["skip_marker"] for c in sample_frame(scene, 1 + 1e-8)["paths"][0]["curves"]))

    def test_unsupported_stroke_marker_and_topology_are_rejected(self):
        for mutation in (lambda path: path.update(stroke_width=1),
                         lambda path: path.update(fill_border_width=0.1),
                         lambda path: path.update(anti_alias_width=-1),
                         lambda path: path.update(fill_orientation=0),
                         lambda path: path.update(fill_orientation=-1),
                         lambda path: path["curves"][0].update(skip_marker=0),
                         lambda path: path["curves"][0]["points"].append([0, 0])):
            scene = fan_scene()
            mutation(scene["frames"][1]["paths"][0])
            with self.assertRaises(SceneError):
                validate_scene(scene)

    def test_event_times_colliding_in_gpu_float32_are_rejected(self):
        scene = fan_scene()
        for timestamp in (1.0, 1.0 + 1e-9):
            frame = copy.deepcopy(scene["frames"][0])
            frame["time"] = timestamp
            scene["frames"].insert(-1, frame)
        with self.assertRaisesRegex(SceneError, "float32"):
            validate_scene(scene)


if __name__ == "__main__":
    unittest.main()
