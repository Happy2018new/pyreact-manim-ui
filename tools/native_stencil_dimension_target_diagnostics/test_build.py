"""Offline isolated-target receipts and delegation preserve reviewed carriers."""
import hashlib
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
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


builder = load('isolated_target_builder_under_test', HERE/'build_candidate.py')
runner = load('isolated_target_install_verifier_under_test', HERE/'runner.py')
fixture = load('isolated_target_offline_builder_fixtures', builder.ROUNDTRIP/'test_build.py')


class BuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def files(self, project):
        return {path.relative_to(project).as_posix(): path.read_bytes()
                for path in project.rglob('*') if path.is_file()}

    def project(self):
        base = fixture.BuildTests()
        base.root = self.root
        project = base.project()
        fixture.builder.install(project)
        return project

    def test_receipt_adds_only_target_contract_and_preserves_every_reviewed_byte(self):
        project = self.project()
        before = self.files(project)
        receipt = builder.install(project)
        after = self.files(project)
        self.assertEqual({'dimension_target_receipt.json'}, set(after)-set(before))
        self.assertEqual(before, {name: after[name] for name in before})
        self.assertEqual([0, 2, 0], receipt['default_dimension_sequence'])
        self.assertEqual([0], receipt['room_dimensions'])
        self.assertEqual(2, receipt['maximum_planned_transitions'])
        self.assertEqual(3, receipt['maximum_passive_followups'])
        self.assertTrue(receipt['terrain_sampling_read_only'])
        for key in ('runtime_candidate_modified', 'materials_or_shaders_modified',
                    'runtime_file_writes', 'native_verified'):
            self.assertFalse(receipt[key])
        for name, sha in receipt['source_sha256'].items():
            self.assertEqual(hashlib.sha256((HERE/name).read_bytes()).hexdigest(), sha)
        runner.verify_install(project)

    def test_repeat_install_refuses_before_verifier_or_mutation(self):
        project = self.project()
        builder.install(project)
        before = self.files(project)
        with mock.patch.object(builder, 'module') as loader:
            with self.assertRaisesRegex(ValueError, 'once in a fresh'):
                builder.install(project)
        loader.assert_not_called()
        self.assertEqual(before, self.files(project))

    def test_verifier_rejects_altered_plan_or_source_hash(self):
        project = self.project()
        original = builder.install(project)
        path = project/'dimension_target_receipt.json'
        for key, value in (('room_dimensions', [0, 2]), ('default_dimension_sequence', [0, 1, 0]),
                            ('maximum_planned_transitions', 4), ('maximum_passive_followups', 6),
                            ('source_sha256', {'runner.py': '0'*64})):
            with self.subTest(key=key):
                path.write_text(json.dumps(dict(original, **{key: value})), encoding='utf-8')
                with self.assertRaises(RuntimeError):
                    runner.verify_install(project)

    def test_modified_frozen_carrier_is_rejected_before_annotation(self):
        project = self.project()
        path = project/'behavior_pack/stencil_large/runtime.py'
        path.write_bytes(path.read_bytes()+b'# unexpected\n')
        before = self.files(project)
        with self.assertRaises(RuntimeError):
            builder.install(project)
        self.assertEqual(before, self.files(project))

    def test_build_delegates_fresh_roundtrip_then_target_annotation(self):
        output, game = self.root/'new', self.root/'fake.exe'
        steps = []
        reviewed = types.SimpleNamespace(build=mock.Mock(side_effect=lambda *args: steps.append(('build', args)) or output))
        with mock.patch.object(builder, 'module', return_value=reviewed), \
                mock.patch.object(builder, 'install', side_effect=lambda project: steps.append(('install', project))):
            self.assertEqual(output, builder.build(output, game))
        self.assertEqual([('build', (output.resolve(), game)), ('install', output)], steps)
        self.assertFalse(output.exists())

    def test_build_refuses_existing_project_before_any_builder(self):
        output = self.root/'prepared'
        output.mkdir()
        (output/'preserve').write_bytes(b'original')
        with mock.patch.object(builder, 'module') as loader:
            with self.assertRaisesRegex(ValueError, 'new absent directory'):
                builder.build(output, self.root/'fake.exe')
        loader.assert_not_called()
        self.assertEqual({'preserve': b'original'}, self.files(output))


if __name__ == '__main__':
    unittest.main()
