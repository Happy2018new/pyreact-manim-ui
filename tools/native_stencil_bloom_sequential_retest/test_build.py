"""Offline, temporary-file checks for the two-phase Bloom resource build."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('sequential_bloom_build_under_test', HERE / 'build.py')
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_bytes(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


class SequentialBloomBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'source-project'
        self.game = self.root / 'native/Minecraft.Windows.exe'
        self.game.parent.mkdir(parents=True)
        self.game.write_bytes(b'Offline placeholder; this test never launches it.')
        self.native = self.game.parent / 'data/resource_packs/vanilla_netease'
        self.configs = {}
        for index, filename in enumerate(('post_process.json', 'post_process_rngl.json')):
            config = {'render_order': ['bloom', 'depthoffield', 'vignette'],
                      'unmodified_route_marker': index,
                      'process_array': [
                          {'name': 'bloom', 'enable': True,
                           'paras': {'threshold': .5, 'intensity': 1., 'radius': 1.},
                           'pass_array': [{'material': 'threashold_pick',
                                           'render_target': {'width': 1., 'height': 1.},
                                           'shaderPassName': 'Threshold'}]},
                          {'name': 'depthoffield', 'enable': False, 'paras': {'focus': 2.},
                           'pass_array': [{'material': 'native_blur',
                                           'render_target': {'width': .5, 'height': .5}},
                                          {'material': 'depth_sample_with_blur',
                                           'render_target': {'width': 1., 'height': 1.}}]},
                          {'name': 'vignette', 'enable': False, 'paras': {}, 'pass_array': []}]}
            self.configs[filename] = config
            write_json(self.native / 'graphics_settings' / filename, config)
        native_material = {'vertexShader': 'shaders/uv_fullscreen.vertex',
                           'fragmentShader': 'shaders/depth_sample.fragment',
                           'vertexFields': [{'field': 'Position'}, {'field': 'UV0'}],
                           'samplerStates': [{'samplerIndex': i, 'textureFilter': 'Point'}
                                             for i in (0, 1, 2)],
                           'msaaSupport': 'Both'}
        write_json(self.native / 'materials/postprocess.material', {
            'depth_sample_with_blur': native_material,
            'native_blur': dict(native_material, fragmentShader='shaders/native_blur.fragment'),
            'threashold_pick': dict(native_material, fragmentShader='shaders/threshold.fragment')})
        write_json(self.native / 'materials/common.json', [
            {'path': 'materials/sfx.material'}, {'path': 'materials/postprocess.material'}])
        for source_root in (self.native, self.game.parent / 'data'):
            for filename, source in (
                    ('uv_fullscreen.vertex', '// untouched native vertex\n'),
                    ('depth_sample.fragment', '// untouched native depth\n'),
                    ('native_blur.fragment', '// untouched native blur\n'),
                    ('threshold.fragment', '// untouched native threshold\n')):
                path = source_root / 'shaders/glsl' / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding='utf-8')
        write_json(self.project / 'probe_resources.json',
                   {'native_compatibility': {'variant': 'carrier'}})
        write_json(self.project / '.mcdev.json', {
            'game_executable_path': str(self.game),
            **{name: False for name in ('auto_hot_reload_mods', 'auto_hot_reload_ui',
                                        'auto_hot_reload_shaders', 'auto_hot_reload_materials')}})
        self.carrier_materials = {'carrier_custom': {'unchanged': True}}
        write_json(self.project / build.MATERIAL_PATH, self.carrier_materials)
        for folder in ('behavior_pack', 'resource_pack'):
            write_json(self.project / folder / 'manifest.json', {
                'header': {'uuid': folder, 'name': 'frozen carrier', 'version': [1, 0, 0]},
                'modules': [{'uuid': folder + '-module', 'type': 'data'}]})
        (self.project / 'behavior_pack/runtime.py').write_bytes(b'unchanged carrier runtime\n')
        self.native_before = tree_bytes(self.game.parent)

    def install(self, phase='source-control', project=None):
        return build.install(project or self.project, self.game, phase)

    def assert_configs(self, project, phase):
        for filename, original in self.configs.items():
            expected = copy.deepcopy(original)
            for process in expected['process_array']:
                process['enable'] = phase == 'native' and process['name'] == 'bloom'
            self.assertEqual(read_json(project / 'resource_pack/graphics_settings' / filename), expected)

    def assert_complete_pack_inventory(self, project, receipt):
        current = {path.relative_to(project).as_posix()
                   for folder in ('behavior_pack', 'resource_pack')
                   for path in (project / folder).rglob('*') if path.is_file()}
        self.assertEqual(current, set(receipt['outputs']) | set(receipt['frozen_files']))

    def update_output_digest(self, receipt, relative):
        self.assertIn(relative, receipt['outputs'])
        receipt['outputs'][relative] = digest(self.project / relative)
        write_json(self.project / build.RECEIPT, receipt)

    def test_two_phases_preserve_native_bytes_configs_and_share_owned_resources(self):
        self.assertEqual(build.PHASES, ('source-control', 'native'))
        native_project = self.root / 'native-project'
        shutil.copytree(self.project, native_project)
        source_receipt = self.install()
        native_receipt = self.install('native', native_project)
        resources = build.resources()
        phase_uuids = []
        for phase, project, receipt in (
                ('source-control', self.project, source_receipt),
                ('native', native_project, native_receipt)):
            with self.subTest(phase=phase):
                self.assertEqual(build.validate(project, phase), receipt)
                self.assertEqual(receipt['phase'], phase)
                self.assertEqual(receipt['project'], str(project.resolve()))
                self.assertEqual(receipt['game_executable_path'], str(self.game.resolve()))
                self.assertEqual(receipt['source_sha256'], digest(HERE / 'build.py'))
                self.assertTrue(receipt['native_input_sources'])
                self.assertTrue(receipt['startup_input'])
                self.assert_configs(project, phase)
                self.assert_complete_pack_inventory(project, receipt)
                materials = read_json(project / build.MATERIAL_PATH)
                self.assertEqual(materials, {**self.carrier_materials, **resources['materials']})
                self.assertTrue(resources['materials'])
                for definition in resources['materials'].values():
                    alias = definition['fragmentShader']
                    self.assertTrue(alias.startswith('shaders/'))
                    self.assertNotIn('/glsl/', alias)
                    filename = alias.removeprefix('shaders/')
                    self.assertEqual(filename, Path(filename).name)
                    self.assertEqual((project / 'resource_pack/shaders/glsl' / filename).read_text(encoding='utf-8'),
                                     resources['shaders'][filename])
                self.assertFalse((project / 'resource_pack/materials/native_post_candidate.material').exists())
                self.assertEqual((project / 'behavior_pack/runtime.py').read_bytes(), b'unchanged carrier runtime\n')
                uuids = set()
                for folder in ('behavior_pack', 'resource_pack'):
                    manifest = read_json(project / folder / 'manifest.json')
                    uuids.add(manifest['header']['uuid'])
                    uuids.update(item['uuid'] for item in manifest['modules'])
                self.assertEqual(len(uuids), 4)
                phase_uuids.append(uuids)
        self.assertTrue(phase_uuids[0].isdisjoint(phase_uuids[1]))
        self.assertEqual(source_receipt['resources_sha256'], native_receipt['resources_sha256'])
        self.assertEqual(source_receipt['fixture_identity'], native_receipt['fixture_identity'])
        self.assertEqual(tree_bytes(self.game.parent), self.native_before)

    def test_added_pack_file_is_rejected(self):
        self.install()
        added = self.project / 'resource_pack/shaders/glsl/untracked.fragment'
        added.parent.mkdir(parents=True, exist_ok=True)
        added.write_text('// undeclared override\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            build.validate(self.project)

    def test_hash_updated_owned_shader_and_material_are_rederived(self):
        receipt = self.install()
        original_receipt = copy.deepcopy(receipt)
        resources = build.resources()
        shader = next(iter(resources['shaders']))
        shader_relative = 'resource_pack/shaders/glsl/' + shader
        original_shader = (self.project / shader_relative).read_bytes()
        (self.project / shader_relative).write_bytes(original_shader + b'\n// self-consistent tamper\n')
        self.update_output_digest(receipt, shader_relative)
        with self.assertRaises(ValueError):
            build.validate(self.project)
        (self.project / shader_relative).write_bytes(original_shader)
        receipt = copy.deepcopy(original_receipt)
        materials = read_json(self.project / build.MATERIAL_PATH)
        owned = next(iter(resources['materials']))
        materials[owned]['unexpectedState'] = 'tampered'
        write_json(self.project / build.MATERIAL_PATH, materials)
        self.update_output_digest(receipt, build.MATERIAL_PATH)
        with self.assertRaises(ValueError):
            build.validate(self.project)

    def test_hash_updated_native_parameter_tamper_is_rederived(self):
        receipt = self.install('native')
        relative = 'resource_pack/graphics_settings/post_process.json'
        config = read_json(self.project / relative)
        config['process_array'][0]['paras']['threshold'] = .25
        write_json(self.project / relative, config)
        self.update_output_digest(receipt, relative)
        with self.assertRaises(ValueError):
            build.validate(self.project)

    def test_receipt_resource_and_fixture_identity_tamper_is_rejected(self):
        original = self.install()
        for key in ('resources_sha256', 'fixture_identity'):
            with self.subTest(key=key):
                tampered = copy.deepcopy(original)
                tampered[key] = 'self-consistent-looking-but-forged'
                write_json(self.project / build.RECEIPT, tampered)
                with self.assertRaises(ValueError):
                    build.validate(self.project)

    def test_rebuild_and_launch_markers_are_rejected_without_further_writes(self):
        self.install()
        before = tree_bytes(self.project)
        with self.assertRaises(ValueError):
            self.install('native')
        self.assertEqual(tree_bytes(self.project), before)
        for marker in ('launch.json', 'native_post_candidate.json', 'native_post_startup.json'):
            fresh = self.root / ('fresh-' + marker.replace('.', '-'))
            shutil.copytree(self.project, fresh)
            for receipt_name in (build.RECEIPT, 'native_post_startup.json'):
                (fresh / receipt_name).unlink(missing_ok=True)
            write_json(fresh / marker, {'existing': True})
            marked_before = tree_bytes(fresh)
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                self.install(project=fresh)
            self.assertEqual(tree_bytes(fresh), marked_before)

    def test_installed_input_mutation_is_rejected(self):
        self.install()
        path = self.native / 'shaders/glsl/threshold.fragment'
        path.write_text('// changed native source\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            build.validate(self.project)

    def test_registration_omission_or_project_override_fails_before_writes(self):
        registration = self.native / 'materials/common.json'
        write_json(registration, [{'path': 'materials/sfx.material'}])
        before = tree_bytes(self.project)
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(tree_bytes(self.project), before)
        write_json(registration, [{'path': 'materials/postprocess.material'}])
        write_json(self.project / 'resource_pack/materials/common.json', [])
        before = tree_bytes(self.project)
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(tree_bytes(self.project), before)

    def test_resource_loader_failure_is_preflight_and_writes_nothing(self):
        before = tree_bytes(self.project)
        with patch.object(build, 'resources', side_effect=RuntimeError('resource preflight failed')):
            with self.assertRaises(RuntimeError):
                self.install()
        self.assertEqual(tree_bytes(self.project), before)

    def test_changed_pinned_candidate_source_is_rejected_before_writes(self):
        runner = build.runner_module()
        changed = self.root / 'changed-frozen-bloom.py'
        changed.write_text('raise AssertionError("changed source must never execute")\n', encoding='utf-8')
        before = tree_bytes(self.project)
        with patch.object(build, 'runner_module', return_value=runner), \
                patch.object(runner, 'FROZEN_BLOOM', changed):
            with self.assertRaises(ValueError):
                self.install()
        self.assertEqual(tree_bytes(self.project), before)

    def test_unknown_phase_and_wrong_validation_phase_are_rejected(self):
        before = tree_bytes(self.project)
        with self.assertRaises(ValueError):
            self.install('unknown')
        self.assertEqual(tree_bytes(self.project), before)
        self.install()
        with self.assertRaises(ValueError):
            build.validate(self.project, 'native')


if __name__ == '__main__':
    unittest.main()
