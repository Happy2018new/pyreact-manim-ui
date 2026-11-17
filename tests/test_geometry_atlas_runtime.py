"""Public world-upload lifecycle and immutable indexed-gather source contracts."""
import copy
import importlib.util
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'tools/geometry_atlas_probe'


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClientSystem:
    def __init__(self, *args):
        self.events, self.created, self.destroyed = [], [], []
        self.entity_result = 'client-anchor-1'

    def ListenForEvent(self, *args):
        self.events.append(args)

    def UnListenForEvent(self, *args):
        self.events.remove(args)

    def CreateClientEntityByTypeStr(self, identifier, position, rotation):
        self.created.append((identifier, position, rotation))
        return self.entity_result

    def DestroyClientEntity(self, entity):
        self.destroyed.append(entity)
        # Public API returns None, so cleanup must not demand a truthy result.


class PostProcess:
    def __init__(self):
        self.added, self.parameters, self.enables, self.connections = [], [], [], []
        self.order = []
        self.add_ok, self.enable_ok, self.connection_ok = True, True, True
        self.fail_parameter = None

    def AddPostProcess(self, definition):
        self.added.append(copy.deepcopy(definition))
        return self.add_ok

    def GetPostProcessOrder(self):
        return list(self.order)

    def SetEnableByName(self, name, enabled):
        self.enables.append((name, enabled))
        return self.enable_ok

    def PostPassResultToOtherPass(self, *args):
        self.connections.append(args)
        return self.connection_ok

    def SetParameter(self, name, key, value):
        self.parameters.append((name, key, list(value)))
        return key != self.fail_parameter


class Palette:
    def __init__(self, factory):
        self.factory = factory

    def DeserializeBlockPalette(self, data):
        self.factory.palettes.append(data)
        return self.factory.deserialize_ok


class Factory:
    def __init__(self):
        self.post = PostProcess()
        self.palettes, self.combines, self.attachments = [], [], []
        self.uniforms, self.visibility, self.shadows = [], [], []
        self.transparency_enabled, self.transparencies = [], []
        self.uniform_ok, self.deserialize_ok, self.combine_ok, self.attach_ok = True, True, True, True
        self.transparent_ok, self.transparency_ok = True, True
        self.blank_ok = True
        self.hide_fail_names = set()
        self.camera_position, self.camera_forward = (10., 20., 30.), (0., 0., -1.)

    def CreateGame(self, level):
        return self

    def GetScreenSize(self):
        return (360., 540.)

    def GetFps(self):
        return 60.

    def CreateBlock(self, level):
        return self

    def CreateBlockGeometry(self, level):
        return self

    def CreatePostProcess(self, level):
        return self.post

    def CreateCamera(self, level):
        return self

    def GetPosition(self):
        return self.camera_position

    def GetForward(self):
        return self.camera_forward

    def CreateActorRender(self, entity):
        return self

    def CreateModel(self, entity):
        return self

    def SetEntityShadowShow(self, enabled):
        self.shadows.append(enabled)

    def SetEntityExtraUniforms(self, index, value):
        self.uniforms.append((index, value))
        return self.uniform_ok

    def GetBlankBlockPalette(self):
        return Palette(self) if self.blank_ok else None

    def CombineBlockPaletteToGeometry(self, palette, name, mode):
        self.combines.append((name, mode))
        return name if self.combine_ok else None

    def AddActorBlockGeometry(self, name, offset, rotation):
        self.attachments.append((name, offset, rotation))
        return self.attach_ok

    def SetActorBlockGeometryVisible(self, name, visible):
        self.visibility.append((name, visible))
        return name not in self.hide_fail_names

    def EnableActorBlockGeometryTransparent(self, name, enabled):
        self.transparency_enabled.append((name, enabled))
        return self.transparent_ok

    def SetActorBlockGeometryTransparency(self, name, value):
        self.transparencies.append((name, value))
        return self.transparency_ok


class GeometryAtlasRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.factory = Factory()
        self.now = 100.
        self.hud_calls = []
        api = types.ModuleType('mod.client.extraClientApi')
        api.GetClientSystemCls = lambda: ClientSystem
        api.GetEngineCompFactory = lambda: self.factory
        api.GetLevelId = lambda: 'level'
        api.GetEngineNamespace = lambda: 'Minecraft'
        api.GetEngineSystemName = lambda: 'engine'
        # HideHudGUI has a void return, including when the request succeeds.
        api.HideHudGUI = lambda hidden: self.hud_calls.append(hidden)
        builder = load_module('_geometry_atlas_runtime_builder', PROBE / 'build_probe.py')
        pipeline = types.ModuleType('geometry_atlas_probe.pipeline_config')
        pipeline.PROCESS = builder.pipeline_config()
        package = types.ModuleType('geometry_atlas_probe')
        package.__path__ = [str(PROBE)]
        codec = load_module('_geometry_atlas_runtime_codec', PROBE.parent / 'geometry_packet_probe/codec.py')
        modules = patch.dict(sys.modules, {
            'mod': types.ModuleType('mod'), 'mod.client': types.ModuleType('mod.client'),
            'mod.client.extraClientApi': api,
            'geometry_atlas_probe': package,
            'geometry_atlas_probe.codec': codec, 'geometry_atlas_probe.pipeline_config': pipeline})
        modules.start()
        self.addCleanup(modules.stop)
        clock = patch.object(time, 'clock', lambda: self.now, create=True)
        clock.start()
        self.addCleanup(clock.stop)
        self.runtime = load_module('_geometry_atlas_runtime_contract', PROBE / 'runtime.py')
        self.probe = self.runtime.ProbeSystem('probe', 'test')

    def ready(self, count=256, generation=1):
        self.probe.open()
        return self.probe.load(count, seed=54321, generation=generation)

    def pipeline(self):
        self.probe.install_pipeline()
        self.factory.post.order = ['pmanim_geometry_atlas_gather']
        return self.probe.finish_pipeline()

    @staticmethod
    def identity(state):
        return {key: state[key] for key in ('seed', 'generation', 'slot_count', 'geometry_name',
                                          'geometry_build_serial', 'encoding', 'upload_history')}

    def test_async_actor_readiness_retries_then_times_out_without_upload(self):
        self.factory.uniform_ok = False
        state = self.probe.open()
        self.assertFalse(state['ready'])
        self.assertIsNone(state['error'])
        self.assertEqual(self.probe.created,
                         [('pmanim_geometry_atlas:anchor', (10., 20., 27.), (0., 0.))])
        self.assertEqual(self.factory.shadows, [False])
        with self.assertRaisesRegex(RuntimeError, 'wait for actor readiness'):
            self.probe.load(256)
        self.now += .2
        self.factory.uniform_ok = True
        self.probe.on_frame({})
        self.assertTrue(self.probe.snapshot()['ready'])
        self.assertEqual(len(self.probe.created), 1)
        self.assertEqual([index for index, _ in self.factory.uniforms[-4:]], [1, 2, 3, 4])
        other = self.runtime.ProbeSystem('probe', 'timeout')
        self.factory.uniform_ok = False
        other.open()
        self.now += 10.1
        other.on_frame({})
        failed = other.snapshot()
        self.assertFalse(failed['ready'])
        self.assertIn('timeout', failed['error'])
        calls = len(self.factory.uniforms)
        self.factory.uniform_ok = True
        other.on_frame({})
        self.assertFalse(other.snapshot()['ready'])
        self.assertEqual(len(self.factory.uniforms), calls)
        self.assertEqual(self.factory.combines, [])

    def test_world_upload_renames_codec_and_packs_calibrated_atlas_controls(self):
        self.assertEqual(self.probe.snapshot()['center'], [1., .5, .5])
        state = self.ready(273)
        self.assertEqual(state['center'], [1., .5, .5])
        self.assertEqual(state['layout'], [273, 64, 8, 64])
        self.assertEqual(state['dimensions'], [4, 720, 1080, 0])
        self.assertEqual(self.factory.uniforms[-4:], [
            (1, (32., 8., 273., 64.)), (2, (8., 64., 4., 720.)),
            (3, (1080., 1., .5, .5)), (4, (1., 0., 0., 0.))])
        palette = self.factory.palettes[-1]
        self.assertEqual(palette['volume'], (32, 32, 16))
        recovered = {}
        for (identifier, aux), addresses in palette['common'].items():
            self.assertTrue(identifier.startswith('pmanim_geometry_atlas:quad_compact8_'))
            self.assertEqual(aux, 0)
            template = int(identifier.rsplit('_', 1)[1])
            for address in addresses:
                high, record = divmod(address, 1024)
                self.assertNotIn(record, recovered)
                recovered[record] = high * 16 + template
        self.assertEqual([recovered[index] for index in range(273)],
                         [self.runtime.byte_at(54321, 1, index) for index in range(273)])
        self.assertEqual(self.factory.attachments[-1],
                         (state['geometry_name'], (0., 0., 0.), (0., 0., 0.)))
        self.assertFalse(state['gpu_verified'])
        self.assertFalse(state['gpu_to_python_readback'])

    def test_fresh_names_hide_old_writer_and_session_budgets_survive_new_dataset(self):
        first = self.ready(256)
        second = self.probe.load(273, seed=99, generation=2)
        self.assertNotEqual(first['geometry_name'], second['geometry_name'])
        self.assertEqual(second['geometry_build_serial'], 2)
        self.assertIn((first['geometry_name'], False), self.factory.visibility)
        self.assertEqual(second['resource_budget']['names'], 2)
        self.assertEqual(second['resource_budget']['named_records'], 529)
        self.assertEqual(second['upload_history'][-1]['seed'], 99)
        budget = copy.deepcopy(second['resource_budget'])
        empty = self.probe.begin_dataset()
        self.assertEqual(empty['resource_budget'], budget)
        self.assertEqual(empty['geometry_build_serial'], 2)
        self.assertEqual(empty['upload_history'], [])
        self.assertEqual(empty['geometry_name'], '')
        self.assertEqual(empty['slot_count'], 0)
        self.assertIn((second['geometry_name'], False), self.factory.visibility)
        next_dataset = self.probe.load(256, generation=3)
        self.assertIn('epoch1_version3', next_dataset['geometry_name'])
        self.assertEqual(next_dataset['resource_budget']['named_records'], 785)
        self.assertFalse(next_dataset['resource_budget']['native_reclamation_verified'])
        for field, limit in (('MAX_NAMES', len(self.probe.names)),
                             ('MAX_RECORDS', self.probe.named_records + 255)):
            calls = len(self.factory.combines)
            with patch.object(self.runtime, field, limit):
                with self.assertRaisesRegex(RuntimeError, 'budget exhausted'):
                    self.probe.load(256)
            self.assertEqual(len(self.factory.combines), calls)

    def test_three_pass_pipeline_waits_for_registration_and_connects_copy_to_nonadjacent_consumer(self):
        self.ready()
        with self.assertRaisesRegex(RuntimeError, 'preceding render turn'):
            self.probe.finish_pipeline()
        state = self.probe.install_pipeline()
        self.assertTrue(state['pipeline_installed'])
        self.assertFalse(state['pipeline_ready'])
        definition = self.factory.post.added[0]
        self.assertFalse(definition['enable'])
        self.assertEqual([item['name'] for item in definition['paras']], ['query', 'layout', 'dimensions'])
        self.assertEqual([item['material'] for item in definition['pass_array']],
                         ['pmanim_geometry_atlas_copy', 'pmanim_geometry_atlas_poison',
                          'pmanim_geometry_atlas_consumer'])
        with self.assertRaisesRegex(RuntimeError, 'not settled'):
            self.probe.finish_pipeline()
        self.assertEqual(self.factory.post.connections, [])
        self.factory.post.order = [definition['name']]
        state = self.probe.finish_pipeline()
        self.assertTrue(state['pipeline_ready'])
        self.assertTrue(state['connection'])
        self.assertEqual(self.factory.post.connections,
                         [('pmanim_geometry_atlas_gather', 0, 'pmanim_geometry_atlas_gather', 2, 3)])
        self.assertEqual([key for _, key, _ in self.factory.post.parameters[-3:]],
                         ['query', 'layout', 'dimensions'])

    def test_queries_and_rgb_negative_controls_leave_resident_source_identity_unchanged(self):
        self.ready(4096)
        before = self.pipeline()
        identity = copy.deepcopy(self.identity(before))
        counts = (len(self.factory.palettes), len(self.factory.combines), len(self.factory.attachments))
        state = self.probe.query(127, 2048, mode=2, salt=37, salt2=91,
                                 flip_y=True, channel_mode=1, direct_source=True)
        self.assertEqual(self.identity(state), identity)
        self.assertEqual(state['packed_mode'], 2 + 4 + 8 + 16)
        self.assertEqual(state['dimensions'][3], 91)
        self.assertEqual(self.factory.post.parameters[-3][2], [127., 2048., 30., 37.])
        self.assertEqual(self.factory.post.parameters[-1][2], [4., 720., 1080., 91.])
        hidden = self.probe.set_writer_visible(False)
        self.assertEqual(self.factory.uniforms[-1], (4, (0., 0., 0., 0.)))
        self.assertEqual(self.identity(hidden), identity)
        rgb = self.probe.query(0, 256, mode=3)
        self.assertEqual(self.identity(rgb), identity)
        self.probe.set_writer_visible(True)
        self.assertEqual(self.identity(self.probe.snapshot()), identity)
        self.assertEqual(counts, (len(self.factory.palettes), len(self.factory.combines),
                                 len(self.factory.attachments)))

    def test_partial_parameter_failure_invalidates_pipeline_without_publishing_new_query(self):
        for key in ('query', 'layout', 'dimensions'):
            with self.subTest(parameter=key):
                probe = self.runtime.ProbeSystem('probe', key)
                probe.open()
                probe.load(256)
                probe.install_pipeline()
                self.factory.post.order = ['pmanim_geometry_atlas_gather']
                self.factory.post.fail_parameter = None
                before = probe.finish_pipeline()
                identity = copy.deepcopy(self.identity(before))
                self.factory.post.fail_parameter = key
                with self.assertRaisesRegex(RuntimeError, 'Gather control rejected: ' + key):
                    probe.query(0, 128, mode=2, salt=17, salt2=29)
                after = probe.snapshot()
                self.assertFalse(after['pipeline_ready'])
                self.assertEqual(after['query'], before['query'])
                self.assertEqual(self.identity(after), identity)
                with self.assertRaisesRegex(ValueError, 'Invalid frozen atlas query'):
                    probe.query(0, 128)

    def test_native_failures_do_not_claim_completed_upload_and_count_allocated_candidates(self):
        before = self.ready()
        identity = copy.deepcopy(self.identity(before))
        for field, message in (('blank_ok', 'DeserializeBlockPalette'),
                               ('deserialize_ok', 'DeserializeBlockPalette'),
                               ('combine_ok', 'CombineBlockPaletteToGeometry'),
                               ('attach_ok', 'World geometry attachment')):
            with self.subTest(failure=field):
                budget = copy.deepcopy(self.probe.snapshot()['resource_budget'])
                setattr(self.factory, field, False)
                with self.assertRaisesRegex(RuntimeError, message):
                    self.probe.load(273, generation=2)
                setattr(self.factory, field, True)
                failed = self.probe.snapshot()
                self.assertEqual(self.identity(failed), identity)
                self.assertFalse(failed['gpu_verified'])
                allocated = 1 if field == 'attach_ok' else 0
                self.assertEqual(failed['resource_budget']['names'], budget['names'] + allocated)
                self.assertEqual(failed['resource_budget']['named_records'],
                                 budget['named_records'] + 273 * allocated)
        self.factory.hide_fail_names.add(before['geometry_name'])
        with self.assertRaisesRegex(RuntimeError, 'Previous world geometry could not be hidden'):
            self.probe.load(273, generation=2)
        self.assertEqual(self.identity(self.probe.snapshot()), identity)
        candidate = self.factory.attachments[-1][0]
        self.assertIn((candidate, False), self.factory.visibility)
        self.factory.hide_fail_names.clear()
        self.factory.uniform_ok = False
        with self.assertRaisesRegex(RuntimeError, 'Actor control upload failed after native geometry creation'):
            self.probe.load(273, generation=2)
        failed = self.probe.snapshot()
        self.assertFalse(failed['ready'])
        self.assertIsNotNone(failed['error'])
        self.assertEqual(failed['geometry_build_serial'], before['geometry_build_serial'])
        self.assertEqual(failed['upload_history'], before['upload_history'])
        self.assertFalse(failed['gpu_verified'])

    def test_failed_candidates_never_reuse_names_when_native_creation_or_attachment_is_retried(self):
        first = self.ready()
        self.factory.combine_ok = False
        with self.assertRaisesRegex(RuntimeError, 'CombineBlockPaletteToGeometry'):
            self.probe.load(273, generation=2)
        failed_combine = self.factory.combines[-1][0]
        self.factory.combine_ok = True
        self.factory.attach_ok = False
        with self.assertRaisesRegex(RuntimeError, 'World geometry attachment failed'):
            self.probe.load(273, generation=2)
        failed_attachment = self.factory.attachments[-1][0]
        self.factory.attach_ok = True
        self.factory.hide_fail_names.add(first['geometry_name'])
        with self.assertRaisesRegex(RuntimeError, 'Previous world geometry could not be hidden'):
            self.probe.load(273, generation=2)
        hidden_candidate = self.factory.attachments[-1][0]
        self.assertIn((hidden_candidate, False), self.factory.visibility)
        self.assertEqual(self.probe.snapshot()['geometry_build_serial'], 1)
        self.factory.hide_fail_names.clear()
        retried = self.probe.load(273, generation=2)
        names = [name for name, _ in self.factory.combines]
        self.assertEqual(len(names), len(set(names)))
        self.assertNotIn(retried['geometry_name'],
                         (first['geometry_name'], failed_combine, failed_attachment, hidden_candidate))
        self.assertNotIn((retried['geometry_name'], False), self.factory.visibility)
        self.assertEqual(retried['geometry_build_serial'], 2)
        self.assertEqual(retried['native_attempt_serial'], 5)
        self.assertEqual(retried['resource_budget']['names'], 4)
        self.assertEqual(retried['resource_budget']['named_records'], 256 + 273 * 3)
        self.probe.begin_dataset()
        new_dataset = self.probe.load(2, generation=3)
        self.assertEqual(new_dataset['native_attempt_serial'], 6)
        self.assertIn('epoch1_version6', new_dataset['geometry_name'])

    def test_failed_pipeline_disable_still_destroys_entity_restores_hud_and_unsubscribes(self):
        self.ready()
        self.pipeline()
        self.factory.post.enable_ok = False
        with self.assertRaisesRegex(RuntimeError, 'Owned geometry pipeline disable rejected'):
            self.probe.Destroy()
        self.assertEqual(self.probe.destroyed, ['client-anchor-1'])
        self.assertEqual(self.hud_calls, [True, False])
        self.assertIsNone(self.probe.entity)
        self.assertFalse(self.probe.snapshot()['ready'])
        self.assertFalse(self.probe.snapshot()['pipeline_ready'])
        self.assertFalse(self.probe.snapshot()['native_hud_hidden'])
        self.assertEqual(self.probe.events, [])

    def test_destroy_uses_void_entity_cleanup_and_unsubscribes(self):
        self.ready()
        self.pipeline()
        self.assertEqual(self.hud_calls, [True])
        self.assertTrue(self.probe.snapshot()['native_hud_hidden'])
        self.assertEqual(len(self.probe.events), 1)
        self.probe.Destroy()
        self.assertEqual(self.probe.destroyed, ['client-anchor-1'])
        self.assertIsNone(self.probe.entity)
        self.assertIsNone(self.probe.render)
        self.assertEqual(self.probe.events, [])
        self.assertFalse(self.probe.snapshot()['ready'])
        self.assertFalse(self.probe.snapshot()['pipeline_ready'])
        self.assertFalse(self.probe.snapshot()['native_hud_hidden'])
        self.assertEqual(self.hud_calls, [True, False])
        self.assertEqual(self.factory.post.enables[-1], ('pmanim_geometry_atlas_gather', False))
        self.assertFalse(self.probe.snapshot()['resource_budget']['native_reclamation_verified'])

    def test_eight_second_measurement_samples_frame_stats_without_mutating_payload_or_query(self):
        with self.assertRaisesRegex(ValueError, 'idle ready pipeline'):
            self.probe.start_measurement()
        self.ready(4096)
        self.pipeline()
        before = self.probe.query(127, 2048, mode=2, salt=37, salt2=91)
        identity = copy.deepcopy(self.identity(before))
        query = copy.deepcopy(before['query'])
        counts = (len(self.factory.palettes), len(self.factory.combines),
                  len(self.factory.attachments), len(self.factory.post.parameters))
        for invalid in (0, 1.99, 30.01, float('nan'), float('inf')):
            with self.subTest(duration=invalid), self.assertRaises(ValueError):
                self.probe.start_measurement(invalid)
        started = self.probe.start_measurement(8.)
        self.assertTrue(started['measurement_running'])
        self.assertIsNone(started['last_measurement'])
        with self.assertRaisesRegex(ValueError, 'idle ready pipeline'):
            self.probe.start_measurement(8.)
        start = self.now
        # Simulated render timestamps include the warmup and exact end boundary.
        for frame in range(481):
            self.now = start + frame / 60.
            self.probe.on_frame({})
        measured = self.probe.snapshot()
        self.assertFalse(measured['measurement_running'])
        self.assertEqual(self.identity(measured), identity)
        self.assertEqual(measured['query'], query)
        result = measured['last_measurement']
        self.assertEqual(result['elapsed'], 8.)
        self.assertEqual(result['frames'], 481)
        self.assertEqual(result['geometry_name'], before['geometry_name'])
        self.assertEqual(result['generation'], before['generation'])
        self.assertEqual(result['geometry_build_serial'], before['geometry_build_serial'])
        self.assertEqual(result['query'], query)
        self.assertFalse(result['gpu_completion_fence'])
        self.assertEqual(result['interval_ms']['count'], 421)
        self.assertAlmostEqual(result['interval_ms']['mean'], 1000. / 60., places=7)
        self.assertAlmostEqual(result['interval_ms']['p95'], 1000. / 60., places=7)
        self.assertEqual(result['fps'], {'count': 28, 'mean': 60., 'min': 60., 'max': 60., 'p95': 60.})
        self.assertEqual(counts, (len(self.factory.palettes), len(self.factory.combines),
                                 len(self.factory.attachments), len(self.factory.post.parameters)))
        self.assertFalse(measured['gpu_verified'])
        self.assertFalse(measured['gpu_to_python_readback'])

    def test_delayed_candidate_is_budgeted_without_replacing_resident_identity_or_allowing_overwrite(self):
        self.probe.configure_updates(policy='double', publish_delay_ms=100.)
        self.probe.open()
        queued = self.probe.load(256, seed=54321, generation=1)
        self.assertIsNotNone(queued['pending_upload'])
        self.assertEqual(queued['slot_count'], 0)
        self.assertEqual(queued['geometry_build_serial'], 0)
        self.assertEqual(queued['resource_budget']['names'], 1)
        self.assertEqual(queued['resource_budget']['named_records'], 256)
        calls = len(self.factory.combines)
        with self.assertRaisesRegex(RuntimeError, '[Pp]ending'):
            self.probe.load(256, generation=2)
        self.assertEqual(len(self.factory.combines), calls)
        self.now += .099
        self.probe.on_frame({})
        self.assertIsNotNone(self.probe.snapshot()['pending_upload'])
        self.assertEqual(self.probe.snapshot()['geometry_build_serial'], 0)
        self.now += .002
        self.probe.on_frame({})
        first = self.probe.snapshot()
        self.assertIsNone(first['pending_upload'])
        self.assertEqual(first['generation'], 1)
        self.assertEqual(first['active_bank'], 0)
        self.assertEqual(first['geometry_build_serial'], 1)
        self.assertEqual(first['center'], [1., .5, .5])
        self.assertEqual(self.factory.uniforms[-2], (3, (1080., 1., .5, .5)))
        self.pipeline()
        identity = copy.deepcopy(self.identity(first))
        diagnostic = self.probe.set_center(2., 3., 4.)
        self.assertEqual(diagnostic['center'], [2., 3., 4.])
        self.assertEqual(self.factory.uniforms[-2], (3, (1080., 2., 3., 4.)))
        queued = self.probe.load(256, seed=54321, generation=2)
        self.assertEqual(self.identity(queued), identity)
        self.assertEqual(queued['center'], [2., 3., 4.])
        self.assertEqual(queued['resource_budget']['names'], 2)
        self.assertEqual(queued['resource_budget']['named_records'], 512)
        self.assertEqual(queued['active_bank'], 0)
        self.assertEqual(self.factory.uniforms[-1], (4, (1., 1., 0., 0.)))
        self.now += .101
        self.probe.on_frame({})
        published = self.probe.snapshot()
        self.assertEqual(published['generation'], 2)
        self.assertEqual(published['geometry_build_serial'], 2)
        self.assertEqual(published['active_bank'], 1)
        self.assertIsNone(published['pending_upload'])
        self.assertEqual(published['center'], [1., .5, .5])
        self.assertEqual(self.factory.uniforms[-2], (3, (1080., 1., .5, .5)))
        self.assertEqual(self.factory.uniforms[-1], (4, (1., 2., 0., 0.)))

    def test_update_configuration_requires_idle_empty_dataset_and_finite_delay(self):
        for policy, delay in (('unknown', 0), ('double', -1),
                              ('fresh', float('nan')), ('fresh', float('inf'))):
            with self.subTest(policy=policy, delay=delay), self.assertRaises(ValueError):
                self.probe.configure_updates(policy=policy, publish_delay_ms=delay)
        self.ready()
        with self.assertRaises(RuntimeError):
            self.probe.configure_updates(policy='double', publish_delay_ms=100.)
        self.probe.begin_dataset()
        changed = self.probe.configure_updates(policy='double', publish_delay_ms=100.)
        self.assertEqual(changed['update_policy'], 'double')
        self.assertEqual(changed['publish_delay_ms'], 100.)

    def test_large_payload_layout_extends_to_512_kib_without_exceeding_physical_atlas(self):
        self.probe.open()
        for count, columns, top, cell in ((65536, 256, 64, 2),
                                         (65537, 512, 32, 1),
                                         (524288, 512, 32, 1)):
            with self.subTest(count=count):
                state = self.probe.load(count, generation=1)
                self.assertEqual(state['layout'], [count, columns, 8, top])
                self.assertEqual(state['dimensions'], [cell, 720, 1080, 0])
                rows = (count + columns - 1) // columns
                self.assertLessEqual(8 + columns * cell, 720)
                self.assertLessEqual(top + rows * cell, 1080)
        builds = len(self.factory.combines)
        with self.assertRaises(ValueError):
            self.probe.load(524289)
        self.assertEqual(len(self.factory.combines), builds)

    def test_double_bank_reuses_only_two_attached_names_and_accounts_latest_payload_per_name(self):
        self.probe.configure_updates(policy='double', publish_delay_ms=0)
        self.probe.open()
        names, banks = [], []
        for generation in range(1, 7):
            state = self.probe.load(256, seed=54321, generation=generation)
            names.append(state['geometry_name'])
            banks.append(state['active_bank'])
        self.assertEqual(banks, [0, 1, 0, 1, 0, 1])
        self.assertEqual(len(set(names)), 2)
        self.assertEqual(names[0], names[2])
        self.assertEqual(names[1], names[3])
        self.assertTrue(all('epoch0_bank' in name for name in set(names)))
        self.assertEqual(len(self.factory.attachments), 2)
        self.assertEqual(set(self.factory.transparency_enabled), {(names[0], True), (names[1], True)})
        self.assertEqual(set(self.factory.transparencies), {(names[0], .25), (names[1], .75)})
        self.assertNotIn((names[0], False), self.factory.visibility)
        self.assertNotIn((names[1], False), self.factory.visibility)
        self.assertEqual(state['resource_budget']['names'], 2)
        self.assertEqual(state['resource_budget']['named_records'], 512)
        # Replacing the inactive name changes the accounting by its new size;
        # upload count is not accumulated as logically resident geometry.
        larger = self.probe.load(273, generation=7)
        self.assertEqual(larger['resource_budget']['names'], 2)
        self.assertEqual(larger['resource_budget']['named_records'], 256 + 273)
        budget = copy.deepcopy(larger['resource_budget'])
        reset = self.probe.begin_dataset()
        self.assertEqual(reset['resource_budget'], budget)
        for name in set(names):
            self.assertIn((name, False), self.factory.visibility)
        next_epoch = self.probe.load(256, generation=8)
        self.assertNotIn(next_epoch['geometry_name'], set(names))
        self.assertEqual(next_epoch['resource_budget']['names'], 3)
        self.assertEqual(next_epoch['resource_budget']['named_records'], 256 * 2 + 273)

    def test_double_bank_reopen_attaches_reused_name_to_new_actor_and_retains_session_budget(self):
        self.probe.configure_updates(policy='double', publish_delay_ms=0)
        self.probe.open()
        first = self.probe.load(256, seed=54321, generation=1)
        second = self.probe.load(256, seed=54321, generation=2)
        self.assertEqual(first['center'], [1., .5, .5])
        self.assertEqual(second['center'], [1., .5, .5])
        self.assertEqual(len(self.factory.attachments), 2)
        self.assertEqual(second['active_bank'], 1)
        budget = copy.deepcopy(second['resource_budget'])
        self.probe.close()
        closed = self.probe.snapshot()
        self.assertEqual(self.probe.destroyed, ['client-anchor-1'])
        self.assertIsNone(closed['entity'])
        self.assertEqual(closed['resource_budget'], budget)
        self.probe.entity_result = 'client-anchor-2'
        opened = self.probe.open()
        self.assertEqual(opened['entity'], 'client-anchor-2')
        self.assertTrue(opened['ready'])
        self.assertEqual(opened['resource_budget'], budget)
        self.assertEqual(opened['center'], [1., .5, .5])
        self.assertEqual(self.factory.uniforms[-2], (3, (1080., 1., .5, .5)))
        diagnostic = self.probe.set_center(3., 4., 5.)
        self.assertEqual(diagnostic['center'], [3., 4., 5.])
        self.assertEqual(self.factory.uniforms[-2], (3, (1080., 3., 4., 5.)))
        published = self.probe.load(256, seed=54321, generation=3)
        self.assertEqual(published['entity'], 'client-anchor-2')
        self.assertEqual(published['geometry_name'], first['geometry_name'])
        self.assertEqual(published['active_bank'], 0)
        self.assertEqual(published['generation'], 3)
        self.assertEqual(published['geometry_build_serial'], 3)
        self.assertEqual(published['center'], [1., .5, .5])
        self.assertEqual(self.factory.uniforms[-2], (3, (1080., 1., .5, .5)))
        self.assertEqual(len(self.factory.attachments), 3)
        self.assertEqual(self.factory.attachments[-1],
                         (first['geometry_name'], (0., 0., 0.), (0., 0., 0.)))
        self.assertEqual(self.factory.uniforms[-1], (4, (1., 1., 0., 0.)))
        self.assertEqual(published['resource_budget'], budget)
        receipt = published['upload_history'][-1]
        self.assertEqual(receipt['name'], first['geometry_name'])
        self.assertEqual(receipt['seed'], 54321)
        self.assertEqual(receipt['generation'], 3)
        self.assertEqual(receipt['bank'], 0)
        self.assertEqual(receipt['serial'], 3)
        self.assertEqual(receipt['attempt_serial'], 3)
        self.assertIsNotNone(receipt['published_at'])

    def test_pending_candidate_cannot_be_overwritten_and_cannot_bypass_budget(self):
        self.probe.configure_updates(policy='double', publish_delay_ms=100.)
        self.probe.open()
        self.probe.load(256)
        before = self.probe.snapshot()
        with self.assertRaisesRegex(RuntimeError, '[Pp]ending'):
            self.probe.begin_dataset()
        with self.assertRaisesRegex(RuntimeError, '[Pp]ending'):
            self.probe.configure_updates(policy='fresh', publish_delay_ms=0)
        self.assertEqual(self.probe.snapshot()['resource_budget'], before['resource_budget'])
        self.now += .101
        self.probe.on_frame({})
        with patch.object(self.runtime, 'MAX_RECORDS', 511):
            with self.assertRaisesRegex(RuntimeError, 'budget exhausted'):
                self.probe.load(256, generation=2)
        self.assertEqual(len(self.factory.combines), 1)

    def test_render_scheduled_updates_skip_pending_and_flush_final_candidate_before_freeze(self):
        self.probe.configure_updates(policy='double', publish_delay_ms=300.)
        self.probe.open()
        self.probe.load(256, generation=1)
        self.now += .301
        self.probe.on_frame({})
        self.pipeline()
        started = self.probe.start_updates(duration_seconds=2., interval_ms=1900., max_updates=2)
        self.assertTrue(started['updates_running'])
        self.assertEqual(started['query'], [0, 256, 2, 37])
        self.assertEqual(started['dimensions'][3], 91)
        start = self.now
        for offset in (0., .301, 1.9, 2.):
            self.now = start + offset
            self.probe.on_frame({})
        pending = self.probe.snapshot()
        self.assertTrue(pending['updates_running'])
        self.assertIsNotNone(pending['pending_upload'])
        completed_before_flush = pending['geometry_build_serial']
        self.now = start + 2.201
        self.probe.on_frame({})
        final = self.probe.snapshot()
        self.assertFalse(final['updates_running'])
        self.assertIsNone(final['pending_upload'])
        self.assertEqual(final['geometry_build_serial'], completed_before_flush + 1)
        self.assertEqual(final['query'], [0, 256, 2, 37])
        self.assertEqual(final['dimensions'][3], 91)
        self.assertEqual(final['last_updates']['generation'], final['generation'])
        self.assertEqual(final['last_updates']['geometry_name'], final['geometry_name'])
        self.assertFalse(final['last_updates']['gpu_completion_fence'])
        # Once frozen, later frame callbacks cannot submit another generation.
        calls = len(self.factory.combines)
        self.now += 10.
        self.probe.on_frame({})
        self.assertEqual(len(self.factory.combines), calls)

    def test_update_run_never_rebuilds_pending_bank_and_records_skipped_deadlines(self):
        self.probe.configure_updates(policy='double', publish_delay_ms=100.)
        self.probe.open()
        self.probe.load(256, generation=1)
        self.now += .101
        self.probe.on_frame({})
        self.pipeline()
        self.probe.start_updates(duration_seconds=2., interval_ms=10., max_updates=3)
        start = self.now
        for frame in range(241):
            self.now = start + frame / 120.
            self.probe.on_frame({})
        # A final callback also drains any candidate crossing the duration.
        self.now = start + 2.2
        self.probe.on_frame({})
        state = self.probe.snapshot()
        self.assertFalse(state['updates_running'])
        self.assertEqual(len(self.factory.combines), 4)  # initial + 3 uploads
        self.assertEqual(state['generation'], 4)
        self.assertEqual(state['geometry_build_serial'], 4)
        self.assertEqual(len(self.factory.attachments), 2)
        report = state['last_updates']
        self.assertGreater(report['skipped_updates'], 0)
        self.assertEqual(report['updates'], 3)
        self.assertEqual(report['published'], 3)
        self.assertFalse(report['gpu_completion_fence'])

    def test_dynamic_statistics_measure_real_uploads_and_frame_stalls_for_full_duration(self):
        self.ready(256)
        self.pipeline()
        self.probe.start_updates(duration_seconds=8., interval_ms=1000., max_updates=3)
        start = self.now
        combine = self.factory.CombineBlockPaletteToGeometry

        def measured_combine(*args):
            result = combine(*args)
            self.now += .004  # Four milliseconds spent inside the mocked FFI call.
            return result

        offsets = [frame / 60. for frame in range(61)] + [1.03, 1.07]
        cursor = 1.07
        while cursor + 1. / 60. < 8.:
            cursor += 1. / 60.
            offsets.append(cursor)
        offsets.append(8.)
        with patch.object(self.factory, 'CombineBlockPaletteToGeometry', side_effect=measured_combine):
            for offset in offsets:
                self.now = start + offset
                self.probe.on_frame({})
                if offset < 8.:
                    self.assertTrue(self.probe.snapshot()['updates_running'])
        final = self.probe.snapshot()
        report = final['last_updates']
        self.assertFalse(final['updates_running'])
        self.assertEqual(report['elapsed'], 8.)
        self.assertEqual(report['updates'], 3)
        self.assertEqual(report['published'], 3)
        self.assertTrue(report['truncated'])
        self.assertFalse(report['budget_limited'])
        self.assertGreater(report['skipped_updates'], 0)
        self.assertEqual(report['interval_ms']['over_25_ms'], 2)
        self.assertEqual(report['interval_ms']['over_33_3_ms'], 1)
        self.assertAlmostEqual(report['interval_ms']['max'], 40.)
        self.assertLess(report['interval_ms']['p95'], 17.)
        self.assertGreater(report['fps']['count'], 0)
        self.assertEqual(report['fps']['mean'], 60.)
        for stage in ('generation_ms', 'encode_ms', 'deserialize_ms', 'combine_ms', 'attach_ms', 'total_ms'):
            self.assertEqual(report['timings'][stage]['count'], 3)
        self.assertAlmostEqual(report['timings']['combine_ms']['mean'], 4.)
        self.assertAlmostEqual(report['timings']['combine_ms']['max'], 4.)
        self.assertEqual(final['query'], [0, 256, 2, 37])
        self.assertEqual(report['query'], final['query'])
        self.assertEqual(report['generation'], final['generation'])
        self.assertFalse(report['gpu_completion_fence'])

    def test_fresh_budget_limit_stops_uploading_but_keeps_sampling_until_requested_end(self):
        self.ready(256)
        self.pipeline()
        with patch.object(self.runtime, 'MAX_RECORDS', 512):
            self.probe.start_updates(duration_seconds=2., interval_ms=10., max_updates=20)
            start = self.now
            for frame in range(121):
                self.now = start + frame / 60.
                self.probe.on_frame({})
                if frame < 120:
                    self.assertTrue(self.probe.snapshot()['updates_running'])
        final = self.probe.snapshot()
        report = final['last_updates']
        self.assertFalse(final['updates_running'])
        self.assertEqual(len(self.factory.combines), 2)  # Initial resident payload + one permitted update.
        self.assertEqual(report['elapsed'], 2.)
        self.assertEqual(report['updates'], 1)
        self.assertEqual(report['published'], 1)
        self.assertTrue(report['budget_limited'])
        self.assertTrue(report['truncated'])
        self.assertGreater(report['fps']['count'], 0)
        self.assertGreater(report['interval_ms']['count'], 0)

    def test_scheduled_native_creation_failure_stops_without_claiming_a_new_upload(self):
        resident = self.ready(256)
        self.pipeline()
        identity = copy.deepcopy(self.identity(resident))
        self.probe.start_updates(duration_seconds=2., interval_ms=10., max_updates=20)
        self.factory.combine_ok = False
        self.probe.on_frame({})
        failed = self.probe.snapshot()
        report = failed['last_updates']
        self.assertFalse(failed['updates_running'])
        self.assertIsNone(failed['pending_upload'])
        self.assertEqual(self.identity(failed), identity)
        self.assertEqual(failed['native_attempt_serial'], 2)
        self.assertEqual(failed['resource_budget']['names'], 1)
        self.assertEqual(failed['resource_budget']['named_records'], 256)
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['success'])
        self.assertEqual(report['end_reason'], 'error')
        self.assertFalse(report['duration_completed'])
        self.assertIn('CombineBlockPaletteToGeometry rejected', report['error'])
        self.assertEqual(report['updates'], 0)
        self.assertEqual(report['published'], 0)
        self.assertEqual(report['uploads'], [])
        for stage in ('generation_ms', 'encode_ms', 'deserialize_ms', 'combine_ms', 'attach_ms', 'total_ms'):
            self.assertEqual(report['timings'][stage]['count'], 0)
        self.factory.combine_ok = True
        self.now += 3.
        self.probe.on_frame({})
        self.assertEqual(len(self.factory.combines), 2)

    def test_delayed_publication_failure_retains_resident_identity_and_reports_unpublished_candidate(self):
        self.probe.configure_updates(policy='double', publish_delay_ms=100.)
        self.probe.open()
        self.probe.load(256, generation=1)
        self.now += .101
        self.probe.on_frame({})
        self.pipeline()
        resident = copy.deepcopy(self.identity(self.probe.snapshot()))
        self.probe.start_updates(duration_seconds=2., interval_ms=10., max_updates=20)
        self.probe.on_frame({})
        queued = self.probe.snapshot()
        self.assertIsNotNone(queued['pending_upload'])
        self.assertEqual(queued['resource_budget']['names'], 2)
        self.factory.uniform_ok = False
        self.now += .101
        self.probe.on_frame({})
        failed = self.probe.snapshot()
        report = failed['last_updates']
        self.assertFalse(failed['updates_running'])
        self.assertFalse(failed['ready'])
        self.assertIsNone(failed['pending_upload'])
        self.assertEqual(self.identity(failed), resident)
        self.assertEqual(failed['active_bank'], 0)
        self.assertEqual(failed['resource_budget']['names'], 2)
        self.assertEqual(failed['resource_budget']['named_records'], 512)
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['success'])
        self.assertEqual(report['end_reason'], 'error')
        self.assertFalse(report['duration_completed'])
        self.assertIn('Actor control upload failed', report['error'])
        self.assertEqual(report['updates'], 1)
        self.assertEqual(report['published'], 0)
        self.assertEqual(len(report['uploads']), 1)
        self.assertIsNone(report['uploads'][0]['published_at'])
        self.assertEqual(report['generation'], failed['generation'])
        self.assertEqual(report['geometry_name'], failed['geometry_name'])
        self.factory.uniform_ok = True
        self.now += 3.
        self.probe.on_frame({})
        self.assertEqual(len(self.factory.combines), 2)

    def test_final_query_failure_reports_failed_run_after_full_measurement_duration(self):
        self.ready(256)
        self.pipeline()
        self.probe.start_updates(duration_seconds=2., interval_ms=10., max_updates=1)
        self.probe.on_frame({})
        resident = copy.deepcopy(self.identity(self.probe.snapshot()))
        self.factory.post.fail_parameter = 'layout'
        self.now += 2.
        self.probe.on_frame({})
        failed = self.probe.snapshot()
        report = failed['last_updates']
        self.assertFalse(failed['updates_running'])
        self.assertFalse(failed['pipeline_ready'])
        self.assertEqual(self.identity(failed), resident)
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['success'])
        self.assertEqual(report['end_reason'], 'error')
        self.assertTrue(report['duration_completed'])
        self.assertEqual(report['elapsed'], 2.)
        self.assertIn('Gather control rejected: layout', report['error'])
        self.assertEqual(report['updates'], 1)
        self.assertEqual(report['published'], 1)
        self.assertEqual(report['generation'], failed['generation'])
        self.assertFalse(report['gpu_completion_fence'])

    def test_active_measurement_and_updates_reject_manual_controls_before_native_mutation(self):
        self.ready(256)
        self.pipeline()
        native_mutations = (
            self.factory.palettes, self.factory.combines, self.factory.attachments,
            self.factory.uniforms, self.factory.visibility,
            self.factory.transparency_enabled, self.factory.transparencies,
            self.factory.post.parameters, self.factory.post.enables,
            self.factory.post.added, self.factory.post.connections)
        changes = (
            ('load', lambda: self.probe.load(273, seed=99, generation=17)),
            ('query', lambda: self.probe.query(0, 256, 1, 5, 29)),
            ('center', lambda: self.probe.set_center(1., 2., 3.)),
            ('writer_visibility', lambda: self.probe.set_writer_visible(False)),
            ('pipeline_enabled', lambda: self.probe.set_pipeline_enabled(False)))
        for mode in ('measurement', 'updates'):
            if mode == 'measurement':
                self.probe.start_measurement(2.)
            else:
                self.probe.start_updates(duration_seconds=2., interval_ms=10., max_updates=1)
                self.probe.on_frame({})
            before = copy.deepcopy(self.probe.snapshot())
            calls = tuple(len(values) for values in native_mutations)
            for operation, change in changes:
                with self.subTest(mode=mode, operation=operation):
                    with self.assertRaises(RuntimeError):
                        change()
                    self.assertEqual(self.probe.snapshot(), before)
                    self.assertEqual(tuple(len(values) for values in native_mutations), calls)
            self.now += 2.
            self.probe.on_frame({})
            state = self.probe.snapshot()
            self.assertFalse(state['measurement_running'])
            self.assertFalse(state['updates_running'])


if __name__ == '__main__':
    unittest.main()
