"""Public client block readback and failure cleanup must work before a live retry."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest


_SPEC=importlib.util.spec_from_file_location('attached_highlight_test',Path(__file__).with_name('attached_highlight_runner.py'))
attached=importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(attached)


class AttachedTests(unittest.TestCase):
    def test_native_snapshot_uses_client_getblock(self):
        view=SimpleNamespace(HighlightBoxSelection=lambda enabled: None)
        blocks=SimpleNamespace(GetBlock=lambda position: ('minecraft:stone',0))
        factory=SimpleNamespace(CreatePlayerView=lambda entity:view,CreateBlockInfo=lambda entity:blocks)
        probe=SimpleNamespace(level='level',factory=factory,camera=SimpleNamespace(
            GetPosition=lambda:(.5,-58.38,-3.5),GetForward=lambda:(0.,-.139,.99),
            PickFacing=lambda:{'type':'Block','x':0,'y':-59,'z':-2,'face':2}))
        class Experiment:
            def call(self,label,code='',expression=''):
                namespace={'probe':probe}
                exec(compile(code,label,'exec'),namespace)
                return eval(compile(expression,label,'eval'),namespace)
        snapshot=attached._snapshot(Experiment(),'client_snapshot',True,(0,-59,-2))
        self.assertEqual(snapshot['block_readback'],('minecraft:stone',0))
        self.assertTrue(snapshot['highlight_requested'])

    def test_failed_player_backup_still_saves_original_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            class Experiment:
                evidence=Path(temporary)
                variant='carrier'
                labels=[]
                def save(self):
                    pass
                def call(self,label,code='',expression=''):
                    self.labels.append(label)
                    if label=='attached_highlight_camera_backup':
                        return {'player':'player','position':[0,-58,-3],'rotation':[8,180,0],
                                'anchor':[0,0,0],'offset':[0,0,0],'perspective':0}
                    return {}
                def server(self,label,code):
                    raise RuntimeError('player backup unavailable')
            experiment=Experiment()
            with self.assertRaisesRegex(RuntimeError,'player backup unavailable'):
                attached.run(experiment)
            status=json.loads((Path(temporary)/'attached-highlight-status.json').read_text())
            self.assertIn('player backup unavailable',status['failure'])
            self.assertIn('attached_highlight_off_final',experiment.labels)
            self.assertNotIn('attached_highlight_camera_restore',experiment.labels)


if __name__=='__main__':
    unittest.main()
