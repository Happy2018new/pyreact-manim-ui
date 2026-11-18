"""Independent host-oracle and receipt regressions; no Minecraft operations."""
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'tools/runtime_packet_probe'
sys.path.insert(0, str(PROBE))
import run_tree_case as runner
from tree_assets import tree_config


def reference_word(seed, steps):
    """Exponentiate an affine map instead of iterating the runtime recurrence."""
    modulus = 1 << 24
    result_scale, result_offset = 1, 0
    scale, offset = 1664525, 1013904223
    while steps:
        if steps & 1:
            result_scale, result_offset = ((scale * result_scale) % modulus,
                                           (scale * result_offset + offset) % modulus)
        scale, offset = (scale * scale) % modulus, (scale * offset + offset) % modulus
        steps //= 2
    return (result_scale * (seed % modulus) + result_offset) % modulus


def reference_words(seed, leaves):
    return [[reference_word(seed, leaf * 12 + word + 1) for word in range(12)]
            for leaf in range(leaves)]


def receipt(config, initial_seed=12345, updates=(), budget=108):
    words = reference_words(initial_seed, config['pages'])
    cursor, journal = 0, []
    for seed, count in updates:
        valid = 0
        for offset, values in enumerate(reference_words(seed, count)):
            leaf = (cursor + offset) % config['pages']
            words[leaf] = values
            valid += min(36, config['payload_bytes'] - leaf * 36)
        journal.append({'seed': seed, 'first_leaf': cursor, 'leaf_count': count,
                        'budget_bytes': budget,
                        'actual_storage_bytes': count * 36, 'valid_payload_bytes': valid,
                        'generation_ms': 0.25, 'upload_ms': 0.5})
        cursor = (cursor + count) % config['pages']
    return {'transport': 'tree_atlas', 'ready': True, 'enabled': True, 'error': None,
            'runner_running': False, 'case_namespace': config['namespace'],
            'native_crosshair_hidden': True, 'screen_size': list(config['screen_size']),
            'payload_bytes': config['payload_bytes'],
            'process_names': [process['name'] for process in config['processes']],
            'initial_seed': initial_seed, 'initialized': True, 'payload_consistent': True,
            'history_complete': True, 'update_history': journal, 'update_count': len(journal),
            'update_budget_bytes': budget, 'cursor': cursor,
            'aggregate': {'pages': config['pages'], 'words_per_page': 12, 'words': words,
                          'layout': dict(config['layout']),
                          'display_rect_norm': list(config['display_rect_norm']),
                          'query': list(config['query'])}}


def word_bytes(words):
    return b''.join(value.to_bytes(3, 'big') for leaf in words for value in leaf)


class TreeOracleTests(unittest.TestCase):
    def test_lcg_matches_independent_affine_exponentiation_across_leaf_boundaries(self):
        for seed in (0, 1, -1, 54321, (1 << 24) + 54321):
            with self.subTest(seed=seed):
                self.assertEqual(runner.words_for_seed(seed, 7), reference_words(seed, 7))
        self.assertEqual(runner.words_for_seed(54321, 2)[0], runner.words_for_seed(54321, 1)[0])
        self.assertNotEqual(runner.words_for_seed(54321, 2)[0], runner.words_for_seed(54321, 2)[1])

    def test_unmodified_initial_payload_excludes_the_storage_padding(self):
        for size in (1, 35, 36, 37, 96, 251):
            with self.subTest(size=size):
                config = tree_config(size, namespace='oracle_initial')
                state = receipt(config)
                words, source = runner.replay(state, config)
                self.assertEqual(words, reference_words(12345, config['pages']))
                self.assertEqual(source, word_bytes(words)[:size])
                self.assertEqual(len(source), size)
                self.assertEqual(state['cursor'], 0)

    def test_circular_replay_restarts_lcg_per_update_and_accounts_for_partial_leaf(self):
        config = tree_config(251, namespace='oracle_wrap')
        state = receipt(config, updates=((11, 3), (23, 3), (47, 3)))
        self.assertEqual(state['update_history'][-1]['first_leaf'], 6)
        self.assertEqual(state['update_history'][-1]['actual_storage_bytes'], 108)
        self.assertEqual(state['update_history'][-1]['valid_payload_bytes'], 107)
        self.assertEqual(state['cursor'], 2)
        words, source = runner.replay(state, config)
        self.assertEqual(words[6], reference_words(47, 3)[0])
        self.assertEqual(words[0], reference_words(47, 3)[1])
        self.assertEqual(words[1], reference_words(47, 3)[2])
        self.assertEqual(words[2], reference_words(11, 3)[2])
        self.assertEqual(source, word_bytes(state['aggregate']['words'])[:251])

    def test_history_corruption_and_partial_upload_flags_are_rejected(self):
        config = tree_config(251, namespace='oracle_negative')
        original = receipt(config, updates=((11, 3), (23, 3), (47, 3)))
        changes = {
            'not_initialized': lambda state: state.update(initialized=False),
            'partial_upload': lambda state: state.update(payload_consistent=False),
            'truncated_history': lambda state: state.update(history_complete=False),
            'missing_record': lambda state: state['update_history'].pop(),
            'wrong_cursor': lambda state: state.update(cursor=3),
            'wrong_first_leaf': lambda state: state['update_history'][1].update(first_leaf=4),
            'boolean_count': lambda state: state['update_history'][0].update(leaf_count=True),
            'zero_count': lambda state: state['update_history'][0].update(leaf_count=0),
            'too_many_leaves': lambda state: state['update_history'][0].update(leaf_count=8),
            'wrong_storage': lambda state: state['update_history'][0].update(actual_storage_bytes=107),
            'exceeded_budget': lambda state: state['update_history'][0].update(
                leaf_count=4, actual_storage_bytes=144),
            'wrong_valid_tail': lambda state: state['update_history'][-1].update(valid_payload_bytes=108),
            'wrong_update_seed': lambda state: state['update_history'][-1].update(seed=48),
            'changed_native_word': lambda state: state['aggregate']['words'][0].__setitem__(0, 1),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                state = copy.deepcopy(original)
                change(state)
                with self.assertRaises(ValueError):
                    runner.replay(state, config)

    def test_initial_seed_is_observable_while_an_initial_leaf_remains(self):
        config = tree_config(251, namespace='oracle_initial_seed')
        state = receipt(config, updates=((11, 3), (23, 3)))
        state['initial_seed'] = 12346
        with self.assertRaises(ValueError):
            runner.replay(state, config)

    def test_512_complete_updates_replay_and_513_truncated_updates_fail(self):
        config = tree_config(73, namespace='oracle_journal_boundary')
        state = receipt(config, updates=tuple((100 + index * 97, 1) for index in range(512)), budget=36)
        words, source = runner.replay(state, config)
        self.assertEqual(len(source), 73)
        self.assertEqual(words, state['aggregate']['words'])
        state['update_count'] = 513
        state['history_complete'] = False
        with self.assertRaisesRegex(ValueError, 'complete update journal'):
            runner.replay(state, config)
        state['history_complete'] = True
        with self.assertRaisesRegex(ValueError, 'Missing incremental'):
            runner.replay(state, config)

    def test_recorded_budgets_survive_a_smaller_current_budget(self):
        config = tree_config(251, namespace='oracle_budget_change')
        state = receipt(config, updates=((11, 3), (23, 1)), budget=108)
        state['update_history'][-1]['budget_bytes'] = 36
        state['update_budget_bytes'] = 36
        words, source = runner.replay(state, config)
        self.assertEqual(words, state['aggregate']['words'])
        self.assertEqual(len(source), 251)

    def test_invalid_recorded_budgets_cannot_be_hidden_by_a_larger_current_budget(self):
        config = tree_config(251, namespace='oracle_budget_negative')
        original = receipt(config, updates=((11, 3),), budget=108)
        original['update_budget_bytes'] = 3072
        for budget in (True, 35, 36, 3073, 108.0):
            with self.subTest(budget=budget):
                state = copy.deepcopy(original)
                state['update_history'][0]['budget_bytes'] = budget
                with self.assertRaises(ValueError):
                    runner.replay(state, config)


class TreeReceiptTests(unittest.TestCase):
    def test_native_validation_accepts_one_frozen_owned_layout_and_query(self):
        config = tree_config(251, namespace='receipt_valid')
        state = receipt(config)
        words, unused = runner.replay(state, config)
        runner.validate(state, config, words, config['query'])

    def test_native_validation_rejects_identity_layout_visibility_and_generation_changes(self):
        config = tree_config(251, namespace='receipt_invalid')
        original = receipt(config)
        words, unused = runner.replay(original, config)
        changes = {
            'transport': lambda state: state.update(transport='isolated_atlas'),
            'ready': lambda state: state.update(ready=False),
            'enabled': lambda state: state.update(enabled=False),
            'error': lambda state: state.update(error='partial SDK write'),
            'active_writer': lambda state: state.update(runner_running=True),
            'owner': lambda state: state.update(case_namespace='other_tree'),
            'viewport': lambda state: state.update(screen_size=[1080, 720]),
            'logical_length': lambda state: state.update(payload_bytes=252),
            'page_count': lambda state: state['aggregate'].update(pages=8),
            'word_format': lambda state: state['aggregate'].update(words_per_page=8),
            'layout': lambda state: state['aggregate'].update(layout={'columns': 24, 'rows': 4}),
            'rectangle': lambda state: state['aggregate'].update(display_rect_norm=[0, 0, 1, 1]),
            'crosshair': lambda state: state.update(native_crosshair_hidden=False),
            'missing_process': lambda state: state['process_names'].pop(),
            'reordered_processes': lambda state: state['process_names'].reverse(),
            'new_words': lambda state: state['aggregate']['words'][0].__setitem__(0, 1),
            'new_query': lambda state: state['aggregate'].update(query=[1, 0, 251, 7]),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                state = copy.deepcopy(original)
                change(state)
                with self.assertRaises(ValueError):
                    runner.validate(state, config, words, config['query'])


class TreeBenchmarkJournalTests(unittest.TestCase):
    def setUp(self):
        self.config = tree_config(251, namespace='benchmark_journal')
        self.seed, self.budget = 700, 72
        self.prefix = ((19, 1), (29, 1))
        self.before = receipt(self.config, updates=self.prefix, budget=self.budget)
        self.frames = tuple((self.seed + frame * 97, 2) for frame in range(1, 4))
        self.after = receipt(self.config, updates=self.prefix + self.frames, budget=self.budget)
        self.run = {'frames': 3}

    def test_dynamic_journal_preserves_reused_prefix_and_matches_each_owned_frame(self):
        runner.validate_benchmark(self.before, self.after, self.run, self.seed, True, self.budget)
        runner.replay(self.after, self.config)

    def test_static_benchmark_cannot_append_even_a_self_consistent_update(self):
        runner.validate_benchmark(self.before, self.before, {'frames': 99}, self.seed, False, self.budget)
        with self.assertRaises(ValueError):
            runner.validate_benchmark(self.before, self.after, self.run, self.seed, False, self.budget)

    def test_dynamic_journal_rejects_missing_extra_reseeded_or_rebudgeted_frames(self):
        changes = {
            'prefix_seed': lambda state: state['update_history'][0].update(seed=20),
            'initial_seed': lambda state: state.update(initial_seed=12346),
            'missing_record': lambda state: state['update_history'].pop(),
            'extra_record': lambda state: state['update_history'].append(copy.deepcopy(
                state['update_history'][-1])),
            'missing_count': lambda state: state.update(update_count=state['update_count'] - 1),
            'wrong_seed': lambda state: state['update_history'][-1].update(seed=self.seed + 999),
            'wrong_budget': lambda state: state['update_history'][-1].update(budget_bytes=36),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                after = copy.deepcopy(self.after)
                change(after)
                with self.assertRaises(ValueError):
                    runner.validate_benchmark(self.before, after, self.run, self.seed, True, self.budget)

    def test_frame_count_is_bound_to_record_count(self):
        for frames in (2, 4):
            with self.subTest(frames=frames), self.assertRaises(ValueError):
                runner.validate_benchmark(self.before, self.after, {'frames': frames},
                                          self.seed, True, self.budget)


class TreeHostTests(unittest.TestCase):
    def test_saved_command_is_not_replayed_after_a_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            host = runner.NativeHost(directory / 'project', directory / 'evidence')
            timeout = runner.subprocess.TimeoutExpired('host', runner.HOST_TIMEOUT + 10)
            with mock.patch.object(runner.subprocess, 'run', side_effect=timeout) as call:
                with self.assertRaises(runner.subprocess.TimeoutExpired):
                    host.call('once', 'probe.aggregation.write(123)\n')
                with self.assertRaisesRegex(ValueError, 'Refusing to replay'):
                    host.call('once', 'probe.aggregation.write(123)\n')
            self.assertEqual(call.call_count, 1)
            self.assertEqual((host.commands / 'once.py').read_text(encoding='utf-8'),
                             'probe.aggregation.write(123)\n')

    def test_capture_receipt_requires_fresh_frame_and_an_allowed_owner_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            host = runner.NativeHost(directory / 'project', directory / 'evidence')
            base = {'ok': True, 'background_only': True,
                    'frame_qpc_100ns': 12, 'request_qpc_100ns': 11}
            cases = [(base, True), ({**base, 'frame_qpc_100ns': 10}, False),
                     ({**base, 'ok': False}, False), ({**base, 'background_only': False}, False),
                     ({**base, 'background_only': False, 'user_foreground_allowed': True,
                       'agent_activation_allowed': False}, True),
                     ({**base, 'background_only': False, 'user_foreground_allowed': True,
                       'agent_activation_allowed': True}, False)]
            for index, (report, accepted) in enumerate(cases):
                label = 'frame_%d' % index
                (host.evidence / (label + '.json')).write_text(json.dumps(report), encoding='utf-8')
                with self.subTest(index=index), mock.patch.object(runner.subprocess, 'run'):
                    if accepted:
                        self.assertEqual(host.run('capture', label), report)
                    else:
                        with self.assertRaises(ValueError):
                            host.run('capture', label)


class SyntheticScanHost:
    """Render the declared integer byte grid, without using the pixel verifier."""
    def __init__(self, evidence, state, corrupt_alpha=False, change_words=False):
        self.evidence = evidence
        self.state = copy.deepcopy(state)
        self.source = word_bytes(state['aggregate']['words'])[:state['payload_bytes']]
        self.calls = []
        self.corrupt_alpha, self.change_words = corrupt_alpha, change_words

    def call(self, label, code):
        self.calls.append((label, code))
        if '.select(' in code:
            arguments = code.split('probe.aggregation.select(', 1)[1].split(')', 1)[0]
            self.state['aggregate']['query'] = [int(value) for value in arguments.split(',')]
            if self.change_words and len(self.calls) == 2:
                self.state['aggregate']['words'][0][0] ^= 1
        state = copy.deepcopy(self.state)
        (self.evidence / (label + '.state.json')).write_text(json.dumps(state), encoding='utf-8')
        return state

    def run(self, action, label):
        if action != 'capture':
            raise AssertionError('Synthetic scan supports capture only')
        mode, start, count, salt = self.state['aggregate']['query']
        rows = (count + 23) // 24
        width, height = self.state['screen_size']
        image = Image.new('RGBA', (width, height), (19, 31, 47, 255))
        draw = ImageDraw.Draw(image)
        for offset in range(rows * 24):
            row, column = divmod(offset, 24)
            index = start + offset
            valid = offset < count and index < len(self.source)
            target = ((index + self.source[index] + salt) % len(self.source)
                      if valid and mode == 2 else index)
            value = self.source[target] if valid else 0
            x0 = math.ceil((0.05 + column * 0.9 / 24) * width - 0.5)
            x1 = math.ceil((0.05 + (column + 1) * 0.9 / 24) * width - 0.5) - 1
            y0 = math.ceil((0.05 + row * 0.9 / rows) * height - 0.5)
            y1 = math.ceil((0.05 + (row + 1) * 0.9 / rows) * height - 0.5) - 1
            draw.rectangle((x0, y0, x1, y1), fill=(value, value, value, 255))
        if self.corrupt_alpha:
            center = (math.floor((0.05 + 0.9 / 48) * width),
                      math.floor((0.05 + 0.9 / (2 * rows)) * height))
            image.putpixel(center, image.getpixel(center)[:3] + (254,))
        image.save(self.evidence / (label + '.png'))
        provenance = {'ok': True, 'background_only': True,
                      'request_qpc_100ns': 1, 'frame_qpc_100ns': 2}
        (self.evidence / (label + '.json')).write_text(json.dumps(provenance), encoding='utf-8')
        return provenance


class TreeFrozenScanTests(unittest.TestCase):
    def test_full_identity_and_dependent_windows_cover_exact_bytes_without_writing_source(self):
        config = tree_config(4097, namespace='scan_full')
        state = receipt(config, updates=((11, 3), (23, 3), (47, 3)))
        with tempfile.TemporaryDirectory() as temporary:
            host = SyntheticScanHost(Path(temporary), state)
            report = runner.scan(host, 'scan', config, state, 'full')
            self.assertTrue(report['passed'])
            self.assertEqual(report['source_sha256'], hashlib.sha256(host.source).hexdigest())
            for mode in report['modes']:
                self.assertTrue(mode['passed'])
                self.assertTrue(mode['full_query_coverage'])
                self.assertEqual(mode['query_count'], 4097)
                self.assertEqual([window['count'] for window in mode['windows']], [3072, 1025])
                self.assertEqual(mode['windows'][-1]['padding_cells'], 7)
                self.assertTrue(all(window['checked_pixels'] == window['checked_cells'] * 9
                                    for window in mode['windows']))
            self.assertEqual(report['modes'][0]['observed_sha256'], report['source_sha256'])
            self.assertGreater(report['modes'][1]['cross_leaf_queries'], 0)
            self.assertEqual(len(host.calls), 5)
            self.assertTrue(all('.write(' not in code and '.finish(' not in code
                                for unused, code in host.calls))

    def test_failed_patch_retains_pixel_evidence_and_a_failed_verification(self):
        config = tree_config(96, namespace='scan_alpha')
        state = receipt(config)
        with tempfile.TemporaryDirectory() as temporary:
            host = SyntheticScanHost(Path(temporary), state, corrupt_alpha=True)
            with self.assertRaisesRegex(ValueError, 'byte comparison failed'):
                runner.scan(host, 'bad', config, state, 'full')
            report = json.loads((host.evidence / 'bad_m1_w000.verify.json').read_text(encoding='utf-8'))
            self.assertFalse(report['passed'])
            self.assertEqual(report['failed_cells'], 1)
            self.assertTrue((host.evidence / 'bad_m1_w000.png').is_file())

    def test_source_change_between_windows_is_rejected_before_the_next_capture(self):
        config = tree_config(4097, namespace='scan_generation')
        state = receipt(config)
        with tempfile.TemporaryDirectory() as temporary:
            host = SyntheticScanHost(Path(temporary), state, change_words=True)
            with self.assertRaisesRegex(ValueError, 'Frozen payload changed'):
                runner.scan(host, 'changed', config, state, 'full')
            self.assertTrue((host.evidence / 'changed_m1_w000.png').is_file())
            self.assertFalse((host.evidence / 'changed_m1_w001.png').exists())


if __name__ == '__main__':
    unittest.main()
