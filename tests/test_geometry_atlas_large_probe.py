import importlib.util
from pathlib import Path
import unittest

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('large_atlas_oracle', ROOT / 'tools/geometry_atlas_large_probe/verify_capture.py')
oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oracle)


def receipt(n=65536):
    pages = [{'base': i*65536, 'count': 65536, 'loaded': True, 'ready': True, 'name': 'page%d' % i}
        for i in range(n//65536)]
    return {'schema': oracle.SCHEMA, 'screen_size': [2560,1440], 'slot_count': n, 'loaded_bytes': n,
        'pipeline_ready': True, 'connection': True, 'layout': [n,2048,8,32], 'dimensions': [1,2560,1440,91],
        'query': [0,n,0,37], 'flip_y': True, 'pages': pages, 'geometry_names': [p['name'] for p in pages],
        'seed': 54321, 'generation': 1, 'writer_visible': True, 'runtime_payload_files': False, 'diagnostic_layout': [16,128,2048,1], 'border_guard_rect_native': [0,128,2560,1408], 'diagnostic_border_policy': 'declared_guard_rect_excluding_native_debug_UI'}


class LargeAtlasTests(unittest.TestCase):
    def test_every_pixel_last_pixel_and_border(self):
        state = receipt()
        pixels = np.empty((1440,2560,4), dtype=np.uint8)
        pixels[:] = [8,16,32,255]
        expected = oracle.expected_bytes(54321,1,np.arange(65536)).reshape(32,2048)
        pixels[128:160,16:2064,:3] = expected[:,:,None]
        self.assertTrue(oracle.verify_image(state,Image.fromarray(pixels))['passed'])
        pixels[159,2063,0] ^= 1
        report = oracle.verify_image(state,Image.fromarray(pixels))
        self.assertEqual(report['failed_queries'],1)
        self.assertEqual(report['failures_first32'][0]['ordinal'],65535)
        pixels[128,0,0] ^= 1
        self.assertEqual(oracle.verify_image(state,Image.fromarray(pixels))['border_failures'],1)

    def test_bounded_float32_permutation_every_index(self):
        for n in (1048576,1572864,2097152):
            with self.subTest(n=n):
                index = np.arange(n,dtype=np.float32)
                value = index.copy()
                for _ in range(7):
                    value = np.mod(value*2,np.float32(n))
                actual = np.mod(value+3*index+37,np.float32(n)).astype(np.uint64)
                expected = (131*np.arange(n,dtype=np.uint64)+37)%n
                self.assertTrue(np.array_equal(actual,expected))

    def test_rejects_resized_and_incomplete(self):
        state = receipt()
        with self.assertRaises(ValueError):
            oracle.validate_receipt(state,(1280,720))
        state['loaded_bytes'] -= 1
        with self.assertRaises(ValueError):
            oracle.validate_receipt(state,(2560,1440))


if __name__ == '__main__':
    unittest.main()
