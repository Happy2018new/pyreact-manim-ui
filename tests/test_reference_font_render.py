"""Localized installed font names must draw the selected face, not Sans."""

from importlib import metadata
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pyreact_manim.reference import ExportSettings, export_text_transform

SIMSUN = Path("C:/Windows/Fonts/simsun.ttc")
try:
    HAS_SYSTEM_REFERENCE = metadata.version("manimgl") == "1.7.2" and SIMSUN.is_file()
except metadata.PackageNotFoundError:
    HAS_SYSTEM_REFERENCE = False


@unittest.skipUnless(HAS_SYSTEM_REFERENCE, "Requires pinned ManimGL and installed Windows SimSun")
class LocalizedFontRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.results = {}
        for family, name in (("宋体", "localized"), ("SimSun", "canonical")):
            output = Path(cls.temporary.name) / name
            result = export_text_transform(output, ExportSettings(
                source="中", target="文", font=family, font_file=None,
                frame_count=5, glyph_height=3, geometry_mode="curve_slots",
                allow_marker_approximation=True))
            cls.results[name] = (result["data"], json.loads((output / "upstream_control_points.json").read_text(encoding="utf-8")))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_localized_and_canonical_font_have_identical_raw_geometry(self):
        localized, canonical = self.results["localized"], self.results["canonical"]
        self.assertEqual(localized[1], canonical[1])
        self.assertEqual(localized[0]["input"]["requested_font"], "宋体")
        self.assertEqual(canonical[0]["input"]["requested_font"], "SimSun")
        for report, _ in self.results.values():
            self.assertEqual(report["input"]["actual_font"], "SimSun")
            self.assertEqual(report["input"]["font_coverage"]["collection_index"], 0)

    def test_export_matches_native_simsun_and_differs_from_sans(self):
        from manimlib import Text, Transform
        from manimlib.mobject.svg.text_mobject import register_font

        with register_font(SIMSUN):
            source = Text("中", font="SimSun", font_size=48).set_height(3)
            target = Text("文", font="SimSun", font_size=48).set_height(3)
            animation = Transform(source, target, run_time=2)
            animation.begin()
            frame = self.results["localized"][1]["frames"][0]
            self.assertEqual([mob.get_points().tolist() for mob in source.family_members_with_points()],
                             [path["points"] for path in frame["paths"]])
            sans = Text("中", font="Sans", font_size=48).set_height(3)
            simsun = Text("中", font="SimSun", font_size=48).set_height(3)
            self.assertNotEqual([mob.get_points().tolist() for mob in simsun.family_members_with_points()],
                                [mob.get_points().tolist() for mob in sans.family_members_with_points()])


if __name__ == "__main__":
    unittest.main()
