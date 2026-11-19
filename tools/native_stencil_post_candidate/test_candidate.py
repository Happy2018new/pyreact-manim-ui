"""Offline invariants for isolated candidates; no game APIs or host transport."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

import build_candidate as build
import dof


NATIVE_SOURCE = '''// __multiversion__
uniform sampler2D TEXTURE_0;
uniform sampler2D TEXTURE_1;
uniform sampler2D TEXTURE_2;
uniform vec4 DEPTH_OF_FIELD_VECTOR4_1;
uniform float DEPTH_OF_FIELD_FLOAT1_1;
vec4 depth_sample_auto(vec4 c) { return c + texture(TEXTURE_2, vec2(.5)); }
vec4 depth_sample_defined(vec4 c) { return c; }
void main() { vec4 clearColor = texture(TEXTURE_1, uv);
    gl_FragColor = depth_sample_auto(clearColor) + texture(TEXTURE_0, uv); }
'''


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build.json_bytes(value))


class CandidateAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / 'project'
        self.game = self.root / 'native/Minecraft.Windows.exe'
        self.game.parent.mkdir(parents=True)
        self.game.write_bytes(b'offline placeholder; never executed')
        self.native = self.game.parent / 'data/resource_packs/vanilla_netease'
        self.config = {'render_order': ['bloom', 'depthoffield', 'vignette'], 'untouched': {'x': [1, 2]},
                       'process_array': [
            {'name': 'bloom', 'enable': True, 'paras': {'threshold': .5}, 'pass_array': [
                {'material': 'threashold_pick', 'render_target': {'width': 1., 'height': 1.},
                 'shaderPassName': 'Threshold'}]},
            {'name': 'depthoffield', 'enable': False, 'paras': {'focus': 2, 'useAuto': 0.}, 'pass_array': [
                {'material': 'native_blur', 'render_target': {'width': .5, 'height': .5},
                 'shaderPassName': 'DownScalePass'},
                {'material': 'depth_sample_with_blur', 'render_target': {'width': 1., 'height': 1.},
                 'shaderPassName': 'UpScalePass'}]},
            {'name': 'vignette', 'enable': False, 'paras': {}, 'pass_array': []}]}
        for name in ('post_process.json', 'post_process_rngl.json'):
            write_json(self.native / 'graphics_settings' / name, self.config)
        material = {'vertexShader': 'shaders/uv_fullscreen.vertex',
                    'fragmentShader': 'shaders/depth_sample.fragment',
                    'vertexFields': [{'field': 'Position'}, {'field': 'UV0'}],
                    'samplerStates': [{'samplerIndex': i, 'textureFilter': 'Point'} for i in (0, 1, 2)],
                    'msaaSupport': 'Both'}
        definitions = {'depth_sample_with_blur': material,
                       'native_blur': dict(material, fragmentShader='shaders/native_blur.fragment'),
                       'threashold_pick': dict(material, fragmentShader='shaders/threshold.fragment')}
        write_json(self.native / 'materials/postprocess.material', definitions)
        for source_root in (self.native, self.game.parent / 'data'):
            for name, source in (('depth_sample.fragment', NATIVE_SOURCE), ('uv_fullscreen.vertex', 'vertex'),
                                 ('native_blur.fragment', 'original blur'), ('threshold.fragment', 'original threshold')):
                path = source_root / 'shaders/glsl' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding='utf-8')
        write_json(self.project / 'probe_resources.json', {'native_compatibility': {'variant': 'carrier'}})
        write_json(self.project / '.mcdev.json', {'game_executable_path': str(self.game),
                   **{name: False for name in ('auto_hot_reload_mods', 'auto_hot_reload_ui',
                                               'auto_hot_reload_shaders', 'auto_hot_reload_materials')}})
        write_json(self.project / 'resource_pack/materials/postprocess.material', {'carrier_custom': {'unchanged': True}})
        for folder in ('behavior_pack', 'resource_pack'):
            write_json(self.project / folder / 'manifest.json', {
                'header': {'uuid': folder, 'name': 'frozen carrier', 'version': [1, 0, 0]},
                'modules': [{'uuid': folder + '-module', 'type': 'data'}]})
        (self.project / 'behavior_pack/runtime.py').write_bytes(b'frozen runtime')

    def test_identity_install_keeps_native_auto_math_and_two_routes(self):
        receipt = build.install(self.project, self.game, 'dof-identity')
        self.assertEqual(build.validate(self.project), receipt)
        self.assertEqual((self.project / 'behavior_pack/runtime.py').read_bytes(), b'frozen runtime')
        detail = receipt['native_detail']
        self.assertFalse(detail['decode_static_enabled'])
        local_materials = build.read_json(self.project / 'resource_pack/materials/native_post_candidate.material')
        original = copy.deepcopy(detail['native_material'])
        original['fragmentShader'] = 'shaders/glsl/' + detail['material_name'] + '.fragment'
        self.assertEqual(local_materials, {detail['material_name']: original})
        for name in ('post_process.json', 'post_process_rngl.json'):
            actual = build.read_json(self.project / 'resource_pack/graphics_settings' / name)
            expected = copy.deepcopy(self.config)
            for process in expected['process_array']:
                process['enable'] = process['name'] == 'depthoffield'
            expected['process_array'][1]['pass_array'][-1]['material'] = detail['material_name']
            self.assertEqual(actual, expected)

    def test_active_starts_native_disabled_and_static_decode_requires_gate(self):
        receipt = build.install(self.project, self.game, 'dof-active')
        self.assertTrue(receipt['active_requires_identity_gate'])
        for name in ('post_process.json', 'post_process_rngl.json'):
            actual = build.read_json(self.project / 'resource_pack/graphics_settings' / name)
            self.assertTrue(all(item['enable'] is False for item in actual['process_array']))
        shader = next((self.project / 'resource_pack/shaders/glsl').glob('pmanim_dof*.fragment')).read_text()
        self.assertIn('mod(encoded, 64.0)', shader)
        self.assertNotIn('clearScene.a =', shader)
        self.assertEqual(build.derive_dof(NATIVE_SOURCE, True), shader)

    def test_bloom_adds_owned_resources_without_native_override(self):
        receipt = build.install(self.project, self.game, 'bloom-control')
        self.assertTrue(receipt['native_detail']['original_bloom_sources_unchanged'])
        self.assertEqual(build.validate(self.project), receipt)
        self.assertFalse(any('threshold.fragment' in name for name in receipt['outputs']))
        self.assertEqual(build.read_json(self.project / 'resource_pack/graphics_settings/post_process.json'), self.config)

    def test_tampering_and_reinstall_rejected(self):
        build.install(self.project, self.game, 'dof-identity')
        with self.assertRaisesRegex(ValueError, 'fresh project'):
            build.install(self.project, self.game, 'dof-active')
        shader = next((self.project / 'resource_pack/shaders/glsl').glob('pmanim_dof*.fragment'))
        shader.write_text(shader.read_text() + '\n// tampered', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'file changed'):
            build.validate(self.project)

    def test_launch_receipt_prevents_candidate_install(self):
        write_json(self.project / 'launch.json', {'already': 'launched'})
        with self.assertRaisesRegex(ValueError, 'before launch'):
            build.install(self.project, self.game, 'dof-identity')
        self.assertFalse((self.project / build.RECEIPT).exists())

    def test_shader_rejects_ambiguous_native_sample(self):
        for source in (NATIVE_SOURCE.replace('TEXTURE_1, uv', 'TEXTURE_1, other'),
                       NATIVE_SOURCE + '\nvec4 duplicate() { return texture(TEXTURE_1, uv); }'):
            with self.assertRaisesRegex(ValueError, 'exactly one'):
                build.derive_dof(source, True)
        for active in (False, True):
            actual = build.derive_dof(NATIVE_SOURCE, active)
            self.assertIn('texture(TEXTURE_2, vec2(.5))', actual)
            self.assertIn('texture(TEXTURE_0, uv)', actual)
            self.assertIn('DEPTH_OF_FIELD_FLOAT1_1', actual)

    def test_active_decode_rounding_restores_all_byte_colors_with_original_alpha(self):
        # Independent integer reference over every channel value and payload
        # symbol; alpha remains a separate untouched channel.
        colors = np.arange(256, dtype=np.int64)
        quantized = (colors*63+127)//255
        for symbol in range(4):
            encoded = quantized + symbol*64
            restored = np.floor((encoded % 64)*255./63.+.5).astype(np.int64)
            self.assertLessEqual(int(np.abs(restored-colors).max()), 2)
        shader = build.derive_dof(NATIVE_SOURCE, True)
        self.assertNotIn('clearScene.a =', shader)


class DofGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = dof.native_module()
        cls.payload = cls.native.verify_module.payload_bytes(65536)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / 'identity-project'
        self.project.mkdir()
        (self.project / build.RECEIPT).write_text('immutable fake candidate receipt')
        late = 'stencil_integrated_after_depthoffield'
        order = [*self.native.CORE, *self.native.NATIVE, late]
        required = [*self.native.CORE, 'depthoffield', late]
        self.state = {'state': 'resident', 'ready': True, 'logical_bytes': 65536,
            'viewport': build.VIEWPORT, 'source_roi': build.ROI,
            'identity': {'host_sha256': hashlib.sha256(self.payload).hexdigest(), 'byte_count': 65536},
            'generation': 1, 'active_pages': ['low', 'high'], 'native_page_names': ['clear', 'low', 'high'],
            'native_attempt_count': 3, 'native_records_reserved': 131073,
            'actual_post_order': order, 'native_post_flags': [(name, name == 'depthoffield') for name in self.native.NATIVE],
            'native_test_all_flags': [(name, name in required) for name in order], 'mode': 'off',
            'known_fixture': {'varying_alpha': False}}
        self.receipt = {'ok': True, 'backend': 'Windows.Graphics.Capture', 'native_resolution': True,
                        'width': 720, 'height': 1080, 'request_qpc_100ns': 1, 'frame_qpc_100ns': 2,
                        'agent_activation_allowed': False,
                        'background_before': {'window_noactivate': True, 'foreground': {'pid': 9}},
                        'background_after': {'window_noactivate': True, 'foreground': {'pid': 9}}}
        image = np.zeros((1080, 720, 3), dtype=np.uint8)
        fixture = self.native.verify_module.fixture_rgba(build.ROI)[:, :3].reshape(512, 512, 3)
        image[128:640, 8:520] = fixture
        self.images = []
        for index, profile in enumerate(dof.PROFILES):
            actual = image.copy()
            if index in (1, 2, 3):
                actual[256:300, 128:200] ^= 127
            self.images.append(actual)
        self.gate = {'schema': 'native_dof_candidate_run_v1', 'case': 'dof-identity',
                     'project': str(self.project), 'failure': None, 'cleanup_failure': None,
                     'candidate_receipt_sha256': build.sha(self.project / build.RECEIPT),
                     'payload_sha256': hashlib.sha256(self.payload).hexdigest(), 'profiles': [], 'diagnostics': []}
        for index, profile in enumerate(dof.PROFILES):
            row = self.save_image('profile_%d' % index, self.images[index])
            row.update(profile=dict(profile), camera={'position': [0., 1., 2.], 'forward': [0., 0., 1.]})
            self.gate['profiles'].append(row)
        values = np.frombuffer(self.payload, dtype=np.uint8)
        for mode in (1, 2, 6):
            actual = np.zeros_like(image)
            output = actual[650:].reshape(-1, 3)
            output[:] = self.native.verify_module.GUARD
            if mode == 6:
                output[:262144] = fixture.reshape(-1, 3)
            else:
                address = np.arange(65536, dtype=np.int64)
                if mode == 2:
                    first = (13*address+7) % 65536
                    address = (first+3*values[first].astype(np.int64)+5) % 65536
                selected = values[address].astype(np.uint16)
                output[:65536] = np.column_stack((selected, (71*selected+43) % 256, (131*selected+17) % 256)).astype(np.uint8)
            row = self.save_image('diagnostic_%d' % mode, actual)
            row.update(mode=mode, exact=True)  # Deliberately untrusted field.
            self.gate['diagnostics'].append(row)
        self.path = self.root / dof.STATUS
        self.persist()
        self.validated = {'native_detail': {'native_dof_sha256': 'native-fixed-source'}}

    def save_image(self, label, image):
        path = self.root / (label + '.png')
        Image.fromarray(image).save(path)
        return {'capture_file': str(path), 'capture_sha256': build.sha(path),
                'capture_receipt': copy.deepcopy(self.receipt), 'state': copy.deepcopy(self.state)}

    def persist(self):
        self.path.write_bytes(build.json_bytes(self.gate))

    def verify(self):
        with patch.object(build, 'validate', return_value=self.validated):
            return dof.verify_identity_gate(self.path, self.payload, self.native)

    def test_gate_reopens_profiles_and_fully_redecodes_actual_bytes(self):
        result = self.verify()
        self.assertTrue(result['accepted'])
        self.assertEqual(result['actual_bytes_redecoded'], 65536)
        self.assertEqual(result['profile_images_reopened'], 5)
        self.assertTrue(result['native_final_zero_return_verified'])

    def test_claimed_exact_does_not_hide_corrupted_data_or_guard(self):
        for output_index in (0, 70000):
            row = self.gate['diagnostics'][0]
            with Image.open(row['capture_file']) as source:
                actual = np.array(source.convert('RGB'))
            actual[650:].reshape(-1, 3)[output_index, 0] ^= 1
            Image.fromarray(actual).save(row['capture_file'])
            row['capture_sha256'] = build.sha(row['capture_file'])
            self.persist()
            with self.assertRaisesRegex(ValueError, 're-decoding failed'):
                self.verify()

    def test_guard_motion_is_not_a_native_blur_positive(self):
        zero = self.images[0]
        for row in self.gate['profiles'][1:-1]:
            image = zero.copy()
            image[120:128, 8:520] = 250
            Image.fromarray(image).save(row['capture_file'])
            row['capture_sha256'] = build.sha(row['capture_file'])
        self.persist()
        with self.assertRaisesRegex(ValueError, 'no bounded visual positive'):
            self.verify()

    def test_final_native_zero_return_and_camera_are_required(self):
        last = self.gate['profiles'][-1]
        Image.fromarray(self.images[1]).save(last['capture_file'])
        last['capture_sha256'] = build.sha(last['capture_file'])
        self.persist()
        with self.assertRaisesRegex(ValueError, 'zero-blur return'):
            self.verify()
        last['camera']['position'][0] += 1
        self.persist()
        with self.assertRaisesRegex(ValueError, 'camera moved'):
            self.verify()

    def test_active_initialize_refuses_missing_gate_before_transport(self):
        experiment = SimpleNamespace(args=SimpleNamespace(project=self.project), call=Mock(), invoke=Mock())
        with patch.object(build, 'validate', return_value={'effect': 'depthoffield'}):
            with self.assertRaisesRegex(ValueError, 'accepted identity gate'):
                dof.initialize(experiment, 'dof-active')
        experiment.call.assert_not_called()
        experiment.invoke.assert_not_called()

    def test_cleanup_preserves_carrier_if_native_disable_fails(self):
        calls = []
        def call(label, code='', expression='probe.snapshot()'):
            calls.append((label, code))
            return {'accepted': False, 'enabled': True}
        experiment = SimpleNamespace(args=SimpleNamespace(project=self.project), evidence=self.root,
                                     payload=self.payload, call=call, save=lambda: None)
        with patch.object(build, 'validate', return_value=self.validated):
            result = dof.run(experiment, 'dof-active')
        self.assertIsNotNone(result['cleanup_failure'])
        self.assertEqual([label for label, _ in calls], ['candidate_dof_disable_before_hide'])
        self.assertFalse(any("configure('off')" in code for _, code in calls))

    def test_cleanup_fixture_hide_runs_even_after_carrier_hide_failure(self):
        calls = []
        def call(label, code='', expression='probe.snapshot()'):
            calls.append((label, code))
            if label == 'candidate_dof_disable_before_hide':
                return {'accepted': True, 'enabled': False}
            if label == 'candidate_dof_carrier_off':
                self.assertIn('probe.pipeline_ready=False', code)
                raise RuntimeError('synthetic carrier hide failure')
            return {}
        experiment = SimpleNamespace(args=SimpleNamespace(project=self.project), evidence=self.root,
                                     payload=self.payload, call=call, save=lambda: None)
        with patch.object(build, 'validate', return_value=self.validated):
            result = dof.run(experiment, 'dof-active')
        self.assertEqual(calls[-1][0], 'candidate_dof_fixture_off')
        self.assertIn('synthetic carrier hide failure', result['cleanup_failure'])

    def test_auto_profile_sets_manual_focus_before_enabling_center_mode(self):
        calls = []
        experiment = SimpleNamespace(call=lambda label, code='', expression='':
            (calls.append(code) or {'accepted': [('all', True)], 'enabled': True}))
        with patch.object(self.native.time, 'sleep'), patch.object(self.native, '_chain', return_value='late'):
            dof._profile(experiment, self.native, dof.PROFILES[3], {})
        source = calls[0]
        self.assertLess(source.index('SetDepthOfFieldUseCenterFocus(False)'), source.index('SetDepthOfFieldFocusDistance'))
        self.assertLess(source.index('SetDepthOfFieldFocusDistance'), source.index('SetDepthOfFieldUseCenterFocus(True)'))


if __name__ == '__main__':
    unittest.main()
