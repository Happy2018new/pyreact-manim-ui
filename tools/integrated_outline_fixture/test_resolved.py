"""Host name resolution must not rewrite raw receipts or loosen original gates."""
import copy
import importlib.util
from pathlib import Path
import unittest

import numpy as np


_SPEC = importlib.util.spec_from_file_location(
    'outline_resolved_under_test', Path(__file__).with_name('verify_resolved.py'))
resolved = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(resolved)


def _snapshots():
    base = {'entity': 'frozen-client-entity', 'registered': True,
            'position_matches_requested': True, 'camera_matches_initial': True,
            'projection_all_visible': True, 'native_material_recipe_present': False,
            'native_render_controllers_present': True,
            'registered_material_values': [name + '.skinning' for name in resolved.MATERIALS],
            'registered_render_controllers': list(resolved.CONTROLLERS),
            'native_position': [0., 0., 4.], 'requested_position': [0., 0., 4.],
            'camera': [0., 0., 0.], 'roi': [10, 10, 50, 60], 'viewport': [120, 100],
            'projected_corners': [], 'projected_bounds': [50, 25, 70, 55]}
    return [dict(base, native_query=value) for value in (0., 1., 0.)]


class ResolvedVerifierTests(unittest.TestCase):
    def test_exact_variant_acceptance_and_raw_receipts_unchanged(self):
        states = _snapshots()
        original = copy.deepcopy(states)
        self.assertTrue(resolved.compare_snapshots(*states)['pass'])
        self.assertEqual(states, original)
        for name in resolved.MATERIALS:
            self.assertEqual(resolved.EXACT_VARIANTS[name + '.skinning'], name)

    def test_unknown_or_nested_suffix_and_projection_change_fail(self):
        for suffix in ('.skinning.extra', '.SKINNING', '.other'):
            states = copy.deepcopy(_snapshots())
            states[1]['registered_material_values'][0] = resolved.MATERIALS[0] + suffix
            self.assertFalse(resolved.compare_snapshots(*states)['pass'])
        states = _snapshots()
        states[1]['projected_bounds'] = [1, 2, 3, 4]
        self.assertFalse(resolved.compare_snapshots(*states)['pass'])

    def test_original_strict_whole_window_drift_is_unchanged(self):
        before = np.zeros((100, 120, 3), dtype=np.uint8)
        before[25:55, 50:70] = 224
        active = before.copy()
        active[23:57, 48:72] = [255, 0, 255]
        active[25:55, 50:70] = 224
        after = before.copy()
        after[13:22, 38:48] = 255
        args = (before, active, after, [10, 10, 50, 60], [50, 25, 70, 55])
        actual = resolved.compare_outline(*args)
        self.assertEqual(actual, resolved._ORIGINAL.compare_outline(*args))
        self.assertFalse(actual['pass'])
        self.assertIn('off-before/off-after fixture window changed', actual['errors'])


if __name__ == '__main__':
    unittest.main()
