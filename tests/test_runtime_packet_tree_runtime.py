"""Bounded tree upload and lifecycle regressions using SDK doubles only."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'tools/runtime_packet_probe'


def load_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def independent_words(seed, pages):
    """Integer host oracle, independent of the runtime's dataset function."""
    state = int(seed) & 0xffffff
    result = []
    for page in range(pages):
        words = []
        for index in range(12):
            state = (1664525*state+1013904223) & 0xffffff
            words.append(state)
        result.append(words)
    return result


def replay(state):
    result = independent_words(state['initial_seed'], state['aggregate']['pages'])
    for record in state['update_history']:
        update = independent_words(record['seed'], record['leaf_count'])
        for index, words in enumerate(update):
            result[(record['first_leaf']+index) % len(result)] = words
    return result


class TreeRuntimeTests(unittest.TestCase):
    def setUp(self):
        harness_module = load_path('_tree_runtime_harness', ROOT / 'tests/test_runtime_packet_runtime.py')
        self.harness = harness_module.RuntimePacketRuntimeTests()
        self.harness.setUp()
        self.addCleanup(self.harness.doCleanups)
        self.isolated = self.harness.load_module(
            '_runtime_packet_behavior_test.isolated_runtime', 'isolated_runtime.py')
        self.isolated.time = self.harness.clock
        self.module = self.harness.load_module(
            '_runtime_packet_behavior_test.tree_runtime', 'tree_runtime.py')
        self.module.time = self.harness.clock
        self.assets = load_path('_tree_runtime_assets', PROBE / 'tree_assets.py')
        self.config = self.assets.tree_config(251, namespace='runtime_tree')
        self.post = self.harness.post

    def probe(self):
        return self.module.TreeProbe(self.post, self.config, 12345)

    def cleanup_order(self):
        return self.config['producer_names'] + [self.config['display_name'], self.config['saved_scene_name']]

    def test_finish_initializes_every_leaf_with_twelve_words_and_restores_only_merge_metadata(self):
        probe = self.probe()
        self.assertFalse(probe.ready)
        self.assertFalse(probe.enabled)
        self.assertEqual(probe.words, [])
        self.assertTrue(all(not value for value in self.post.enabled.values()))
        state = probe.finish()
        self.assertTrue(state['ready'])
        self.assertTrue(state['enabled'])
        self.assertEqual(state['aggregate']['words_per_page'], 12)
        self.assertEqual(state['aggregate']['words'], independent_words(12345, self.config['pages']))
        self.assertEqual(state['initial_seed'], 12345)
        self.assertTrue(state['initialized'])
        self.assertTrue(state['payload_consistent'])
        self.assertEqual(state['update_history'], [])
        self.assertEqual(state['update_count'], 0)
        self.assertEqual(state['cursor'], 0)
        self.assertEqual(state['update_budget_bytes'], 3072)
        self.assertTrue(state['history_complete'])
        self.assertEqual(state['transport'], 'tree_atlas')
        self.assertEqual(state['screen_size'], [720, 1080])
        self.assertEqual(state['payload_bytes'], 251)
        self.assertEqual(state['aggregate']['layout'], self.config['layout'])
        self.assertFalse(state['gpu_verified'])
        for name in self.config['leaf_names']:
            keys = [key for called, key, values in self.post.parameter_calls if called == name]
            self.assertEqual(keys, ['packet0', 'packet1', 'packet2'])
        for name, parameters in self.config['merge_parameters'].items():
            for key, value in parameters.items():
                self.assertEqual(self.post.parameters[(name, key)], value)
        for key, value in (('query', self.config['query']),
                            ('display_rect', self.config['display_rect_norm']),
                            ('atlas_layout', self.config['display_layout'])):
            self.assertEqual(self.post.parameters[(self.config['display_name'], key)], value)

    def test_large_storage_increment_generates_only_budgeted_leaves_and_uses_three_calls_per_leaf(self):
        self.config = self.assets.tree_config(65537, namespace='large_tree')
        probe = self.probe()
        with patch.object(self.module, 'dataset', wraps=self.module.dataset) as generate:
            probe.finish()
            generate.assert_called_once_with(12345, self.config['pages']*4)
            generate.reset_mock()
            self.post.parameter_calls.clear()
            timings = probe.write(67890)
            generate.assert_called_once_with(67890, 85*4)
        self.assertEqual(len(self.post.parameter_calls), 85*3)
        self.assertTrue(all(name in self.config['leaf_names'][:85] for name, key, value in self.post.parameter_calls))
        self.assertEqual(probe.cursor, 85)
        self.assertEqual(probe.update_history[0]['actual_storage_bytes'], 3060)
        self.assertEqual(probe.update_history[0]['budget_bytes'], 3072)
        self.assertEqual(probe.update_history[0]['valid_payload_bytes'], 3060)
        self.assertEqual(probe.words[:85], independent_words(67890, 85))
        self.assertEqual(probe.words[85:], independent_words(12345, self.config['pages'])[85:])
        self.assertEqual(len(timings), 2)
        self.assertTrue(all(value >= 0 for value in timings))
        self.assertEqual(probe.words, replay(probe.snapshot()))
        for name, key, value in self.post.parameter_calls:
            page = self.config['leaf_names'].index(name)
            offset = int(key[-1])*4
            self.assertEqual(value, [word/16777216. for word in probe.words[page][offset:offset+4]])

    def test_wrap_uploads_two_segments_with_one_continuous_seed_sequence_and_correct_padding_receipt(self):
        self.config = self.assets.tree_config(175, namespace='wrap_tree')
        probe = self.probe()
        probe.finish()
        probe.set_update_budget(108)
        probe.write(101)
        unchanged = copy.deepcopy(probe.words[1:3])
        self.post.parameter_calls.clear()
        probe.write(202)
        self.assertEqual([name for name, key, value in self.post.parameter_calls],
                         [name for index in (3, 4, 0) for name in [self.config['leaf_names'][index]]*3])
        expected = independent_words(202, 3)
        self.assertEqual([probe.words[index] for index in (3, 4, 0)], expected)
        self.assertEqual(probe.words[1:3], unchanged)
        receipt = probe.update_history[-1]
        self.assertEqual(receipt['seed'], 202)
        self.assertEqual(receipt['first_leaf'], 3)
        self.assertEqual(receipt['leaf_count'], 3)
        self.assertEqual(receipt['actual_storage_bytes'], 108)
        self.assertEqual(receipt['valid_payload_bytes'], 103)
        self.assertEqual(probe.cursor, 1)
        self.assertEqual(probe.words, replay(probe.snapshot()))

    def test_minimum_budget_counts_physical_bytes_even_for_one_payload_byte(self):
        self.config = self.assets.tree_config(1, namespace='tail_tree')
        probe = self.probe()
        probe.finish()
        probe.set_update_budget(37)
        probe.write(777)
        receipt = probe.update_history[-1]
        self.assertEqual(receipt['leaf_count'], 1)
        self.assertEqual(receipt['actual_storage_bytes'], 36)
        self.assertEqual(receipt['valid_payload_bytes'], 1)
        self.assertEqual(probe.words, independent_words(777, 1))
        self.assertEqual(probe.cursor, 0)

    def test_each_history_record_keeps_its_own_budget_after_budget_changes(self):
        probe = self.probe()
        probe.finish()
        probe.set_update_budget(108)
        probe.write(101)
        probe.set_update_budget(37)
        probe.write(202)
        probe.set_update_budget(72)
        state = probe.snapshot()
        self.assertEqual(state['update_budget_bytes'], 72)
        self.assertEqual([record['budget_bytes'] for record in state['update_history']], [108, 37])
        self.assertEqual([record['actual_storage_bytes'] for record in state['update_history']], [108, 36])
        self.assertTrue(all(record['actual_storage_bytes'] <= record['budget_bytes']
                            for record in state['update_history']))

    def test_budget_and_inherited_query_validation(self):
        probe = self.probe()
        for budget in (0, 35, 3073, 36., True, '72', None):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                probe.set_update_budget(budget)
        self.assertEqual(probe.update_budget_bytes, 3072)
        probe.set_update_budget(36)
        probe.select(mode=2, start=250, count=3072, salt=17)
        self.assertEqual(probe.query, [2., 250., 3072., 17.])
        with self.assertRaises(ValueError):
            probe.select(start=251)

    def test_history_limit_preserves_receipts_and_explicitly_marks_incomplete(self):
        self.config = self.assets.tree_config(1, namespace='history_tree')
        probe = self.probe()
        probe.finish()
        for seed in range(512):
            probe.write(seed)
        first = copy.deepcopy(probe.update_history[0])
        self.assertTrue(probe.history_complete)
        self.assertEqual(len(probe.update_history), 512)
        probe.write(512)
        self.assertFalse(probe.history_complete)
        self.assertEqual(probe.update_count, 513)
        self.assertEqual(len(probe.update_history), 512)
        self.assertEqual(probe.update_history[0], first)
        state = probe.snapshot()
        state['update_history'][0]['seed'] = -1
        self.assertEqual(probe.update_history[0], first)

    def test_metadata_and_connection_failure_disable_all_owned_passes(self):
        probe = self.probe()
        merge = next(iter(self.config['merge_parameters']))
        self.post.fail_parameter[(merge, 'node')] = True
        self.post.enable_calls.clear()
        with self.assertRaises(RuntimeError):
            probe.finish()
        self.assertEqual(self.post.enable_calls, [(name, False) for name in self.cleanup_order()])
        self.assertFalse(probe.initialized)
        self.assertFalse(probe.ready)
        self.post.fail_parameter.clear()
        self.post.fail_connection = True
        self.post.enable_calls.clear()
        with self.assertRaises(RuntimeError):
            probe.finish()
        self.assertEqual(self.post.enable_calls, [(name, False) for name in self.cleanup_order()])
        self.assertFalse(probe.ready)
        self.assertTrue(probe.initialized)

    def test_partial_increment_rejects_further_upload_and_preserves_last_committed_words(self):
        probe = self.probe()
        probe.finish()
        probe.set_update_budget(72)
        committed = copy.deepcopy(probe.words)
        self.post.fail_parameter[(self.config['leaf_names'][1], 'packet1')] = True
        self.post.enable_calls.clear()
        with self.assertRaises(RuntimeError):
            probe.write(101)
        self.assertEqual(probe.words, committed)
        self.assertEqual(probe.update_history, [])
        self.assertEqual(probe.cursor, 0)
        self.assertFalse(probe.payload_consistent)
        self.assertFalse(probe.ready)
        self.assertFalse(probe.enabled)
        self.assertEqual(self.post.enable_calls, [(name, False) for name in self.cleanup_order()])
        self.post.fail_parameter.clear()
        with self.assertRaisesRegex(RuntimeError, 'new TreeProbe'):
            probe.finish()

    def test_invalid_tree_identity_edges_and_merge_ranges_fail_before_registration(self):
        original = self.config
        merge = next(iter(original['merge_parameters']))
        for fault in ('pages', 'words', 'leaf_parameter', 'merge_parameter', 'process_order',
                      'back_edge', 'missing_edge', 'duplicate_parent', 'capacity', 'root', 'size'):
            with self.subTest(fault=fault):
                config = copy.deepcopy(original)
                if fault == 'pages':
                    config['pages'] += 1
                elif fault == 'words':
                    config['words_per_page'] = 8
                elif fault == 'leaf_parameter':
                    config['processes'][1]['paras'][0]['name'] = 'page'
                elif fault == 'merge_parameter':
                    index = config['producer_names'].index(merge)+1
                    config['processes'][index]['paras'][0]['name'] = 'packet0'
                elif fault == 'process_order':
                    config['processes'][1:3] = reversed(config['processes'][1:3])
                elif fault == 'back_edge':
                    config['connections'][0][0], config['connections'][0][2] = config['connections'][0][2], config['connections'][0][0]
                elif fault == 'missing_edge':
                    config['connections'].pop(0)
                elif fault == 'duplicate_parent':
                    config['connections'].insert(0, list(config['connections'][0]))
                elif fault == 'capacity':
                    config['merge_parameters'][merge]['node'][2] = 2
                elif fault == 'root':
                    config['root_name'] = config['leaf_names'][0]
                else:
                    config['display_layout'][0] += 1
                with self.assertRaises(ValueError):
                    self.module.TreeProbe(self.post, config, 12345)
                self.assertEqual(self.post.add_calls, [])


if __name__ == '__main__':
    unittest.main()
