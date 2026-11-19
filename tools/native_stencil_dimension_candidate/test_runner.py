"""Offline host acceptance gates and guaranteed return-request regressions."""
import copy
import importlib.util
from pathlib import Path
import types
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('dimension_candidate_runner_under_test', HERE/'runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def resident(serial=1, pair=None):
    return {'state': 'resident', 'ready': True, 'error': None,
            'identity': {'host_sha256': 'a'*64, 'adler32': 123, 'byte_count': 65536},
            'native_page_names': ['clear', 'bit64', 'bit128'], 'pipeline_ready': True,
            'pipeline_links': [['copy', 0, 'restore', 0, 3],
                               ['copy', 0, 'consumer', 0, 3],
                               ['restore', 0, 'consumer', 0, 4]],
            'dimension_recovery': {'phase': 'ready', 'serial': serial,
                                   'ready_serial': serial, 'pair': pair or [0, 1]}}


class HostGateTests(unittest.TestCase):
    def setUp(self):
        self.state = resident()
        self.identity = copy.deepcopy(self.state['identity'])
        self.pages = list(self.state['native_page_names'])

    def test_gate_requires_same_identity_pages_and_usable_pipeline(self):
        runner.gate(self.state, self.identity, self.pages, 1, [0, 1])
        changes = [('state', 'frozen'), ('ready', False), ('error', 'native rejected'),
                   ('identity', {'host_sha256': 'b'*64}),
                   ('native_page_names', ['different-page']), ('pipeline_ready', False),
                   ('pipeline_links', self.state['pipeline_links'][:2])]
        for key, value in changes:
            with self.subTest(key=key):
                changed = copy.deepcopy(self.state)
                changed[key] = value
                with self.assertRaisesRegex(RuntimeError, 'same static bytes'):
                    runner.gate(changed, self.identity, self.pages, 1, [0, 1])

    def test_gate_rejects_stale_or_wrong_transition_receipts(self):
        for key, value in (('phase', 'wait_links'), ('serial', 0), ('ready_serial', 0),
                           ('ready_serial', None), ('pair', [1, 0])):
            with self.subTest(key=key, value=value):
                changed = copy.deepcopy(self.state)
                changed['dimension_recovery'][key] = value
                with self.assertRaisesRegex(RuntimeError, 'stale or belongs'):
                    runner.gate(changed, self.identity, self.pages, 1, [0, 1])

    def test_faulted_arm_does_not_prevent_owned_return_server_request(self):
        failed = resident(2, [1, 0])
        failed['error'] = 'renderer failed'
        failed['dimension_recovery']['phase'] = 'failed'
        experiment = types.SimpleNamespace(server=mock.Mock(return_value={'accepted': True}))
        progress = {}
        with mock.patch.object(runner, 'current', side_effect=[
                {'dimension': 1, 'probe': self.state}, {'dimension': 0, 'probe': failed}]), \
                mock.patch.object(runner, 'arm', side_effect=RuntimeError('pending or faulted')), \
                mock.patch.object(runner.time, 'sleep'), mock.patch.object(runner, 'raw_readback') as capture:
            with self.assertRaisesRegex(RuntimeError, 'Automatic dimension recovery failed'):
                runner.transit(experiment, 'return', 0, [10, 80, 20], 'owned-player',
                               self.identity, self.pages, None, progress)
        experiment.server.assert_called_once()
        self.assertIn('ChangePlayerDimension(0,(10, 80, 20))', experiment.server.call_args.args[1])
        self.assertIn('pending or faulted', progress['arm_failure'])
        self.assertEqual({'accepted': True}, progress['request'])
        capture.assert_not_called()

    def test_outbound_arm_failure_never_requests_another_dimension(self):
        experiment = types.SimpleNamespace(server=mock.Mock())
        with mock.patch.object(runner, 'current', return_value={'dimension': 0, 'probe': self.state}), \
                mock.patch.object(runner, 'arm', side_effect=RuntimeError('arm failed')):
            with self.assertRaisesRegex(RuntimeError, 'arm failed'):
                runner.transit(experiment, 'outbound', 1, [0, 70, 0], 'owned-player',
                               self.identity, self.pages, None)
        experiment.server.assert_not_called()

    def test_run_finally_attempts_return_after_outbound_recovery_failure(self):
        experiment = types.SimpleNamespace(variant='carrier', viewport=[720, 1080],
            roi=[8, 128, 512, 512], payload=bytes(65536), dimension=0,
            state=resident(0, [0, 1]), initialize=mock.Mock(),
            call=mock.Mock(return_value='owned-player'), server=mock.Mock(return_value=[10.5, 80., -20.5]))
        progress = {}

        def snapshot(*args):
            return {'dimension': experiment.dimension, 'probe': copy.deepcopy(experiment.state)}

        def transit(probe, label, target, position, player, identity, pages, original, record):
            if target == 1:
                experiment.dimension = 1
                record['request'] = {'accepted': True}
                raise RuntimeError('outbound pixel readback failed')
            experiment.dimension = 0
            record['requested_position'] = position
            record['pixel_verified'] = True
            return record

        with mock.patch.object(runner, 'current', side_effect=snapshot), \
                mock.patch.object(runner, 'arm'), mock.patch.object(runner, 'raw_readback', return_value={}), \
                mock.patch.object(runner, 'transit', side_effect=transit) as transition:
            with self.assertRaisesRegex(RuntimeError, 'Dimension round trip failed'):
                runner.run(experiment, None, repeats=1, progress=progress)
        self.assertEqual([1, 0], [call.args[2] for call in transition.call_args_list])
        self.assertEqual([10, 80, -20], progress['trips'][0]['return']['requested_position'])
        self.assertEqual(0, experiment.dimension)
        self.assertFalse(progress['pixel_verified'])
        self.assertIn('outbound pixel readback failed', progress['trips'][0]['outbound_failure'])


if __name__ == '__main__':
    unittest.main()
