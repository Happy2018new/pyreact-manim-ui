"""Offline positive-pose installer checks using tiny temporary carrier files."""
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load('positive_pose_builder_under_test', HERE/'build_candidate.py')
candidate = load('positive_pose_reviewed_candidate_builder', builder.CANDIDATE/'build_candidate.py')


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


class PositivePoseBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def make_project(self, name='carrier', prepared=True):
        project = self.root/name
        package = project/'behavior_pack/stencil_large'
        package.mkdir(parents=True)
        (package/'modMain.py').write_bytes(
            b"api.RegisterSystem('fixture', 'probe', '"+candidate.ORIGINAL+b"')\n")
        (package/'runtime.py').write_bytes(b'# Frozen bulk runtime sentinel\n')
        (package/'integrated_runtime.py').write_bytes(b'# Frozen integrated runtime sentinel\n')
        for relative, data in (
                ('resource_pack/shaders/glsl/frozen.fragment', b'// Frozen shader sentinel\n'),
                ('resource_pack/materials/frozen.material', b'{"frozen":true}\n')):
            path = project/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        write_json(project/'probe_resources.json', {
            'native_compatibility': {'variant': 'carrier'},
            'runtime': {'class': candidate.ORIGINAL.decode('ascii')},
            'payload': {'sha256': 'a'*64, 'bytes': 65536}})
        write_json(project/'.mcdev.json', {
            'world_source_path': '', 'world_name': 'fixture-world-label',
            'auto_hot_reload_mods': False, 'custom_preserved': {'nested': [1, 2]}})
        if prepared:
            candidate.install(project)
        return project

    def files(self, project):
        return {path.relative_to(project).as_posix(): path.read_bytes()
                for path in project.rglob('*') if path.is_file()}

    def test_annotation_preserves_every_reviewed_candidate_and_resource_byte(self):
        project = self.make_project()
        before = self.files(project)
        receipt = builder.install(project)
        after = self.files(project)
        self.assertEqual({'dimension_positive_pose_receipt.json'}, set(after)-set(before))
        self.assertEqual(before, {name: after[name] for name in before})
        self.assertEqual((builder.CANDIDATE/'runtime.py').read_bytes(),
                         after['behavior_pack/stencil_large/dimension_candidate.py'])
        self.assertEqual(builder.digest((builder.CANDIDATE/'runtime.py').read_bytes()),
                         receipt['candidate_runtime_sha256'])
        self.assertEqual(builder.digest((HERE/'pose.py').read_bytes()), receipt['pose_source_sha256'])
        self.assertEqual(builder.digest((HERE/'runner.py').read_bytes()), receipt['runner_source_sha256'])
        self.assertEqual('positive_pose_dimension_fixture_v3', receipt['schema'])
        self.assertEqual([8., 72., 5.], receipt['camera'])
        self.assertEqual([8.5, 70., 8.5], receipt['player_feet'])
        self.assertEqual([8, 72, 8], receipt['dimension_target'])
        self.assertEqual([0, 1], receipt['room_dimensions'])
        self.assertEqual({'controlled': [0, 1], 'nether_natural': [0]}, receipt['supported_room_modes'])
        self.assertEqual([4, 69, 3], receipt['room_minimum'])
        self.assertEqual([12, 78, 13], receipt['room_maximum'])
        self.assertEqual('sequential_single_chunk_later_verification_v2', receipt['room_pipeline'])
        self.assertEqual(3, receipt['maximum_room_write_attempts'])
        self.assertEqual('', receipt['independent_world_source'])
        self.assertIs(False, receipt['existing_level_dat'])
        self.assertEqual('PYR_<fresh instance UUID>', receipt['launcher_world_name'])
        for key in ('candidate_runtime_modified', 'materials_or_shaders_modified',
                    'runtime_file_writes', 'continuous_update_tested', 'native_verified'):
            self.assertIs(False, receipt[key])
        self.assertEqual(receipt, json.loads(after['dimension_positive_pose_receipt.json']))

    def test_fresh_carrier_installs_exact_reviewed_candidate_before_annotation(self):
        project = self.make_project(prepared=False)
        before = self.files(project)
        builder.install(project)
        after = self.files(project)
        for name in ('behavior_pack/stencil_large/runtime.py',
                     'behavior_pack/stencil_large/integrated_runtime.py',
                     'resource_pack/shaders/glsl/frozen.fragment',
                     'resource_pack/materials/frozen.material'):
            self.assertEqual(before[name], after[name])
        self.assertEqual(before['behavior_pack/stencil_large/modMain.py'].replace(
            candidate.ORIGINAL, candidate.CLASS.encode('ascii')),
            after['behavior_pack/stencil_large/modMain.py'])
        self.assertEqual((builder.CANDIDATE/'runtime.py').read_bytes(),
                         after['behavior_pack/stencil_large/dimension_candidate.py'])
        self.assertIn('dimension_candidate_receipt.json', after)
        self.assertIn('dimension_positive_pose_receipt.json', after)

    def test_repeat_install_refuses_without_mutating_any_file(self):
        project = self.make_project()
        builder.install(project)
        before = self.files(project)
        with self.assertRaisesRegex(ValueError, 'once in a fresh'):
            builder.install(project)
        self.assertEqual(before, self.files(project))

    def test_changed_runtime_source_or_recorded_hash_is_rejected_before_annotation(self):
        for changed in ('source', 'receipt_hash'):
            with self.subTest(changed=changed):
                project = self.make_project(changed)
                if changed == 'source':
                    (project/'behavior_pack/stencil_large/dimension_candidate.py').write_bytes(b'# changed\n')
                else:
                    path = project/'dimension_candidate_receipt.json'
                    receipt = json.loads(path.read_text())
                    receipt['runtime_sha256'] = '0'*64
                    write_json(path, receipt)
                before = self.files(project)
                with self.assertRaisesRegex(ValueError, 'exact reviewed static dimension carrier'):
                    builder.install(project)
                self.assertEqual(before, self.files(project))

    def test_changed_variant_or_runtime_registration_is_rejected_before_annotation(self):
        for section, key, value in (('native_compatibility', 'variant', 'stock'),
                                     ('runtime', 'class', 'other.System')):
            with self.subTest(section=section):
                project = self.make_project(section)
                path = project/'probe_resources.json'
                resources = json.loads(path.read_text())
                resources[section][key] = value
                write_json(path, resources)
                before = self.files(project)
                with self.assertRaisesRegex(ValueError, 'exact reviewed static dimension carrier'):
                    builder.install(project)
                self.assertEqual(before, self.files(project))

    def test_changed_candidate_entry_is_rejected_before_annotation(self):
        project = self.make_project()
        entry = project/'behavior_pack/stencil_large/modMain.py'
        entry.write_bytes(entry.read_bytes()+b'# Unexpected registration change\n')
        before = self.files(project)
        with self.assertRaisesRegex(ValueError, 'exact reviewed static dimension carrier'):
            builder.install(project)
        self.assertEqual(before, self.files(project))

    def test_existing_world_level_dat_is_rejected_before_any_candidate_mutation(self):
        project = self.make_project(prepared=False)
        (project/'level.dat').write_bytes(b'existing independent world must be preserved')
        before = self.files(project)
        with mock.patch.object(builder, 'module') as loader:
            with self.assertRaisesRegex(ValueError, 'independent generated development world'):
                builder.install(project)
        loader.assert_not_called()
        self.assertEqual(before, self.files(project))

    def test_explicit_world_source_is_rejected_before_any_candidate_mutation(self):
        for index, source in enumerate(('C:/copied/world', '../existing_world', False, 0, [])):
            with self.subTest(source=source):
                project = self.make_project('explicit_world_%d' % index, prepared=False)
                config_path = project/'.mcdev.json'
                config = json.loads(config_path.read_text())
                config['world_source_path'] = source
                write_json(config_path, config)
                before = self.files(project)
                with mock.patch.object(builder, 'module') as loader:
                    with self.assertRaisesRegex(ValueError, 'independent generated development world'):
                        builder.install(project)
                loader.assert_not_called()
                self.assertEqual(before, self.files(project))

    def test_implicit_world_sources_are_normalized_without_losing_other_config(self):
        cases = ('absent_config', 'absent_key', None, '', 'auto')
        for index, source in enumerate(cases):
            with self.subTest(source=source):
                project = self.make_project('fresh_world_%d' % index)
                path = project/'.mcdev.json'
                config = json.loads(path.read_text())
                if source == 'absent_config':
                    path.unlink()
                    preserved = {}
                else:
                    if source == 'absent_key':
                        config.pop('world_source_path')
                    else:
                        config['world_source_path'] = source
                    write_json(path, config)
                    preserved = {key: value for key, value in config.items() if key != 'world_source_path'}
                receipt = builder.install(project)
                expected = dict(preserved, world_source_path='')
                self.assertEqual(expected, json.loads(path.read_text()))
                self.assertEqual('', receipt['independent_world_source'])
                self.assertFalse((project/'level.dat').exists())

    def test_changed_frozen_runtime_shader_or_material_is_rejected_before_annotation(self):
        for index, relative in enumerate(('behavior_pack/stencil_large/runtime.py',
                                           'resource_pack/shaders/glsl/frozen.fragment',
                                           'resource_pack/materials/frozen.material')):
            with self.subTest(relative=relative):
                project = self.make_project('changed_frozen_%d' % index)
                path = project/relative
                path.write_bytes(path.read_bytes()+b'changed')
                before = self.files(project)
                with self.assertRaisesRegex(ValueError, 'Frozen carrier file changed'):
                    builder.install(project)
                self.assertEqual(before, self.files(project))

    def test_build_rejects_existing_output_before_loading_any_builder(self):
        output = self.root/'existing'
        output.mkdir()
        sentinel = output/'preserved.txt'
        sentinel.write_bytes(b'preserved')
        with mock.patch.object(builder, 'module') as loader, mock.patch.object(builder, 'install') as install:
            with self.assertRaisesRegex(ValueError, 'new absent directory'):
                builder.build(output, self.root/'fake-client.exe')
        loader.assert_not_called()
        install.assert_not_called()
        self.assertEqual({'preserved.txt': b'preserved'}, self.files(output))

    def test_build_delegates_fresh_carrier_then_installs_positive_annotation(self):
        output = self.root/'fresh'
        fake_game = self.root/'fake-client.exe'
        project = output/'project'
        compat = types.SimpleNamespace(build=mock.Mock(return_value=project))
        calls = []
        compat.build.side_effect = lambda *args: calls.append(('build', args)) or project
        with mock.patch.object(builder, 'module', return_value=compat), \
                mock.patch.object(builder, 'install', side_effect=lambda value: calls.append(('install', value))):
            result = builder.build(output, fake_game)
        self.assertEqual(project, result)
        self.assertEqual([('build', (output.resolve(), fake_game, 'carrier')),
                          ('install', project)], calls)
        self.assertFalse(output.exists(), 'Only fake host functions may run in this test')


if __name__ == '__main__':
    unittest.main()
