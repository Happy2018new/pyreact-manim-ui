"""Structural and addressing checks for the private-RT tree asset contract.

These host checks do not establish native RT allocation, GLSL execution or
Minecraft performance. GPU and native acceptance use the generated assets.
"""
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'tools/runtime_packet_probe'
sys.path.insert(0, str(PROBE))
import tree_assets
from tree_assets import build_tree_assets, tree_config


class TreeConfigurationTests(unittest.TestCase):
    def test_default_has_three_local_leaves_and_one_forward_merge(self):
        config = tree_config(namespace='tree_default')
        self.assertEqual(config['payload_bytes'], 96)
        self.assertEqual(config['pages'], 3)
        self.assertEqual(config['storage_bytes'], 108)
        self.assertEqual(config['words_per_page'], 12)
        self.assertEqual(config['bytes_per_page'], 36)
        self.assertEqual(config['target_pixels'], [12, 3])
        self.assertEqual(config['layout'], {'columns': 12, 'rows': 3})
        self.assertEqual(config['query'], [0.0, 0.0, 96.0, 7.0])
        self.assertEqual(config['display_layout'], [12.0, 3.0, 96.0, 0.0])
        self.assertEqual(config['parameter_names'], ['packet0', 'packet1', 'packet2'])
        self.assertEqual(config['producer_names'][:3], config['leaf_names'])
        self.assertEqual(len(config['merge_parameters']), 1)
        root = config['root_name']
        self.assertEqual(config['merge_parameters'][root],
                         {'node': [12.0, 3.0, 1.0, 3.0],
                          'layout': [1080.0, 12.0, 0.0, 0.0]})
        processes = {item['name']: item for item in config['processes']}
        for name in config['leaf_names']:
            leaf = processes[name]
            self.assertFalse(leaf['enable'])
            self.assertEqual([parameter['name'] for parameter in leaf['paras']],
                             config['parameter_names'])
            self.assertEqual([parameter['value'] for parameter in leaf['paras']], [[0.0] * 4] * 3)
            target = leaf['pass_array'][0]['render_target']
            self.assertEqual(math.floor(target['width'] * 720), 12)
            self.assertEqual(math.floor(target['height'] * 1080), 1)
        self.assertEqual(config['connections'][:3],
                         [[name, 0, root, 0, 3 + index]
                          for index, name in enumerate(config['leaf_names'])])
        self.assertEqual(config['connections'][-2:],
                         [[root, 0, config['display_name'], 0, 3],
                          [config['saved_scene_name'], 0, config['display_name'], 0, 4]])
        self.assertEqual(config['stats']['total_passes'], 6)

    def test_one_byte_has_one_leaf_no_merge_and_an_exact_logical_length(self):
        config = tree_config(payload_bytes=1, namespace='tree_byte')
        self.assertEqual(config['pages'], 1)
        self.assertEqual(config['storage_bytes'], 36)
        self.assertEqual(config['payload_bytes'], 1)
        self.assertEqual(config['merge_parameters'], {})
        self.assertEqual(config['root_name'], config['leaf_names'][0])
        self.assertEqual(config['target_pixels'], [12, 1])
        self.assertEqual(config['display_layout'][2], 1)
        self.assertEqual(len(config['processes']), 3)

    def test_every_edge_is_forward_and_each_producer_has_one_data_parent(self):
        config = tree_config(payload_bytes=36 * 126 - 1, namespace='tree_edges')
        expected = ([config['saved_scene_name']] + config['producer_names'] +
                    [config['display_name']])
        self.assertEqual([item['name'] for item in config['processes']], expected)
        positions = {name: index for index, name in enumerate(expected)}
        outgoing = {name: [] for name in config['producer_names']}
        incoming = {name: [] for name in config['merge_parameters']}
        for source, source_pass, dest, dest_pass, slot in config['connections']:
            self.assertEqual((source_pass, dest_pass), (0, 0))
            self.assertLess(positions[source], positions[dest])
            self.assertIn(slot, range(3, 8))
            if source in outgoing:
                outgoing[source].append((dest, slot))
            if dest in incoming:
                incoming[dest].append(slot)
        self.assertTrue(all(len(edges) == 1 for edges in outgoing.values()))
        for slots in incoming.values():
            self.assertEqual(slots, list(range(3, 3 + len(slots))))
            self.assertLessEqual(len(slots), 5)

    def test_nested_routing_preserves_word_order_and_partial_children(self):
        for pages in (1, 3, 6, 26, 126, 1081):
            with self.subTest(pages=pages):
                config = tree_config(payload_bytes=pages * 36 - 1, namespace='tree_route')
                nodes = {node['name']: node for node in config['nodes']}
                leaves = {name: index for index, name in enumerate(config['leaf_names'])}

                def route(name, word):
                    node = nodes[name]
                    self.assertLess(word, node['pages'] * 12)
                    if name in leaves:
                        return leaves[name] * 12 + word
                    capacity = int(config['merge_parameters'][name]['node'][2])
                    child_index, local_word = divmod(word, capacity * 12)
                    child = nodes[node['children'][child_index]]
                    child_pages = min(capacity, node['pages'] - child_index * capacity)
                    child_width = 12 * math.ceil(child_pages / 1080)
                    child_height = math.ceil(child_pages / (child_width // 12))
                    self.assertEqual(child['pages'], child_pages)
                    self.assertEqual(child['target_pixels'], [child_width, child_height])
                    x, y = local_word % child_width, local_word // child_width
                    self.assertLess(y, child_height)
                    return route(child['name'], x + child_width * y)

                for word in range(pages * 12):
                    self.assertEqual(route(config['root_name'], word), word)
                width, height = config['target_pixels']
                self.assertGreaterEqual(width * height, pages * 12)
                self.assertLess(width * height - pages * 12, width)
                for node in nodes.values():
                    if node['level']:
                        self.assertEqual(node['child_capacity_pages'], 5 ** (node['level'] - 1))

    def test_128k_requested_pixels_are_linear_per_level(self):
        config = tree_config(payload_bytes=131072, namespace='tree_bulk')
        self.assertEqual(config['pages'], 3641)
        self.assertEqual(config['target_pixels'], [48, 911])
        self.assertEqual(config['storage_bytes'] - config['payload_bytes'], 4)
        self.assertEqual(config['stats']['merge_nodes'], 914)
        self.assertEqual(config['stats']['data_passes'], 4555)
        self.assertEqual(config['stats']['data_pixels_per_frame'], 305892)
        nodes = config['nodes']
        for level in config['levels']:
            members = [node for node in nodes if node['level'] == level['level']]
            self.assertEqual(level['nodes'], len(members))
            self.assertEqual(level['passes'], len(members))
            self.assertEqual(level['pixels'], sum(math.prod(node['target_pixels']) for node in members))
            self.assertLessEqual(level['pixels'], config['pages'] * 12 + 48)
        self.assertLess(config['stats']['data_pixels_per_frame'],
                        config['stats']['flat_full_atlas_chain_pixels_per_frame'] // 100)
        self.assertEqual(config['stats']['total_passes'], len(config['processes']))
        self.assertFalse(config['gpu_verified'])

    def test_validation_rejects_invalid_sizes_names_and_unfittable_targets(self):
        for value in (0, -1, True, 1.5, '96'):
            with self.subTest(payload=value), self.assertRaises(ValueError):
                tree_config(payload_bytes=value)
        for value in ((0, 1080), (720, 0), (True, 1080), (720,), '720x1080'):
            with self.subTest(screen=value), self.assertRaises(ValueError):
                tree_config(screen_size=value)
        for value in ('', 'a-b', '123bad', '中文', 7):
            with self.subTest(namespace=value), self.assertRaises(ValueError):
                tree_config(namespace=value)
        with self.assertRaises(ValueError):
            tree_config(screen_size=(11, 1080))
        with self.assertRaises(ValueError):
            tree_config(payload_bytes=60 * 1080 * 36 + 1)
        first, second = tree_config(), tree_config()
        self.assertNotEqual(first['namespace'], second['namespace'])
        first['processes'][1]['paras'][0]['value'][0] = 0.5
        self.assertEqual(second['processes'][1]['paras'][0]['value'][0], 0.0)

    def test_shaders_reserve_vector4_and_keep_payload_off_scene_samplers(self):
        for filename in ('tree_leaf.fragment', 'tree_merge.fragment', 'tree_consumer.fragment'):
            source = (PROBE / filename).read_text(encoding='utf-8')
            self.assertNotIn('EXTRA_VECTOR4', source)
            for slot in (0, 1, 2):
                self.assertNotIn('TEXTURE_%d' % slot, source)
        leaf = (PROBE / 'tree_leaf.fragment').read_text(encoding='utf-8')
        self.assertNotIn('sampler2D', leaf)
        for index in (1, 2, 3):
            self.assertIn('uniform vec4 EXTRA_VECTOR%d;' % index, leaf)
        merge = (PROBE / 'tree_merge.fragment').read_text(encoding='utf-8')
        for slot in range(3, 8):
            self.assertIn('uniform sampler2D TEXTURE_%d;' % slot, merge)
        consumer = (PROBE / 'tree_consumer.fragment').read_text(encoding='utf-8')
        self.assertIn('float byteAt(float index)', consumer)
        self.assertIn('EXTRA_VECTOR3.xy', consumer)
        self.assertIn('ordinal < EXTRA_VECTOR1.z && index < EXTRA_VECTOR3.z', consumer)
        self.assertIn('gl_FragColor = original;', consumer)


class TreeBuilderTests(unittest.TestCase):
    def fixture(self, directory):
        project = directory / 'project'
        resource = project / 'resource_pack'
        resource.mkdir(parents=True)
        (project / '.pmanim_packet_probe.json').write_text(
            json.dumps({'kind': 'pmanim_runtime_packet_probe'}), encoding='utf-8')
        (project / 'behavior_pack/packet_probe').mkdir(parents=True)
        source = directory / 'sources'
        source.mkdir()
        for filename in ('tree_leaf.fragment', 'tree_merge.fragment', 'tree_consumer.fragment',
                         'isolated_copy.fragment'):
            (source / filename).write_text((PROBE / filename).read_text(encoding='utf-8'), encoding='utf-8')
        (source / 'tree_runtime.py').write_text('# owned runtime fixture\n', encoding='utf-8')
        (source / 'isolated_runtime.py').write_text('# owned isolated dependency fixture\n', encoding='utf-8')
        return resource, source

    def test_owned_build_preserves_original_materials_and_installs_new_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            resource, source = self.fixture(Path(temporary))
            material_path = resource / 'materials/postprocess.material'
            material_path.parent.mkdir()
            original = {'existing_material': {'fragmentShader': 'shaders/existing.fragment'}}
            material_path.write_text(json.dumps(original), encoding='utf-8')
            with mock.patch.object(tree_assets, 'HERE', source):
                config = build_tree_assets(resource, payload_bytes=37, namespace='owned_tree')
                repeated = build_tree_assets(resource, payload_bytes=37, namespace='owned_tree')
            self.assertEqual(config, repeated)
            materials = json.loads(material_path.read_text(encoding='utf-8'))
            self.assertEqual(materials['existing_material'], original['existing_material'])
            self.assertEqual(len(materials), 5)
            merge = materials[tree_assets.MERGE_MATERIAL]
            self.assertEqual([item['samplerIndex'] for item in merge['samplerStates']], [3, 4, 5, 6, 7])
            self.assertEqual(materials[tree_assets.LEAF_MATERIAL]['samplerStates'], [])
            for filename in ('tree_leaf.fragment', 'tree_merge.fragment', 'tree_consumer.fragment',
                             'isolated_copy.fragment'):
                self.assertEqual((resource / 'shaders/glsl' / filename).read_bytes(),
                                 (source / filename).read_bytes())
            self.assertEqual((resource.parent / 'behavior_pack/packet_probe/tree_runtime.py').read_bytes(),
                             (source / 'tree_runtime.py').read_bytes())
            self.assertEqual((resource.parent / 'behavior_pack/packet_probe/isolated_runtime.py').read_bytes(),
                             (source / 'isolated_runtime.py').read_bytes())

    def test_unowned_or_conflicting_materials_fail_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with self.assertRaises(ValueError):
                build_tree_assets(directory / 'resource_pack')
            resource, source = self.fixture(directory)
            path = resource / 'materials/postprocess.material'
            path.parent.mkdir()
            content = json.dumps({tree_assets.LEAF_MATERIAL: {'unexpected': 'owned elsewhere'}})
            path.write_text(content, encoding='utf-8')
            with mock.patch.object(tree_assets, 'HERE', source), self.assertRaises(ValueError):
                build_tree_assets(resource)
            self.assertEqual(path.read_text(encoding='utf-8'), content)


if __name__ == '__main__':
    unittest.main()
