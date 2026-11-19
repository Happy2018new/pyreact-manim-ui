"""Offline installer checks on a tiny independent frozen carrier fixture."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('dimension_candidate_builder_under_test', HERE/'build_candidate.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class CandidateInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)/'carrier'
        self.package = self.project/'behavior_pack/stencil_large'
        self.package.mkdir(parents=True)
        self.entry = self.package/'modMain.py'
        self.entry.write_bytes(b"api.RegisterSystem('fixture', 'probe', '"+builder.ORIGINAL+b"')\n")
        (self.package/'runtime.py').write_bytes(b'# Frozen bulk runtime sentinel\n')
        (self.package/'integrated_runtime.py').write_bytes(b'# Frozen integrated runtime sentinel\n')
        shader = self.project/'resource_pack/shaders/glsl/frozen.fragment'
        shader.parent.mkdir(parents=True)
        shader.write_bytes(b'// Frozen shader sentinel\n')
        self.receipt = self.project/'probe_resources.json'
        self.write_receipt('carrier', builder.ORIGINAL.decode('ascii'))

    def write_receipt(self, variant, runtime_class):
        self.receipt.write_text(json.dumps({'native_compatibility': {'variant': variant},
                                           'runtime': {'class': runtime_class},
                                           'payload': {'sha256': 'a'*64}}), encoding='utf-8')

    def files(self):
        return {path.relative_to(self.project).as_posix(): path.read_bytes()
                for path in self.project.rglob('*') if path.is_file()}

    def test_install_replaces_only_registration_and_adds_candidate(self):
        before = self.files()
        result = builder.install(self.project)
        after = self.files()
        for name in ('behavior_pack/stencil_large/runtime.py',
                     'behavior_pack/stencil_large/integrated_runtime.py',
                     'resource_pack/shaders/glsl/frozen.fragment'):
            self.assertEqual(before[name], after[name])
            self.assertEqual(builder.digest(before[name]), result['frozen_file_hashes'][name])
        self.assertEqual(before['behavior_pack/stencil_large/modMain.py'].replace(
            builder.ORIGINAL, builder.CLASS.encode('ascii')), self.entry.read_bytes())
        self.assertEqual((HERE/'runtime.py').read_bytes(),
                         (self.package/'dimension_candidate.py').read_bytes())
        receipt = json.loads(self.receipt.read_text(encoding='utf-8'))
        self.assertEqual(builder.CLASS, receipt['runtime']['class'])
        self.assertEqual({'sha256': 'a'*64}, receipt['payload'])
        self.assertTrue(result['frozen_files_unchanged'])
        self.assertFalse(result['materials_or_shaders_modified'])
        self.assertFalse(result['runtime_file_writes'])
        self.assertFalse(result['native_verified'])
        self.assertEqual(result, json.loads((self.project/'dimension_candidate_receipt.json').read_text()))

    def test_reinstall_refuses_without_changing_any_file(self):
        builder.install(self.project)
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'once in a fresh'):
            builder.install(self.project)
        self.assertEqual(before, self.files())

    def test_noncarrier_or_changed_runtime_is_rejected_before_writing(self):
        for variant, runtime_class in (('stock', builder.ORIGINAL.decode('ascii')),
                                       ('carrier', 'other.System')):
            with self.subTest(variant=variant, runtime_class=runtime_class):
                self.write_receipt(variant, runtime_class)
                before = self.files()
                with self.assertRaisesRegex(ValueError, 'unchanged integrated'):
                    builder.install(self.project)
                self.assertEqual(before, self.files())

    def test_missing_or_duplicate_registration_is_rejected_before_writing(self):
        for registration in (b'# No registration\n', builder.ORIGINAL+b'\n'+builder.ORIGINAL):
            with self.subTest(registration=registration):
                self.entry.write_bytes(registration)
                before = self.files()
                with self.assertRaisesRegex(ValueError, 'exactly one'):
                    builder.install(self.project)
                self.assertEqual(before, self.files())


if __name__ == '__main__':
    unittest.main()
