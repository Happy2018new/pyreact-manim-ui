"""Face-interior highlight must reject line-only and drifting target evidence."""
import copy
import importlib.util
from pathlib import Path
import unittest

import numpy as np


_SPEC=importlib.util.spec_from_file_location('native_highlight_test',Path(__file__).with_name('highlight.py'))
highlight=importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(highlight)


class HighlightTests(unittest.TestCase):
    def test_face_crossing_line_only_and_background_negatives(self):
        plan=highlight.make_plan([120,100],[10,10,50,60],[[40,20],[80,20],[80,60],[40,60]],
            [[10,75],[30,75],[30,90],[10,90]],{'type':'Block','x':-1,'y':-59,'z':-1,'face':2},100)
        off=np.full((100,120,3),100,dtype=np.uint8)
        active=off.copy(); active[20:61,40:81]=150
        self.assertTrue(highlight.compare_visible(off,active,off,plan)['pass'])
        lines=off.copy(); lines[20,40:81]=255; lines[60,40:81]=255
        lines[20:61,40]=255; lines[20:61,80]=255
        self.assertFalse(highlight.compare_visible(off,lines,off,plan)['pass'])
        whole=np.full_like(off,150)
        self.assertFalse(highlight.compare_visible(off,whole,off,plan)['pass'])
        states=[{'highlight_requested':value,'pick':plan['target'],'camera':[0,0,0],
                 'block_readback':{'name':'minecraft:stone','aux':0}} for value in (False,True,False)]
        self.assertTrue(highlight.compare_snapshots(states,plan)['pass'])
        changed=copy.deepcopy(states); changed[1]['pick']['x']=4
        self.assertFalse(highlight.compare_snapshots(changed,plan)['pass'])

    def test_thin_oblique_face_is_rejected_before_capture(self):
        with self.assertRaises(ValueError):
            highlight.make_plan([120,100],[10,10,50,60],[[40,20],[44,20],[80,60],[76,60]],
                [[10,75],[30,75],[30,90],[10,90]],{'type':'Block','x':-1,'y':-59,'z':-1,'face':2},100)


if __name__=='__main__':
    unittest.main()
