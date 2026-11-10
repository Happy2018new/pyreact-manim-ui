"""CPU regression for whole-caption rejection during rotated glyph morphs."""
import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from presentation.vector_morph import _pair_bounds, render_pairs


def emitted(values):
    return np.array([float('%.6f' % value) for value in values])


class VectorGroupBoundsTests(unittest.TestCase):
    def test_bounds_cover_emitted_rotated_tiles_throughout_interpolation(self):
        cases = (
            ((-4, 2), (3, -1), (2, .2), (.3, 3), .08),
            ((1.1234567, -.0000004), (-.25, 2.1234567), (1e-9, 2), (4, 1e-9), -.15),
            ((-1e4, 3e3), (1e4, -3e3), (1, 1), (2, .5), 1.2),
            ((0, 0), (0, 0), (.01, 4), (4, .01), 0),
        )
        for a, b, sa, sb, arc in cases:
            first, second = dict(center=a, size=sa), dict(center=b, size=sb)
            lower, upper = _pair_bounds(first, second, arc)
            lower, upper = emitted(lower), emitted(upper)
            arc = float('%.6f' % arc)
            for u in np.linspace(0, 1, 257):
                lift = math.sin(math.pi * u)
                center = emitted(a) * (1-u) + emitted(b) * u + np.array((.21, 1)) * arc * lift
                size = np.maximum(emitted(sa) * (1-u) + emitted(sb) * u, .00001)
                angle = lift * arc * .16
                turn = np.array(((math.cos(angle), -math.sin(angle)),
                                 (math.sin(angle), math.cos(angle))))
                corners = np.array(((-.5, -.5), (-.5, .5), (.5, -.5), (.5, .5)))
                points = (corners * size) @ turn.T + center
                self.assertTrue(np.all(points >= lower), (u, points, lower))
                self.assertTrue(np.all(points <= upper), (u, points, upper))

    def test_outside_progress_is_not_rejected_by_normalized_progress_bounds(self):
        a = dict(center=[-2, 0], size=[1, 1], tile=[0, 0, 100, 100], opacity=1)
        b = dict(a, center=[2, 0])
        code = render_pairs(None, [(a, b)], amount='progress')
        self.assertIn('(progress)<0.0 || (progress)>1.0', code)
        self.assertEqual(code.count('vectorStaticGlyph('), 1)

    def test_absent_group_emits_no_region_or_glyph_work(self):
        glyph = dict(center=[0, 0], size=[1, 1], tile=[0, 0, 100, 100], opacity=0)
        self.assertEqual(render_pairs(None, [(glyph, glyph)]), '')


if __name__ == '__main__':
    unittest.main()
