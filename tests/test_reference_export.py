"""Integration against a separate execution of the pinned official ManimGL."""

from importlib import metadata
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pyreact_manim.reference import ExportSettings, export_text_transform
from pyreact_manim.reference.exporter import DEFAULT_FONT
from pyreact_manim.reference.sampling import contour_curves, quadratic_point


try:
    HAS_REFERENCE = metadata.version("manimgl") == "1.7.2"
except metadata.PackageNotFoundError:
    HAS_REFERENCE = False


@unittest.skipUnless(HAS_REFERENCE, "Use .venv-reference with official ManimGL 1.7.2 installed")
class RealReferenceExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temporary.name) / "o_to_b"
        cls.result = export_text_transform(cls.output, ExportSettings(frame_count=9))
        cls.scene = json.loads((cls.output / "scene.json").read_text(encoding="utf-8"))
        cls.raw = json.loads((cls.output / "upstream_control_points.json").read_text(encoding="utf-8"))
        cls.report = cls.result["data"]

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_independent_upstream_execution_has_identical_control_points(self):
        # This fresh run uses upstream classes directly; it does not use our
        # exporter snapshot, sampling or matching implementation as its oracle.
        from manimlib import Text, Transform
        from manimlib.mobject.svg.text_mobject import register_font
        with register_font(DEFAULT_FONT):
            original = Text("O", font="DejaVu Serif").set_height(4)
            target = Text("B", font="DejaVu Serif").set_height(4)
            animation = Transform(original, target, run_time=2)
            animation.begin()
            for index in (0, 2, 4, 6, 8):
                animation.interpolate(index / 8)
                members = original.family_members_with_points()
                self.assertEqual(len(members), len(self.raw["frames"][index]["paths"]))
                for actual, recorded in zip(members, self.raw["frames"][index]["paths"]):
                    self.assertEqual(actual.get_points().tolist(), recorded["points"])
        middle = self.raw["frames"][4]["paths"][0]["points"]
        self.assertNotEqual(middle, self.raw["frames"][0]["paths"][0]["points"])
        self.assertNotEqual(middle, self.raw["frames"][-1]["paths"][0]["points"])

    def test_compiler_accepts_fixed_topology_and_zero_area_phantom_is_preserved(self):
        from pyreact_manim.compiler import validate_scene
        normalized = validate_scene(self.scene)
        topology = [[len(c) for c in p["contours"]] for p in normalized["frames"][0]["paths"]]
        for frame in normalized["frames"]:
            self.assertEqual([[len(c) for c in p["contours"]] for p in frame["paths"]], topology)
        self.assertEqual(len(topology[0]), 3)
        self.assertEqual(sum(topology[0]), 269)
        areas = self.report["sampling"]["endpoint_contour_signed_areas"][0][0]
        self.assertGreater(areas[0], 0)
        self.assertLess(areas[1], 0)
        self.assertAlmostEqual(areas[2], 0, places=10)
        self.assertEqual(self.scene["frames"][0]["time"], 0)
        self.assertEqual(self.scene["frames"][-1]["time"], 2)

    def test_every_exported_curve_obeys_geometric_bound_against_raw_upstream(self):
        subdivisions = self.report["sampling"]["subdivisions"]
        tolerance = self.report["sampling"]["max_chord_error_bound_scene_units_at_exported_frames"]
        for frame, raw in zip(self.scene["frames"], self.raw["frames"]):
            for pi, (path, topology) in enumerate(zip(frame["paths"], self.raw["topology"])):
                for ci, ((lo, hi), polygon) in enumerate(zip(topology["spans"], path["contours"])):
                    offset = 0
                    curves = contour_curves(raw["paths"][pi]["points"][lo:hi])
                    for curve, n in zip(curves, subdivisions[pi][ci]):
                        for segment in range(n):
                            a = polygon[offset + segment]
                            b = polygon[(offset + segment + 1) % len(polygon)]
                            actual = quadratic_point(curve, (segment + 0.5) / n)
                            self.assertLessEqual(math.hypot(*(actual[k] - (a[k] + b[k]) / 2
                                                            for k in (0, 1))), tolerance + 1e-9)
                        offset += n

    def test_provenance_and_verification_claims_are_explicit(self):
        report = self.report
        self.assertEqual(report["environment"]["upstream"]["version"], "1.7.2")
        self.assertEqual(report["input"]["font_sha256"],
                         "107244956e9962b9e96faccdc551825e0ae0898ae13737133e1b921a2fd35ffa")
        self.assertEqual(report["upstream_execution"]["rate_func"], "manimlib.utils.rate_functions.smooth")
        self.assertTrue(report["verification"]["real_upstream_execution"])
        self.assertFalse(report["verification"]["minecraft_pixel_parity_verified"])
        self.assertFalse(report["verification"]["native_reference_rendered"])

    def test_variable_upstream_subpath_boundaries_are_rejected(self):
        output = Path(self.temporary.name) / "unsupported_eight_to_one"
        with self.assertRaisesRegex(ValueError, "endpoint contour spans differ"):
            export_text_transform(output, ExportSettings(source="8", target="1", frame_count=3))
        self.assertFalse((output / "scene.json").exists())


if __name__ == "__main__":
    unittest.main()
