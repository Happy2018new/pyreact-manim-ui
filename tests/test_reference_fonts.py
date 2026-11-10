"""Verify text cannot silently fall back to unrelated or missing glyphs."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pyreact_manim.reference.fonts import resolve_system_font, validate_font_coverage

CJK = ROOT / "tools/reference/fonts/PyreactManimSong-Regular.ttf"
LATIN = ROOT / "tools/reference/fonts/DejaVuSerif.ttf"


class FontCoverageTests(unittest.TestCase):
    def test_real_chinese_and_latin_characters_are_covered_by_the_bundled_subset(self):
        result = validate_font_coverage(CJK, "中文变换 数学动画\nABC123", "Pyreact Manim Song")
        self.assertTrue(result["coverage_verified"])
        self.assertIn(ord("中"), result["checked_codepoints"])
        self.assertNotIn(ord("\n"), result["checked_codepoints"])
        self.assertLess(CJK.stat().st_size, 150_000)

    def test_dejavu_retains_existing_sample_coverage(self):
        result = validate_font_coverage(LATIN, "OBCS81UIUX", "DejaVu Serif")
        self.assertTrue(result["coverage_verified"])

    def test_missing_chinese_glyph_rejects_silent_pango_fallback(self):
        with self.assertRaisesRegex(ValueError, "U\\+4E2D.*refusing fallback/tofu"):
            validate_font_coverage(LATIN, "中文", "DejaVu Serif")

    def test_wrong_family_rejects_fallback_even_if_character_exists(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            validate_font_coverage(CJK, "中", "Noto Sans SC")

    def test_subset_expansion_is_explained_when_a_character_is_absent(self):
        with self.assertRaisesRegex(ValueError, "setup_cjk.py --text-file"):
            validate_font_coverage(CJK, "龘", "Pyreact Manim Song")

    def test_missing_font_file_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                validate_font_coverage(Path(directory) / "missing.ttf", "中")

    def test_collection_selects_actual_family_instead_of_first_face(self):
        from fontTools.ttLib import TTCollection, TTFont

        with tempfile.TemporaryDirectory() as directory:
            collection = TTCollection()
            with TTFont(LATIN) as latin, TTFont(CJK) as chinese:
                chinese["name"].setName("测试宋体", 1, 3, 1, 0x804)
                collection.fonts = [latin, chinese]
                path = Path(directory) / "open_test_fonts.ttc"
                collection.save(path)
            result = validate_font_coverage(path, "中文", "测试宋体")
            self.assertEqual(result["collection_index"], 1)
            self.assertIn("Pyreact Manim Song", result["family_names"])
            self.assertEqual(result["pango_family"], "Pyreact Manim Song")
            with self.assertRaisesRegex(ValueError, "multiple faces"):
                validate_font_coverage(path, "中文")
            with self.assertRaisesRegex(ValueError, "does not match"):
                validate_font_coverage(path, "中文", "Nonexistent Family")
            with patch("pyreact_manim.reference.fonts._system_font_candidates", return_value=iter([LATIN, path])):
                self.assertEqual(resolve_system_font("测试宋体"), path.resolve())

    def test_installed_family_lookup_does_not_guess_missing_names(self):
        with patch("pyreact_manim.reference.fonts._system_font_candidates", return_value=iter([LATIN, CJK])):
            with self.assertRaisesRegex(ValueError, "was not found"):
                resolve_system_font("No Such Font Family")

    def test_installed_family_lookup_is_case_insensitive(self):
        with patch("pyreact_manim.reference.fonts._system_font_candidates", return_value=iter([CJK, LATIN])):
            self.assertEqual(resolve_system_font("  dejavu serif  "), LATIN.resolve())


if __name__ == "__main__":
    unittest.main()
