"""Execute the generated restoration command against a deliberately auto-orienting SDK."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('particle_wall_runner_under_test', HERE/'runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def backups():
    rows = []
    for x in range(-5, 5):
        for y in range(-61, -51):
            block = {'name': 'minecraft:air', 'aux': 0}
            if (x, y) in ((2, -60), (4, -60)):
                block = {'name': 'minecraft:torch', 'aux': 0}
            rows.append({'pos': [x, y, 3], 'before': block})
    return {'edits': rows, 'blocks': 100}


class FakeWorld:
    def __init__(self, drift=True, refuse=False, unexpected=None, mapping=None):
        self.values, self.writes, self.state_calls, self.mapping_calls = {}, [], [], []
        self.drift, self.refuse, self.unexpected = drift, refuse, unexpected
        self.mapping = {'torch_facing_direction': 'unknown'} if mapping is None else mapping

    def SetBlockNew(self, pos, block, dimension, mode, legacy, notify):
        assert (dimension, mode, legacy, notify) == (0, 0, False, False)
        value = dict(block)
        if self.drift and value['name'] == 'minecraft:torch':
            value['aux'] = 2 if pos[0] == 2 else 5
        if pos == self.unexpected:
            value = {'name': 'minecraft:stone', 'aux': 3}
        self.values[pos] = value
        self.writes.append((pos, dict(block)))
        return True

    def GetBlockNew(self, pos, dimension):
        assert dimension == 0
        return dict(self.values[pos])

    def GetBlockStatesFromAuxValue(self, name, aux):
        self.mapping_calls.append((name, aux))
        return copy.deepcopy(self.mapping)

    def GetBlockStates(self, pos, dimension):
        assert dimension == 0
        return {'torch_facing_direction': {0: 'unknown', 2: 'east', 5: 'top'}[self.values[pos]['aux']]}

    def SetBlockStates(self, pos, states, dimension):
        assert dimension == 0
        self.state_calls.append((pos, dict(states)))
        if self.refuse:
            return False
        self.values[pos]['aux'] = 0
        return True


class FakeExperiment:
    def __init__(self, world):
        self.world, self.last_result = world, None

    def server(self, label, code):
        assert label == 'particle_frameani_restore_wall'
        factory = SimpleNamespace(CreateBlockInfo=lambda level: self.world,
                                  CreateBlockState=lambda level: self.world)
        api = SimpleNamespace(GetEngineCompFactory=lambda: factory, GetLevelId=lambda: 'owned-level')
        namespace = {'api': api, 'json': json}
        exec(compile(code, '<candidate-wall-server>', 'exec'), namespace)
        self.last_result = json.loads(namespace['_result'])
        return self.last_result


class WallRestoreTests(unittest.TestCase):
    def test_known_two_torch_orientation_residuals_recover_all_100_positions(self):
        world = FakeWorld()
        result = runner.restore_frameani_wall(FakeExperiment(world), backups())
        self.assertTrue(result['all_exact'])
        self.assertEqual(result['count'], 100)
        self.assertEqual(len(result['initial_mismatches']), 2)
        self.assertEqual(len(world.writes), 100)
        self.assertEqual(world.mapping_calls, [('minecraft:torch', 0)])
        self.assertEqual({pos for pos, states in world.state_calls}, {(2, -60, 3), (4, -60, 3)})
        self.assertTrue(all(states == {'torch_facing_direction': 'unknown'} for pos, states in world.state_calls))
        self.assertEqual(result['mismatches'], [])
        self.assertTrue(all(row['states_after'] == {'torch_facing_direction': 'unknown'}
                            for row in result['torch_aux0_recovery']['repairs']))

    def test_already_exact_restore_does_not_call_state_mutator(self):
        world = FakeWorld(drift=False)
        result = runner.restore_frameani_wall(FakeExperiment(world), backups())
        self.assertTrue(result['all_exact'])
        self.assertEqual(world.state_calls, [])
        self.assertEqual(world.mapping_calls, [])

    def test_unrelated_residual_is_not_repaired_or_accepted(self):
        world = FakeWorld(unexpected=(-5, -61, 3))
        experiment = FakeExperiment(world)
        with self.assertRaisesRegex(RuntimeError, '100'):
            runner.restore_frameani_wall(experiment, backups())
        self.assertEqual(len(experiment.last_result['mismatches']), 1)
        self.assertNotIn((-5, -61, 3), {pos for pos, states in world.state_calls})

    def test_state_failure_or_unexpected_mapping_keeps_acceptance_false(self):
        for world in (FakeWorld(refuse=True), FakeWorld(mapping={'torch_facing_direction': 'top'})):
            experiment = FakeExperiment(world)
            with self.subTest(world=world), self.assertRaises(RuntimeError):
                runner.restore_frameani_wall(experiment, backups())
            self.assertFalse(experiment.last_result['all_exact'])
            self.assertEqual(len(experiment.last_result['mismatches']), 2)

    def test_nonzero_original_torch_aux_is_outside_narrow_recovery(self):
        receipt = backups()
        next(row for row in receipt['edits'] if row['pos'] == [2, -60, 3])['before']['aux'] = 5
        world = FakeWorld()
        experiment = FakeExperiment(world)
        with self.assertRaises(RuntimeError):
            runner.restore_frameani_wall(experiment, receipt)
        self.assertNotIn((2, -60, 3), {pos for pos, states in world.state_calls})

    def test_partial_or_duplicate_backups_are_rejected_before_server_call(self):
        receipt = backups()
        for rows in (receipt['edits'][:99], receipt['edits'][:99]+[receipt['edits'][0]]):
            experiment = SimpleNamespace(server=lambda *args: self.fail('must reject before server mutation'))
            with self.subTest(count=len(rows)), self.assertRaises(RuntimeError):
                runner.restore_frameani_wall(experiment, {'edits': rows})

    def test_wrapper_replaces_only_imported_helper_restore_hook(self):
        original = lambda: None
        helper = SimpleNamespace(restore_wall=original, run=lambda experiment: helper.restore_wall)
        with patch.object(runner, 'frameani_helper', return_value=helper):
            self.assertIs(runner.run_frameani(object()), runner.restore_frameani_wall)


if __name__ == '__main__':
    unittest.main()
