"""SDK-double checks for isolated atlas setup; no Minecraft operations."""
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def isolated_config(payload=49):
    pages = (payload+23)//24
    producers = ['isolated_page_%d' % page for page in range(pages)]
    save, display = 'isolated_save', 'isolated_display'
    names = [save] + producers + [display]
    connections = [[producers[index-1], 0, producers[index], 0, 3]
                   for index in range(1, pages)]
    connections.extend([[producers[-1], 0, display, 0, 3], [save, 0, display, 0, 4]])
    return {'transport': 'isolated_atlas', 'pages': pages, 'payload_bytes': payload,
            'saved_scene_name': save, 'producer_names': producers, 'display_name': display,
            # Deliberately enabled inputs must still be registered disabled.
            'processes': [{'name': name, 'enable': True} for name in names],
            'connections': connections, 'query': [0., 0., float(min(payload, 3072)), 7.],
            'page_uniforms': [[float(page), float(pages), 2., 2.] for page in range(pages)],
            'display_layout': [2., 2., float(payload), 0.],
            'layout': {'columns': 2, 'rows': 2}, 'words_per_page': 8,
            'display_rect_norm': [.05, .05, .9, .9],
            'screen_size': [720, 1080], 'target_pixels': [64, 8]}


class IsolatedRuntimeTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            '_isolated_runtime_harness', ROOT / 'tests/test_runtime_packet_runtime.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.harness = module.RuntimePacketRuntimeTests()
        self.harness.setUp()
        self.addCleanup(self.harness.doCleanups)
        self.module = self.harness.load_module(
            '_runtime_packet_behavior_test.isolated_runtime', 'isolated_runtime.py')
        self.module.time = self.harness.clock
        self.post = self.harness.post
        self.events = []
        for method in ('GetPostProcessOrder', 'AddPostProcess', 'SetEnableByName',
                       'SetParameter', 'PostPassResultToOtherPass'):
            original = getattr(self.post, method)

            def tracked(*args, _method=method, _original=original):
                self.events.append((_method, args))
                return _original(*args)

            setattr(self.post, method, tracked)
        self.config = isolated_config()

    def probe(self):
        return self.module.IsolatedProbe(self.post, self.config, 12345)

    def cleanup_order(self):
        return self.config['producer_names'] + [self.config['display_name'], self.config['saved_scene_name']]

    def test_registration_stays_disabled_and_finish_connects_before_enabling(self):
        probe = self.probe()
        self.assertFalse(probe.ready)
        self.assertFalse(probe.enabled)
        self.assertTrue(all(not value for value in self.post.enabled.values()))
        added = [args[0] for method, args in self.events if method == 'AddPostProcess']
        self.assertTrue(all(definition['enable'] is False for definition in added))
        self.assertTrue(all(definition['enable'] for definition in self.config['processes']))
        self.assertEqual(self.post.enable_calls, [(name, False) for name in self.cleanup_order()])
        self.events.clear()
        state = probe.finish()
        enable_index = next(index for index, event in enumerate(self.events)
                            if event[0] == 'SetEnableByName' and event[1][1])
        before, after = self.events[:enable_index], self.events[enable_index:]
        self.assertEqual([args for method, args in before if method == 'PostPassResultToOtherPass'],
                         [tuple(connection) for connection in self.config['connections']])
        self.assertEqual(before[-1][0], 'GetPostProcessOrder')
        self.assertTrue(all(method == 'SetEnableByName' and args[1] for method, args in after))
        self.assertEqual([args[0] for method, args in after],
                         [self.config['saved_scene_name'], self.config['display_name']] +
                         self.config['producer_names'])
        for name, values in zip(self.config['producer_names'], self.config['page_uniforms']):
            self.assertEqual(self.post.parameters[(name, 'page')], values)
        for key, values in (('query', self.config['query']),
                            ('display_rect', self.config['display_rect_norm']),
                            ('atlas_layout', self.config['display_layout'])):
            self.assertEqual(self.post.parameters[(self.config['display_name'], key)], values)
        self.assertTrue(state['ready'])
        self.assertTrue(state['enabled'])
        self.assertEqual(state['connections'], [True]*len(self.config['connections']))
        self.assertEqual(state['aggregate']['layout'], self.config['layout'])
        self.assertEqual(state['aggregate']['words_per_page'], 8)
        self.assertEqual(state['payload_bytes'], 49)
        self.assertEqual(state['screen_size'], [720, 1080])
        self.assertEqual(state['source'], 'in_game_python')
        self.assertFalse(state['gpu_verified'])

    def test_repeated_write_uses_full_pages_and_only_two_payload_vec4_calls_each(self):
        self.config = isolated_config(65537)
        probe = self.probe()
        probe.finish()
        self.post.parameter_calls.clear()
        timings = probe.write(54321)
        pages = self.config['pages']
        values = self.harness.runtime.dataset(54321, (pages*8+2)//3)
        flat = [value for row in values for value in row][:pages*8]
        self.assertEqual([word for page in probe.words for word in page], flat)
        self.assertEqual(len(self.post.parameter_calls), pages*2)
        self.assertTrue(all(key in ('packet0', 'packet1') and len(value) == 4
                            for name, key, value in self.post.parameter_calls))
        self.assertEqual(len(timings), 2)
        self.assertTrue(all(value >= 0 for value in timings))

    def test_select_accepts_tail_window_and_all_three_modes(self):
        probe = self.probe()
        for mode in (0, 1, 2):
            probe.select(mode=mode, start=48, count=3072, salt=-3)
            self.assertEqual(probe.snapshot()['aggregate']['query'], [float(mode), 48., 3072., -3.])
        probe.select()
        self.assertEqual(probe.query, [0., 0., 49., 7.])

    def test_invalid_query_does_not_touch_engine(self):
        probe = self.probe()
        for query in ({'mode': 3}, {'mode': True}, {'start': -1}, {'start': 49},
                      {'start': .5}, {'count': 0}, {'count': 3073},
                      {'salt': float('nan')}, {'salt': float('inf')}, {'salt': '7'}):
            with self.subTest(query=query):
                before = list(self.post.parameter_calls)
                with self.assertRaises(ValueError):
                    probe.select(**query)
                self.assertEqual(self.post.parameter_calls, before)

    def test_parameter_connection_and_order_failures_never_enable_and_cleanup_in_order(self):
        probe = self.probe()
        for failure in ('parameter', 'connection', 'order', 'missing'):
            with self.subTest(failure=failure):
                self.post.fail_parameter.clear()
                self.post.fail_connection = False
                self.post.present = list(probe.names)
                self.post.enable_calls.clear()
                if failure == 'parameter':
                    self.post.fail_parameter[(self.config['display_name'], 'atlas_layout')] = True
                elif failure == 'connection':
                    self.post.fail_connection = True
                elif failure == 'order':
                    self.post.present.reverse()
                else:
                    self.post.present.remove(self.config['saved_scene_name'])
                with self.assertRaises(RuntimeError):
                    probe.finish()
                self.assertFalse(probe.ready)
                self.assertFalse(probe.enabled)
                self.assertIsNotNone(probe.error)
                self.assertEqual(self.post.enable_calls, [(name, False) for name in self.cleanup_order()])

    def test_existing_processes_are_disabled_without_replacing_their_definitions(self):
        self.post.present = [process['name'] for process in self.config['processes']]
        self.post.enabled = dict((name, True) for name in self.post.present)
        probe = self.probe()
        self.assertEqual(self.post.add_calls, [])
        self.assertEqual(self.post.enable_calls, [(name, False) for name in self.cleanup_order()])
        self.assertTrue(all(not value for value in self.post.enabled.values()))
        probe.finish()
        probe.set_enabled(False)
        self.assertTrue(probe.ready)
        self.assertFalse(probe.enabled)
        self.post.enable_calls.clear()
        probe.set_enabled(True)
        self.assertEqual(self.post.enable_calls,
                         [(name, True) for name in [self.config['saved_scene_name'],
                          self.config['display_name']] + self.config['producer_names']])

    def test_query_upload_rejection_cleans_up_active_passes(self):
        probe = self.probe()
        probe.finish()
        previous = list(probe.query)
        self.post.fail_parameter[(self.config['display_name'], 'query')] = True
        self.post.enable_calls.clear()
        with self.assertRaisesRegex(RuntimeError, 'query rejected'):
            probe.select(mode=2, start=1, count=12)
        self.assertEqual(probe.query, previous)
        self.assertFalse(probe.ready)
        self.assertFalse(probe.enabled)
        self.assertEqual(self.post.enable_calls, [(name, False) for name in self.cleanup_order()])

    def test_invalid_configuration_fails_before_any_sdk_side_effect(self):
        for field, value in (('pages', 2), ('words_per_page', 7),
                             ('producer_names', ['duplicate']*3),
                             ('connections', [[self.config['display_name'], 0,
                                               self.config['saved_scene_name'], 0, 3]])):
            with self.subTest(field=field):
                config = dict(self.config)
                config[field] = value
                before = list(self.events)
                with self.assertRaises(ValueError):
                    self.module.IsolatedProbe(self.post, config, 12345)
                self.assertEqual(self.events, before)

    def test_disable_keeps_all_failures_and_attempts_every_owned_name(self):
        probe = self.probe()
        probe.finish()
        producers = self.config['producer_names']
        self.post.fail_enable[(producers[0], False)] = True
        self.post.fail_enable[(self.config['display_name'], False)] = RuntimeError('consumer stuck')
        self.post.enable_calls.clear()
        with self.assertRaisesRegex(RuntimeError, 'consumer stuck'):
            probe.set_enabled(False)
        self.assertEqual(self.post.enable_calls, [(name, False) for name in self.cleanup_order()])
        self.assertFalse(probe.ready)
        self.assertIsNone(probe.enabled)
        self.assertEqual(len(probe.cleanup_errors), 2)
        self.assertIn(producers[0], probe.cleanup_errors[0])
        self.assertIn(self.config['display_name'], probe.cleanup_errors[1])

    def test_registration_failure_owns_failed_name_and_cleans_it(self):
        failed = self.config['producer_names'][1]
        self.post.fail_add[failed] = RuntimeError('partial registration')
        with self.assertRaisesRegex(RuntimeError, 'partial registration') as caught:
            self.probe()
        probe = caught.exception.aggregate_probe
        owned = [self.config['saved_scene_name']] + self.config['producer_names'][:2]
        self.assertEqual(probe.names, owned)
        self.assertEqual(self.post.enable_calls,
                         [(name, False) for name in self.config['producer_names'][:2] +
                          [self.config['saved_scene_name']]])
        self.assertTrue(all(not self.post.enabled[name] for name in owned))

    def test_enable_failure_and_payload_failure_disable_every_pass(self):
        probe = self.probe()
        self.post.fail_enable[(self.config['producer_names'][1], True)] = True
        with self.assertRaises(RuntimeError):
            probe.finish()
        self.assertEqual(self.post.enable_calls[-len(probe.names):],
                         [(name, False) for name in self.cleanup_order()])
        self.post.fail_enable.clear()
        probe.finish()
        self.post.fail_parameter[(self.config['producer_names'][1], 'packet1')] = True
        with self.assertRaises(RuntimeError):
            probe.write(87654)
        self.assertFalse(probe.ready)
        self.assertFalse(probe.enabled)
        self.assertEqual(self.post.enable_calls[-len(probe.names):],
                         [(name, False) for name in self.cleanup_order()])


if __name__ == '__main__':
    unittest.main()
