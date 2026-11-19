"""Offline target-only scheduling, passive failure observation and terrain reads."""
import copy
import importlib.util
import json
from pathlib import Path
import types
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


runner = load('isolated_target_runner_under_test', HERE/'runner.py')
fixture = load('isolated_target_offline_shared_fixtures', runner.ROUNDTRIP/'test_runner.py')


def ready(target=2, serial=1):
    owned = fixture.experiment()
    owned.dimension = target
    result = fixture.snapshot(owned)
    result['probe'].update(mode='all', consumer_mode=1, diagnostic_output_y=128,
                           pipeline_enabled=True, shape_enabled=False)
    result['probe']['dimension_recovery'].update(phase='ready', serial=serial,
                                                ready_serial=serial, pair=[0, target])
    return result


class TerrainTests(unittest.TestCase):
    def test_actual_terrain_source_floors_deduplicates_and_reads_only_loaded_blocks(self):
        reads = []
        positions = {'camera': (-.2, 72.1, 5.9), 'anchor': (.2, 71.8, 7.2),
                     'effect_0': (.2, 71.8, 7.2), 'effect_1': (.2, 71.8, 7.2),
                     'effect_2': (.2, 71.8, 7.2)}
        block = types.SimpleNamespace(GetBlock=lambda pos: reads.append(pos) or (None if pos[0] == -2 else ('minecraft:stone', 0)))
        factory = types.SimpleNamespace(CreateBlockInfo=lambda level: block,
            CreateFrameAniTrans=lambda index: types.SimpleNamespace(GetPos=lambda: positions['effect_%d'%index]))
        probe = types.SimpleNamespace(factory=factory, game=types.SimpleNamespace(GetCurrentDimension=lambda: 2),
            camera=types.SimpleNamespace(GetPosition=lambda: positions['camera']),
            anchor=positions['anchor'], effects=[0, 1, 2], render_event=100)
        context = {'probe': probe, 'api': types.SimpleNamespace(GetLevelId=lambda: 'level'), 'json': json}
        # Mirror Experiment.call's appended expression result rather than only
        # executing the source body, which would miss a transport overwrite.
        code = runner.terrain_source()+"\n_result=json.dumps(terrain_result)\n"
        exec(compile(code, '<offline-terrain>', 'exec'), context)
        result = json.loads(context['_result'])
        expected = {(cx+dx, cy+dy, cz+dz) for cx, cy, cz in ((-1, 72, 5), (0, 71, 7))
                    for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)}
        self.assertEqual(expected, set(reads))
        self.assertEqual(len(reads), len(set(reads)))
        self.assertEqual([-1, 72, 5], result['centers'][0]['floor'])
        self.assertEqual(5, len(result['centers']))
        self.assertTrue(result['read_only'])
        self.assertTrue(result['loaded_terrain_only'])
        self.assertEqual(2, result['dimension_before'])
        self.assertEqual(2, result['dimension_after'])
        self.assertTrue(any(row['block'] is None for row in result['samples']))

    def test_supplemental_terrain_error_is_recorded_without_replacing_pixel_failure(self):
        owned = types.SimpleNamespace(call=mock.Mock(side_effect=RuntimeError('terrain unavailable')))
        record = {'automatic_readback': {'exact': False}}
        runner.terrain_after_capture(owned, 'end', record)
        self.assertEqual('terrain_result', owned.call.call_args.kwargs['expression'])
        self.assertIn('terrain unavailable', record['terrain_read_failure'])
        self.assertFalse(record['automatic_readback']['exact'])


class TransitTests(unittest.TestCase):
    def setup_transit(self):
        owned = fixture.experiment()
        owned.reports = []
        owned.data_checks = mock.Mock(return_value=[{'exact': True}, {'exact': True}])
        owned.server = mock.Mock(side_effect=[{'accepted': True}, {'dimension': 2, 'position': [8., 71.62, 8.]}])
        return owned, fixture.snapshot(owned), ready()

    def test_ready_capture_precedes_terrain_admission_and_any_standard_rearm(self):
        owned, before, after = self.setup_transit()
        events = []

        def capture(exp, label, original):
            events.append('capture')
            report = {'label': label, 'exact': True}
            exp.reports.append(report)
            return report

        owned.data_checks.side_effect = lambda label: events.append('checks') or [{'exact': True}]
        with mock.patch.object(runner.positive, 'current', side_effect=[before, after]), \
                mock.patch.object(runner.positive.candidate, 'arm', side_effect=lambda *args: events.append('arm')), \
                mock.patch.object(runner.positive.candidate, 'raw_readback', side_effect=capture), \
                mock.patch.object(runner, 'terrain_after_capture', side_effect=lambda *args: events.append('terrain')), \
                mock.patch.object(runner.time, 'sleep'):
            result = runner.transit(owned, 'target_end_1', 2, 'player', runner.positive.static_identity(before['probe']), None, {})
        self.assertEqual(['arm', 'capture', 'terrain', 'checks'], events)
        self.assertTrue(result['pixel_verified'])
        self.assertTrue(result['admitted_position']['verified'])
        self.assertIn('ChangePlayerDimension(2,', owned.server.call_args_list[0].args[1])

    def test_failed_automatic_report_is_preserved_and_no_standard_controls_run(self):
        owned, before, after = self.setup_transit()
        record, events = {}, []

        def capture(exp, label, original):
            events.append('capture')
            exp.reports.append({'label': label, 'exact': False, 'data_error_pixels': 12})
            raise RuntimeError('first automatic pixel failure')

        with mock.patch.object(runner.positive, 'current', side_effect=[before, after]), \
                mock.patch.object(runner.positive.candidate, 'arm'), \
                mock.patch.object(runner.positive.candidate, 'raw_readback', side_effect=capture), \
                mock.patch.object(runner, 'terrain_after_capture', side_effect=lambda *args: events.append('terrain')), \
                mock.patch.object(runner.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'first automatic pixel failure'):
                runner.transit(owned, 'target_end_1', 2, 'player', runner.positive.static_identity(before['probe']), None, record)
        self.assertEqual(['capture', 'terrain'], events)
        self.assertFalse(record['automatic_readback']['exact'])
        self.assertEqual(12, record['automatic_readback']['data_error_pixels'])
        self.assertTrue(record['admitted_position']['verified'])
        owned.data_checks.assert_not_called()

    def test_capture_without_saved_report_does_not_read_terrain(self):
        owned, before, after = self.setup_transit()
        with mock.patch.object(runner.positive, 'current', side_effect=[before, after]), \
                mock.patch.object(runner.positive.candidate, 'arm'), \
                mock.patch.object(runner.positive.candidate, 'raw_readback', side_effect=RuntimeError('capture transport failed')), \
                mock.patch.object(runner, 'terrain_after_capture') as terrain, \
                mock.patch.object(runner.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'capture transport failed'):
                runner.transit(owned, 'target_end_1', 2, 'player', runner.positive.static_identity(before['probe']), None, {})
        terrain.assert_not_called()
        owned.data_checks.assert_not_called()


class PassiveTests(unittest.TestCase):
    def record(self):
        value = ready()
        return {'automatic_readback': {'exact': False}, 'last_state': value,
                'expected_serial': 1, 'before': {'dimension': 0}}

    def test_three_delayed_followups_are_read_only_and_preserve_first_failed_report(self):
        owned, record = fixture.experiment(), self.record()
        owned.reports = []
        owned.server, owned.call, owned.data_checks = mock.Mock(), mock.Mock(), mock.Mock()
        frozen = runner.positive.static_identity(record['last_state']['probe'])

        def capture(exp, label, original):
            report = {'label': label, 'exact': True}
            exp.reports.append(report)
            return report

        with mock.patch.object(runner.positive, 'current', return_value=ready()) as current, \
                mock.patch.object(runner.positive.candidate, 'raw_readback', side_effect=capture) as captures, \
                mock.patch.object(runner.positive.candidate, 'arm') as arm, \
                mock.patch.object(runner.time, 'sleep') as sleep:
            rows = runner.observe_failure(owned, None, 'target_end_1', 2, frozen, record, 3)
        self.assertEqual([.6, 1.2, 2.4], [call.args[0] for call in sleep.call_args_list])
        self.assertEqual(3, current.call_count)
        self.assertEqual(3, captures.call_count)
        self.assertTrue(all(row['readback']['exact'] for row in rows))
        self.assertTrue(all(row['runtime_mutation_performed'] is False for row in rows))
        self.assertFalse(record['automatic_readback']['exact'])
        arm.assert_not_called()
        owned.call.assert_not_called()
        owned.server.assert_not_called()
        owned.data_checks.assert_not_called()

    def test_stale_followup_state_stops_before_capture_without_rearm(self):
        record, owned = self.record(), fixture.experiment()
        owned.reports = []
        frozen = runner.positive.static_identity(record['last_state']['probe'])
        with mock.patch.object(runner.positive, 'current', return_value=ready(serial=2)), \
                mock.patch.object(runner.positive.candidate, 'raw_readback') as capture, \
                mock.patch.object(runner.positive.candidate, 'arm') as arm, \
                mock.patch.object(runner.time, 'sleep'):
            rows = runner.observe_failure(owned, None, 'end', 2, frozen, record, 3)
        self.assertEqual(1, len(rows))
        self.assertIsNotNone(rows[0]['failure'])
        capture.assert_not_called()
        arm.assert_not_called()

    def test_missing_failed_report_or_disabled_followups_cannot_observe(self):
        owned = fixture.experiment()
        for report, count in ((None, 3), ({'exact': True}, 3), ({'exact': False}, 0)):
            with self.subTest(report=report, count=count):
                record = dict(self.record(), automatic_readback=report)
                with mock.patch.object(runner.positive, 'current') as current, \
                        mock.patch.object(runner.positive.candidate, 'raw_readback') as capture:
                    self.assertEqual([], runner.observe_failure(owned, None, 'end', 2, {}, record, count))
                current.assert_not_called()
                capture.assert_not_called()

    def test_passive_gate_rejects_any_changed_automatic_output_control(self):
        base = ready()
        frozen = runner.positive.static_identity(base['probe'])
        for key, value in (('mode', 'off'), ('consumer_mode', 3), ('diagnostic_output_y', 650),
                            ('pipeline_enabled', False), ('shape_enabled', True)):
            with self.subTest(key=key):
                changed = copy.deepcopy(base)
                changed['probe'][key] = value
                with self.assertRaises(RuntimeError):
                    runner.passive_gate(changed, frozen, 1, [0, 2])


class RunTests(unittest.TestCase):
    def run_case(self, target=2, failed=False):
        owned, progress, events = fixture.experiment(), {}, []
        owned.reports = []

        def transit(exp, label, destination, player, frozen, original, record):
            events.append(destination)
            exp.dimension = destination
            record.update(request_intent=True, pixel_verified=not failed)
            if failed:
                record['automatic_readback'] = {'exact': False}
                raise RuntimeError('first exact image failed')

        def return_home(exp, original, player, frozen, row):
            events.append(0)
            exp.dimension = 0
            row['return']['pixel_verified'] = True

        def observe(exp, original, label, destination, frozen, record, followups):
            events.append('observe')
            record['passive_followups'] = [{'readback': {'exact': True}}]*3

        with mock.patch.object(runner.positive, 'current', side_effect=lambda exp, label: fixture.snapshot(exp)), \
                mock.patch.object(runner, 'transit', side_effect=transit), \
                mock.patch.object(runner, 'observe_failure', side_effect=observe), \
                mock.patch.object(runner.roundtrip, 'return_to_overworld', side_effect=return_home), \
                mock.patch.object(runner.positive.candidate, 'arm'), \
                mock.patch.object(runner.positive.candidate, 'raw_readback', return_value={'exact': True}), \
                mock.patch.object(runner.positive, 'restore', side_effect=lambda exp: events.append('restore') or {'all_exact': True}):
            if failed:
                with self.assertRaisesRegex(RuntimeError, 'Isolated dimension trip failed'):
                    runner.run(owned, None, target=target, progress=progress)
            else:
                runner.run(owned, None, target=target, progress=progress)
        return owned, progress, events

    def test_default_end_is_not_short_circuited_by_a_nether_trip(self):
        owned, progress, events = self.run_case()
        self.assertEqual([2, 0, 'restore'], events)
        self.assertEqual([0, 2, 0], progress['planned_dimensions'])
        self.assertTrue(progress['end_pixel_verified'])
        self.assertTrue(progress['pixel_verified'])
        self.assertEqual(1, progress['resident_payload_uploads'])
        owned.initialize.assert_called_once_with()

    def test_optional_nether_does_one_nether_roundtrip_only(self):
        owned, progress, events = self.run_case(target=1)
        self.assertEqual([1, 0, 'restore'], events)
        self.assertFalse(progress['end_attempted'])
        self.assertFalse(progress['end_pixel_verified'])
        self.assertTrue(progress['pixel_verified'])

    def test_later_passive_success_never_promotes_first_automatic_failure(self):
        owned, progress, events = self.run_case(failed=True)
        self.assertEqual([2, 'observe', 0, 'restore'], events)
        self.assertIn('first exact image failed', progress['trips'][0]['outbound_failure'])
        self.assertTrue(all(row['readback']['exact'] for row in progress['trips'][0]['outbound']['passive_followups']))
        self.assertFalse(progress['pixel_verified'])
        self.assertFalse(progress['end_pixel_verified'])
        self.assertTrue(progress['cleanup']['all_exact'])

    def test_plan_rejects_invalid_target_or_followup_budget_before_initialization(self):
        for target, followups in ((0, 3), (True, 3), (2, 1), (2, True), (2, 4)):
            with self.subTest(target=target, followups=followups):
                owned = fixture.experiment()
                with self.assertRaises(ValueError):
                    runner.run(owned, None, target, followups)
                owned.initialize.assert_not_called()

    def test_initialization_failure_preserves_first_and_cleanup_errors(self):
        owned, progress = fixture.experiment(), {}
        owned.initialize.side_effect = RuntimeError('setup failed')
        with mock.patch.object(runner.positive, 'restore', side_effect=RuntimeError('cleanup failed')):
            with self.assertRaisesRegex(RuntimeError, 'setup failed'):
                runner.run(owned, None, progress=progress)
        self.assertEqual(0, progress['resident_payload_uploads'])
        self.assertIn('cleanup failed', progress['cleanup_failure'])
        self.assertFalse(progress['pixel_verified'])


if __name__ == '__main__':
    unittest.main()
