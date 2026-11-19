"""Fail-closed host acceptance boundaries; no native host invocation."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('particle_runner_under_test', HERE/'runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def state():
    return {'state': 'resident', 'ready': True, 'pipeline_ready': True, 'pipeline_enabled': True,
        'error': None, 'measurement': None, 'identity': {'host_sha256': '0'*64},
        'active_pages': ['data'], 'native_page_names': ['clear', 'data'],
        'native_attempt_count': 3, 'native_records_reserved': 131073, 'actor_count': 2,
        'effects': [], 'native_post_flags': [('bloom', False)],
        'viewport': [720, 1080], 'source_roi': [8, 128, 512, 512],
        'pipeline_links': [list(link) for link in runner.LINKS],
        'particle_candidate': {'sfx_overlay_omitted': True}}


class RunnerTests(unittest.TestCase):
    def test_frozen_legacy_helper_restores_import_namespace_and_owner(self):
        previous = object()
        with patch.dict(sys.modules, {'runner': previous}):
            helper = runner.frameani_helper()
            self.assertIs(sys.modules['runner'], previous)
        self.assertEqual(helper.HERE, runner.COMPAT)
        self.assertEqual(runner.compat.OWNER, runner.OWNER)
        self.assertEqual(runner.compat.integrated.bulk.OWNER, runner.OWNER)
        self.assertEqual(runner.compat.integrated.bulk.order.OWNER, runner.OWNER)

    def test_frameani_cleanup_failure_is_rejected_before_any_pixel_claim(self):
        for cleanup in ({}, {'effects_destroyed': True, 'wall': {'all_exact': False}},
                        {'effects_destroyed': True, 'wall': {'all_exact': True}, 'wall_error': 'failed'}):
            with self.subTest(cleanup=cleanup), self.assertRaisesRegex(RuntimeError, 'cleanup'):
                runner.check_frameani(SimpleNamespace(reports=[]),
                    {'complete': True, 'failure': None, 'cleanup': cleanup, 'cases': []})

    def test_empty_frameani_matrix_cannot_pass(self):
        outcome = {'complete': True, 'failure': None, 'cases': [],
            'cleanup': {'effects_destroyed': True, 'wall': {'all_exact': True}}}
        with self.assertRaisesRegex(RuntimeError, 'sixteen'):
            runner.check_frameani(SimpleNamespace(reports=[]), outcome)

    def test_frozen_resident_gate_rejects_shared_effect_or_missing_link(self):
        frozen = state()
        experiment = SimpleNamespace(state=state(), candidate={'viewport': [720, 1080], 'roi': [8, 128, 512, 512]})
        runner.resident(experiment, frozen)
        for key, value in (('effects', ['shared-frameani']), ('pipeline_links', []), ('active_pages', ['changed'])):
            experiment.state = dict(state(), **{key: value})
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                runner.resident(experiment, frozen)

    def test_missing_actual_host_input_fails_and_persists_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            current = state()
            experiment = SimpleNamespace(args=SimpleNamespace(project=directory), evidence=directory,
                state=current, payload=b'not-a-real-input', loads=[], weather_is_raining=False,
                candidate={'viewport': [720, 1080], 'roi': [8, 128, 512, 512], 'logical_bytes': 65536},
                save=lambda: None, call=lambda label: current)
            with patch.object(runner, 'validate_assets', return_value=experiment.candidate):
                with self.assertRaisesRegex(RuntimeError, 'actual host input'):
                    runner.run(experiment, include_frameani=False)
            result = json.loads((directory/'particle-candidate-status.json').read_text(encoding='utf-8'))
            self.assertFalse(result['pass'])
            self.assertFalse(result['complete'])
            self.assertIn('actual host input', result['failure'])


if __name__ == '__main__':
    unittest.main()
