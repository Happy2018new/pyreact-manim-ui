"""Offline bounded serial-dimension orchestration and guaranteed cleanup tests."""
import copy
import importlib.util
from pathlib import Path
import types
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('repeated_dimension_runner_under_test', HERE/'runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def resident(serial=0):
    return {'state': 'resident', 'ready': True, 'error': None, 'generation': 1,
        'logical_bytes': 65536, 'native_attempt_count': 3, 'clear_page': 'clear',
        'identity': {'host_sha256': 'a'*64, 'adler32': 4010454780, 'byte_count': 65536},
        'native_page_names': ['clear', 'bit64', 'bit128'], 'pipeline_ready': True,
        'pipeline_links': [[0], [1], [2]],
        'dimension_recovery': {'phase': 'idle' if serial == 0 else 'ready',
                               'serial': serial, 'ready_serial': serial, 'pair': None}}


def snapshot(experiment):
    return {'dimension': experiment.dimension, 'probe': copy.deepcopy(experiment.state),
        'camera': [8., 72., 5.], 'anchor': [8., 71.58, 7.97],
        'effect_positions': [[8., 71.44, 8.96]]*3,
        'player_position': [8., 71.62, 8.]}


def experiment():
    return types.SimpleNamespace(args=types.SimpleNamespace(nether_natural=True),
        pose_receipt={'prepared_dimensions': [0]}, variant='carrier',
        viewport=[720, 1080], roi=[8, 128, 512, 512], payload=bytes(65536),
        dimension=0, state=resident(), initialize=mock.Mock(),
        call=mock.Mock(return_value='owned-player'))


class PlanTests(unittest.TestCase):
    def test_default_plan_contains_two_nether_trips_then_end_within_transition_budget(self):
        result = runner.plan()
        self.assertEqual([1, 1, 2], [item['dimension'] for item in result])
        self.assertEqual(['nether_1', 'nether_2', 'end_1'], [item['name'] for item in result])
        self.assertEqual(6, 2*len(result))
        self.assertLessEqual(2*len(result), 8)

    def test_reduced_plan_is_explicit_and_invalid_plans_fail_before_initialization(self):
        self.assertEqual([1], [item['dimension'] for item in runner.plan(1, False)])
        for count, end in ((0, True), (3, True), (True, True), (2, 1), (2, None)):
            with self.subTest(count=count, end=end):
                owned = experiment()
                with self.assertRaises(ValueError):
                    runner.run(owned, None, count, end)
                owned.initialize.assert_not_called()


class RepeatedRunTests(unittest.TestCase):
    def test_same_resident_payload_runs_six_transitions_without_reinitialization(self):
        owned, progress, events, frozen_ids = experiment(), {}, [], []

        def transit(exp, label, target, player, frozen, original, record):
            events.append(target)
            frozen_ids.append((id(frozen), copy.deepcopy(frozen)))
            self.assertEqual('owned-player', player)
            record.update(request_intent=True, pixel_verified=True)
            exp.dimension = target
            exp.state['dimension_recovery']['serial'] += 1

        with mock.patch.object(runner.positive, 'current', side_effect=lambda exp, label: snapshot(exp)), \
                mock.patch.object(runner.positive, 'transit', side_effect=transit) as transport, \
                mock.patch.object(runner.positive.candidate, 'arm') as arm, \
                mock.patch.object(runner.positive.candidate, 'raw_readback', return_value={'exact': True}) as capture, \
                mock.patch.object(runner.positive, 'restore', side_effect=lambda exp: events.append('restore') or {'all_exact': True}) as restore:
            result = runner.run(owned, None, progress=progress)
        self.assertEqual([1, 0, 1, 0, 2, 0, 'restore'], events)
        owned.initialize.assert_called_once_with()
        owned.call.assert_called_once_with('roundtrip_player', expression='api.GetLocalPlayerId()')
        arm.assert_called_once_with(owned, 'roundtrip_initial_arm')
        capture.assert_called_once()
        restore.assert_called_once_with(owned)
        self.assertEqual(6, transport.call_count)
        self.assertEqual(1, len({item[0] for item in frozen_ids}))
        self.assertTrue(all(item[1] == progress['frozen_static_identity'] for item in frozen_ids))
        self.assertTrue(result['pixel_verified'])
        self.assertTrue(result['end_attempted'])
        self.assertTrue(result['end_pixel_verified'])
        self.assertEqual(1, result['resident_payload_uploads'])
        self.assertFalse(result['continuous_updates_tested'])

    def test_each_outbound_failure_returns_restores_and_stops_later_trips(self):
        for failed_outbound in (1, 2, 3):
            with self.subTest(failed_outbound=failed_outbound):
                owned, progress, events = experiment(), {}, []
                outbound_count = [0]

                def transit(exp, label, target, player, frozen, original, record):
                    events.append(target)
                    exp.dimension = target
                    record['request_intent'] = True
                    if target:
                        outbound_count[0] += 1
                        if outbound_count[0] == failed_outbound:
                            raise RuntimeError('saved automatic pixels failed')
                    record['pixel_verified'] = True

                with mock.patch.object(runner.positive, 'current', side_effect=lambda exp, label: snapshot(exp)), \
                        mock.patch.object(runner.positive, 'transit', side_effect=transit), \
                        mock.patch.object(runner.positive.candidate, 'arm'), \
                        mock.patch.object(runner.positive.candidate, 'raw_readback', return_value={'exact': True}), \
                        mock.patch.object(runner.positive, 'restore', side_effect=lambda exp: events.append('restore') or {'all_exact': True}):
                    with self.assertRaisesRegex(RuntimeError, 'Bounded repeated dimension trip failed'):
                        runner.run(owned, None, progress=progress)
                expected = [value for target in [1, 1, 2][:failed_outbound] for value in (target, 0)]
                self.assertEqual(expected+['restore'], events)
                self.assertEqual(failed_outbound, len(progress['trips']))
                self.assertIn('saved automatic pixels failed', progress['trips'][-1]['outbound_failure'])
                self.assertTrue(progress['cleanup']['all_exact'])
                self.assertFalse(progress['pixel_verified'])
                self.assertEqual(failed_outbound == 3, progress['end_attempted'])
                self.assertFalse(progress['end_pixel_verified'])

    def test_return_failure_restores_and_does_not_start_next_trip(self):
        owned, progress, events = experiment(), {}, []

        def transit(exp, label, target, player, frozen, original, record):
            events.append(target)
            exp.dimension = target
            record['request_intent'] = True
            if target == 0:
                raise RuntimeError('return readback failed')
            record['pixel_verified'] = True

        with mock.patch.object(runner.positive, 'current', side_effect=lambda exp, label: snapshot(exp)), \
                mock.patch.object(runner.positive, 'transit', side_effect=transit), \
                mock.patch.object(runner.positive.candidate, 'arm'), \
                mock.patch.object(runner.positive.candidate, 'raw_readback', return_value={'exact': True}), \
                mock.patch.object(runner.positive, 'restore', side_effect=lambda exp: events.append('restore') or {'all_exact': True}):
            with self.assertRaisesRegex(RuntimeError, 'trip failed'):
                runner.run(owned, None, progress=progress)
        self.assertEqual([1, 0, 'restore'], events)
        self.assertIn('return readback failed', progress['trips'][0]['return_failure'])
        self.assertFalse(progress['end_attempted'])

    def test_broken_return_inspection_still_attempts_owned_return_when_requested(self):
        owned = experiment()
        row = {'name': 'end_1', 'outbound': {'request_intent': True}, 'return': {}, 'return_failure': None}
        with mock.patch.object(runner.positive, 'current', side_effect=TypeError('stale effect')), \
                mock.patch.object(runner.positive, 'transit') as transit:
            runner.return_to_overworld(owned, None, 'player', {'frozen': True}, row)
        transit.assert_called_once_with(owned, 'roundtrip_end_1_overworld', 0, 'player',
                                        {'frozen': True}, None, row['return'])
        self.assertIn('stale effect', row['return_decision_failure'])

    def test_no_observed_departure_cannot_claim_return_success(self):
        owned = experiment()
        row = {'name': 'nether_1', 'outbound': {}, 'return': {}, 'return_failure': None}
        with mock.patch.object(runner.positive, 'current', return_value={'dimension': 0}), \
                mock.patch.object(runner.positive, 'transit') as transit:
            runner.return_to_overworld(owned, None, 'player', {}, row)
        transit.assert_not_called()
        self.assertIn('unverified', row['return_failure'])

    def test_preexisting_transition_serial_is_rejected_and_rooms_are_restored(self):
        owned, progress = experiment(), {}
        owned.state = resident(1)
        with mock.patch.object(runner.positive, 'current', return_value=snapshot(owned)), \
                mock.patch.object(runner.positive, 'transit') as transit, \
                mock.patch.object(runner.positive, 'restore', return_value={'all_exact': True}) as restore:
            with self.assertRaisesRegex(RuntimeError, 'fresh 64 KiB Overworld'):
                runner.run(owned, None, progress=progress)
        transit.assert_not_called()
        restore.assert_called_once_with(owned)
        self.assertFalse(progress['pixel_verified'])

    def test_initialization_failure_preserves_first_error_and_cleanup_failure(self):
        owned, progress = experiment(), {}
        owned.initialize.side_effect = RuntimeError('initial setup failed')
        with mock.patch.object(runner.positive, 'restore', side_effect=RuntimeError('restore failed')) as restore:
            with self.assertRaisesRegex(RuntimeError, 'initial setup failed'):
                runner.run(owned, None, progress=progress)
        restore.assert_called_once_with(owned)
        self.assertIn('restore failed', progress['cleanup_failure'])
        self.assertEqual([], progress['trips'])
        self.assertFalse(progress['pixel_verified'])

    def test_non_natural_mode_is_rejected_before_initialization(self):
        owned = experiment()
        owned.args.nether_natural = False
        with self.assertRaisesRegex(ValueError, 'Overworld-only foothold'):
            runner.run(owned, None)
        owned.initialize.assert_not_called()


if __name__ == '__main__':
    unittest.main()
