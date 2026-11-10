"""Artifact precision, hole semantics and rejection of unsupported geometry."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pyreact_manim.compiler import SceneError, compile_scene, validate_scene
from pyreact_manim.compiler.codec import decode_unit, encode_unit
from pyreact_manim.compiler.preview import decode_frame, render_preview, sample_frame


def donut_scene():
    outer = [[-2, -2], [2, -2], [2, 2], [-2, 2]]
    inner = [[-1, -1], [-1, 1], [1, 1], [1, -1]]
    path = {"id": "ring", "contours": [outer, inner], "fill": [1, 0.25, 0.5, 1],
            "stroke": [0, 0, 0, 0], "stroke_width": 0}
    moved = copy.deepcopy(path)
    moved["contours"] = [[[x + 0.75, y + 0.125] for x, y in contour] for contour in moved["contours"]]
    return {"schema_version": 1, "name": "ring", "duration": 2.0, "width": 8.0, "height": 8.0,
            "background": [0, 0, 0], "frames": [{"time": 0, "paths": [path]}, {"time": 2, "paths": [moved]}]}


class CompilerTests(unittest.TestCase):
    def test_scalar_roundtrip_bound_and_opaque_alpha(self):
        for value in [0, 1, 0.5, 1 / 255, 256 / 65535, 0.123456789]:
            pixel = encode_unit(value)
            self.assertEqual(pixel[3], 255)
            self.assertLessEqual(abs(decode_unit(pixel) - value), 0.5 / 65535 + 1e-15)

    def test_emitted_atlas_recovers_every_coordinate_and_style(self):
        source = donut_scene()
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = compile_scene(source, temporary)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            with Image.open(Path(temporary) / manifest["texture"]["path"]) as image:
                self.assertEqual(image.getchannel("A").getextrema(), (255, 255))
                for index, frame in enumerate(source["frames"]):
                    decoded = decode_frame(manifest, image, index)
                    for expected, actual in zip(frame["paths"], decoded["paths"]):
                        for contour_a, contour_b in zip(expected["contours"], actual["contours"]):
                            for point_a, point_b in zip(contour_a, contour_b):
                                for axis in (0, 1):
                                    bound = manifest["precision"]["coordinate_absolute_error_bound"][axis]
                                    self.assertLessEqual(abs(point_a[axis] - point_b[axis]), bound + 1e-12)
                        for a, b in zip(expected["fill"], actual["fill"]):
                            self.assertLessEqual(abs(a - b), 0.5 / 65535 + 1e-12)
            shader = (Path(temporary) / manifest["shader"]["path"]).read_text(encoding="utf-8")
            self.assertIn("uniform sampler2D TEXTURE_2;", shader)
            self.assertFalse(manifest["precision"]["reference_pixel_parity_verified"])

    def test_nonzero_fill_preserves_a_reversed_inner_contour(self):
        image = render_preview(donut_scene(), 0, 128, 128)
        self.assertEqual(image.getpixel((64, 64)), (0, 0, 0))
        self.assertEqual(image.getpixel((88, 64)), (255, 64, 128))
        self.assertEqual(image.getpixel((120, 64)), (0, 0, 0))
        same_direction = donut_scene()
        for frame in same_direction["frames"]:
            frame["paths"][0]["contours"][1].reverse()
        image = render_preview(same_direction, 0, 128, 128)
        self.assertEqual(image.getpixel((64, 64)), (255, 64, 128))
        self.assertEqual(image.getpixel((79, 64)), (255, 64, 128))
        self.assertEqual(image.getpixel((80, 64)), (255, 64, 128))

    def test_time_sampling_clamps_and_interpolates_nonuniform_intervals(self):
        scene = donut_scene()
        middle = copy.deepcopy(scene["frames"][1])
        middle["time"] = 0.5
        scene["frames"].insert(1, middle)
        point = sample_frame(scene, 0.25)["paths"][0]["contours"][0][0]
        self.assertEqual(point, [-1.625, -1.9375])
        self.assertEqual(sample_frame(scene, -1)["time"], 0)
        self.assertEqual(sample_frame(scene, 20)["time"], 2)

    def test_topology_changes_are_rejected(self):
        scene = donut_scene()
        scene["frames"][1]["paths"][0]["contours"][0].append([0, 0])
        with self.assertRaisesRegex(SceneError, "topology"):
            validate_scene(scene)

    def test_nonfinite_and_unsafe_resource_names_are_rejected(self):
        for bad_name in ["../escape", "quote\"", "new\nline", "UPPER"]:
            scene = donut_scene()
            scene["name"] = bad_name
            with self.assertRaises(SceneError):
                validate_scene(scene)
        for bad in [float("nan"), float("inf"), True, 1e200]:
            scene = donut_scene()
            scene["frames"][0]["paths"][0]["contours"][0][0][0] = bad
            with self.assertRaises(SceneError):
                validate_scene(scene)

    def test_nonmonotone_times_fail_before_writing(self):
        scene = donut_scene()
        scene["frames"][1]["time"] = 0
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "artifacts"
            with self.assertRaises(SceneError):
                compile_scene(scene, destination)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
