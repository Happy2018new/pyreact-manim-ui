"""Numerical bounds and winding are part of the exported format's contract."""

import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pyreact_manim.reference.sampling import (choose_subdivisions, chord_error_bound,
                                             quadratic_point, sample_contour, signed_area)


class ReferenceSamplingTests(unittest.TestCase):
    def test_quadratic_chord_error_bound_is_tight_at_midpoint(self):
        curve = [[0, 0], [1, 2], [2, 0]]
        for count in (1, 2, 7, 31):
            bound = chord_error_bound(curve, count)
            worst = 0.0
            for segment in range(count):
                a = quadratic_point(curve, segment / count)
                b = quadratic_point(curve, (segment + 1) / count)
                for step in range(101):
                    local = step / 100
                    actual = quadratic_point(curve, (segment + local) / count)
                    linear = [a[k] + (b[k] - a[k]) * local for k in (0, 1)]
                    distance = math.hypot(*(actual[k] - linear[k] for k in (0, 1)))
                    self.assertLessEqual(distance, bound + 1e-12)
                    worst = max(worst, distance)
            self.assertAlmostEqual(worst, bound, places=12)

    def test_requested_tolerance_is_respected_even_for_large_curvature(self):
        for curve in ([[0, 0], [1000, -1000], [0, 0]], [[0, 0], [1, 1], [2, 2]]):
            for tolerance in (0.5, 0.003, 1e-5):
                n = choose_subdivisions(curve, tolerance)
                self.assertLessEqual(chord_error_bound(curve, n), tolerance + 1e-15)
                if n > 1:
                    self.assertGreater(chord_error_bound(curve, n - 1), tolerance)

    def test_winding_and_degenerate_retraced_contour_are_retained(self):
        rounded = [[1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0],
                   [-1, -1], [0, -1], [1, -1], [1, 0]]
        forward = sample_contour(rounded, [4] * 4)
        reverse = sample_contour(list(reversed(rounded)), [4] * 4)
        self.assertEqual(len(forward), 16)
        self.assertGreater(signed_area(forward), 0)
        self.assertAlmostEqual(signed_area(forward), -signed_area(reverse))
        retraced = rounded[:-1] + list(reversed(rounded))
        degenerate = sample_contour(retraced, [4] * 8)
        self.assertEqual(len(degenerate), 32)
        self.assertAlmostEqual(signed_area(degenerate), 0, places=12)

    def test_invalid_sampling_contracts_are_rejected(self):
        curve = [[0, 0], [1, 1], [2, 0]]
        for invalid in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                choose_subdivisions(curve, invalid)
        with self.assertRaises(ValueError):
            sample_contour(curve, [True])
        with self.assertRaises(ValueError):
            sample_contour(curve, [1, 2])


if __name__ == "__main__":
    unittest.main()
