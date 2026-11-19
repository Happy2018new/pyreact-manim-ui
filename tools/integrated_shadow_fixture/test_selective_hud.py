"""Selective widget setup retains the frozen full diagnostic verifier and cleanup."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


_SPEC=importlib.util.spec_from_file_location('selective_hud_test',Path(__file__).with_name('selective_hud_highlight_runner.py'))
wrapper=importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(wrapper)


class SelectiveHudTests(unittest.TestCase):
    def test_failure_restores_widgets_and_harness_global_hide(self):
        with tempfile.TemporaryDirectory() as temporary:
            class Experiment:
                evidence=Path(temporary)
                calls=[]
                def call(self,label,code='',expression=''):
                    self.calls.append((label,code))
                def save(self):
                    pass
            original=wrapper.attached.run
            def failed(experiment):
                raise RuntimeError('unchanged diagnostic rejected')
            try:
                wrapper.attached.run=failed
                experiment=Experiment()
                with self.assertRaisesRegex(RuntimeError,'unchanged diagnostic'):
                    wrapper.run(experiment)
            finally:
                wrapper.attached.run=original
            for method in ('HideSlotBarGui','HideHealthGui','HideArmorGui'):
                self.assertIn(method+'(True)',experiment.calls[0][1])
                self.assertIn(method+'(False)',experiment.calls[-1][1])
            self.assertIn('HideHudGUI(False)',experiment.calls[0][1])
            self.assertIn('HideHudGUI(True)',experiment.calls[-1][1])
            status=json.loads((Path(temporary)/'selective-hud-highlight-status.json').read_text())
            self.assertFalse(status['pass'])
            self.assertFalse(status['oracle_relaxation'])
            self.assertTrue(status['frozen_attached_source_unchanged'])


if __name__=='__main__':
    unittest.main()
