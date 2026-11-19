"""Offline receipts preserve the reviewed fresh candidate and host source hashes."""
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


builder = load('repeated_dimension_builder_under_test', HERE/'build_candidate.py')
runner = load('repeated_dimension_install_verifier_under_test', HERE/'runner.py')


class BuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def files(self, project):
        return {path.relative_to(project).as_posix(): path.read_bytes()
                for path in project.rglob('*') if path.is_file()}

    def project(self):
        project = self.root/'carrier'
        package = project/'behavior_pack/stencil_large'
        package.mkdir(parents=True)
        candidate = load('roundtrip_tiny_candidate_builder', builder.POSITIVE.parent/'native_stencil_dimension_candidate/build_candidate.py')
        (package/'modMain.py').write_bytes(b"api.RegisterSystem('fixture','probe','"+candidate.ORIGINAL+b"')\n")
        (package/'runtime.py').write_bytes(b'# frozen bulk\n')
        (package/'integrated_runtime.py').write_bytes(b'# frozen integrated\n')
        shader = project/'resource_pack/shaders/glsl/frozen.fragment'
        shader.parent.mkdir(parents=True)
        shader.write_bytes(b'// frozen shader\n')
        (project/'probe_resources.json').write_text(json.dumps({
            'native_compatibility': {'variant': 'carrier'},
            'runtime': {'class': candidate.ORIGINAL.decode('ascii')}}), encoding='utf-8')
        positive = load('roundtrip_tiny_positive_builder', builder.POSITIVE/'build_candidate.py')
        positive.install(project)
        return project

    def test_install_adds_only_bounded_receipt_and_preserves_all_frozen_bytes(self):
        project = self.project()
        before = self.files(project)
        receipt = builder.install(project)
        after = self.files(project)
        self.assertEqual({'dimension_roundtrip_receipt.json'}, set(after)-set(before))
        self.assertEqual(before, {name: after[name] for name in before})
        self.assertEqual([0, 1, 0, 1, 0, 2, 0], receipt['default_dimension_sequence'])
        self.assertEqual([0], receipt['room_dimensions'])
        self.assertEqual(6, receipt['maximum_planned_transitions'])
        self.assertEqual(8, receipt['candidate_transition_limit'])
        for flag in ('runtime_candidate_modified', 'materials_or_shaders_modified',
                     'runtime_file_writes', 'native_verified'):
            self.assertFalse(receipt[flag])
        for name, sha in receipt['source_sha256'].items():
            self.assertEqual(hashlib.sha256((HERE/name).read_bytes()).hexdigest(), sha)
        runner.verify_install(project)

    def test_repeated_install_refuses_without_loading_verifier_or_mutation(self):
        project = self.project()
        builder.install(project)
        before = self.files(project)
        with mock.patch.object(builder, 'module') as loader:
            with self.assertRaisesRegex(ValueError, 'once in a fresh'):
                builder.install(project)
        loader.assert_not_called()
        self.assertEqual(before, self.files(project))

    def test_modified_reviewed_candidate_is_rejected_before_annotation(self):
        project = self.project()
        runtime = project/'behavior_pack/stencil_large/dimension_candidate.py'
        runtime.write_bytes(runtime.read_bytes()+b'# altered\n')
        before = self.files(project)
        with self.assertRaises(RuntimeError):
            builder.install(project)
        self.assertEqual(before, self.files(project))

    def test_verifier_rejects_changed_source_hash_or_room_plan(self):
        project = self.project()
        original = builder.install(project)
        receipt_path = project/'dimension_roundtrip_receipt.json'
        for key, value in (('source_sha256', {'runner.py': '0'*64}),
                            ('room_dimensions', [0, 1]), ('maximum_planned_transitions', 8)):
            with self.subTest(key=key):
                receipt = dict(original, **{key: value})
                receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
                with self.assertRaises(RuntimeError):
                    runner.verify_install(project)

    def test_build_refuses_existing_output_before_loading_any_builder(self):
        output = self.root/'prepared'
        output.mkdir()
        (output/'keep').write_bytes(b'unchanged')
        with mock.patch.object(builder, 'module') as loader:
            with self.assertRaisesRegex(ValueError, 'new absent directory'):
                builder.build(output, self.root/'fake.exe')
        loader.assert_not_called()
        self.assertEqual({'keep': b'unchanged'}, self.files(output))

    def test_build_delegates_one_fresh_positive_build_then_annotation(self):
        output, game = self.root/'new', self.root/'fake.exe'
        steps = []
        positive = types.SimpleNamespace(build=mock.Mock(side_effect=lambda *args: steps.append(('build', args)) or output))
        with mock.patch.object(builder, 'module', return_value=positive), \
                mock.patch.object(builder, 'install', side_effect=lambda project: steps.append(('install', project))):
            self.assertEqual(output, builder.build(output, game))
        self.assertEqual([('build', (output.resolve(), game)), ('install', output)], steps)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
