"""Contracts for isolated probe resources and exact logical array lengths."""
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/runtime_packet_probe'))
from isolated_assets import build_isolated_assets, isolated_config, CONSUMER_MATERIAL


class IsolatedAssetTests(unittest.TestCase):
    def test_exact_length_and_explicit_input_picture_are_independent(self):
        for size in (1, 96, 65536, 131072):
            config = isolated_config(payload_bytes=size)
            self.assertEqual(config['payload_bytes'], size)
            self.assertEqual(config['storage_bytes'], (size + 23) // 24 * 24)
            self.assertEqual(config['display_layout'][2], size)
            self.assertEqual(config['query'][0], 0)
            self.assertTrue(all(not process['enable'] for process in config['processes']))
            order = {item['name']: index for index, item in enumerate(config['processes'])}
            self.assertEqual(order[config['saved_scene_name']], 0)
            self.assertIn([config['saved_scene_name'], 0, config['display_name'], 0, 4],
                          config['connections'])
            self.assertIn([config['producer_names'][-1], 0, config['display_name'], 0, 3],
                          config['connections'])
            self.assertTrue(all(order[edge[0]] < order[edge[2]] for edge in config['connections']))

    def test_invalid_sizes_fail_before_creating_any_resources(self):
        for size in (0, -1, True, 1.0, 393217):
            with self.subTest(size=size), self.assertRaises(ValueError):
                isolated_config(payload_bytes=size)

    def test_unowned_or_incomplete_projects_are_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            resource = parent / 'resource_pack'
            resource.mkdir()
            marker = parent / '.pmanim_packet_probe.json'
            for owner in (None, 'another_project', 'pmanim_runtime_packet_probe'):
                if owner:
                    marker.write_text(json.dumps({'kind': owner}), encoding='utf-8')
                with self.subTest(owner=owner), self.assertRaises(ValueError):
                    build_isolated_assets(resource)
                self.assertEqual(list(resource.iterdir()), [])

    def test_builder_keeps_existing_materials_and_does_not_install_global_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            resource = parent / 'resource_pack'
            material = resource / 'materials/postprocess.material'
            material.parent.mkdir(parents=True)
            material.write_text(json.dumps({'existing': {'kept': True}}), encoding='utf-8')
            (parent / 'behavior_pack/packet_probe').mkdir(parents=True)
            (parent / '.pmanim_packet_probe.json').write_text(
                json.dumps({'kind': 'pmanim_runtime_packet_probe'}), encoding='utf-8')
            config = build_isolated_assets(resource, payload_bytes=65536)
            materials = json.loads(material.read_text(encoding='utf-8'))
            self.assertEqual(materials['existing'], {'kept': True})
            self.assertEqual([entry['samplerIndex'] for entry in
                              materials[CONSUMER_MATERIAL]['samplerStates']], [3, 4])
            self.assertEqual(config['payload_bytes'], 65536)
            self.assertFalse((resource / 'graphics_settings/post_process.json').exists())
            self.assertEqual((parent / 'behavior_pack/packet_probe/isolated_runtime.py').read_bytes(),
                             (ROOT / 'tools/runtime_packet_probe/isolated_runtime.py').read_bytes())


if __name__ == '__main__':
    unittest.main()
