"""Semantic guards for preserving native effect structure and sample domains."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('compat_builder', HERE / 'build_overlay.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
CLIENT_SPEC = importlib.util.spec_from_file_location('compat_client', HERE / 'runtime_client.py')
CLIENT = importlib.util.module_from_spec(CLIENT_SPEC)
CLIENT_SPEC.loader.exec_module(CLIENT)


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.native = self.root / 'native'
        self.config = {'render_order': ['bloom', 'depthoffield', 'vignette'], 'process_array': []}
        self.materials = {}
        self.fragments = {}
        for name, material, fragment, owned in BUILDER.TARGETS:
            self.config['process_array'].append({
                'name': name, 'enable': name == 'bloom',
                'paras': {'threshold': .5, 'radius': 1., 'intensity': 1.},
                'pass_array': [{'material': 'untouched', 'render_target': {'width': .5, 'height': .5}},
                               {'material': material, 'shaderPassName': 'NativeFinal',
                                'render_target': {'width': 1., 'height': 1.}}]})
            self.materials[material] = {
                'fragmentShader': 'shaders/' + fragment,
                'vertexShader': 'shaders/uv_fullscreen.vertex',
                '+defines': ['LAST_RENDER_PASS'],
                '+variants': [{'rngl': {'+defines': ['RNGL']}}],
                'samplerStates': [{'samplerIndex': 1, 'textureFilter': 'Point'}],
                'states': ['DisableDepthTest'], 'msaaSupport': 'Both'}
            source = ('// __multiversion__\n#include "util.h"\n'
                      'uniform sampler2D TEXTURE_0;\nuniform sampler2D TEXTURE_1;\n'
                      'uniform sampler2D TEXTURE_2;\nuniform vec4 EXTRA_VECTOR1;\n'
                      'vec4 nativeMath() { return texture(TEXTURE_0, uv) + texture(TEXTURE_2, uv); }\n'
                      'void main() { gl_FragColor = texture(TEXTURE_1, uv) + nativeMath(); }\n')
            self.fragments[fragment] = source
            path = self.native / 'shaders/glsl' / fragment
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding='utf-8')
        pack = self.native / 'resource_packs/vanilla_netease'
        BUILDER.write_json(pack / 'graphics_settings/post_process.json', self.config)
        BUILDER.write_json(pack / 'materials/postprocess.material', self.materials)

    def tearDown(self):
        self.temporary.cleanup()

    def build(self, decode=True, physical=(720, 1080), roi=(8, 32, 128, 683)):
        path = self.root / ('carrier' if decode else 'identity')
        manifest = BUILDER.build_overlay(path, self.native, physical, roi, carrier_decode=decode)
        return path, manifest

    def test_only_two_native_config_references_change(self):
        output, manifest = self.build()
        config = json.loads((output / 'resource_pack/graphics_settings/post_process.json').read_text())
        self.assertEqual(len(BUILDER.changed_paths(self.config, config)), 2)
        self.assertEqual(config['render_order'], self.config['render_order'])
        self.assertEqual(manifest['config_changed_paths'],
                         ['/process_array/0/pass_array/1/material', '/process_array/1/pass_array/1/material'])
        derived = json.loads((output / 'resource_pack/materials/postprocess.material').read_text())
        for _, old, _, owned in BUILDER.TARGETS:
            self.assertEqual(BUILDER.changed_paths(self.materials[old], derived[owned]), ['/fragmentShader'])
        self.assertEqual(manifest['runtime_contract']['new_uniform_bindings'], [])

    def test_native_shader_math_and_non_raw_bindings_preserved_exactly(self):
        output, _ = self.build()
        for _, _, fragment, owned in BUILDER.TARGETS:
            source = self.fragments[fragment]
            patched = (output / 'resource_pack/shaders/glsl' / (owned + '.fragment')).read_text()
            helper = BUILDER.helper_source((720, 1080), (8, 32, 128, 683), 2, True)
            reconstructed = patched.replace(helper, '').replace('pmanimSceneCompatSample(uv)', 'texture(TEXTURE_1, uv)')
            self.assertEqual(reconstructed, source)
            self.assertEqual(patched.count('texture(TEXTURE_0, uv)'), source.count('texture(TEXTURE_0, uv)'))
            self.assertEqual(patched.count('texture(TEXTURE_2, uv)'), source.count('texture(TEXTURE_2, uv)'))
            self.assertIn('rawScene.rgb =', helper)
            self.assertNotIn('rawScene.a =', helper)
            self.assertNotRegex(helper, r'(?m)^\s*uniform\s')

    def test_identity_has_only_unmodified_sampler(self):
        output, manifest = self.build(False)
        self.assertFalse(manifest['carrier_decode'])
        helper = BUILDER.helper_source((720, 1080), (8, 32, 128, 683), 2, False)
        self.assertIn('return texture(TEXTURE_1, sampleUV)', helper)
        self.assertNotIn('floor(', helper)
        self.assertNotIn('mod(', helper)
        self.assertTrue((output / 'compat_manifest.json').exists())

    def test_large_roi_and_all_boundary_pixels(self):
        physical, roi = (1080, 1440), (8, 128, 704, 993)
        _, manifest = self.build(physical=physical, roi=roi)
        self.assertEqual(manifest['roi_top_left_pixels'], list(roi))
        helper = BUILDER.helper_source(physical, roi, 2, True)
        self.assertIn('vec2(1080.0, 1440.0)', helper)
        self.assertIn('point.x < 712.0 && point.y < 1121.0', helper)
        left, top, width, height = roi
        def inside(x, y):
            return left <= x < left+width and top <= y < top+height
        for x, y, expected in ((8, 128, True), (711, 1120, True), (7, 128, False),
                               (712, 128, False), (8, 127, False), (8, 1121, False)):
            self.assertEqual(inside(x, y), expected)

    def test_all_channel_codes_restore_quantized_value_with_known_error(self):
        # Independent integer arithmetic; no original scene-codec functions imported.
        for bits, maximum_error in ((1, 1), (2, 2), (3, 4)):
            levels = 1 << (8-bits)
            worst = 0
            for original in range(256):
                quantized = (2*original*(levels-1)+255) // 510
                for symbol in range(1 << bits):
                    code = quantized + symbol*levels
                    restored = (2*(code % levels)*255+(levels-1)) // (2*(levels-1))
                    worst = max(worst, abs(original-restored))
            self.assertEqual(worst, maximum_error)

    def test_rn_gl_layout_and_changed_native_source_rejected(self):
        with self.assertRaisesRegex(ValueError, 'RNGL'):
            BUILDER.build_overlay(self.root / 'rngl', self.native, (720, 1080), (8, 32, 128, 683), renderer_branch='rngl')
        for physical, roi in (((720, 1080), (8, 32, 800, 683)), ((720, 1080), (-1, 32, 128, 683))):
            with self.assertRaises(ValueError):
                BUILDER.validate_layout(physical, roi, 2)
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            BUILDER.patch_fragment('void main() {}', (720, 1080), (8, 32, 128, 683), 2, True)

    def test_host_install_merges_custom_materials_and_copies_runtime_without_importing_it(self):
        output, _ = self.build()
        project = self.root / 'project'
        BUILDER.write_json(project / 'resource_pack/manifest.json', {'format_version': 2})
        BUILDER.write_json(project / 'resource_pack/materials/postprocess.material', {'existing_codec': {'unchanged': True}})
        (project / 'behavior_pack/geometry_atlas_probe').mkdir(parents=True)
        BUILDER.install_overlay(project, output)
        materials = json.loads((project / 'resource_pack/materials/postprocess.material').read_text())
        self.assertEqual(materials['existing_codec'], {'unchanged': True})
        self.assertIn('pmanim_scene_compat_bloom_final', materials)
        self.assertTrue((project / 'behavior_pack/geometry_atlas_probe/compat_scene_server.py').exists())
        with self.assertRaisesRegex(ValueError, 'separate directory'):
            BUILDER.build_overlay(project, self.native, (720, 1080), (8, 32, 128, 683))

    def test_install_rejects_changed_shader_before_writing_project(self):
        output, _ = self.build()
        project = self.root / 'project'
        BUILDER.write_json(project / 'resource_pack/manifest.json', {})
        (output / 'resource_pack/shaders/glsl/pmanim_scene_compat_bloom_final.fragment').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'changed after build'):
            BUILDER.install_overlay(project, output)
        self.assertFalse((project / 'resource_pack/materials/postprocess.material').exists())

    def test_alpha_math_expected_native_legacy_threshold(self):
        _, manifest = self.build()
        for item in manifest['native_math_validation']['alpha_bytes_at_threshold_half']:
            self.assertEqual(int(1.0-item['alpha']/255.0 >= .5), item['mask'])


class ClientReceiptTests(unittest.TestCase):
    def setUp(self):
        self.previous = {key: sys.modules.get(key) for key in ('geometry_atlas_probe', 'geometry_atlas_probe.compat_config')}
        sys.modules['geometry_atlas_probe'] = types.ModuleType('geometry_atlas_probe')
        config = types.ModuleType('geometry_atlas_probe.compat_config')
        config.CONFIG = {'physical_size': [720, 1080]}
        config.ALPHA_PROCESS = copy.deepcopy(BUILDER.ALPHA_PROCESS)
        sys.modules['geometry_atlas_probe.compat_config'] = config

    def tearDown(self):
        for key, value in self.previous.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value

    def test_install_validates_order_without_mutating_post(self):
        class Post:
            def GetPostProcessOrder(self):
                return ['restored', 'bloom', 'depthoffield']
        receipt = CLIENT.install(Post(), ('restored', 0))
        self.assertEqual(receipt['new_passes_added'], 0)
        with self.assertRaises(ValueError):
            CLIENT.install(Post(), ('restored', 0), (1080, 1440))
        with self.assertRaises(RuntimeError):
            CLIENT.install(Post(), ('absent', 0))


if __name__ == '__main__':
    unittest.main()
