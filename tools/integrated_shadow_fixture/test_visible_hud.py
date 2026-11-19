"""HUD visibility retry preserves original verifier and restores on failure."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


_SPEC=importlib.util.spec_from_file_location('visible_hud_test',Path(__file__).with_name('visible_hud_highlight_runner.py'))
wrapper=importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(wrapper)


class VisibleHudTests(unittest.TestCase):
    def test_exception_restores_harness_hidden_hud(self):
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
                raise RuntimeError('unchanged native positive control failed')
            try:
                wrapper.attached.run=failed
                experiment=Experiment()
                with self.assertRaisesRegex(RuntimeError,'unchanged native positive'):
                    wrapper.run(experiment)
            finally:
                wrapper.attached.run=original
            self.assertIn('HideHudGUI(False)',experiment.calls[0][1])
            self.assertIn('HideCrossHairGUI(False)',experiment.calls[0][1])
            self.assertIn('HideHudGUI(True)',experiment.calls[-1][1])
            self.assertIn('HideCrossHairGUI(True)',experiment.calls[-1][1])
            status=json.loads((Path(temporary)/'visible-hud-highlight-status.json').read_text())
            self.assertFalse(status['pass'])
            self.assertTrue(status['frozen_attached_source_unchanged'])


if __name__=='__main__':
    unittest.main()
