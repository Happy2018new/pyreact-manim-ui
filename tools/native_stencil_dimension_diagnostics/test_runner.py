"""Offline positive-pose rooms, passive acceptance ordering and cleanup tests."""
import copy
import importlib.util
import json
from pathlib import Path
import types
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('positive_diagnostic_runner_under_test', HERE/'runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
pose = runner.pose


class World:
    """SDK replacement: writes succeed but return False, requiring readback."""

    def __init__(self):
        self.blocks = {(dim, (x, y, z)): {'name': 'minecraft:dirt', 'aux': (x+y+z+dim) % 4}
                       for dim in (0, 1) for x in range(pose.MINIMUM[0], pose.MAXIMUM[0]+1)
                       for y in range(pose.MINIMUM[1], pose.MAXIMUM[1]+1)
                       for z in range(pose.MINIMUM[2], pose.MAXIMUM[2]+1)}
        self.original = copy.deepcopy(self.blocks)
        self.writes, self.requests, self.pending = [], [], []
        self.read_count, self.read_dimensions = 0, []
        self.before_write = None
        self.bad_write = None
        self.callbacks, self.chunk_checks = [], []
        self.defer_visibility, self.deferred = False, {}
        self.reject_writes = {}
        self.borrowed_results, self.shared_result = False, {}

    def GetBlockNew(self, position, dimension):
        self.read_count += 1
        self.read_dimensions.append(dimension)
        value = self.blocks.get((dimension, tuple(position)))
        if self.borrowed_results and value is not None:
            self.shared_result.clear()
            self.shared_result.update(value)
            return self.shared_result
        return copy.deepcopy(value)

    def SetBlockNew(self, position, block, mode, dimension, legacy, notify):
        key = (dimension, tuple(position))
        if self.before_write is not None:
            self.before_write(key, block, legacy)
        self.writes.append((key, copy.deepcopy(block), mode, legacy, notify))
        if self.reject_writes.get(key, 0):
            self.reject_writes[key] -= 1
            return False
        values = self.deferred if self.defer_visibility else self.blocks
        values[key] = copy.deepcopy(block)
        if key == self.bad_write:
            values[key] = {'name': 'minecraft:unexpected', 'aux': 9}
        return False

    def DoTaskOnChunkAsync(self, dimension, minimum, maximum, callback):
        self.requests.append((dimension, minimum, maximum))
        self.pending.append((dimension, callback))
        self.callbacks.append(callback)
        return True

    def CheckChunkState(self, dimension, position):
        self.chunk_checks.append((dimension, position))
        return True

    def complete(self, dimension, code=1):
        index = next(i for i, row in enumerate(self.pending) if row[0] == dimension)
        _, callback = self.pending.pop(index)
        self.blocks.update(self.deferred)
        self.deferred.clear()
        callback({'code': code})


class RoomExperiment:
    def __init__(self):
        self.world = World()
        self.pose_receipt = {}
        factory = types.SimpleNamespace(CreateBlockInfo=lambda level: self.world,
                                         CreateChunkSource=lambda level: self.world)
        self.api = types.SimpleNamespace(GetEngineCompFactory=lambda: factory,
                                          GetLevelId=lambda: 'offline-level')
        self.world.before_write = self.verify_backup_before_mutation
        self.contexts = []

    def verify_backup_before_mutation(self, key, block, preparing):
        if not preparing:
            return
        backup = getattr(self.api, pose.STATE)['backup_index'][key]
        assert (backup['dimension'], tuple(backup['position'])) == key
        assert backup['block'] == self.world.original[key]

    def server(self, label, code):
        # Each SDK exec has its own globals. Keep those globals alive through the
        # registered callbacks, matching asynchronous execution after exec exits.
        context = {'api': self.api, 'json': json}
        self.contexts.append(context)
        exec(compile(code, '<offline-positive-room>', 'exec'), context)
        return json.loads(context['_result'])

    def prepared(self):
        self.server('request', pose.room_request())
        self.drive()
        return self.server('status', pose.room_status(True))

    def drive(self, restoring=False):
        status_source = pose.restore_status if restoring else pose.room_status
        for _ in range(40):
            if self.world.pending:
                self.world.complete(self.world.pending[0][0])
            value = self.server('status', status_source())
            rows = value['rooms']
            if all(row['phase'] in ('ready', 'failed') for row in rows.values()):
                return value
            self.server('advance', pose.room_advance())
        raise AssertionError('Offline room state machine exceeded bounded steps')


def state(serial=1, pair=None):
    return {'state': 'resident', 'ready': True, 'error': None, 'generation': 7,
            'logical_bytes': 65536, 'native_attempt_count': 3, 'clear_page': 'clear',
            'identity': {'host_sha256': 'a'*64, 'adler32': 123, 'byte_count': 65536},
            'native_page_names': ['clear', 'bit64', 'bit128'], 'pipeline_ready': True,
            'pipeline_links': [[0], [1], [2]],
            'dimension_recovery': {'phase': 'ready', 'serial': serial,
                                   'ready_serial': serial, 'pair': pair or [0, 1]}}


def receipt(dimension=0, serial=1, pair=None):
    return {'dimension': dimension, 'probe': state(serial, pair), 'camera': pose.CAMERA,
            'anchor': (8., 72., 8.), 'effect_positions': [(8., 72., 9.)]*3,
            'player_position': pose.DIMENSION_TARGET}


class RoomScriptTests(unittest.TestCase):
    def test_natural_nether_mode_never_touches_dimension_one_room(self):
        experiment = RoomExperiment()
        result = experiment.server('request', pose.room_request((0,)))
        self.assertEqual({'0'}, set(result['rooms']))
        prepared = experiment.drive()
        self.assertEqual(pose.ROOM_BLOCKS, prepared['backup_count'])
        self.assertEqual({'0'}, set(prepared['rooms']))
        experiment.server('restore', pose.restore_rooms())
        restored = experiment.drive(restoring=True)
        self.assertTrue(restored['all_exact'])
        self.assertEqual({'0'}, set(restored['rooms']))
        self.assertEqual({0}, set(experiment.world.read_dimensions))
        self.assertEqual({0}, {key[0] for key, *_ in experiment.world.writes})
        self.assertEqual({0}, {row[0] for row in experiment.world.requests})
        self.assertEqual({0}, {row[0] for row in experiment.world.chunk_checks})
        self.assertEqual(4, len(experiment.world.requests))
        self.assertEqual(2*pose.ROOM_BLOCKS, len(experiment.world.writes))
        self.assertEqual(4*pose.ROOM_BLOCKS, experiment.world.read_count)
        self.assertEqual(experiment.world.original, experiment.world.blocks)

    def test_host_natural_mode_requests_only_the_overworld_foothold(self):
        experiment = RoomExperiment()
        experiment.args = types.SimpleNamespace(nether_natural=True)
        original_server = experiment.server

        def execute_with_callback(label, code):
            if experiment.world.pending:
                experiment.world.complete(experiment.world.pending[0][0])
            return original_server(label, code)

        with mock.patch.object(experiment, 'server', side_effect=execute_with_callback), \
                mock.patch.object(runner.time, 'sleep'):
            result = runner.wait_rooms(experiment)
            self.assertEqual({'0'}, set(result['rooms']))
            self.assertEqual([0], experiment.pose_receipt['prepared_dimensions'])
            self.assertTrue(runner.restore(experiment)['all_exact'])
        self.assertEqual({0}, set(experiment.world.read_dimensions))
        self.assertEqual({0}, {row[0] for row in experiment.world.requests})
        self.assertEqual({0}, {row[0] for row in experiment.world.chunk_checks})

    def test_invalid_room_dimension_selection_is_rejected_without_sdk_work(self):
        for dimensions in ((), (1,), (1, 0), (0, 0), (0, 1, 2)):
            with self.subTest(dimensions=dimensions), self.assertRaises(ValueError):
                pose.room_request(dimensions)

    def test_async_callbacks_build_only_bounded_rooms_and_restore_every_backup(self):
        experiment = RoomExperiment()
        result = experiment.server('request', pose.room_request())
        self.assertEqual([0], [row['dimension'] for row in result['requests']])
        self.assertEqual([], experiment.world.writes)
        self.assertEqual([(0, pose.MINIMUM, pose.MAXIMUM)], experiment.world.requests)
        experiment.world.complete(0)
        intermediate = experiment.server('status', pose.room_status())
        self.assertEqual('await_verify', intermediate['rooms']['0']['phase'])
        self.assertEqual(0, intermediate['rooms']['0']['verified_blocks'])
        self.assertEqual('queued', intermediate['rooms']['1']['phase'])
        self.assertEqual([], experiment.world.pending)
        experiment.drive()
        ready = experiment.server('status', pose.room_status(True))
        self.assertEqual(2*pose.ROOM_BLOCKS, ready['backup_count'])
        self.assertLess(len(json.dumps(ready['backups']).encode('utf-8')), 512*1024)
        self.assertTrue(all(row['verified_blocks'] == pose.ROOM_BLOCKS for row in ready['rooms'].values()))
        self.assertEqual(set(experiment.world.original), {row[0] for row in experiment.world.writes})
        self.assertEqual('minecraft:stone', experiment.world.blocks[(0, pose.MINIMUM)]['name'])
        self.assertEqual('minecraft:air', experiment.world.blocks[(1, pose.DIMENSION_TARGET)]['name'])
        count = len(experiment.world.writes)
        experiment.server('restore', pose.restore_rooms())
        self.assertEqual(count, len(experiment.world.writes), 'Restoration must await loaded chunks')
        final = experiment.drive(restoring=True)
        self.assertTrue(final['all_exact'])
        self.assertEqual(2*pose.ROOM_BLOCKS, final['count'])
        self.assertEqual(experiment.world.original, experiment.world.blocks)
        self.assertEqual(8, len(experiment.world.requests))
        self.assertEqual(4*pose.ROOM_BLOCKS, len(experiment.world.writes))
        self.assertEqual(8*pose.ROOM_BLOCKS, experiment.world.read_count)
        self.assertEqual(32, len(experiment.world.chunk_checks))
        self.assertTrue(all(row[2:] == (0, False, False) for row in experiment.world.writes[count:]))
        for dimension in (0, 1):
            actual = [row[0][1] for row in experiment.world.writes[count:] if row[0][0] == dimension]
            expected = [tuple(row['position']) for row in ready['backups']
                        if row['dimension'] == dimension]
            self.assertEqual(expected, actual)

    def test_pending_preparation_is_cancelled_and_late_callback_cannot_write(self):
        experiment = RoomExperiment()
        experiment.server('request', pose.room_request())
        stale = experiment.world.callbacks[0]
        experiment.server('restore', pose.restore_rooms())
        stale({'code': 1})
        self.assertEqual([], experiment.world.writes)
        result = experiment.drive(restoring=True)
        self.assertTrue(result['all_exact'])
        self.assertEqual(0, result['count'])
        self.assertEqual(experiment.world.original, experiment.world.blocks)

    def test_cleanup_reentering_during_write_stops_after_current_backed_block(self):
        experiment = RoomExperiment()
        experiment.server('request', pose.room_request())
        original = experiment.world.SetBlockNew

        def cancel_after_first_write(position, block, mode, dimension, preparing, notify):
            accepted = original(position, block, mode, dimension, preparing, notify)
            if preparing:
                experiment.server('cancel', pose.restore_rooms())
            return accepted

        with mock.patch.object(experiment.world, 'SetBlockNew', side_effect=cancel_after_first_write):
            experiment.world.complete(0)
        self.assertEqual(1, len(experiment.world.writes))
        self.assertEqual(1, len(getattr(experiment.api, pose.STATE)['backups']))
        self.assertNotEqual('ready', experiment.server('status', pose.room_status())['rooms']['0']['phase'])
        self.assertTrue(experiment.drive(restoring=True)['all_exact'])
        self.assertEqual(experiment.world.original, experiment.world.blocks)

    def test_cleanup_reentering_last_verification_read_cannot_publish_ready(self):
        experiment = RoomExperiment()
        experiment.server('request', pose.room_request())
        experiment.world.complete(0)
        experiment.server('advance', pose.room_advance())
        original = experiment.world.GetBlockNew
        read_count = 0

        def cancel_after_last_read(position, dimension):
            nonlocal read_count
            value = original(position, dimension)
            read_count += 1
            if read_count == pose.ROOM_BLOCKS:
                experiment.server('cancel', pose.restore_rooms())
            return value

        with mock.patch.object(experiment.world, 'GetBlockNew', side_effect=cancel_after_last_read):
            experiment.world.complete(0)
        row = experiment.server('status', pose.room_status())['rooms']['0']
        self.assertNotEqual('ready', row['phase'])
        self.assertEqual(0, row['verified_blocks'])
        self.assertTrue(experiment.drive(restoring=True)['all_exact'])
        self.assertEqual(experiment.world.original, experiment.world.blocks)

    def test_permanent_mismatch_fails_at_three_writes_and_retains_exact_originals(self):
        experiment = RoomExperiment()
        experiment.world.bad_write = (0, pose.MINIMUM)
        experiment.server('request', pose.room_request())
        result = experiment.drive()
        self.assertEqual('failed', result['rooms']['0']['phase'])
        self.assertEqual(3, result['rooms']['0']['attempts'])
        self.assertEqual(pose.ROOM_BLOCKS+2, result['rooms']['0']['write_calls'])
        self.assertEqual(1, result['rooms']['0']['mismatch_count'])
        mismatch = result['rooms']['0']['first_mismatches'][0]
        self.assertEqual(list(pose.MINIMUM), mismatch['position'])
        self.assertEqual('minecraft:stone', mismatch['wanted']['name'])
        self.assertEqual('minecraft:unexpected', mismatch['actual']['name'])
        self.assertEqual(3, mismatch['last_write']['attempt'])
        self.assertEqual([1, 2, 3], [row['attempt'] for row in result['rooms']['0']['verification_history']])
        self.assertEqual(2*pose.ROOM_BLOCKS, result['backup_count'])
        experiment.world.bad_write = None
        experiment.server('restore', pose.restore_rooms())
        self.assertTrue(experiment.drive(restoring=True)['all_exact'])
        self.assertEqual(experiment.world.original, experiment.world.blocks)

    def test_delayed_visibility_and_one_rejected_write_recover_with_unique_backups(self):
        experiment = RoomExperiment()
        experiment.world.defer_visibility = True
        experiment.world.reject_writes[(1, pose.MINIMUM)] = 1
        ready = experiment.prepared()
        self.assertEqual('ready', ready['rooms']['1']['phase'])
        self.assertEqual(2, ready['rooms']['1']['attempts'])
        self.assertEqual(pose.ROOM_BLOCKS+1, ready['rooms']['1']['write_calls'])
        self.assertEqual(2*pose.ROOM_BLOCKS, ready['backup_count'])
        keys = [(row['dimension'], tuple(row['position'])) for row in ready['backups']]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(row['block'] == experiment.world.original[key]
                            for key, row in zip(keys, ready['backups'])))
        experiment.server('restore', pose.restore_rooms())
        self.assertTrue(experiment.drive(restoring=True)['all_exact'])
        self.assertEqual(experiment.world.original, experiment.world.blocks)

    def test_borrowed_block_result_cannot_mutate_copied_originals(self):
        experiment = RoomExperiment()
        experiment.world.borrowed_results = True
        ready = experiment.prepared()
        self.assertEqual(2*pose.ROOM_BLOCKS, ready['backup_count'])
        self.assertTrue(all(row['block'] == experiment.world.original[
            (row['dimension'], tuple(row['position']))] for row in ready['backups']))
        experiment.server('restore', pose.restore_rooms())
        self.assertTrue(experiment.drive(restoring=True)['all_exact'])
        self.assertEqual(experiment.world.original, experiment.world.blocks)

    def test_duplicate_and_stale_success_or_failure_callbacks_are_inert(self):
        experiment = RoomExperiment()
        experiment.server('request', pose.room_request())
        first = experiment.world.callbacks[0]
        experiment.world.complete(0)
        count = len(experiment.world.writes)
        first({'code': 1})
        first({'code': 0})
        self.assertEqual(count, len(experiment.world.writes))
        self.assertEqual('await_verify', experiment.server('status', pose.room_status())['rooms']['0']['phase'])
        experiment.drive()
        experiment.server('restore', pose.restore_rooms())
        self.assertTrue(experiment.drive(restoring=True)['all_exact'])
        count = len(experiment.world.writes)
        for callback in experiment.world.callbacks:
            callback({'code': 1})
            callback({'code': 0})
        self.assertEqual(count, len(experiment.world.writes))
        self.assertTrue(experiment.server('status', pose.restore_status())['all_exact'])

    def test_immediate_chunk_callbacks_preserve_separate_write_and_verify_stages(self):
        experiment = RoomExperiment()
        original = experiment.world.DoTaskOnChunkAsync

        def immediate(dimension, minimum, maximum, callback):
            accepted = original(dimension, minimum, maximum, callback)
            experiment.world.complete(dimension)
            return accepted

        with mock.patch.object(experiment.world, 'DoTaskOnChunkAsync', side_effect=immediate):
            result = experiment.server('request', pose.room_request())
            self.assertEqual('await_verify', result['rooms']['0']['phase'])
            self.assertEqual('queued', result['rooms']['1']['phase'])
            self.assertEqual(0, result['rooms']['0']['verified_blocks'])
            ready = experiment.drive()
            self.assertTrue(all(row['phase'] == 'ready' for row in ready['rooms'].values()))
            self.assertEqual(2*pose.ROOM_BLOCKS, ready['backup_count'])
            experiment.server('restore', pose.restore_rooms())
            self.assertTrue(experiment.drive(restoring=True)['all_exact'])
        self.assertEqual(experiment.world.original, experiment.world.blocks)

    def test_rejected_chunk_callback_changes_no_blocks_in_that_dimension(self):
        experiment = RoomExperiment()
        experiment.server('request', pose.room_request())
        experiment.world.complete(0, code=0)
        result = experiment.drive()
        self.assertEqual('failed', result['rooms']['0']['phase'])
        self.assertEqual(pose.ROOM_BLOCKS, result['backup_count'])
        self.assertTrue(all(key[0] == 1 for key, *_ in experiment.world.writes))

    def test_missing_corner_chunk_prevents_any_write(self):
        experiment = RoomExperiment()
        experiment.server('request', pose.room_request())
        with mock.patch.object(experiment.world, 'CheckChunkState', return_value=False):
            experiment.world.complete(0)
        row = experiment.server('status', pose.room_status())['rooms']['0']
        self.assertEqual('failed', row['phase'])
        self.assertEqual(0, row['write_calls'])
        self.assertEqual([], experiment.world.writes)

    def test_host_waits_for_two_verified_rooms_and_reports_restore_failure(self):
        experiment = types.SimpleNamespace(pose_receipt={}, server=mock.Mock(side_effect=[
            {'requests': [{'accepted': True}, {'accepted': True}]},
            {'rooms': {'0': {'phase': 'loading'}, '1': {'phase': 'loading'}}},
            {'dispatched': False, 'pending': True},
            {'rooms': {'0': {'phase': 'ready', 'verified_blocks': pose.ROOM_BLOCKS},
                       '1': {'phase': 'ready', 'verified_blocks': pose.ROOM_BLOCKS}}},
            {'backups': ['offline'], 'backup_count': 2*pose.ROOM_BLOCKS}]))
        with mock.patch.object(runner.time, 'sleep'):
            result = runner.wait_rooms(experiment)
        self.assertEqual(2*pose.ROOM_BLOCKS, result['backup_count'])
        experiment.server.side_effect = [
            {'requested': True}, {'all_exact': False, 'rooms': {'0': {'phase': 'failed'}}}]
        with self.assertRaisesRegex(RuntimeError, 'restoration failed'):
            runner.restore(experiment)

    def test_request_response_loss_still_restores_rooms_applied_by_sdk(self):
        experiment = RoomExperiment()
        actual_server = experiment.server

        def lose_request_response(label, code):
            result = actual_server(label, code)
            if label == 'positive_rooms_request':
                experiment.world.complete(0)
                raise OSError('SDK applied request; transport lost the response')
            if 'restore' in label and experiment.world.pending:
                experiment.world.complete(experiment.world.pending[0][0])
            return result

        with mock.patch.object(experiment, 'server', side_effect=lose_request_response):
            with self.assertRaisesRegex(OSError, 'transport lost'):
                runner.wait_rooms(experiment)
            result = runner.restore(experiment)
        self.assertTrue(result['all_exact'])
        self.assertEqual(experiment.world.original, experiment.world.blocks)

    def test_room_prepare_and_restore_timeouts_have_bounded_poll_counts(self):
        loading = {'rooms': {'0': {'phase': 'loading'}, '1': {'phase': 'loading'}}}
        experiment = types.SimpleNamespace(pose_receipt={}, server=mock.Mock(side_effect=
            lambda label, code: {'requests': [{'accepted': True}, {'accepted': True}]}
            if label == 'positive_rooms_request' else copy.deepcopy(loading)))
        with mock.patch.object(runner.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'preparation timed out'):
                runner.wait_rooms(experiment)
        self.assertEqual(161, experiment.server.call_count)
        self.assertEqual(80, sleep.call_count)
        experiment.server.reset_mock()
        experiment.server.side_effect = lambda label, code: (
            {'requested': True} if label == 'positive_rooms_restore_request'
            else {'all_exact': False, **copy.deepcopy(loading)})
        with mock.patch.object(runner.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'restoration timed out'):
                runner.restore(experiment)
        self.assertEqual(161, experiment.server.call_count)
        self.assertEqual(80, sleep.call_count)


class CameraBase:
    def __init__(self, args):
        self.events = []
        self.initial = {'origin': None, 'anchor': None, 'actors': 0, 'effects': 0,
                        'state': 'empty', 'payload': False, 'dimension': 0,
                        'player': 'owned-player', 'frame': 0}
        self.settlements = [{'position': pose.CAMERA, 'forward': (0., 0., 1.), 'frame': 10},
                            {'position': pose.CAMERA, 'forward': (0., 0., 1.), 'frame': 11}]
        self.move_result = {'before': (5., 60., 5.), 'after': pose.PLAYER_FEET, 'accepted': True}
        self.settled_player = (8.5, 71.62, 8.5)

    def call(self, label, code='', expression=''):
        self.events.append(('call', label, code, expression))
        if label == 'positive_pose_initial':
            return copy.deepcopy(self.initial)
        if label == 'positive_camera_request':
            return {'render_event': 10}
        if label.startswith('positive_camera_settle_'):
            return self.settlements.pop(0) if len(self.settlements) > 1 else self.settlements[0]
        return {'actor_count': 1}

    def server(self, label, code):
        self.events.append(('server', label, code))
        return self.move_result if label == 'positive_player_request' else self.settled_player


class PositiveCameraTests(unittest.TestCase):
    def experiment(self):
        return runner.create_experiment_type(types.SimpleNamespace(Experiment=CameraBase))(None)

    def test_camera_waits_for_later_frame_before_creating_positive_anchor(self):
        experiment = self.experiment()
        with mock.patch.object(runner, 'wait_rooms', side_effect=lambda exp: exp.events.append(('rooms',))), \
                mock.patch.object(runner.time, 'sleep'):
            experiment.prepare_camera()
        labels = [row[1] if len(row) > 1 else row[0] for row in experiment.events]
        self.assertEqual(['positive_pose_initial', 'rooms', 'positive_player_request',
                          'positive_camera_request', 'positive_camera_settle_00',
                          'positive_camera_settle_01'], labels[:6])
        self.assertEqual('positive_create_delayed_anchor', labels[-1])
        self.assertEqual('server', experiment.events[-2][0])
        self.assertEqual((8., 72., 8.), experiment.pose_receipt['anchor'])
        self.assertIn(str(pose.PLAYER_FEET), experiment.events[2][2])
        self.assertIn(str(pose.CAMERA), experiment.events[3][2])
        self.assertIn("probe._new_actor('clear',0)", experiment.events[-1][2])

    def test_preexisting_resident_or_render_state_is_rejected_before_room_edits(self):
        for key, value in (('origin', (0, 0, 0)), ('anchor', (0, 72, 0)), ('actors', 1),
                           ('effects', 1), ('state', 'resident'), ('payload', True), ('dimension', 1)):
            with self.subTest(key=key):
                experiment = self.experiment()
                experiment.initial[key] = value
                with mock.patch.object(runner, 'wait_rooms') as rooms:
                    with self.assertRaisesRegex(RuntimeError, 'fresh empty Overworld'):
                        experiment.prepare_camera()
                rooms.assert_not_called()

    def test_outside_anchor_or_unsettled_camera_never_creates_an_actor(self):
        for settlement in ({'position': pose.CAMERA, 'forward': (0., -1., 0.), 'frame': 11},
                            {'position': (0., 0., 0.), 'forward': (0., 0., 1.), 'frame': 11}):
            with self.subTest(settlement=settlement):
                experiment = self.experiment()
                experiment.settlements = [settlement]
                with mock.patch.object(runner, 'wait_rooms'), mock.patch.object(runner.time, 'sleep'):
                    with self.assertRaises(RuntimeError):
                        experiment.prepare_camera()
                self.assertFalse(any(row[1] == 'positive_create_delayed_anchor' for row in experiment.events))

    def test_wrong_player_position_readback_prevents_delayed_actor_creation(self):
        experiment = self.experiment()
        experiment.settled_player = (.5, 0., .5)
        with mock.patch.object(runner, 'wait_rooms'), mock.patch.object(runner.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                experiment.prepare_camera()
        self.assertFalse(any(row[1] == 'positive_create_delayed_anchor' for row in experiment.events))


class AcceptanceTests(unittest.TestCase):
    def test_natural_roundtrip_budget_is_one_and_validated_before_initialization(self):
        self.assertEqual(1, runner.repeats_for(True, None))
        self.assertEqual(2, runner.repeats_for(False, None))
        self.assertEqual(1, runner.repeats_for(True, 1))
        self.assertEqual(3, runner.repeats_for(False, 3))
        for repeats in (0, 2, 3, 4):
            with self.subTest(repeats=repeats):
                experiment = types.SimpleNamespace(args=types.SimpleNamespace(nether_natural=True),
                                                    initialize=mock.Mock())
                with self.assertRaisesRegex(ValueError, 'one bounded round trip'):
                    runner.run(experiment, None, repeats=repeats)
                experiment.initialize.assert_not_called()

    def test_admission_records_exact_head_and_accepts_local_natural_terrain_height(self):
        exact = runner.admission(receipt(1), {'dimension': 1, 'position': pose.DIMENSION_TARGET}, 1)
        self.assertTrue(exact['verified'])
        self.assertTrue(exact['exact_requested_head'])
        self.assertEqual(list(pose.DIMENSION_TARGET), exact['requested_head'])
        client = receipt(1)
        client['player_position'] = (9., 90., 9.)
        adjusted = runner.admission(client, {'dimension': 1, 'position': (9., 91.62, 9.)}, 1)
        self.assertTrue(adjusted['verified'])
        self.assertFalse(adjusted['exact_requested_head'])
        self.assertEqual((9., 90., 9.), adjusted['client']['position'])
        self.assertEqual((9., 91.62, 9.), adjusted['server']['position'])

    def test_admission_rejects_wrong_dimensions_invalid_positions_and_far_locations(self):
        bad_positions = [None, (), (8., float('nan'), 8.), (8., float('inf'), 8.),
                         (True, 72., 8.), (8., 0., 8.), (8., 127., 8.),
                         (12.1, 72., 8.), (8., 72., 3.9)]
        for position in bad_positions:
            for side in ('client', 'server'):
                with self.subTest(position=position, side=side):
                    client, server = receipt(1), {'dimension': 1, 'position': pose.DIMENSION_TARGET}
                    if side == 'client':
                        client['player_position'] = position
                    else:
                        server['position'] = position
                    self.assertFalse(runner.admission(client, server, 1)['verified'])
        self.assertFalse(runner.admission(receipt(0), {'dimension': 1, 'position': pose.DIMENSION_TARGET}, 1)['verified'])
        self.assertFalse(runner.admission(receipt(1), {'dimension': 0, 'position': pose.DIMENSION_TARGET}, 1)['verified'])
        self.assertFalse(runner.admission(receipt(1), None, 1)['verified'])

    def test_natural_admission_failure_happens_after_capture_without_rearming(self):
        before, ready = receipt(0, 0), receipt(1, 1)
        ready['player_position'] = (300., 72., 300.)
        events, record = [], {}
        experiment = types.SimpleNamespace(args=types.SimpleNamespace(nether_natural=True),
            data_checks=mock.Mock())

        def server(label, code):
            events.append('admission' if 'admitted_server_position' in label else 'request')
            return {'dimension': 1, 'position': (300., 72., 300.)} if 'admitted_server_position' in label else {'accepted': True}

        experiment.server = mock.Mock(side_effect=server)
        with mock.patch.object(runner, 'current', side_effect=[before, ready]), \
                mock.patch.object(runner.candidate, 'arm', side_effect=lambda *args: events.append('arm')) as arm, \
                mock.patch.object(runner.candidate, 'raw_readback', side_effect=lambda *args: events.append('capture') or {'exact': True}), \
                mock.patch.object(runner.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'actual natural-Nether player admission'):
                runner.transit(experiment, 'natural', 1, 'owned-player',
                               runner.static_identity(before['probe']), None, record)
        self.assertEqual(['arm', 'request', 'capture', 'admission'], events)
        arm.assert_called_once()
        experiment.data_checks.assert_not_called()
        self.assertTrue(record['automatic_readback']['exact'])
        self.assertFalse(record['admitted_position']['verified'])
        self.assertNotIn('pixel_verified', record)

    def test_natural_capture_error_still_records_read_only_server_admission(self):
        before, ready = receipt(0, 0), receipt(1, 1)
        experiment = types.SimpleNamespace(args=types.SimpleNamespace(nether_natural=True),
            server=mock.Mock(side_effect=[{'accepted': True},
                {'dimension': 1, 'position': pose.DIMENSION_TARGET}]))
        record = {}
        with mock.patch.object(runner, 'current', side_effect=[before, ready]), \
                mock.patch.object(runner.candidate, 'arm'), \
                mock.patch.object(runner.candidate, 'raw_readback', side_effect=RuntimeError('pixel mismatch')), \
                mock.patch.object(runner.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'pixel mismatch'):
                runner.transit(experiment, 'natural', 1, 'owned-player',
                               runner.static_identity(before['probe']), None, record)
        self.assertEqual(2, experiment.server.call_count)
        self.assertIn('admitted_server_position', experiment.server.call_args.args[0])
        self.assertIn('GetEntityDimensionId()', experiment.server.call_args.args[1])
        self.assertTrue(record['admitted_position']['verified'])
        self.assertNotIn('pixel_verified', record)

    def test_gate_checks_all_static_identity_fields_and_positive_poses(self):
        value = receipt()
        frozen = copy.deepcopy(runner.static_identity(value['probe']))
        runner.gate(value, frozen, 1, [0, 1])
        for key, changed in (('identity', {}), ('generation', 8), ('logical_bytes', 1),
                             ('native_attempt_count', 4), ('native_page_names', ['other']),
                             ('clear_page', 'other')):
            with self.subTest(key=key):
                invalid = copy.deepcopy(value)
                invalid['probe'][key] = changed
                with self.assertRaises(RuntimeError):
                    runner.gate(invalid, frozen, 1, [0, 1])
        for key, changed in (('camera', (0., 0., -3.)), ('anchor', (0., 69., 0.)),
                             ('effect_positions', [(0., 0., 0.)]*3), ('effect_positions', [])):
            with self.subTest(key=key, changed=changed):
                invalid = copy.deepcopy(value)
                invalid[key] = changed
                with self.assertRaises(RuntimeError):
                    runner.gate(invalid, frozen, 1, [0, 1])

    def test_matching_ready_receipt_is_followed_immediately_by_passive_capture(self):
        before, stale, ready = receipt(0, 0), receipt(1, 0), receipt(1, 1)
        events = []
        frozen = runner.static_identity(before['probe'])
        record = {}
        experiment = types.SimpleNamespace(server=mock.Mock(side_effect=lambda *args: events.append('request') or {'accepted': True}),
            data_checks=mock.Mock(side_effect=lambda *args: events.append('checks') or [{'exact': True}, {'exact': True}]))
        values = iter([before, stale, ready])

        def current(*args):
            value = next(values)
            events.append('ready' if value is ready else 'read_state')
            return value

        with mock.patch.object(runner, 'current', side_effect=current), \
                mock.patch.object(runner.candidate, 'arm', side_effect=lambda *args: events.append('arm')), \
                mock.patch.object(runner.candidate, 'raw_readback', side_effect=lambda *args: events.append('capture') or {'exact': True}), \
                mock.patch.object(runner.time, 'sleep'):
            result = runner.transit(experiment, 'outbound', 1, 'owned-player', frozen, None, record)
        self.assertTrue(result['pixel_verified'])
        self.assertEqual(['read_state', 'arm', 'request', 'read_state', 'ready', 'capture', 'checks'], events)
        self.assertIn('ChangePlayerDimension(1,%r)' % (pose.DIMENSION_TARGET,),
                      experiment.server.call_args.args[1])

    def test_static_change_blocks_capture_despite_matching_ready_serial(self):
        before, changed = receipt(0, 0), receipt(1, 1)
        changed['probe']['native_attempt_count'] += 1
        experiment = types.SimpleNamespace(server=mock.Mock(return_value={'accepted': True}))
        with mock.patch.object(runner, 'current', side_effect=[before, changed]), \
                mock.patch.object(runner.candidate, 'arm'), \
                mock.patch.object(runner.candidate, 'raw_readback') as capture, \
                mock.patch.object(runner.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'Static generation'):
                runner.transit(experiment, 'outbound', 1, 'owned-player',
                               runner.static_identity(before['probe']), None, {})
        capture.assert_not_called()

    def test_stale_ready_receipts_expire_after_bounded_polls_without_capture(self):
        before, stale = receipt(0, 0), receipt(1, 0)
        experiment = types.SimpleNamespace(server=mock.Mock(return_value={'accepted': True}))
        with mock.patch.object(runner, 'current', side_effect=[before]+[stale]*40) as current, \
                mock.patch.object(runner.candidate, 'arm'), \
                mock.patch.object(runner.candidate, 'raw_readback') as capture, \
                mock.patch.object(runner.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'before host deadline'):
                runner.transit(experiment, 'outbound', 1, 'owned-player',
                               runner.static_identity(before['probe']), None, {})
        self.assertEqual(41, current.call_count)
        self.assertEqual(40, sleep.call_count)
        capture.assert_not_called()

    def test_run_returns_and_restores_rooms_after_outbound_failure(self):
        experiment = types.SimpleNamespace(variant='carrier', viewport=[720, 1080],
            roi=[8, 128, 512, 512], payload=bytes(65536), dimension=0,
            pose_receipt={'rooms_request': {'requested': True}}, initialize=mock.Mock(),
            call=mock.Mock(return_value='owned-player'))
        progress, events = {}, []

        def current(*args):
            return receipt(experiment.dimension, 0)

        def transit(exp, label, target, player, frozen, original, record):
            events.append(target)
            experiment.dimension = target
            if target == 1:
                raise RuntimeError('outbound pixels failed')
            record['pixel_verified'] = True

        with mock.patch.object(runner, 'current', side_effect=current), \
                mock.patch.object(runner, 'transit', side_effect=transit), \
                mock.patch.object(runner.candidate, 'arm'), \
                mock.patch.object(runner.candidate, 'raw_readback', return_value={'exact': True}), \
                mock.patch.object(runner, 'restore', side_effect=lambda exp: events.append('restore') or {'all_exact': True}):
            with self.assertRaisesRegex(RuntimeError, 'round trip failed'):
                runner.run(experiment, None, repeats=1, progress=progress)
        self.assertEqual([1, 0, 'restore'], events)
        self.assertTrue(progress['cleanup']['all_exact'])
        self.assertFalse(progress['pixel_verified'])
        self.assertIn('outbound pixels failed', progress['trips'][0]['outbound_failure'])

    def test_initialization_error_still_restores_and_preserves_cleanup_error(self):
        experiment = types.SimpleNamespace(pose_receipt={'rooms_request': True},
            initialize=mock.Mock(side_effect=RuntimeError('initialization failed')))
        progress = {}
        with mock.patch.object(runner, 'restore', side_effect=RuntimeError('restore failed')) as restore:
            with self.assertRaisesRegex(RuntimeError, 'initialization failed'):
                runner.run(experiment, None, progress=progress)
        restore.assert_called_once_with(experiment)
        self.assertIn('restore failed', progress['cleanup_failure'])
        self.assertFalse(progress['pixel_verified'])

    def test_broken_return_decision_and_preflight_still_request_return_then_restore(self):
        experiment = types.SimpleNamespace(variant='carrier', viewport=[720, 1080],
            roi=[8, 128, 512, 512], payload=bytes(65536),
            pose_receipt={'rooms_request': True}, initialize=mock.Mock(),
            call=mock.Mock(return_value='owned-player'),
            server=mock.Mock(return_value={'accepted': True}))
        progress = {}
        before = receipt(0, 0)

        def current(exp, label):
            if label == 'positive_initial' or label == 'positive_nether_0_before':
                return copy.deepcopy(before)
            raise TypeError('stale effect entity GetPos')

        with mock.patch.object(runner, 'current', side_effect=current), \
                mock.patch.object(runner.candidate, 'arm'), \
                mock.patch.object(runner.candidate, 'raw_readback', return_value={'exact': True}), \
                mock.patch.object(runner.time, 'sleep'), \
                mock.patch.object(runner, 'restore', return_value={'all_exact': True}) as restore:
            with self.assertRaisesRegex(RuntimeError, 'Positive pose dimension round trip failed'):
                runner.run(experiment, None, repeats=1, progress=progress)
        self.assertEqual(2, experiment.server.call_count)
        outbound, returning = experiment.server.call_args_list
        self.assertIn('ChangePlayerDimension(1,', outbound.args[1])
        self.assertIn('ChangePlayerDimension(0,', returning.args[1])
        self.assertIn('without_client_preflight', returning.args[0])
        restore.assert_called_once_with(experiment)
        row = progress['trips'][0]
        self.assertTrue(row['outbound']['request_intent'])
        self.assertTrue(row['return']['request_intent'])
        self.assertIn('stale effect entity', row['outbound_failure'])
        self.assertIn('stale effect entity', row['return_decision_failure'])
        self.assertIn('pixel verification unavailable', row['return_failure'])
        self.assertTrue(progress['cleanup']['all_exact'])
        self.assertFalse(progress['pixel_verified'])


if __name__ == '__main__':
    unittest.main()
