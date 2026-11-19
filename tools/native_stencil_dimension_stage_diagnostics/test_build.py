"""Offline stage receipts bind new host sources without changing native assets."""
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


builder = load('stage_builder_under_test', HERE/'build_candidate.py')
target_fixture = load('stage_target_builder_fixture', builder.TARGET/'test_build.py')


class BuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def files(self, project):
        return {path.relative_to(project).as_posix(): path.read_bytes()
                for path in project.rglob('*') if path.is_file()}

    def project(self):
        fixture = target_fixture.BuildTests()
        fixture.root = self.root
        project = fixture.project()
        target_fixture.builder.install(project)
        return project

    def test_receipt_adds_only_stage_contract_preserving_every_native_byte(self):
        project = self.project()
        before = self.files(project)
        receipt = builder.install(project)
        after = self.files(project)
        self.assertEqual({'dimension_stage_receipt.json'}, set(after)-set(before))
        self.assertEqual(before, {name: after[name] for name in before})
        self.assertEqual([0, 2, 0], receipt['default_dimension_sequence'])
        self.assertEqual([0], receipt['room_dimensions'])
        self.assertEqual(2, receipt['maximum_transitions'])
        self.assertEqual(21, receipt['maximum_stage_captures'])
        self.assertEqual(6, receipt['manual_control_captures'])
        self.assertEqual(13, receipt['maximum_routing_captures'])
        self.assertEqual(1, receipt['resident_payload_uploads'])
        for key in ('runtime_candidate_modified', 'materials_or_shaders_modified',
                    'runtime_file_writes', 'native_verified'):
            self.assertFalse(receipt[key])
        self.assertEqual({'runner.py', 'observations.py', 'routing.py', 'build_candidate.py'}, set(receipt['source_sha256']))
        for name, sha in receipt['source_sha256'].items():
            self.assertEqual(hashlib.sha256((HERE/name).read_bytes()).hexdigest(), sha)
        load('stage_receipt_verifier', HERE/'runner.py').verify_install(project)

    def test_duplicate_annotation_refuses_before_loading_verifier_or_mutating(self):
        project = self.project()
        builder.install(project)
        before = self.files(project)
        with mock.patch.object(builder, 'module') as loader:
            with self.assertRaisesRegex(ValueError, 'once in a fresh'):
                builder.install(project)
        loader.assert_not_called()
        self.assertEqual(before, self.files(project))

    def test_changed_reviewed_native_candidate_is_rejected_before_annotation(self):
        project = self.project()
        path = project/'behavior_pack/stencil_large/dimension_candidate.py'
        path.write_bytes(path.read_bytes()+b'# changed native candidate\n')
        before = self.files(project)
        with self.assertRaises(RuntimeError):
            builder.install(project)
        self.assertEqual(before, self.files(project))

    def test_verifier_rejects_relaxed_plan_missing_binding_and_source_hash(self):
        project = self.project()
        original = builder.install(project)
        path = project/'dimension_stage_receipt.json'
        runner = load('stage_invalid_receipt_verifier', HERE/'runner.py')
        cases = [('room_dimensions', [0, 2]), ('default_dimension_sequence', [0, 1, 0]),
                 ('maximum_transitions', 4), ('maximum_stage_captures', 99),
                 ('manual_control_captures', 7), ('resident_payload_uploads', 2),
                 ('maximum_routing_captures', 14),
                 ('source_sha256', {'runner.py': '0'*64})]
        for key, value in cases:
            with self.subTest(key=key):
                path.write_text(json.dumps(dict(original, **{key: value})), encoding='utf-8')
                with self.assertRaises(RuntimeError):
                    runner.verify_install(project)

    def test_build_refuses_existing_output_without_loading_or_changing_it(self):
        output = self.root/'prepared'
        output.mkdir()
        (output/'keep').write_bytes(b'unchanged')
        with mock.patch.object(builder, 'module') as loader:
            with self.assertRaisesRegex(ValueError, 'new absent directory'):
                builder.build(output, self.root/'fake.exe')
        loader.assert_not_called()
        self.assertEqual({'keep': b'unchanged'}, self.files(output))

    def test_build_delegates_one_target_build_before_stage_annotation(self):
        output, game, steps = self.root/'new', self.root/'fake.exe', []
        target = types.SimpleNamespace(build=mock.Mock(side_effect=lambda *args: steps.append(('build', args)) or output))
        with mock.patch.object(builder, 'module', return_value=target), \
                mock.patch.object(builder, 'install', side_effect=lambda project: steps.append(('install', project))):
            self.assertEqual(output, builder.build(output, game))
        self.assertEqual([('build', (output.resolve(), game)), ('install', output)], steps)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
