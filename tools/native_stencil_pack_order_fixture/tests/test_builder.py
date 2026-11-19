"""Offline regressions for the separately loaded extra behavior pack."""
import base64
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

from tools.native_stencil_pack_order_fixture import build_fixture as packs


class FixtureTests(unittest.TestCase):
    def setUp(self):
        runtime = (packs.ROOT/'.runtime').resolve()
        runtime.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='pack-order-loader-test-', dir=str(runtime))
        self.base = Path(self.temporary.name).resolve()
        if runtime not in self.base.parents:
            raise AssertionError('Temporary fixture must remain inside repository .runtime')
        self.addCleanup(self.temporary.cleanup)

    def test_both_variants_include_discoverable_loader_and_client_module(self):
        fake_game = self.base/'installed/Minecraft.Windows.exe'
        fake_game.parent.mkdir()
        fake_game.write_bytes(b'offline executable-path fixture')
        native = fake_game.parent/'data/resource_packs/vanilla_netease/materials/sfx.material'
        native.parent.mkdir(parents=True)
        routes = ('sequence:billboard_base', 'point_sequence:sequence',
                  'point_sequence_add:point_sequence', 'sequence_add:sequence')
        original = b'\xef\xbb\xbf'+json.dumps({'materials': dict.fromkeys(routes, {})}).encode('utf-8')+b'\r\n'
        native.write_bytes(original)
        receipts = []
        for variant in packs.VARIANTS:
            receipt = packs.install(self.base/variant, variant, fake_game)
            receipts.append(receipt)
            behavior = Path(receipt['behavior_pack'])
            discovered = [path.name for path in behavior.iterdir()
                          if path.is_dir() and (path/'modMain.py').is_file()]
            self.assertEqual(discovered, [packs.PACKAGE])
            self.assertEqual((behavior/packs.PACKAGE/'modMain.py').read_bytes(),
                             (packs.HERE/'modMain.py').read_bytes())
            self.assertEqual(receipt['version'], [1, 0, 1])
            self.assertEqual(receipt['loader_entrypoint'], packs.PACKAGE+'.modMain')
            self.assertIn('behavior_pack/'+packs.PACKAGE+'/modMain.py', receipt['file_sha256'])
            self.assertFalse(receipt['automatic_ui_or_effect_initialization'])
            self.assertFalse(receipt['automatic_system_registration'])
        self.assertNotEqual(receipts[0]['resource_uuid'], receipts[1]['resource_uuid'])
        self.assertNotEqual(receipts[0]['behavior_uuid'], receipts[1]['behavior_uuid'])
        self.assertEqual((Path(receipts[1]['resource_pack'])/'materials/sfx.material').read_bytes(), original)
        self.assertEqual(native.read_bytes(), original)
        self.assertFalse((Path(receipts[0]['resource_pack'])/'materials/sfx.material').exists())

    def test_loader_imports_client_class_only_during_client_init(self):
        receipt = packs.install(self.base/'addon')
        calls = []

        class FakeMod(object):
            @staticmethod
            def Binding(**metadata):
                def decorate(cls):
                    cls.binding = metadata
                    return cls
                return decorate

            @staticmethod
            def InitClient():
                def decorate(method):
                    method.client_init = True
                    return method
                return decorate

            @staticmethod
            def DestroyClient():
                def decorate(method):
                    method.client_destroy = True
                    return method
                return decorate

        fake_modules = {}
        for name in ('mod', 'mod.common', 'mod.client'):
            fake_modules[name] = types.ModuleType(name)
            fake_modules[name].__path__ = []
        fake_modules['mod.common.mod'] = types.ModuleType('mod.common.mod')
        fake_modules['mod.common.mod'].Mod = FakeMod
        fake_api = types.ModuleType('mod.client.extraClientApi')

        def screen_node_class():
            calls.append('GetScreenNodeCls')
            return type('FakeScreenNode', (object,), {})

        fake_api.GetScreenNodeCls = screen_node_class
        fake_modules['mod.client.extraClientApi'] = fake_api
        for name in (packs.PACKAGE, packs.PACKAGE+'.modMain', packs.PACKAGE+'.runtime'):
            self.assertNotIn(name, sys.modules)
        root = str(Path(receipt['behavior_pack']))
        with mock.patch.dict(sys.modules, fake_modules):
            sys.path.insert(0, root)
            try:
                importlib.invalidate_caches()
                entry_module = importlib.import_module(receipt['loader_entrypoint'])
                entry = entry_module.PackOrderFixtureEntry()
                self.assertEqual(entry.binding['version'], '1.0.1')
                self.assertEqual(calls, [])
                self.assertNotIn(packs.PACKAGE+'.runtime', sys.modules)
                entry.client_init()
                self.assertEqual(calls, ['GetScreenNodeCls'])
                self.assertEqual(entry.canary_class.__name__, 'PackOrderCanary')
                self.assertIn(packs.PACKAGE+'.runtime', sys.modules)
                entry.client_destroy()
                self.assertIsNone(entry.canary_class)
                self.assertEqual(calls, ['GetScreenNodeCls'])
            finally:
                sys.path.remove(root)

    def test_config_plan_remains_byte_exact_and_read_only_after_loader_fix(self):
        receipt = packs.install(self.base/'addon')
        project = self.base/'project'
        project.mkdir()
        target = project/'.mcdev.json'
        before = b'\xef\xbb\xbf{\r\n  "included_mod_dirs": ["./"]\r\n}\r\n'
        target.write_bytes(before)
        for position in ('first', 'last'):
            plan = packs.config_plan(project, receipt, position)
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(base64.b64decode(plan['before_base64']), before)
            after = json.loads(base64.b64decode(plan['after_base64']))
            self.assertEqual(after['included_mod_dirs'][0 if position=='first' else -1], receipt['root'])


if __name__ == '__main__':
    unittest.main()
