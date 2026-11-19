"""Semantic host tests for stable receiver witnesses and same-frame payload gates."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image


_SPEC = importlib.util.spec_from_file_location('native_shadow_test_verify', Path(__file__).with_name('verify.py'))
verify = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verify)


def fixture():
    plan = verify.make_plan([120, 100], [10, 10, 50, 60],
        [[35, 43], [90, 43], [90, 70], [35, 70]], [48, 20, 72, 40],
        [[10, 75], [30, 75], [30, 90], [10, 90]], output_y=100)
    off = np.full((100, 120, 3), 150, dtype=np.uint8)
    active = off.copy()
    active[50:65, 45:75] = 100
    return plan, off, active


class NativeShadowTests(unittest.TestCase):
    def test_neutral_receiver_shadow_crosses_roi(self):
        plan, off, active = fixture()
        result = verify.compare_shadow(off, active, off, plan)
        self.assertTrue(result['pass'], result)
        self.assertGreater(result['shadow_pixels']['at_roi_boundary'], 0)

    def test_body_animation_background_drift_and_whole_scene_darkening_fail(self):
        plan, off, active = fixture()
        moving = off.copy()
        moving[48:60, 37:48] = 240
        self.assertFalse(verify.compare_shadow(off, active, moving, plan)['pass'])
        animated = active.copy()
        animated[28:33, 58:63] = 20
        self.assertFalse(verify.compare_shadow(off, animated, off, plan)['pass'])
        whole_scene = np.full_like(off, 100)
        self.assertFalse(verify.compare_shadow(off, whole_scene, off, plan)['pass'])
        self.assertFalse(verify.compare_shadow(off, off, off, plan)['pass'])

    def test_plan_cannot_change_after_capture(self):
        plan, off, active = fixture()
        changed = copy.deepcopy(plan)
        changed['receiver_polygon'][0][0] += 1
        with self.assertRaises(ValueError):
            verify.compare_shadow(off, active, off, changed)

    def test_exact_payload_and_shadow_are_required_in_same_captures(self):
        plan = verify.make_plan([720,1080], [8,128,512,512],
            [[400,410],[680,410],[680,600],[400,600]], [480,250,560,400],
            [[200,450],[300,450],[300,500],[200,500]], output_y=650)
        off = np.full((1080,720,3), 150, dtype=np.uint8)
        active = off.copy()
        active[450:480,470:570] = 100
        payload = bytes(range(256)) * 256
        identity = {'byte_count': 65536, 'host_sha256': hashlib.sha256(payload).hexdigest()}
        with tempfile.TemporaryDirectory() as temporary:
            reports = []
            for mode in (1,3):
                pixels = active.copy()
                output = pixels[650:].reshape(-1,3)
                output[:] = verify._PAYLOAD_VERIFY.GUARD
                values = np.frombuffer(payload, dtype=np.uint8).astype(np.uint16)
                if mode == 1:
                    output[:65536] = np.column_stack((values, (71*values+43)%256, (131*values+17)%256))
                else:
                    symbols = ((values[:,None] >> np.arange(0,8,2)) & 3).reshape(-1)
                    output[:262144] = np.column_stack((symbols*64, np.full(262144,255), np.zeros(262144)))
                capture = Path(temporary) / ('diagnostic%d.png' % mode)
                Image.fromarray(pixels).save(capture)
                reports.append({'mode': mode, 'label': 'mode' + str(mode), 'logical_bytes': 65536,
                'exact': True, 'error_pixels': 0, 'configuration': 'all', 'source_roi': plan['roi'],
                'payload_sha256': identity['host_sha256'], 'capture_file': str(capture),
                'query_count': 65536 if mode == 1 else 262144, 'distinct_final_addresses': 65536,
                'output_origin': [0, 650], 'state': {'identity': identity, 'payload_visible': True,
                    'state':'resident', 'ready':True, 'generation':1, 'active_pages':['bit64','bit128'],
                    'native_page_names':['clear','bit64','bit128'], 'native_attempt_count':3,
                    'native_records_reserved':131073}})
            frames = [off, active, off]
            result = verify.compare_coexistence(frames, frames, plan, reports, payload)
            self.assertTrue(result['pass'], result)
            broken = copy.deepcopy(reports)
            broken[1]['error_pixels'] = 1
            broken[1]['exact'] = False
            self.assertFalse(verify.compare_coexistence(frames, frames, plan, broken, payload)['pass'])
            self.assertFalse(verify.compare_coexistence(frames, frames, plan, reports)['pass'])
            broken = copy.deepcopy(reports)
            del broken[1]['state']['active_pages']
            self.assertFalse(verify.compare_coexistence(frames, frames, plan, broken, payload)['pass'])
            capture = Path(reports[0]['capture_file'])
            pixels = np.array(Image.open(capture))
            pixels[650,0,0] ^= 1
            Image.fromarray(pixels).save(capture)
            corrupted = verify.compare_coexistence(frames, frames, plan, reports, payload)
            self.assertFalse(corrupted['pass'])
            self.assertFalse(corrupted['payload_is_byte_exact'])

    def test_actual_installed_shadow_receipt(self):
        receipt = verify.native_material_receipt('D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.467018')
        self.assertEqual(receipt['shadow_volume_shared_write_bits'], 0)
        self.assertEqual(receipt['shadow_overlay_shared_read_bits'], 192)
        self.assertFalse(receipt['engine_route_proven'])


if __name__ == '__main__':
    unittest.main()
