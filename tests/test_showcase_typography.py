"""Guard the shader-facing point atlas against byte-order and alpha loss."""
import io
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/showcase"))
from build_typography import POINT_COUNT, encode_points, outline_points


class ShowcaseTypographyTests(unittest.TestCase):
    def test_shader_byte_decode_survives_png_and_retains_alpha_data(self):
        points = np.column_stack((np.linspace(-2, 2, POINT_COUNT),
                                  np.linspace(2, -2, POINT_COUNT)))
        image = Image.fromarray(encode_points(points)[None, :, :])
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        loaded = np.asarray(Image.open(io.BytesIO(buffer.getvalue())))[0].astype(float)
        decoded = np.column_stack((loaded[:, 0] * 256 + loaded[:, 1],
                                    loaded[:, 2] * 256 + loaded[:, 3])) / 65535 * 4 - 2
        self.assertLessEqual(np.abs(decoded - points).max(), 2 / 65535 + 1e-10)
        np.testing.assert_array_equal(loaded[0], [0, 0, 255, 255])
        np.testing.assert_array_equal(loaded[-1], [255, 255, 0, 0])

    def test_outside_range_and_nonfinite_values_fail_before_uint_conversion(self):
        for value in (float("nan"), float("inf"), -2.01, 2.01):
            points = np.zeros((POINT_COUNT, 2))
            points[0, 0] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                encode_points(points)

    def test_real_font_outlines_produce_a_fixed_reproducible_cloud(self):
        font = ROOT / "tools/reference/fonts/DejaVuSerif.ttf"
        first, description = outline_points("OB", font)
        second, repeated = outline_points("OB", font)
        self.assertEqual(first.shape, (POINT_COUNT, 2))
        self.assertGreater(description["contours"], 2)
        self.assertTrue(np.isfinite(first).all())
        self.assertLessEqual(np.abs(first[:, 0]).max(), 1.8 + 1e-9)
        self.assertLessEqual(np.abs(first[:, 1]).max(), 0.8 + 1e-9)
        np.testing.assert_array_equal(first, second)
        self.assertEqual(description, repeated)


if __name__ == "__main__":
    unittest.main()
