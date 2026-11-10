"""Real upstream curve slots, explicit approximate previews and strict rejection."""

from importlib import metadata
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pyreact_manim.reference import ExportSettings, export_text_transform
from pyreact_manim.reference.curve_export import _marker_candidate
from pyreact_manim.reference.exporter import DEFAULT_FONT
from pyreact_manim.reference.sampling import marker_behavior, sample_curve


class MarkerAnalysisTests(unittest.TestCase):
    def test_affine_marker_classification_is_not_an_opacity_interpolation(self):
        skipped = [[0, 0, 0], [0, 0, 0], [1, 1, 0]]
        left = [[0, 0, 0], [1, 0, 0], [1, 1, 0]]
        right = [[0, 0, 0], [-1, 0, 0], [1, 1, 0]]
        self.assertEqual(marker_behavior(skipped, skipped)["kind"], "always_skip")
        self.assertEqual(marker_behavior(skipped, left)["kind"], "start_only")
        self.assertEqual(marker_behavior(left, skipped)["kind"], "end_only")
        self.assertEqual(marker_behavior(left, right), {"kind": "interior_event", "rate_fraction": 0.5})

    def test_planar_candidate_detects_rotated_z_roundoff_that_exact_3d_analysis_misses(self):
        start = [[0, 0, 0], [1, 0, 1e-17], [1, 1, 0]]
        end = [[0, 0, 0], [-1, 0, -1.0000001e-17], [1, 1, 0]]
        self.assertEqual(marker_behavior(start, end)["kind"], "never_skip")
        _, candidate = _marker_candidate(start, end)
        self.assertEqual(candidate["kind"], "xy_roundoff_candidate")
        self.assertEqual(candidate["rate_fraction"], 0.5)
        self.assertEqual(candidate["minimum_xy_separation"], 0)

    def test_independent_curve_sampling_includes_both_anchors(self):
        curve = [[1, 2], [3, 4], [5, 2]]
        sampled = sample_curve(curve, 7)
        self.assertEqual(len(sampled), 8)
        self.assertEqual(sampled[0], curve[0])
        self.assertEqual(sampled[-1], curve[-1])

    def test_string_false_does_not_accidentally_opt_into_approximation(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "explicit bool"):
                export_text_transform(temporary, ExportSettings(
                    geometry_mode="curve_slots", allow_marker_approximation="false"))


try:
    HAS_REFERENCE = metadata.version("manimgl") == "1.7.2"
except metadata.PackageNotFoundError:
    HAS_REFERENCE = False


@unittest.skipUnless(HAS_REFERENCE, "Use the pinned .venv-reference environment")
class RealCurveSlotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temporary.name) / "eight_to_one_preview"
        cls.result = export_text_transform(cls.output, ExportSettings(
            source="8", target="1", name="eight_to_one", frame_count=9,
            geometry_mode="curve_slots", allow_marker_approximation=True))
        cls.scene = json.loads((cls.output / "scene.json").read_text(encoding="utf-8"))
        cls.raw = json.loads((cls.output / "upstream_control_points.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_exported_slots_retain_real_markers_and_original_geometry(self):
        from pyreact_manim.compiler import validate_scene
        validated = validate_scene(self.scene)
        self.assertEqual(validated["schema_version"], 2)
        for frame, raw in zip(self.scene["frames"], self.raw["frames"]):
            path, original = frame["paths"][0], raw["paths"][0]
            self.assertEqual(path["base"], original["points"][0][:2])
            self.assertEqual(path["fill_border_width"], 0.005)
            self.assertEqual(path["anti_alias_width"], 1.5)
            self.assertEqual(len(path["curves"]), 66)
            for i, curve in enumerate(path["curves"]):
                self.assertIs(type(curve["skip_marker"]), bool)
                self.assertEqual(curve["skip_marker"], original["points"][2 * i] == original["points"][2 * i + 1])
                self.assertEqual(curve["points"][0], original["points"][2 * i][:2])
                self.assertEqual(curve["points"][-1], original["points"][2 * i + 2][:2])
        # A move marker is retained as untouched geometry plus an explicit bool;
        # it is never disguised as a collapsed contour or transparent glyph.
        marker = self.scene["frames"][0]["paths"][0]["curves"][20]
        self.assertTrue(marker["skip_marker"])
        self.assertNotEqual(marker["points"][0], marker["points"][-1])

    def test_fresh_upstream_execution_matches_unmodified_raw_points(self):
        from manimlib import Text, Transform
        from manimlib.mobject.svg.text_mobject import register_font
        with register_font(DEFAULT_FONT):
            source = Text("8", font="DejaVu Serif", font_size=48).set_height(4)
            target = Text("1", font="DejaVu Serif", font_size=48).set_height(4)
            transform = Transform(source, target, run_time=2)
            transform.begin()
            for index in (0, 4, 8):
                transform.interpolate(index / 8)
                points = source.family_members_with_points()[0].get_points().tolist()
                self.assertEqual(points, self.raw["frames"][index]["paths"][0]["points"])

    def test_opt_in_preview_does_not_claim_full_timeline_marker_parity(self):
        report = self.result["data"]
        self.assertTrue(report["input"]["allow_marker_approximation"])
        self.assertTrue(report["verification"]["preview_uses_marker_approximation"])
        self.assertFalse(report["verification"]["full_timeline_marker_parity_verified"])
        self.assertFalse(report["verification"]["minecraft_pixel_parity_verified"])
        candidates = report["markers"]["known_floating_point_candidates"]
        self.assertTrue(any(event["curve"] == 8 and event["native_skip_at_inverse_time"] for event in candidates))

    def test_strict_mode_rejects_known_native_equality_windows_before_scene_output(self):
        output = Path(self.temporary.name) / "strict_eight_to_one"
        with self.assertRaisesRegex(ValueError, "allow_marker_approximation=True"):
            export_text_transform(output, ExportSettings(source="8", target="1", frame_count=3,
                                                        geometry_mode="curve_slots"))
        self.assertFalse((output / "scene.json").exists())
        rejection = json.loads((output / "rejected_reference.json").read_text(encoding="utf-8"))
        self.assertFalse(rejection["accepted"])
        self.assertTrue(rejection["details"]["candidate_events"])

    def test_multicharacter_preview_keeps_separate_glyph_fans(self):
        output = Path(self.temporary.name) / "ui_to_ux"
        result = export_text_transform(output, ExportSettings(
            source="UI", target="UX", glyph_height=3, frame_count=3, geometry_mode="curve_slots",
            allow_marker_approximation=True))
        scene = json.loads(result["scene"].read_text(encoding="utf-8"))
        self.assertEqual(len(scene["frames"][0]["paths"]), 2)
        self.assertEqual(result["data"]["sampling"]["vertices_per_path"], [94, 56])


if __name__ == "__main__":
    unittest.main()
