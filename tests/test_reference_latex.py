"""Real Tex formula geometry and the narrowly scoped Windows command adapter."""

from importlib import metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pyreact_manim.reference import ExportSettings, export_text_transform
from pyreact_manim.reference.mobject_source import _TexSubprocess, tex_toolchain, native_tex_environment


try:
    HAS_TEX = metadata.version("manimgl") == "1.7.2" and shutil.which("latex") and shutil.which("dvisvgm")
except metadata.PackageNotFoundError:
    HAS_TEX = False


class TexCommandTests(unittest.TestCase):
    def _proxy(self, miktex=True):
        original = Mock()
        original.run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        tools = {"miktex": miktex, "latex": {"executable": "installed-latex"},
                 "dvisvgm": {"executable": "installed-dvisvgm"}}
        return _TexSubprocess(original, tools), original

    def test_miktex_uses_dvi_without_unsupported_flag_or_shell_escape(self):
        proxy, original = self._proxy()
        source = Path("working.tex").resolve()
        proxy.run(["latex", "-no-pdf", "-halt-on-error", source], capture_output=True)
        command = original.run.call_args.args[0]
        options = original.run.call_args.kwargs
        self.assertEqual(command, ["installed-latex", "-disable-installer", "-disable-write18",
                                   "-halt-on-error", "working.tex"])
        self.assertEqual(options["cwd"], str(source.parent))
        self.assertEqual(options["timeout"], 90)

    def test_texlive_keeps_no_pdf(self):
        proxy, original = self._proxy(miktex=False)
        proxy.run(["latex", "-no-pdf", Path("working.tex")])
        self.assertIn("-no-pdf", original.run.call_args.args[0])
        self.assertIn("-no-shell-escape", original.run.call_args.args[0])
        self.assertNotIn("-disable-installer", original.run.call_args.args[0])

    def test_missing_tool_has_setup_diagnostic(self):
        with patch("pyreact_manim.reference.mobject_source.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "requires latex on PATH"):
                tex_toolchain()

    def test_dvisvgm_failure_is_not_accepted_as_svg(self):
        proxy, original = self._proxy()
        original.run.return_value = subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"invalid DVI")
        with self.assertRaisesRegex(RuntimeError, "invalid DVI"):
            proxy.run(["dvisvgm", "working.dvi"])


@unittest.skipUnless(HAS_TEX, "Requires pinned ManimGL and existing latex/dvisvgm")
class RealLatexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temporary.name) / "fraction"
        cls.result = export_text_transform(cls.output, ExportSettings(
            source=r"\frac{a}{b}", target=r"\frac{b}{a}", name="latex_fraction",
            input_kind="latex", geometry_mode="curve_slots", allow_marker_approximation=True,
            glyph_height=3, frame_count=9))
        cls.raw = json.loads((cls.output / "upstream_control_points.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_independent_native_tex_and_transform_match_all_raw_controls(self):
        from manimlib import Tex, Transform
        with native_tex_environment():
            source = Tex(r"\frac{a}{b}", template="basic").set_height(3)
            target = Tex(r"\frac{b}{a}", template="basic").set_height(3)
            animation = Transform(source, target, run_time=2)
            animation.begin()
            for index, frame in enumerate(self.raw["frames"]):
                animation.interpolate(index / 8)
                members = source.family_members_with_points()
                self.assertEqual(len(members), len(frame["paths"]))
                for actual, recorded in zip(members, frame["paths"]):
                    self.assertEqual(actual.get_points().tolist(), recorded["points"])
                    self.assertEqual(actual.get_unit_normal().tolist(), recorded["native_unit_normal"])

    def test_real_source_artifacts_and_formula_provenance(self):
        report = self.result["data"]
        self.assertEqual(report["upstream_execution"]["classes"], ["manimlib.Tex", "manimlib.Transform"])
        self.assertEqual(report["input"]["kind"], "latex")
        self.assertNotIn("font", report["input"])
        self.assertIn(r"\frac{a}{b}", (self.output / "source.tex").read_text(encoding="utf-8"))
        self.assertIn("<path", (self.output / "source.svg").read_text(encoding="utf-8"))
        self.assertEqual(len(self.raw["topology"]), 3)
        self.assertFalse(report["verification"]["minecraft_pixel_parity_verified"])

    def test_formula_fits_compiler_budget(self):
        from pyreact_manim.compiler import validate_scene
        scene = json.loads((self.output / "scene.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_scene(scene)["schema_version"], 2)
        self.assertLessEqual(sum(self.result["data"]["sampling"]["vertices_per_path"]), 1024)

    def test_module_proxy_restores_even_after_failure(self):
        from manimlib.utils import tex_file_writing
        original = tex_file_writing.subprocess
        original_run = subprocess.run
        with self.assertRaisesRegex(RuntimeError, "intentional"):
            with native_tex_environment(self.result["data"]["input"]["toolchain"]):
                self.assertIs(subprocess.run, original_run)
                self.assertIsNot(tex_file_writing.subprocess, original)
                raise RuntimeError("intentional")
        self.assertIs(tex_file_writing.subprocess, original)


if __name__ == "__main__":
    unittest.main()
