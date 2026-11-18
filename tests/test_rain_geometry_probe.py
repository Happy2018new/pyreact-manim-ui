import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT/'tools/rain_geometry_probe'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


verify = module('rain_geometry_verify_tests', HERE/'verify_capture.py')
codec = module('rain_geometry_codec_tests', ROOT/'tools/scene_codec_probe/codec.py')


class RainGeometryTests(unittest.TestCase):
    def runtime(self):
        scene=types.ModuleType('geometry_atlas_probe.scene_runtime')
        scene.ProbeSystem=object
        config=types.ModuleType('geometry_atlas_probe.rain_config')
        config.SOURCE_BUNDLE_SHA256='unit'
        with mock.patch.dict(sys.modules,{'geometry_atlas_probe':types.ModuleType('geometry_atlas_probe'),
                'geometry_atlas_probe.scene_runtime':scene,'geometry_atlas_probe.rain_config':config}):
            return module('rain_geometry_runtime_test',HERE/'runtime.py')

    def test_transparency_amount_validation_and_exact_api_receipt(self):
        runtime=self.runtime()
        render=mock.Mock()
        render.EnableActorBlockGeometryTransparent.return_value=True
        render.SetActorBlockGeometryTransparency.return_value=True
        probe=types.SimpleNamespace(_require_idle_controls=lambda:None,geometry_name='resident',
            logical_bytes=65536,entity='same_entity',render_event=3,render=render,
            transparency_receipts=[],snapshot=lambda:{'ok':True})
        for value in (-.1,1.1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                runtime.ProbeSystem.set_transparent(probe,True,value)
        render.EnableActorBlockGeometryTransparent.assert_not_called()
        runtime.ProbeSystem.set_transparent(probe,True,.5)
        render.SetActorBlockGeometryTransparency.assert_called_once_with('resident',.5)
        self.assertEqual(probe.transparency_receipts[-1]['amount'],.5)
        self.assertTrue(probe.transparency_receipts[-1]['amount_setter_called'])
        runtime.ProbeSystem.set_transparent(probe,False)
        self.assertFalse(probe.transparency_receipts[-1]['amount_setter_called'])
        render.SetActorBlockGeometryTransparency.assert_called_once()

    def test_quiesce_reads_order_after_each_disable_that_can_reset_chain(self):
        runtime=self.runtime()
        class Post:
            def __init__(self): self.order=['raw','diagnostic']; self.calls=[]
            def GetPostProcessOrder(self): return self.order
            def SetEnableByName(self,name,value):
                self.calls.append(name)
                self.order=[]
                return True
        post=Post()
        probe=types.SimpleNamespace(set_native_writer_visible=mock.Mock(),background_name=None,
            codec_processes=['raw','diagnostic'],post=post,snapshot=lambda:{'ok':True})
        runtime.ProbeSystem.quiesce(probe)
        probe.set_native_writer_visible.assert_called_once_with(False)
        self.assertEqual(post.calls,['raw'])

    def test_fresh_build_metadata_and_rendering_hashes_match(self):
        builder=module('rain_geometry_builder_test',HERE/'build_probe.py')
        with tempfile.TemporaryDirectory(dir=ROOT/'.runtime',prefix='rain-cpu-build-') as folder:
            output=builder.build(Path(folder)/'project')
            manifest=json.loads((output/'source_manifest.json').read_text(encoding='utf-8'))
            import hashlib
            self.assertTrue(all(hashlib.sha256((output/name).read_bytes()).hexdigest()==expected
                for name,expected in manifest['generated_sha256'].items()))
            original=json.loads((builder.NATIVE/'resource_packs/vanilla_netease/graphics_settings/post_process.json').read_text(encoding='utf-8-sig'))
            actual=json.loads((output/'resource_pack/graphics_settings/post_process.json').read_text(encoding='utf-8'))
            for item in original['process_array']: item['enable']=False
            self.assertEqual(actual,original)

    def image(self, rows):
        pixels = np.zeros((1080, 720, 4), dtype=np.uint8)
        pixels[:, :, 3] = 255
        target = pixels[128:1064].reshape(-1, 4)
        target[:len(rows), :3] = rows
        return pixels

    def check(self, pixels, kind, count):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'capture.png'
            Image.fromarray(pixels).save(path)
            return verify.verify(path, kind, count)

    def test_all_payload_bytes_and_all_q_symbols_match_independent_codec(self):
        payload = bytearray(codec.payload_oracle(i, 29) if i < 65536 else 0 for i in range(65568))
        self.assertEqual(verify.payload(np.arange(65568)).tobytes(), payload)
        expected = codec.payload_to_symbols(payload, 2)
        self.assertEqual(verify.symbols(87424).tobytes(), expected)
        self.assertEqual(codec.symbols_to_payload(expected, 2, len(payload)), payload)

    def test_last_query_and_any_guard_pixel_are_checked(self):
        pixels = self.image(verify.expected_query('identity', 65536))
        self.assertTrue(self.check(pixels, 'identity', 65536)['passed'])
        pixels[128+65535//720, 65535 % 720, 0] ^= 1
        bad = self.check(pixels, 'identity', 65536)
        self.assertEqual(bad['query_errors'], 1)
        self.assertEqual(bad['failures_first16'][0]['ordinal'], 65535)
        pixels[900, 0, 0] = 1
        self.assertEqual(self.check(pixels, 'identity', 65536)['guard_errors'], 1)

    def test_q_and_sameframe_alpha_are_independently_counted(self):
        rows = np.column_stack((verify.symbols(87424), np.full(87424, 255), np.zeros(87424))).astype(np.uint8)
        rows[1, 0] ^= 1
        rows[1, 1] = 123
        rows[3, 0] ^= 1
        report = self.check(self.image(rows), 'q_alpha', 87424)
        self.assertEqual(report['bad_q'], 2)
        self.assertEqual(report['bad_q_alpha_not255'], 1)
        self.assertEqual(report['bad_q_alpha255'], 1)
        self.assertEqual(report['alpha_not255'], 1)

    def test_overflow_alpha_error_and_repeated_block_counts(self):
        rows = np.zeros((87424, 3), dtype=np.uint8)
        rows[32:64, 0] = 5
        rows[32:64, 1] = 255
        rows[70, 2] = 3
        report = self.check(self.image(rows), 'block_alpha', 87424)
        self.assertEqual(report['max_block_exceptions'], 5)
        self.assertEqual(report['overflow_source_pixels'], 32)
        self.assertEqual(report['alpha_restore_error_pixels'], 1)
        self.assertEqual(report['inconsistent_block_count_pixels'], 0)

    def test_known_color_domain_covers_every_symbol_and_every_original_byte(self):
        original = verify.domain('domain_original')
        encoded = verify.domain('domain_encoded')
        restored = verify.domain('domain_restored')
        for symbol in range(64):
            self.assertEqual(set(original[symbol*256:(symbol+1)*256, 0]), set(range(256)))
        recovered = encoded[:, 0]//64+4*(encoded[:, 1]//64)+16*(encoded[:, 2]//64)
        self.assertTrue(np.array_equal(recovered, np.arange(16384)//256))
        self.assertLessEqual(np.abs(restored.astype(np.int16)-original.astype(np.int16)).max(), 3)
        self.assertTrue(self.check(self.image(encoded), 'domain_encoded', 16384)['passed'])

    def test_new_diagnostic_uses_raw_q_and_does_not_mask_query_pixels(self):
        source = (HERE/'diagnostic.fragment').read_text(encoding='utf-8')
        self.assertIn('observed/255.0', source)
        self.assertIn('count/255.0,step(4.5,count),abs(decoded.a-raw.a)', source)
        self.assertNotIn('discard', source)
        self.assertIn("'native_config_changes': ['process_array[*].enable=false']",
                      (HERE/'build_probe.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
