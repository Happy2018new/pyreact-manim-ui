"""Small real-GL regressions for production SDF placement and thin-rule AA."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/showcase_v2"))
from audit_sdf import FilmRenderer, glyph_shader
from build_type import sdf_tile


@unittest.skipUnless(importlib.util.find_spec("moderngl"), "desktop GL diagnostic requires moderngl")
class ShowcaseSdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="pmanim-sdf-")
        metadata = json.loads((ROOT / "tools/showcase_v2/type_data.json").read_text(encoding="utf-8"))
        rule = metadata["shapes"]["tex_rule"]
        # The ink rectangle is exactly 480 by 16 output pixels at this viewport.
        glyph = {"center": [0, 0], "size": [8, .2 / .75], "tile": rule["tile"]}
        shader = Path(cls.directory.name) / "rule.fragment"
        shader.write_text(glyph_shader([glyph]), encoding="utf-8")
        cls.renderer = FilmRenderer(shader, ROOT / "resource_pack/textures/manim/client_showcase.png", 1280, 720)

    @classmethod
    def tearDownClass(cls):
        cls.renderer.close()
        cls.directory.cleanup()

    def test_half_pixel_mapping_preserves_exact_rule_ink_bounds(self):
        pixels = np.asarray(self.renderer.image(0))[:, :, 0]
        ys, xs = np.where(pixels > 127)
        self.assertEqual((int(xs.min()), int(xs.max() + 1)), (400, 880))
        self.assertEqual((int(ys.min()), int(ys.max() + 1)), (352, 368))

    def test_thin_horizontal_rule_has_no_horizontal_trail_or_padding_panel(self):
        pixels = np.asarray(self.renderer.image(0))[:, :, 0]
        self.assertLessEqual(int(pixels[354:366, 390:398].max()), 1)
        self.assertLessEqual(int(pixels[354:366, 882:890].max()), 1)
        self.assertLessEqual(int(pixels[345:350, 410:870].max()), 1)

    def test_identical_glyph_keeps_fill_at_start_middle_and_end(self):
        first = np.asarray(self.renderer.image(0))
        np.testing.assert_array_equal(first, np.asarray(self.renderer.image(.5)))
        np.testing.assert_array_equal(first, np.asarray(self.renderer.image(1)))

    def test_tiny_lanczos_ringing_keeps_its_true_outside_distance(self):
        # A tiny resampling halo three pixels from an edge is not a new contour.
        alpha = np.zeros((32, 32), dtype=np.uint8)
        alpha[8:24, 8:24] = 255
        alpha[10:22, 5] = 4
        encoded = np.asarray(sdf_tile(Image.fromarray(alpha)))
        distance = (encoded.astype(float) / 255 - .5) * 48
        self.assertLess(float(distance[16, 5]), -2.0)
        self.assertGreater(float(distance[16, 8]), 0)


if __name__ == "__main__":
    unittest.main()
