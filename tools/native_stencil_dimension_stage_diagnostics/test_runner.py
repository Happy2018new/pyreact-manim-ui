"""Offline execution of emitted stage controls and conservative evidence oracles."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

import numpy as np
from PIL import Image


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


observations = load('stage_observations_under_test', HERE/'observations.py')
native_fixture = load('stage_frozen_native_fixture', HERE.parent/'native_stencil_dimension_candidate/test_runtime.py')
runner = load('stage_runner_under_test', HERE/'runner.py')
routing = load('stage_routing_under_test', HERE/'routing.py')
run_fixture = load('stage_run_fixture', HERE.parent/'native_stencil_dimension_roundtrip_diagnostics/test_runner.py')


class EmittedControlTests(unittest.TestCase):
    def probe(self, automatic=False):
        fixture = native_fixture.DimensionRecoveryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        probe, native = fixture.system, fixture.native
        pages = ['pmanim_stencil_large_g7_clear_0', 'pmanim_stencil_large_g7_bit64_1',
                 'pmanim_stencil_large_g7_bit128_2']
        probe.pages = pages
        probe.clear_page = pages[0]
        probe.clear_actor['pages'] = [pages[0]]
        probe.writer_actors[0]['pages'] = pages[1:]
        probe.active_pages = [{'name': name, 'actor': probe.writer_actors[0]} for name in pages[1:]]
        probe.DestroyClientEntity = lambda entity: native.call('DestroyClientEntity', entity, default=None)
        if automatic:
            fixture.begin(0, 2)
            fixture.drive()
            self.assertEqual('ready', probe.dimension_recovery['phase'])
        native.calls.clear()
        return probe, native

    def execute(self, source, probe):
        context = {'probe': probe}
        exec(compile(source, '<offline-stage-sdk-command>', 'exec'), context)
        return context

    def test_each_stage_drives_shared_writer_pages_reader_controls_and_shader_mode(self):
        expected = {
            'off': (False, set(), set()),
            'base': (True, set(), {0}),
            'bit64': (True, {'bit64'}, {0, 1}),
            'bit128': (True, {'bit128'}, {0, 2}),
            'all': (True, {'bit64', 'bit128'}, {0, 1, 2}),
            'writers_only': (True, {'bit64', 'bit128'}, set()),
            'readers_only': (True, set(), {0, 1, 2}),
        }
        for stage, (clear, writers, readers) in expected.items():
            for mode in (1, 3, 7):
                with self.subTest(stage=stage, mode=mode):
                    probe, native = self.probe()
                    before = (probe.payload, copy.deepcopy(probe.identity), probe.generation,
                              list(probe.pages), len(probe.attempts))
                    context = self.execute(observations.stage_source(stage, mode), probe)
                    visibility = {args[1]: args[2] for args in native.arguments('SetActorBlockGeometryVisible')}
                    self.assertEqual(clear, visibility[probe.clear_page])
                    for name in probe.pages[1:]:
                        kind = 'bit128' if '_bit128_' in name else 'bit64'
                        self.assertEqual(kind in writers, visibility[name])
                    controls = {}
                    for method, args in native.calls:
                        if method in ('Play', 'Stop'):
                            controls[args[0]] = method == 'Play'
                    self.assertEqual({effect: index in readers for index, effect in enumerate(probe.effects)}, controls)
                    # Both pages share this actor, so per-page visibility alone
                    # cannot fix a disabled writer uniform.
                    uniforms = [args for args in native.arguments('SetEntityExtraUniforms')
                                if args[0] == probe.writer_actors[0]['entity'] and args[1] == 4]
                    self.assertTrue(uniforms)
                    if writers:
                        self.assertEqual(1., uniforms[-1][2][0])
                    self.assertEqual(mode, probe.consumer_mode)
                    self.assertFalse(probe.shape_enabled)
                    self.assertFalse(probe.restore_enabled)
                    self.assertTrue(probe.pipeline_enabled)
                    output_parameters = [args[2] for args in native.arguments('SetParameter')
                        if args[0] == 'stencil_integrated_consumer' and args[1] == 'output']
                    self.assertEqual([0., 650. if mode == 7 else 128., 720., 0.], output_parameters[-1])
                    self.assertTrue(all(row['accepted'] is True for row in context['stage_receipts']))
                    self.assertIs(before[0], probe.payload)
                    self.assertEqual(before[1:], (probe.identity, probe.generation, probe.pages, len(probe.attempts)))

    def test_invalid_stage_or_consumer_is_rejected_before_command_generation(self):
        for stage, mode in (('typo', 1), ('all', 0), ('all', 2), ('all', True), ('all', 8)):
            with self.subTest(stage=stage, mode=mode):
                with self.assertRaises(ValueError):
                    observations.stage_source(stage, mode)

    def test_stage_sdk_rejection_is_visible_and_not_silently_captured(self):
        probe, native = self.probe()
        native.responses['SetActorBlockGeometryVisible'] = [False]
        with self.assertRaisesRegex(RuntimeError, 'visibility rejected'):
            self.execute(observations.stage_source('bit64', 1), probe)

    def test_ambiguous_page_or_reader_topology_rejects_before_native_mutation(self):
        for change in ('readers', 'pages', 'identity'):
            with self.subTest(change=change):
                probe, native = self.probe()
                if change == 'readers':
                    probe.controls.pop()
                elif change == 'pages':
                    probe.active_pages.pop()
                else:
                    probe.active_pages[1]['name'] = probe.active_pages[0]['name']
                with self.assertRaises(RuntimeError):
                    self.execute(observations.stage_source('all', 1), probe)
                self.assertEqual([], native.calls)

    def test_manual_effects_checkpoint_recreates_current_readers_only(self):
        probe, native = self.probe(automatic=True)
        original_recovery = copy.deepcopy(probe.dimension_recovery)
        old_actors = [actor['entity'] for actor in probe.actors]
        old_effects, pages, payload = list(probe.effects), list(probe.pages), probe.payload
        # Stage observations may outlive the old automatic recovery deadline.
        native.now += 100.
        self.execute(observations.effects_source(), probe)
        self.assertEqual(old_effects, [args[0] for args in native.arguments('DestroyEntity')])
        self.assertEqual(old_actors, [actor['entity'] for actor in probe.actors])
        self.assertEqual(0, native.count('DestroyClientEntity'))
        self.assertEqual(0, native.count('AddActorBlockGeometry'))
        self.assertTrue(set(old_effects).isdisjoint(probe.effects))
        self.assertEqual(3, native.count('CreateEngineSfxFromEditor'))
        self.assertEqual(pages, probe.pages)
        self.assertIs(payload, probe.payload)
        self.assertEqual(3, len(probe.attempts))
        self.assertEqual(original_recovery, probe.dimension_recovery)
        self.assertEqual(0, native.count('PostPassResultToOtherPass'))

    def test_manual_holders_checkpoint_recreates_current_holders_with_cached_pages_only(self):
        probe, native = self.probe(automatic=True)
        # C follows B; it must preserve B's current late readers.
        self.execute(observations.effects_source(), probe)
        native.calls.clear()
        old_actors, effects = [actor['entity'] for actor in probe.actors], list(probe.effects)
        pages, payload = list(probe.pages), probe.payload
        recovery = copy.deepcopy(probe.dimension_recovery)
        context = self.execute(observations.holders_source(), probe)
        self.assertEqual(old_actors, [args[0] for args in native.arguments('DestroyClientEntity')])
        self.assertTrue(set(old_actors).isdisjoint(actor['entity'] for actor in probe.actors))
        self.assertEqual(pages, [args[1] for args in native.arguments('AddActorBlockGeometry')])
        self.assertEqual(effects, probe.effects)
        self.assertEqual(0, native.count('DestroyEntity'))
        self.assertEqual(0, native.count('CreateEngineSfxFromEditor'))
        self.assertEqual(0, native.count('PostPassResultToOtherPass'))
        self.assertEqual(pages, probe.pages)
        self.assertIs(payload, probe.payload)
        self.assertEqual(3, len(probe.attempts))
        self.assertEqual(recovery, probe.dimension_recovery)
        self.assertFalse(context['manual_result']['runtime_file_writes'])

    def test_manual_relink_checkpoint_changes_links_without_recreating_entities(self):
        probe, native = self.probe(automatic=True)
        recovery = copy.deepcopy(probe.dimension_recovery)
        actors, effects = [actor['entity'] for actor in probe.actors], list(probe.effects)
        native.calls.clear()
        self.execute(observations.relink_source(), probe)
        self.assertEqual(list(native_fixture.LINKS), native.arguments('PostPassResultToOtherPass'))
        self.assertEqual(actors, [actor['entity'] for actor in probe.actors])
        self.assertEqual(effects, probe.effects)
        for method in ('DestroyEntity', 'DestroyClientEntity', 'CreateClientEntityByTypeStr',
                       'CreateEngineSfxFromEditor', 'AddActorBlockGeometry'):
            self.assertEqual(0, native.count(method))
        self.assertEqual('all', probe.mode)
        self.assertEqual(1, probe.consumer_mode)
        self.assertTrue(probe.restore_enabled)
        self.assertEqual(recovery, probe.dimension_recovery)

    def test_transient_new_holder_uniform_failure_is_retried_by_frozen_render_tick(self):
        probe, native = self.probe(automatic=True)
        # configure('off') refreshes both old actors (four uniforms each), then
        # the first new actor rejects both of its immediate uniform attempts.
        native.responses['SetEntityExtraUniforms'] = [True]*8+[False, False]
        self.execute(observations.holders_source(), probe)
        self.assertFalse(probe.clear_actor['ready'])
        self.assertFalse(probe.snapshot()['ready'])
        probe.on_frame({})
        self.assertTrue(probe.clear_actor['ready'])
        self.assertTrue(probe.snapshot()['ready'])
        self.assertIsNone(probe.error)

    def test_manual_native_rejection_stops_before_publishing_success(self):
        for method, message in (('DestroyEntity', 'destruction rejected'),
                                ('AddActorBlockGeometry', 'reattachment rejected'),
                                ('PostPassResultToOtherPass', 'relink rejected')):
            with self.subTest(method=method):
                probe, native = self.probe()
                native.responses[method] = [False]
                source = (observations.relink_source() if method == 'PostPassResultToOtherPass' else
                          observations.effects_source() if method == 'DestroyEntity' else observations.holders_source())
                with self.assertRaisesRegex(RuntimeError, message):
                    self.execute(source, probe)


class RoutingSourceTests(unittest.TestCase):
    def probe(self):
        fixture = native_fixture.DimensionRecoveryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        probe, native = fixture.system, fixture.native
        original_control = native_fixture.Control

        class RoutedControl(original_control):
            def SetGlobal(self, enabled):
                return self.native.call('SetGlobal', self.entity, enabled)

        probe.factory.CreateFrameAniControl = lambda entity: RoutedControl(native, entity)
        probe.controls = [RoutedControl(native, entity) for entity in probe.effects]
        probe.configure_known_fixture(True, False)
        ids = {'fixture': probe.known_fixture.effect, 'late': list(probe.effects)}
        native.calls.clear()
        return probe, native, ids

    def execute(self, source, probe):
        context = {'probe': probe, 'api': types.SimpleNamespace(GetLocalPlayerId=lambda: 'player')}
        exec(compile(source, '<offline-routing-command>', 'exec'), context)
        return context

    def test_global_only_calls_setglobal_on_same_four_entities_without_metadata_or_recreation(self):
        probe, native, ids = self.probe()
        context = self.execute(routing.global_source(ids), probe)
        self.assertEqual([('SetGlobal', (entity, True)) for entity in [ids['fixture']]+ids['late']], native.calls)
        self.assertEqual(ids, context['routing_result']['ids'])
        self.assertEqual(4, len(context['routing_result']['receipts']))
        self.assertEqual(ids['fixture'], probe.known_fixture.effect)
        self.assertEqual(ids['late'], probe.effects)

    def test_changed_ids_missing_controls_and_rejected_global_cannot_claim_success(self):
        for mutation in ('fixture', 'late', 'controls'):
            with self.subTest(mutation=mutation):
                probe, native, ids = self.probe()
                if mutation == 'fixture':
                    probe.known_fixture.effect = 'changed'
                elif mutation == 'late':
                    probe.effects[1] = 'changed'
                else:
                    probe.controls.pop()
                with self.assertRaises(RuntimeError):
                    self.execute(routing.global_source(ids), probe)
                self.assertEqual([], native.calls)
        for invalid in ({'fixture': 'one', 'late': ['two', 'two', 'three']},
                        {'fixture': None, 'late': ['one', 'two', 'three']}):
            probe, native, _ = self.probe()
            with self.assertRaises((ValueError, RuntimeError)):
                self.execute(routing.global_source(invalid), probe)
            self.assertEqual([], native.calls)
        for response in (False, None):
            probe, native, ids = self.probe()
            native.responses['SetGlobal'] = [response]
            with self.assertRaisesRegex(RuntimeError, 'SetGlobal rejected'):
                self.execute(routing.global_source(ids), probe)
            self.assertEqual(1, native.count('SetGlobal'))

    def test_metadata_replays_identical_packing_and_layers_on_existing_ids_only(self):
        probe, native, ids = self.probe()
        context = self.execute(routing.metadata_source(ids), probe)
        packed = tuple((first*4096+second)/16777216. for first, second in
                       (probe.viewport, probe.roi[:2], probe.roi[2:]))
        expected = []
        for index, entity in enumerate([ids['fixture']]+ids['late']):
            mix = packed+(.25 if index == 0 else index/4.,)
            expected.extend((name, (entity, value)) for name, value in
                            (('SetFaceCamera', True), ('SetLoop', True),
                             ('SetLayer', 12+index), ('SetMixColor', mix)))
            expected.append(('Play', (entity,)))
        self.assertEqual(expected, native.calls)
        self.assertEqual(ids, context['routing_result']['ids'])
        self.assertEqual(20, len(context['routing_result']['receipts']))
        self.assertTrue(probe.known_fixture.visible)

    def test_metadata_rejection_stops_before_later_setters_or_play(self):
        probe, native, ids = self.probe()
        native.responses['SetFaceCamera'] = [False]
        with self.assertRaisesRegex(RuntimeError, 'SetFaceCamera'):
            self.execute(routing.metadata_source(ids), probe)
        self.assertEqual([('SetFaceCamera', (ids['fixture'], True))], native.calls)

    def test_fixture_destroy_requires_public_acceptance_before_full_reset(self):
        probe, native, ids = self.probe()
        context = self.execute(routing.destroy_fixture_source(), probe)
        self.assertEqual([('Stop', (ids['fixture'],)), ('DestroyEntity', (ids['fixture'],))], native.calls)
        self.assertEqual(2, len(context['routing_destroy']))
        self.assertIsNone(probe.known_fixture.effect)
        self.assertIsNone(probe.known_fixture.control)
        self.assertIsNone(probe.known_fixture.roi)
        self.assertIsNone(probe.known_fixture.varying_alpha)
        self.assertFalse(probe.known_fixture.visible)
        for method in ('Stop', 'DestroyEntity'):
            probe, native, ids = self.probe()
            native.responses[method] = [False]
            with self.assertRaises(RuntimeError):
                self.execute(routing.destroy_fixture_source(), probe)
            self.assertEqual(ids['fixture'], probe.known_fixture.effect)

    def test_position_only_moves_same_four_ids_to_actual_player_plus_forward(self):
        probe, native, ids = self.probe()
        player, forward = (8., 61.62, 8.), (0., -.25, 1.)
        probe.factory.CreatePos = lambda entity: types.SimpleNamespace(GetPos=lambda: player)
        probe.camera.GetForward = lambda: forward
        probe.factory.CreateFrameAniTrans = lambda entity: types.SimpleNamespace(
            SetPos=lambda position: native.call('FrameAniTrans.SetPos', entity, position))
        recovery, anchor = copy.deepcopy(probe.dimension_recovery), probe.anchor
        context = self.execute(routing.position_source(ids), probe)
        target = (8., 60.62, 12.)
        self.assertEqual([('FrameAniTrans.SetPos', (entity, target))
                          for entity in [ids['fixture']]+ids['late']], native.calls)
        self.assertEqual(target, context['routing_result']['target'])
        self.assertEqual(player, context['routing_result']['player_position'])
        self.assertEqual(forward, context['routing_result']['forward'])
        self.assertEqual(ids, context['routing_result']['ids'])
        self.assertEqual(recovery, probe.dimension_recovery)
        self.assertEqual(anchor, probe.anchor)
        native.calls.clear()
        native.responses['FrameAniTrans.SetPos'] = [False]
        with self.assertRaisesRegex(RuntimeError, 'SFX position rejected'):
            self.execute(routing.position_source(ids), probe)
        self.assertEqual(1, len(native.calls))


class RoutingOrchestrationTests(unittest.TestCase):
    ids = {'fixture': 'fixture', 'late': ['base', 'bit64', 'bit128']}

    def test_fixture_view_requires_independent_screen_t3_and_guard_positive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'fixture.png'
            Image.new('RGB', (8, 654)).save(path)
            experiment = run_fixture.experiment()
            for screen, exported, guard in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)):
                with self.subTest(screen=screen, exported=exported, guard=guard):
                    obs = types.SimpleNamespace(capture=mock.Mock(return_value={
                        'capture_file': str(path), 'guard_error_pixels': guard}),
                        fixture_comparison=mock.Mock(return_value={
                            'screen_roi': {'data_error_pixels': screen},
                            'exported_t3': {'data_error_pixels': exported}}))
                    original = types.SimpleNamespace(integrated=types.SimpleNamespace(verify_module=None))
                    with mock.patch.object(routing.time, 'sleep'):
                        row = routing.fixture_view(experiment, original, None, obs,
                            'trial_fixture', self.ids, mock.Mock())
                    self.assertEqual(screen == exported == guard == 0, row['pixel_verified'])
                    self.assertEqual(7, obs.capture.call_args.args[2])

    def test_routing_views_are_baseline_global_then_optional_later_metadata(self):
        for recovery in ('global_only', 'global_then_metadata_playback', 'global_metadata_then_player_position', None, 'baseline'):
            with self.subTest(recovery=recovery):
                experiment, record, events = run_fixture.experiment(), {}, []

                def call(label, *args, **kwargs):
                    events.append(label)
                    return copy.deepcopy(self.ids) if label == 'routing_target_ids' else {'frame': 100, 'target': [8., 61., 12.]}

                def views(exp, original, positive, obs, label, ids, gate, row):
                    events.append(label)
                    self.assertEqual(self.ids, ids)
                    row['pixel_verified'] = (label == 'routing_baseline' and recovery == 'baseline' or
                                             label == 'routing_global' and recovery == 'global_only' or
                                             label == 'routing_metadata' and recovery == 'global_then_metadata_playback' or
                                             label == 'routing_position' and recovery == 'global_metadata_then_player_position')

                experiment.call.side_effect = call
                gate = mock.Mock(side_effect=[{'probe': {'render_event': 100}}, {'probe': {'render_event': 101}},
                                             {'probe': {'render_event': 102}}])
                with mock.patch.object(routing, 'views', side_effect=views), \
                        mock.patch.object(routing, 'moved_gate', return_value=mock.Mock()), \
                        mock.patch.object(routing.time, 'sleep'):
                    routing.run(experiment, None, None, None, gate, record)
                expected = ['routing_target_fixture_create', 'routing_target_ids', 'routing_baseline',
                            'routing_set_global_only', 'routing_global']
                if recovery != 'global_only':
                    expected += ['routing_metadata_playback_reapply', 'routing_metadata']
                    if recovery != 'global_then_metadata_playback':
                        expected += ['routing_player_relative_position_only', 'routing_position']
                        self.assertEqual(3, gate.call_count)
                    else:
                        self.assertEqual(2, gate.call_count)
                else:
                    gate.assert_not_called()
                self.assertEqual(expected, events)
                self.assertEqual(recovery, record['recovered_at'])
                self.assertEqual(bool(recovery), record['pixel_verified'])
                self.assertTrue(record['completed'])

    def test_no_later_frame_stops_before_metadata_replay(self):
        experiment = run_fixture.experiment()
        experiment.call.side_effect = lambda label, *args, **kwargs: copy.deepcopy(self.ids) if label == 'routing_target_ids' else {'frame': 100}
        with mock.patch.object(routing, 'views', side_effect=lambda *args: args[-1].update(pixel_verified=False)), \
                mock.patch.object(routing.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'later render frame'):
                routing.run(experiment, None, None, None, mock.Mock(return_value={'probe': {'render_event': 100}}), {})
        self.assertNotIn('routing_metadata_playback_reapply', [call.args[0] for call in experiment.call.call_args_list])

    def test_overworld_positive_rejects_failed_analytic_view_but_always_destroys_resets(self):
        for positive in (True, False):
            with self.subTest(positive=positive):
                experiment, record = run_fixture.experiment(), {}

                def call(label, *args, **kwargs):
                    if label == 'routing_overworld_ids':
                        return copy.deepcopy(self.ids)
                    if label == 'routing_overworld_fixture_destroy_reset':
                        return {'fixture': {'entity': None, 'visible': False}, 'control_reset': True}
                    return {}

                experiment.call.side_effect = call
                with mock.patch.object(routing, 'fixture_view', return_value={'pixel_verified': positive}):
                    if positive:
                        routing.preflight(experiment, None, None, None, {}, record)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'analytic positive'):
                            routing.preflight(experiment, None, None, None, {}, record)
                self.assertEqual(['routing_overworld_fixture_create', 'routing_overworld_ids',
                                  'routing_overworld_fixture_destroy_reset'],
                                 [call.args[0] for call in experiment.call.call_args_list])
                self.assertEqual(positive, record['pixel_verified'])

    def test_same_view_order_and_combined_fixture_payload_gate(self):
        for fixture_pass, payload_pass in ((True, True), (False, True), (True, False)):
            with self.subTest(fixture_pass=fixture_pass, payload_pass=payload_pass):
                experiment, record, events = run_fixture.experiment(), {}, []
                experiment.call.side_effect = lambda label, *args, **kwargs: events.append(label) or copy.deepcopy(self.ids)
                obs = types.SimpleNamespace(capture=mock.Mock(side_effect=lambda exp, label, mode, *args:
                    events.append(label) or {'full_payload_comparison': {'exact': payload_pass}}))
                with mock.patch.object(routing, 'fixture_view', side_effect=lambda *args:
                        events.append(args[4]) or {'pixel_verified': fixture_pass}), \
                        mock.patch.object(routing.time, 'sleep'):
                    routing.views(experiment, None, None, obs, 'trial', self.ids, mock.Mock(), record)
                self.assertEqual(['trial_center_ray', 'trial_fixture_m7', 'trial_all_m1_controls', 'trial_all_m1',
                                  'trial_all_m3_controls', 'trial_all_m3', 'trial_ids_after'], events)
                self.assertEqual(fixture_pass and payload_pass, record['pixel_verified'])

    def test_overworld_hook_precedes_initial_arm_routing_replaces_matrix_and_preserves_auto_failure(self):
        experiment, status, events = run_fixture.experiment(), {}, []
        first_report = {'exact': False, 'data_error_pixels': 123}

        def preflight(exp, original, positive, obs, frozen, record):
            events.extend(['ow_fixture_positive', 'ow_fixture_destroy_reset'])
            record['pixel_verified'] = True

        def transit(exp, label, target, player, frozen, original, record):
            events.append('automatic_end')
            exp.dimension = target
            record.update(before={'dimension': 0}, expected_serial=1, request_intent=True,
                          automatic_readback=first_report)
            raise RuntimeError('original automatic end failure')

        def routing_run(exp, original, positive, obs, gate, record):
            events.append('routing')
            record.update(completed=True, pixel_verified=True)

        def call(label, *args, **kwargs):
            if label == 'routing_finally_fixture_destroy_reset':
                events.append('target_fixture_destroy_reset')
                self.assertIn('probe.DestroyEntity', args[0])
            return 'player'

        experiment.call.side_effect = call
        with mock.patch.object(runner.positive, 'current', side_effect=lambda exp, label: run_fixture.snapshot(exp)), \
                mock.patch.object(runner.routing, 'preflight', side_effect=preflight), \
                mock.patch.object(runner.routing, 'run', side_effect=routing_run), \
                mock.patch.object(runner.positive.candidate, 'arm', side_effect=lambda *args: events.append('initial_arm')), \
                mock.patch.object(runner.positive.candidate, 'raw_readback', return_value={'exact': True}), \
                mock.patch.object(runner.target_runner, 'transit', side_effect=transit), \
                mock.patch.object(runner, 'current_gate'), \
                mock.patch.object(runner, 'stage_matrix') as matrix, \
                mock.patch.object(runner, 'fixture_controls') as fixture, \
                mock.patch.object(runner, 'manual_control') as manual, \
                mock.patch.object(runner.target_runner.roundtrip, 'return_to_overworld',
                    side_effect=lambda *args: events.append('return')), \
                mock.patch.object(runner.positive, 'restore', side_effect=lambda *args: events.append('restore') or {'all_exact': True}):
            with self.assertRaisesRegex(RuntimeError, 'retains automatic failure'):
                runner.run(experiment, None, progress=status, sfx_routing=True)
        self.assertEqual(['ow_fixture_positive', 'ow_fixture_destroy_reset', 'initial_arm', 'automatic_end',
                          'routing', 'target_fixture_destroy_reset', 'return', 'restore'], events)
        matrix.assert_not_called()
        fixture.assert_not_called()
        manual.assert_not_called()
        self.assertTrue(status['diagnostics_completed'])
        self.assertTrue(status['routing']['pixel_verified'])
        self.assertFalse(status['pixel_verified'])
        self.assertIs(first_report, status['trips'][0]['outbound']['automatic_readback'])
        self.assertIn('original automatic end failure', status['trips'][0]['outbound_failure'])

    def test_failed_overworld_positive_prevents_arm_and_transit_but_restores(self):
        experiment, status = run_fixture.experiment(), {}
        with mock.patch.object(runner.positive, 'current', side_effect=lambda exp, label: run_fixture.snapshot(exp)), \
                mock.patch.object(runner.routing, 'preflight', side_effect=RuntimeError('preflight analytic failure')), \
                mock.patch.object(runner.positive.candidate, 'arm') as arm, \
                mock.patch.object(runner.target_runner, 'transit') as transit, \
                mock.patch.object(runner.positive, 'restore', return_value={'all_exact': True}) as restore:
            with self.assertRaisesRegex(RuntimeError, 'preflight analytic failure'):
                runner.run(experiment, None, progress=status, sfx_routing=True)
        arm.assert_not_called()
        transit.assert_not_called()
        restore.assert_called_once_with(experiment)

    def test_routing_selector_defaults_false_and_rejects_nonbool_before_initializing(self):
        self.assertIs(runner.run.__defaults__[-1], False)
        for selector in (None, 1, 'yes'):
            experiment = run_fixture.experiment()
            with self.assertRaises(ValueError):
                runner.run(experiment, None, sfx_routing=selector)
            experiment.initialize.assert_not_called()

    def test_moved_gate_accepts_recorded_lower_y_and_rejects_pose_identity_transition_or_target_drift(self):
        experiment = run_fixture.experiment()
        reference = ready_snapshot(experiment)
        target = [8., 60.62, 12.]
        reference['player_position'] = [8., 61.62, 8.]
        # This target deliberately lies below the old common positive-pose
        # effect bounds; only the newly recorded target is authoritative.
        value = copy.deepcopy(reference)
        value['effect_positions'] = [target]*3
        experiment.call.return_value = [target]*4
        gate = routing.moved_gate(experiment, runner.positive, reference, self.ids, target)
        with mock.patch.object(runner.positive, 'current', return_value=value):
            result = gate('moved')
        self.assertEqual([target]*4, result['routing_effect_positions'])
        cases = [('camera', [8., 72.1, 5.]), ('anchor', [8., 71.48, 7.97]),
                 ('dimension', 1), ('identity', {}), ('generation', 2),
                 ('serial', 2), ('pair', [1, 2])]
        for key, changed in cases:
            with self.subTest(key=key):
                bad = copy.deepcopy(value)
                if key in ('identity', 'generation'):
                    bad['probe'][key] = changed
                elif key in ('serial', 'pair'):
                    bad['probe']['dimension_recovery'][key] = changed
                else:
                    bad[key] = changed
                with mock.patch.object(runner.positive, 'current', return_value=bad):
                    with self.assertRaises(RuntimeError):
                        gate('bad')
        for positions in ([target]*3, [target]*3+[[8., 60.7, 12.]], [target]*3+[[8., float('nan'), 12.]]):
            experiment.call.return_value = positions
            with mock.patch.object(runner.positive, 'current', return_value=value):
                with self.assertRaisesRegex(RuntimeError, 'positions differ'):
                    gate('wrong_target')


class ObservationalOracleTests(unittest.TestCase):
    viewport = [8, 132]
    roi = [0, 0, 8, 2]
    payload = bytes([0, 85, 170, 255])

    def image(self, mode):
        count = len(self.payload)*(1 if mode == 1 else 4)
        pixels = np.zeros((132, 8, 3), dtype=np.uint8)
        output = pixels[128:].reshape(-1, 3)
        output[:] = [17, 53, 97]
        output[:count] = [0, 43, 17] if mode == 1 else [0, 192, 0]
        return Image.fromarray(pixels)

    def test_partial_predictions_select_independent_interleaved_bits(self):
        payload = bytes([0, 1, 2, 3, 85, 170, 255])
        self.assertEqual(bytes(7), observations.predicted_payload('base', payload))
        self.assertEqual(bytes(7), observations.predicted_payload('readers_only', payload))
        self.assertEqual(bytes([0, 1, 0, 1, 85, 0, 85]), observations.predicted_payload('bit64', payload))
        self.assertEqual(bytes([0, 0, 2, 2, 0, 170, 170]), observations.predicted_payload('bit128', payload))
        self.assertEqual(payload, observations.predicted_payload('all', payload))
        self.assertIsNone(observations.predicted_payload('off', payload))
        self.assertIsNone(observations.predicted_payload('writers_only', payload))

    def test_partial_stage_mode1_and_mode3_mismatches_are_observations(self):
        for mode in (1, 3):
            with self.subTest(mode=mode):
                verifier = mock.Mock(return_value={'exact': False, 'data_error_pixels': 3})
                result = observations.summarize(self.image(mode), mode, self.payload,
                    self.viewport, self.roi, verifier)
                self.assertFalse(result['exact_asserted'])
                self.assertFalse(result['full_payload_comparison']['exact'])
                self.assertEqual(0, result['guard_error_pixels'])
                verifier.assert_called_once()
                self.assertEqual(128, verifier.call_args.kwargs['output_y'])
                self.assertFalse(verifier.call_args.kwargs['fixture'])

    def test_mode7_records_raw_rgb_without_analytic_fixture_verification(self):
        verifier = mock.Mock(side_effect=AssertionError('Natural RGB has no analytic fixture'))
        result = observations.summarize(self.image(7), 7, self.payload,
            self.viewport, self.roi, verifier, output_y=128)
        verifier.assert_not_called()
        self.assertFalse(result['exact_asserted'])
        self.assertFalse(result['analytic_fixture_reference_asserted'])
        self.assertEqual(16, result['raw_green_or_blue_above63_pixels'])
        self.assertEqual(0, result['guard_error_pixels'])

    def test_guard_damage_and_short_native_images_are_reported_or_rejected(self):
        pixels = np.asarray(self.image(1)).copy()
        pixels[-1, -1] = [0, 0, 0]
        result = observations.summarize(Image.fromarray(pixels), 1, self.payload,
            self.viewport, self.roi, mock.Mock(return_value={'exact': False}))
        self.assertEqual(1, result['guard_error_pixels'])
        with self.assertRaises(ValueError):
            observations.summarize(Image.new('RGB', (8, 131)), 1, self.payload,
                self.viewport, self.roi, mock.Mock())

    def test_passive_capture_accepts_partial_data_but_rejects_invalid_freshness_or_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.image(1).save(root/'stage.png')
            receipt = {'ok': True, 'backend': 'Windows.Graphics.Capture',
                'width': 8, 'height': 132, 'frame_qpc_100ns': 200,
                'request_qpc_100ns': 100, 'agent_activation_allowed': False,
                'background_before': {'window_noactivate': True},
                'background_after': {'window_noactivate': True}}
            experiment = types.SimpleNamespace(args=types.SimpleNamespace(project=root),
                evidence=root, viewport=self.viewport, roi=self.roi, payload=self.payload,
                invoke=mock.Mock(), state={'consumer_mode': 1}, reports=[], save=mock.Mock())
            original = types.SimpleNamespace(integrated=types.SimpleNamespace(verify_module=
                types.SimpleNamespace(verify=mock.Mock(return_value={'exact': False}))))
            positive = types.SimpleNamespace(COMPAT=root)
            (root/'stage.json').write_text(json.dumps(receipt), encoding='utf-8')
            row = observations.capture(experiment, 'stage', 1, original, positive)
            self.assertTrue(row['intentional_stage_observation'])
            self.assertFalse(row['exact_asserted'])
            self.assertFalse(row['full_payload_comparison']['exact'])
            self.assertEqual([row], experiment.reports)
            for key, value in (('ok', False), ('backend', 'other'), ('width', 9),
                                ('frame_qpc_100ns', 99), ('agent_activation_allowed', True),
                                ('background_after', {'window_noactivate': False})):
                with self.subTest(key=key):
                    (root/'stage.json').write_text(json.dumps(dict(receipt, **{key: value})), encoding='utf-8')
                    experiment.save.reset_mock()
                    with self.assertRaisesRegex(RuntimeError, 'fresh passive owned noactivation'):
                        observations.capture(experiment, 'stage', 1, original, positive)
                    experiment.save.assert_not_called()
                    self.assertEqual([row], experiment.reports)

    def test_known_fixture_predictions_are_observations_with_explicit_partial_compression(self):
        fixture_rgb = np.asarray([[1, 128, 255], [192, 63, 17], [33, 64, 191], [255, 0, 42]]*4, dtype=np.uint8)
        verify_module = types.SimpleNamespace(fixture_rgba=lambda roi:
            np.column_stack((fixture_rgb, np.full(16, 255, dtype=np.uint8))))
        payload = np.frombuffer(self.payload, dtype=np.uint8)
        symbols = np.asarray([(int(value) >> shift) & 3 for value in payload for shift in (0, 2, 4, 6)], dtype=np.uint8)
        for stage in ('off', 'base', 'all'):
            with self.subTest(stage=stage):
                expected = fixture_rgb.copy()
                if stage != 'off':
                    expected = np.rint(expected.astype(float)*63/255).astype(np.uint8)
                    if stage == 'all':
                        expected[:, 0] += symbols*64
                viewport, roi = [8, 654], [0, 128, 8, 2]
                pixels = np.zeros((654, 8, 3), dtype=np.uint8)
                pixels[128:130] = expected.reshape(2, 8, 3)
                pixels[650:].reshape(-1, 3)[:16] = expected
                result = observations.fixture_comparison(Image.fromarray(pixels), stage,
                    self.payload, viewport, roi, verify_module)
                self.assertEqual(0, result['screen_roi']['data_error_pixels'])
                self.assertEqual(0, result['exported_t3']['data_error_pixels'])
                self.assertEqual(0, result['same_frame_different_pixels'])
                self.assertEqual(650, result['export_output_y'])
                self.assertFalse(result['exact_asserted'])
                pixels[650, 0, 0] += 3
                damaged = observations.fixture_comparison(Image.fromarray(pixels), stage,
                    self.payload, viewport, roi, verify_module)
                self.assertEqual(0, damaged['screen_roi']['data_error_pixels'])
                self.assertEqual(1, damaged['exported_t3']['data_error_pixels'])
                self.assertEqual(1, damaged['same_frame_different_pixels'])

    def test_mode7_capture_at_y650_preserves_exact_screen_fixture_and_detects_bad_t3(self):
        with tempfile.TemporaryDirectory() as directory:
            root, viewport, roi = Path(directory), [8, 654], [0, 128, 8, 2]
            expected = np.asarray([[1, 128, 255], [192, 63, 17], [33, 64, 191], [255, 0, 42]]*4, dtype=np.uint8)
            pixels = np.zeros((654, 8, 3), dtype=np.uint8)
            pixels[128:130] = expected.reshape(2, 8, 3)
            pixels[650:] = [17, 53, 97]
            pixels[650:].reshape(-1, 3)[:16] = expected
            pixels[650, 0, 0] += 7
            Image.fromarray(pixels).save(root/'raw.png')
            receipt = {'ok': True, 'backend': 'Windows.Graphics.Capture', 'width': 8, 'height': 654,
                'frame_qpc_100ns': 200, 'request_qpc_100ns': 100, 'agent_activation_allowed': False,
                'background_before': {'window_noactivate': True}, 'background_after': {'window_noactivate': True}}
            (root/'raw.json').write_text(json.dumps(receipt), encoding='utf-8')
            experiment = types.SimpleNamespace(args=types.SimpleNamespace(project=root),
                evidence=root, viewport=viewport, roi=roi, payload=self.payload,
                invoke=mock.Mock(), state={'consumer_mode': 7}, reports=[], save=mock.Mock())
            verifier = mock.Mock(side_effect=AssertionError('Raw natural export is observational'))
            verify_module = types.SimpleNamespace(verify=verifier, fixture_rgba=lambda roi:
                np.column_stack((expected, np.full(16, 255, dtype=np.uint8))))
            original = types.SimpleNamespace(integrated=types.SimpleNamespace(verify_module=verify_module))
            row = observations.capture(experiment, 'raw', 7, original, types.SimpleNamespace(COMPAT=root))
            self.assertEqual([0, 650], row['output_origin'])
            self.assertEqual(0, row['guard_error_pixels'])
            self.assertEqual(1, row['same_frame_screen_roi']['different_pixels_vs_t3'])
            self.assertFalse(row['same_frame_screen_roi']['separate_frame_comparison'])
            verifier.assert_not_called()
            result = observations.fixture_comparison(Image.fromarray(pixels), 'off',
                self.payload, viewport, roi, verify_module)
            self.assertEqual(0, result['screen_roi']['data_error_pixels'])
            self.assertEqual(1, result['exported_t3']['data_error_pixels'])
            self.assertEqual(1, result['same_frame_different_pixels'])
            self.assertFalse(result['exact_asserted'])


def ready_snapshot(experiment, target=2, frame=101):
    value = run_fixture.snapshot(experiment)
    value['dimension'] = target
    value['probe'].update(render_event=frame, consumer_mode=1)
    value['probe']['dimension_recovery'].update(phase='ready', serial=1,
        ready_serial=1, pair=[0, target])
    return value


class OrchestrationTests(unittest.TestCase):
    def run_case(self, target=2, automatic_failure=True, image=True, stage_failure=False,
                 manual_failure=False):
        experiment, progress, events = run_fixture.experiment(), {}, []
        automatic = {'label': 'first_automatic', 'exact': not automatic_failure, 'data_error_pixels': 12}

        def transit(exp, label, destination, player, frozen, original, record):
            events.append(('automatic', destination))
            exp.dimension = destination
            record.update(before={'dimension': 0}, expected_serial=1, request_intent=True,
                          pixel_verified=not automatic_failure)
            if image:
                record['automatic_readback'] = automatic
            if automatic_failure:
                raise RuntimeError('preserved first automatic failure')

        def stages(exp, original, frozen, serial, pair, rows):
            events.append('stages')
            if stage_failure:
                raise RuntimeError('stage observation failed')
            rows.extend({'readback': {'full_payload_comparison': {'exact': False}}} for _ in range(21))

        def fixtures(exp, original, frozen, serial, pair, rows):
            events.append('fixture')
            rows.extend({'readback': {}} for _ in range(3))

        def manual(exp, original, frozen, serial, pair, record):
            events.append('manual')
            if manual_failure:
                raise RuntimeError('manual control failed')
            record.update(pixel_verified=True, completed=True, recovered_at='A_relink',
                          checkpoints=[{'name': 'A_relink', 'captures': [{'mode': 1}, {'mode': 3}]}])

        def home(exp, original, player, frozen, row):
            events.append('return')
            exp.dimension = 0
            row['return']['pixel_verified'] = True

        with mock.patch.object(runner.positive, 'current', side_effect=lambda exp, label: run_fixture.snapshot(exp)), \
                mock.patch.object(runner.positive.candidate, 'arm'), \
                mock.patch.object(runner.positive.candidate, 'raw_readback', return_value={'exact': True}), \
                mock.patch.object(runner.target_runner, 'transit', side_effect=transit), \
                mock.patch.object(runner, 'current_gate'), \
                mock.patch.object(runner, 'stage_matrix', side_effect=stages), \
                mock.patch.object(runner, 'fixture_controls', side_effect=fixtures), \
                mock.patch.object(runner, 'manual_control', side_effect=manual), \
                mock.patch.object(runner.target_runner.roundtrip, 'return_to_overworld', side_effect=home), \
                mock.patch.object(runner.positive, 'restore', side_effect=lambda exp: events.append('restore') or {'all_exact': True}):
            if automatic_failure or not image or stage_failure or manual_failure:
                with self.assertRaises(RuntimeError):
                    runner.run(experiment, None, target=target, progress=progress)
            else:
                runner.run(experiment, None, target=target, progress=progress)
        return experiment, progress, events, automatic

    def test_end_default_orders_observations_manual_return_cleanup_without_reclassifying_failure(self):
        experiment, progress, events, automatic = self.run_case()
        self.assertEqual([('automatic', 2), 'stages', 'fixture', 'manual', 'return', 'restore'], events)
        self.assertEqual([0, 2, 0], progress['planned_dimensions'])
        self.assertTrue(progress['diagnostics_completed'])
        self.assertTrue(progress['manual_control']['pixel_verified'])
        self.assertFalse(progress['pixel_verified'])
        self.assertIn('preserved first automatic failure', progress['trips'][0]['outbound_failure'])
        self.assertIs(automatic, progress['trips'][0]['outbound']['automatic_readback'])
        self.assertEqual({'label': 'first_automatic', 'exact': False, 'data_error_pixels': 12}, automatic)
        self.assertTrue(progress['cleanup']['all_exact'])
        self.assertEqual(1, progress['resident_payload_uploads'])
        experiment.initialize.assert_called_once_with()

    def test_optional_nether_runs_only_one_nether_trip(self):
        _, progress, events, _ = self.run_case(target=1, automatic_failure=False)
        self.assertEqual([('automatic', 1), 'stages', 'fixture', 'manual', 'return', 'restore'], events)
        self.assertEqual([0, 1, 0], progress['planned_dimensions'])
        self.assertTrue(progress['pixel_verified'])

    def test_no_actual_first_image_skips_all_diagnostics_but_returns_and_restores(self):
        _, progress, events, _ = self.run_case(image=False)
        self.assertEqual([('automatic', 2), 'return', 'restore'], events)
        self.assertFalse(progress['diagnostics_completed'])
        self.assertFalse(progress['pixel_verified'])

    def test_stage_or_manual_failure_does_not_block_other_evidence_return_and_cleanup(self):
        for stage_failed, manual_failed in ((True, False), (False, True)):
            with self.subTest(stage_failed=stage_failed, manual_failed=manual_failed):
                _, progress, events, _ = self.run_case(stage_failure=stage_failed, manual_failure=manual_failed)
                self.assertEqual([('automatic', 2), 'stages', 'fixture', 'manual', 'return', 'restore'], events)
                self.assertFalse(progress['diagnostics_completed'])
                self.assertIn('preserved first automatic failure', progress['trips'][0]['outbound_failure'])

    def test_invalid_targets_reject_before_initialization(self):
        for target in (0, True, 3, None):
            with self.subTest(target=target):
                experiment = run_fixture.experiment()
                with self.assertRaises(ValueError):
                    runner.run(experiment, None, target=target)
                experiment.initialize.assert_not_called()

    def test_stage_matrix_records_every_ordered_combination_without_exact_requirement(self):
        experiment, rows, mode = run_fixture.experiment(), [], [1]

        def control(label, code, **kwargs):
            mode[0] = int(label.split('_m')[1].split('_')[0])
            return {'frame': 100}

        experiment.call.side_effect = control
        with mock.patch.object(runner, 'current_gate', side_effect=lambda *args: {'probe': {'consumer_mode': mode[0]}}), \
                mock.patch.object(runner.observations, 'predicted_payload', return_value=None), \
                mock.patch.object(runner.observations, 'capture', side_effect=lambda exp, label, mode, *args:
                    {'mode': mode, 'full_payload_comparison': {'exact': False}}) as capture, \
                mock.patch.object(runner.time, 'sleep'):
            runner.stage_matrix(experiment, None, {}, 1, [0, 2], rows)
        self.assertEqual([(stage, mode) for stage in observations.STAGES for mode in (1, 3, 7)],
                         [(row['stage'], row['mode']) for row in rows])
        self.assertEqual(21, capture.call_count)
        self.assertTrue(all(row['readback']['full_payload_comparison']['exact'] is False for row in rows))

    def test_fixture_is_disabled_after_capture_failure(self):
        experiment, rows = run_fixture.experiment(), []
        with mock.patch.object(runner, 'current_gate'), \
                mock.patch.object(runner.observations, 'capture', side_effect=RuntimeError('capture failed')), \
                mock.patch.object(runner.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'capture failed'):
                runner.fixture_controls(experiment, None, {}, 1, [0, 2], rows)
        self.assertEqual('known_fixture_finally_off', experiment.call.call_args.args[0])
        self.assertEqual('probe.configure_known_fixture(False)', experiment.call.call_args.args[1])
        self.assertEqual(1, len(rows))

    def test_manual_checkpoints_wait_then_stop_at_first_mode1_and_mode3_exact(self):
        names = ['A_relink', 'B_effects', 'C_holders']
        for recovered_at in names+[None]:
            with self.subTest(recovered_at=recovered_at):
                experiment, record, events = run_fixture.experiment(), {}, []
                frozen = runner.positive.static_identity(experiment.state)

                def call(label, *args, **kwargs):
                    events.append(label)
                    return {'frame': 100}

                def gate(exp, label, *args):
                    frame = 100 if '_later_frame_0' in label else 101
                    return ready_snapshot(experiment, frame=frame)

                experiment.call.side_effect = call
                with mock.patch.object(runner, 'current_gate', side_effect=gate), \
                        mock.patch.object(runner.positive, 'current', side_effect=gate), \
                        mock.patch.object(runner.observations, 'capture', side_effect=lambda exp, label, mode, *args:
                            {'mode': mode, 'full_payload_comparison': {'exact': bool(recovered_at and label.startswith(recovered_at))}}) as capture, \
                        mock.patch.object(runner.time, 'sleep') as sleep:
                    runner.manual_control(experiment, None, frozen, 1, [0, 2], record)
                expected = names[:names.index(recovered_at)+1] if recovered_at else names
                self.assertEqual(expected, [row['name'] for row in record['checkpoints']])
                self.assertEqual([item for name in expected for item in
                    (name+'_explicit', name+'_m1_controls', name+'_m3_controls')], events)
                self.assertEqual([value for name in expected for value in (.25, .25, .6, .6)],
                                 [call.args[0] for call in sleep.call_args_list])
                self.assertEqual(2*len(expected), capture.call_count)
                self.assertFalse(record['automatic_recovery_reclassified'])
                self.assertEqual(bool(recovered_at), record['pixel_verified'])
                self.assertEqual(recovered_at, record['recovered_at'])
                self.assertTrue(record['completed'])

    def test_manual_no_later_frame_prevents_relink_and_capture(self):
        experiment, record = run_fixture.experiment(), {}
        frozen = runner.positive.static_identity(experiment.state)
        experiment.call.return_value = {'frame': 100}
        with mock.patch.object(runner, 'current_gate', return_value=ready_snapshot(experiment, frame=100)), \
                mock.patch.object(runner.positive, 'current', return_value=ready_snapshot(experiment, frame=100)), \
                mock.patch.object(runner.observations, 'capture') as capture, \
                mock.patch.object(runner.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'later render frame'):
                runner.manual_control(experiment, None, frozen, 1, [0, 2], record)
        self.assertEqual(['A_relink_explicit'], [call.args[0] for call in experiment.call.call_args_list])
        capture.assert_not_called()

    def test_manual_later_frames_with_transient_unready_state_wait_before_capture(self):
        experiment, record = run_fixture.experiment(), {}
        frozen = runner.positive.static_identity(experiment.state)
        waiting = [ready_snapshot(experiment, frame=frame) for frame in (101, 102, 103)]
        waiting[0]['probe']['ready'] = waiting[1]['probe']['ready'] = False
        experiment.call.return_value = {'frame': 100}
        with mock.patch.object(runner, 'current_gate', return_value=ready_snapshot(experiment)), \
                mock.patch.object(runner.positive, 'current', side_effect=waiting) as current, \
                mock.patch.object(runner.observations, 'capture', side_effect=lambda exp, label, mode, *args:
                    {'mode': mode, 'full_payload_comparison': {'exact': True}}) as capture, \
                mock.patch.object(runner.time, 'sleep') as sleep:
            runner.manual_control(experiment, None, frozen, 1, [0, 2], record)
        self.assertEqual(3, current.call_count)
        self.assertEqual([.25, .25, .25, .6, .6], [call.args[0] for call in sleep.call_args_list])
        self.assertEqual(2, capture.call_count)
        self.assertEqual('A_relink', record['recovered_at'])

    def test_current_gate_rejects_changed_payload_generation_attempts_pages_or_transition(self):
        experiment = run_fixture.experiment()
        value = ready_snapshot(experiment)
        frozen = runner.positive.static_identity(value['probe'])
        for key, changed in (('identity', {}), ('generation', 2), ('native_attempt_count', 4),
                                ('native_page_names', ['other'])):
            with self.subTest(key=key):
                bad = copy.deepcopy(value)
                bad['probe'][key] = changed
                with mock.patch.object(runner.positive, 'current', return_value=bad):
                    with self.assertRaises(RuntimeError):
                        runner.current_gate(experiment, 'check', frozen, 1, [0, 2])
        for dimension, serial in ((1, 1), (2, 2)):
            bad = copy.deepcopy(value)
            bad['dimension'] = dimension
            bad['probe']['dimension_recovery']['serial'] = serial
            with mock.patch.object(runner.positive, 'current', return_value=bad):
                with self.assertRaises(RuntimeError):
                    runner.current_gate(experiment, 'check', frozen, 1, [0, 2])


if __name__ == '__main__':
    unittest.main()
