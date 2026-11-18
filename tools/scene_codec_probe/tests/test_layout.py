import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('scene_layout', Path(__file__).parents[1] / 'layout.py')
layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout)


class LayoutTests(unittest.TestCase):
    def test_64k_logical_fits_and_reports_padding(self):
        for bits in (1, 2):
            plan = layout.plan_payload(65536, bits)
            self.assertEqual(plan['logical_bytes'], 65536)
            self.assertGreaterEqual(plan['allocated_bytes'], 65536)
            self.assertEqual(plan['padding_bytes'], plan['allocated_bytes'] - 65536)
            self.assertEqual(plan['allocated_bytes'], plan['pixels'] * 3 * bits // 8)
            self.assertEqual(plan['columns'] % 32, 0)
            self.assertLessEqual(plan['roi'][0] + plan['columns'], 712)
            self.assertLessEqual(plan['roi'][1] + plan['rows'], 1056)

    def test_bounds_are_physical_capacity(self):
        for bits in (1, 2):
            maximum = 22 * 1024 * 12 * bits
            self.assertEqual(layout.plan_payload(maximum, bits)['padding_bytes'], 0)
            with self.assertRaises(ValueError):
                layout.plan_payload(maximum + 1, bits)

    def test_short_partial_block_is_explicit(self):
        plan = layout.plan_payload(1, 2)
        self.assertEqual(plan['allocated_bytes'], 24)
        self.assertEqual(plan['padding_bytes'], 23)
        self.assertEqual(plan['pixels'], 32)


if __name__ == '__main__':
    unittest.main()
