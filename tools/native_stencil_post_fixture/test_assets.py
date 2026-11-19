"""Offline invariants for original native startup variants; no game calls."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('native_post_startup_assets_under_test', HERE/'assets.py')
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root/'case/project'
        self.game = self.root/'native/Minecraft.Windows.exe'
        self.game.parent.mkdir(parents=True)
        self.game.write_bytes(b'offline fake executable')
        self.native = self.game.parent/'data/resource_packs/vanilla_netease'
        self.configs = {}
        for name in assets.CONFIG_NAMES:
            suffix = '.rngl' if 'rngl' in name else ''
            config = {'render_order': ['bloom', 'depthoffield', 'vignette'],
                      'extra_native_field': {'preserved': [1, 2, 3]},
                      'process_array': [
                          {'name': effect, 'enable': effect == 'bloom',
                           'paras': {'radius': 0.25, 'native': [1, 2]},
                           'pass_array': [{'render_target': {'width': 0.5, 'height': 0.25},
                                           'shaderPassName': 'OriginalPass', 'material': effect+suffix}]}
                          for effect in ('bloom', 'depthoffield', 'vignette')]}
            self.configs[name] = copy.deepcopy(config)
            write_json(self.native/'graphics_settings'/name, config)
        native_materials = {effect: {'vertexShader': 'shaders/uv_fullscreen.vertex',
                                    'fragmentShader': 'shaders/'+effect+'.fragment',
                                    '+defines': ['ORIGINAL'], '+variants': [{'rngl': {'+defines': ['RNGL']}}]}
                            for effect in ('bloom', 'depthoffield')}
        write_json(self.native/'materials/postprocess.material', native_materials)
        for shader in ('uv_fullscreen.vertex', 'bloom.fragment', 'depthoffield.fragment'):
            for root in (self.native, self.game.parent/'data'):
                path = root/'shaders/glsl'/shader
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('original native shader '+shader, encoding='utf-8')
        write_json(self.project/'probe_resources.json', {'native_compatibility': {'variant': 'carrier'},
                                                        'frozen': 'untouched'})
        write_json(self.project/'.mcdev.json', {
            'game_executable_path': str(self.game), 'auto_hot_reload_mods': False,
            'auto_hot_reload_ui': False, 'auto_hot_reload_shaders': False,
            'auto_hot_reload_materials': False})
        write_json(self.project/'resource_pack/materials/postprocess.material', {'custom': {'original': True}})
        for folder, identifier in (('behavior_pack', 'behavior'), ('resource_pack', 'resource')):
            write_json(self.project/folder/'manifest.json', {
                'header': {'uuid': identifier, 'name': 'before', 'version': [0, 0, 1]},
                'modules': [{'uuid': identifier+'-module', 'type': 'data'}],
                'dependencies': [{'uuid': 'resource' if identifier == 'behavior' else 'external',
                                  'version': [0, 0, 1]}]})

    def test_both_routes_change_only_enable_flags_and_keep_frozen_inputs(self):
        frozen = {relative: (self.project/relative).read_bytes() for relative in (
            'probe_resources.json', '.mcdev.json', 'resource_pack/materials/postprocess.material')}
        receipt = assets.install_startup(self.project, 'dof')
        self.assertEqual('depthoffield', receipt['effect'])
        self.assertEqual(['depthoffield'], receipt['startup_enabled_effects'])
        self.assertFalse(receipt['native_execution_verified'])
        self.assertEqual(4, len(receipt['installed_files']))
        for name, original in self.configs.items():
            actual = assets.read_json(self.project/'resource_pack/graphics_settings'/name)
            self.assertEqual([False, True, False], [process['enable'] for process in actual['process_array']])
            for index, process in enumerate(original['process_array']):
                actual['process_array'][index]['enable'] = process['enable']
            self.assertEqual(original, actual)
        for relative, before in frozen.items():
            self.assertEqual(before, (self.project/relative).read_bytes())
        behavior = assets.read_json(self.project/'behavior_pack/manifest.json')
        resource = assets.read_json(self.project/'resource_pack/manifest.json')
        self.assertEqual(resource['header']['uuid'], behavior['dependencies'][0]['uuid'])
        self.assertEqual(2, len(receipt['native_shader_sources']))
        self.assertTrue(all(len(records) == 2 for records in receipt['native_shader_sources'].values()))

    def test_repeat_validates_installed_and_native_hashes(self):
        receipt = assets.install_startup(self.project, 'bloom')
        self.assertEqual(receipt, assets.install_startup(self.project, 'bloom'))
        path = self.project/'resource_pack/graphics_settings/post_process_rngl.json'
        path.write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'modified'):
            assets.install_startup(self.project, 'bloom')

    def test_other_effect_requires_fresh_project(self):
        assets.install_startup(self.project, 'bloom')
        with self.assertRaisesRegex(ValueError, 'fresh project'):
            assets.install_startup(self.project, 'depthoffield')

    def test_rejects_launch_receipt_before_any_write(self):
        before = (self.project/'resource_pack/manifest.json').read_bytes()
        write_json(self.project.parent/'evidence/launch.json', {'owned': True})
        with self.assertRaisesRegex(ValueError, 'before launch'):
            assets.install_startup(self.project, 'bloom')
        self.assertFalse((self.project/assets.RECEIPT).exists())
        self.assertEqual(before, (self.project/'resource_pack/manifest.json').read_bytes())

    def test_rejects_native_shader_override_before_any_write(self):
        path = self.project/'resource_pack/shaders/glsl/bloom.fragment'
        path.parent.mkdir(parents=True)
        path.write_text('derived sentinel', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'overrides an original target native shader'):
            assets.install_startup(self.project, 'bloom')
        self.assertFalse((self.project/assets.RECEIPT).exists())

    def test_missing_rngl_source_rejects_before_any_write(self):
        (self.native/'graphics_settings/post_process_rngl.json').unlink()
        before = (self.project/'resource_pack/manifest.json').read_bytes()
        with self.assertRaises(FileNotFoundError):
            assets.install_startup(self.project, 'bloom')
        self.assertFalse((self.project/assets.RECEIPT).exists())
        self.assertEqual(before, (self.project/'resource_pack/manifest.json').read_bytes())

    def test_changed_native_source_rejects_repeat(self):
        assets.install_startup(self.project, 'bloom')
        (self.native/'shaders/glsl/bloom.fragment').write_text('changed native', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'native shader source changed'):
            assets.install_startup(self.project, 'bloom')

    def test_added_native_material_override_rejects_repeat(self):
        assets.install_startup(self.project, 'bloom')
        write_json(self.project/'resource_pack/materials/other.material',
                   {'materials': {'bloom:custom': {'fragmentShader': 'shaders/derived.fragment'}}})
        with self.assertRaisesRegex(ValueError, 'overrides an original target native post material'):
            assets.install_startup(self.project, 'bloom')

    def test_effect_uuid_namespaces_differ(self):
        bloom, _ = assets._manifests(self.project, 'bloom')
        dof, _ = assets._manifests(self.project, 'depthoffield')
        self.assertNotEqual(bloom['resource_pack/manifest.json']['header']['uuid'],
                            dof['resource_pack/manifest.json']['header']['uuid'])

    def test_validate_missing_install_does_not_create_files(self):
        before = {str(path.relative_to(self.project)): path.read_bytes()
                  for path in self.project.rglob('*') if path.is_file()}
        with self.assertRaisesRegex(ValueError, 'not installed'):
            assets.validate_startup(self.project, 'bloom')
        after = {str(path.relative_to(self.project)): path.read_bytes()
                 for path in self.project.rglob('*') if path.is_file()}
        self.assertEqual(before, after)

    def test_validate_after_launch_is_read_only_and_returns_original_receipt(self):
        receipt = assets.install_startup(self.project, 'depthoffield')
        write_json(self.project.parent/'evidence/launch.json', {'owned': True})
        before = {str(path.relative_to(self.project)): path.read_bytes()
                  for path in self.project.rglob('*') if path.is_file()}
        self.assertEqual(receipt, assets.validate_startup(self.project, 'dof'))
        after = {str(path.relative_to(self.project)): path.read_bytes()
                 for path in self.project.rglob('*') if path.is_file()}
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
