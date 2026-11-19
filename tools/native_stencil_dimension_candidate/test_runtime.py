"""Offline adversarial recovery checks with real frozen probe logic and fake SDK.

Nothing imports an installed game client or performs a game operation. The bulk
and integrated probe sources are loaded against a deterministic API replacement;
native geometry compilation is forbidden so a recovery cannot silently reupload.
"""
import copy
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
PROCESSES = ('stencil_integrated_copy', 'stencil_integrated_restore',
             'stencil_integrated_consumer')
LINKS = ((PROCESSES[0], 0, PROCESSES[1], 0, 3),
         (PROCESSES[0], 0, PROCESSES[2], 0, 3),
         (PROCESSES[1], 0, PROCESSES[2], 0, 4))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Native:
    """Record calls and inject rejection/exception at an exact native boundary."""

    def __init__(self):
        self.calls = []
        self.responses = {}
        self.now = 100.
        self.dimension = 0
        self.position = (10., 80., 20.)
        self.forward = (0., 0., 1.)
        self.entity_serial = 0
        self.post = Post(self)
        self.camera = Camera(self)
        self.game = Game(self)
        self.factory = Factory(self)

    def call(self, name, *args, default=True):
        self.calls.append((name, args))
        choices = self.responses.get(name)
        result = choices.pop(0) if choices else default
        if isinstance(result, Exception):
            raise result
        return result

    def count(self, name):
        return sum(call[0] == name for call in self.calls)

    def arguments(self, name):
        return [args for method, args in self.calls if method == name]


class Post:
    def __init__(self, native):
        self.native = native
        self.order = list(PROCESSES)
        self.enabled = dict.fromkeys(PROCESSES, True)

    def GetPostProcessOrder(self):
        return list(self.order)

    def CheckEnabledByName(self, name):
        return self.enabled.get(name, False)

    def SetEnableByName(self, name, enabled):
        accepted = self.native.call('SetEnableByName', name, enabled)
        if accepted:
            self.enabled[name] = enabled
        return accepted

    def SetParameter(self, *args):
        return self.native.call('SetParameter', *args)

    def AddPostProcess(self, process, index):
        accepted = self.native.call('AddPostProcess', process['name'], index)
        if accepted:
            self.order.insert(index, process['name'])
        return accepted

    def PostPassResultToOtherPass(self, *args):
        return self.native.call('PostPassResultToOtherPass', *args)


class Game:
    def __init__(self, native):
        self.native = native

    def GetCurrentDimension(self):
        return self.native.dimension

    def GetFps(self):
        return 60.


class Camera:
    def __init__(self, native):
        self.native = native

    def GetPosition(self):
        return self.native.position

    def GetForward(self):
        return self.native.forward

    def DepartCamera(self):
        return self.native.call('DepartCamera')

    def SetCameraPos(self, position):
        accepted = self.native.call('SetCameraPos', position)
        if accepted:
            self.native.position = position
        return accepted

    def SetCameraRotation(self, rotation):
        return self.native.call('SetCameraRotation', rotation)

    def ResetCameraPos(self):
        return self.native.call('ResetCameraPos')

    def UnDepartCamera(self):
        return self.native.call('UnDepartCamera')


class Render:
    def __init__(self, native, entity):
        self.native, self.entity = native, entity

    def SetEntityExtraUniforms(self, *args):
        return self.native.call('SetEntityExtraUniforms', self.entity, *args)

    def AddActorBlockGeometry(self, *args):
        return self.native.call('AddActorBlockGeometry', self.entity, *args)

    def SetActorBlockGeometryVisible(self, *args):
        return self.native.call('SetActorBlockGeometryVisible', self.entity, *args)

    def SetEntityShadowShow(self, visible):
        return self.native.call('SetEntityShadowShow', self.entity, visible)


class Control:
    def __init__(self, native, entity):
        self.native, self.entity = native, entity

    def __getattr__(self, name):
        if name not in ('SetFaceCamera', 'SetLoop', 'SetLayer', 'Stop', 'Play', 'SetMixColor'):
            raise AttributeError(name)
        return lambda *args: self.native.call(name, self.entity, *args)


class ForbiddenGeometry:
    def GetBlankBlockPalette(self):
        raise AssertionError('Recovery must not deserialize or upload a new palette')

    def CombineBlockPaletteToGeometry(self, *args):
        raise AssertionError('Recovery must reuse retained geometry names')


class Factory:
    def __init__(self, native):
        self.native = native

    def CreateGame(self, level):
        return self.native.game

    def CreateCamera(self, level):
        return self.native.camera

    def CreatePostProcess(self, level):
        return self.native.post

    def CreateBlock(self, level):
        return ForbiddenGeometry()

    def CreateBlockGeometry(self, level):
        return ForbiddenGeometry()

    def CreateActorRender(self, entity):
        return Render(self.native, entity)

    def CreateModel(self, entity):
        return Render(self.native, entity)

    def CreateFrameAniControl(self, entity):
        return Control(self.native, entity)


def fake_api(native):
    api = types.ModuleType('mod.client.extraClientApi')

    class ClientSystem:
        def __init__(self, namespace, name):
            self.namespace, self.name = namespace, name

        def ListenForEvent(self, namespace, system, event, target, handler):
            native.call('ListenForEvent', namespace, system, event, target, handler)

        def UnListenForEvent(self, namespace, system, event, target, handler):
            native.call('UnListenForEvent', namespace, system, event, target, handler)

        def CreateClientEntityByTypeStr(self, *args):
            native.entity_serial += 1
            return native.call('CreateClientEntityByTypeStr', *args,
                               default='new-actor-%d' % native.entity_serial)

        def CreateEngineSfxFromEditor(self, *args):
            native.entity_serial += 1
            return native.call('CreateEngineSfxFromEditor', *args,
                               default='new-effect-%d' % native.entity_serial)

        def DestroyEntity(self, entity):
            return native.call('DestroyEntity', entity)

    api.GetClientSystemCls = lambda: ClientSystem
    api.GetEngineCompFactory = lambda: native.factory
    api.GetLevelId = lambda: 'level'
    api.GetLocalPlayerId = lambda: 'local-player'
    api.GetEngineNamespace = lambda: 'Minecraft'
    api.GetEngineSystemName = lambda: 'engine'
    api.HideHudGUI = lambda value: native.call('HideHudGUI', value)
    return api


class DimensionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.native = Native()
        api = fake_api(self.native)
        codec = types.ModuleType('stencil_large.codec')
        codec.INTEGER_TYPES = (int,)
        codec.encode_values = mock.Mock(side_effect=AssertionError('No recovery byte encoding'))
        config = types.ModuleType('stencil_large.integrated_config')
        config.WITH_UI = config.WITH_OUTLINE = False
        modules = {'mod': types.ModuleType('mod'),
                   'mod.client': types.ModuleType('mod.client'),
                   'mod.client.extraClientApi': api,
                   'stencil_large': types.ModuleType('stencil_large'),
                   'stencil_large.codec': codec,
                   'stencil_large.integrated_config': config}
        self.module_patch = mock.patch.dict(sys.modules, modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.bulk = load_module('stencil_large.runtime',
                                TOOLS/'weather_stencil_large_probe/runtime.py')
        self.bulk.CLOCK = lambda: self.native.now
        load_module('stencil_large.known_fixture',
                    TOOLS/'weather_stencil_integrated_probe/known_fixture_runtime.py')
        load_module('stencil_large.integrated_runtime',
                    TOOLS/'weather_stencil_integrated_probe/runtime.py')
        self.runtime = load_module('dimension_candidate_under_test', HERE/'runtime.py')
        self.traceback_patch = mock.patch.object(self.runtime.traceback, 'print_exc')
        self.traceback_patch.start()
        self.addCleanup(self.traceback_patch.stop)
        self.system = self.runtime.ProbeSystem('offline', 'dimension')
        self.seed_resident()

    def seed_resident(self):
        probe = self.system
        probe.origin, probe.anchor = (10, 79, 20), (10., 80., 23.)
        probe.state, probe.mode = 'resident', 'all'
        probe.payload = bytes([0, 17, 63, 128, 192, 255, 85, 170])
        probe.byte_count, probe.received, probe.chunk_count = len(probe.payload), len(probe.payload), 1
        probe.generation = 7
        probe.identity = {'host_sha256': 'a'*64, 'game_sha256_computed': False,
                          'byte_count': len(probe.payload),
                          'adler32': self.bulk._checksum(bytearray(probe.payload))}
        probe.viewport, probe.roi = [720, 1080], [8, 128, 32, 1]
        clear = {'entity': 'old-clear', 'render': Render(self.native, 'old-clear'),
                 'kind': 'clear', 'index': 0, 'count': 1, 'stride': 2,
                 'offset': 0, 'ready': True, 'deadline': 110., 'pages': ['retained-clear']}
        writer = {'entity': 'old-writer', 'render': Render(self.native, 'old-writer'),
                  'kind': 'writer', 'index': 0, 'count': len(probe.payload), 'stride': 4,
                  'offset': 0, 'ready': True, 'deadline': 110.,
                  'pages': ['retained-bit64', 'retained-bit128']}
        probe.actors, probe.writer_actors, probe.clear_actor = [clear, writer], [writer], clear
        probe.pages = ['retained-clear', 'retained-bit64', 'retained-bit128']
        probe.clear_page = probe.pages[0]
        probe.active_pages = [{'name': name, 'actor': writer} for name in probe.pages[1:]]
        probe.attempts = [{'name': name, 'status': 'attached_hidden'} for name in probe.pages]
        probe.native_records = 1+2*len(probe.payload)
        probe.payload_visible = probe.clear_visible = True
        probe.effects = ['old-base', 'old-bit64', 'old-bit128']
        probe.controls = [Control(self.native, effect) for effect in probe.effects]
        probe.pipeline_registered = list(PROCESSES)
        probe.pipeline_installed = probe.pipeline_ready = probe.pipeline_enabled = True
        probe.pipeline_install_frame = -1
        probe.pipeline_links = list(LINKS)
        probe.consumer_mode, probe.shape_enabled, probe.restore_enabled = 4, True, True

    def event(self, source=0, target=1, player='local-player'):
        return {'playerId': player, 'fromDimensionId': source, 'toDimensionId': target,
                'toX': 10., 'toY': 80., 'toZ': 20., 'toPos': (10., 80., 20.)}

    def begin(self, source=0, target=1):
        event = self.event(source, target)
        self.system.on_dimension_start(event)
        self.native.dimension = target
        self.system.on_dimension_finish(event)

    def drive(self, frames=12):
        for _ in range(frames):
            self.system.on_frame({})
            if self.phase() in ('ready', 'failed'):
                return
        self.fail('Recovery did not settle: %r' % self.system.snapshot()['dimension_recovery'])

    def phase(self):
        return self.system.snapshot()['dimension_recovery']['phase']

    def assert_failed(self):
        self.assertEqual('failed', self.phase())
        recovery = self.system.snapshot()['dimension_recovery']
        self.assertIsNone(recovery['ready_serial'])
        self.assertFalse(self.system.pipeline_ready)
        self.assertFalse(self.system.snapshot()['ready'])
        self.assertTrue(recovery['error'])
        self.assertEqual([], recovery['history'])
        count = len(self.native.calls)
        for _ in range(3):
            self.system.on_frame({})
        self.assertEqual(count, len(self.native.calls), 'A failed operation must not retry natively')

    def test_only_valid_local_player_transitions_invalidate_resident_state(self):
        original = self.system.snapshot()
        for event in (None, {}, self.event(player='other-player'), self.event(1, 1),
                      self.event(True, 1), self.event('0', 1), self.event(-1, 1)):
            self.system.on_dimension_start(event)
            self.system.on_dimension_finish(event)
        result = self.system.snapshot()
        self.assertEqual(0, result['dimension_recovery']['serial'])
        self.assertEqual('idle', self.phase())
        self.assertTrue(result['ready'])
        self.assertEqual(original['pipeline_links'], result['pipeline_links'])
        self.assertEqual(0, self.native.count('CreateClientEntityByTypeStr'))

    def test_start_invalidates_links_and_duplicate_or_stale_events_cannot_finish(self):
        event = self.event()
        self.system.on_dimension_start(event)
        self.assertFalse(self.system.pipeline_ready)
        self.assertEqual([], self.system.pipeline_links)
        self.assertFalse(self.system.snapshot()['ready'])
        with self.assertRaisesRegex(RuntimeError, 'pending or faulted'):
            self.system.configure('all')
        self.system.on_dimension_start(dict(event))
        self.assertEqual(1, self.system.dimension_recovery['serial'])
        self.assertEqual(1, self.system.dimension_recovery['duplicate_starts'])
        self.system.on_dimension_finish(self.event(1, 0))
        self.system.on_dimension_finish(event)  # Destination has not actually changed.
        self.assertEqual('waiting_finish', self.phase())
        self.assertEqual(2, self.system.dimension_recovery['ignored_finishes'])
        self.assertEqual(0, self.native.count('CreateClientEntityByTypeStr'))

    def test_recovery_reuses_bytes_and_geometry_and_reconnects_on_later_frames(self):
        payload, identity = self.system.payload, copy.deepcopy(self.system.identity)
        pages, attempts = list(self.system.pages), copy.deepcopy(self.system.attempts)
        self.begin()
        self.assertEqual('wait_camera_request', self.phase())
        self.assertEqual(0, self.native.count('SetCameraPos'))
        self.system.on_frame({})
        self.assertEqual('wait_camera', self.phase())
        self.assertEqual(0, self.native.count('AddActorBlockGeometry'))
        self.system.on_frame({})
        self.assertEqual('wait_camera', self.phase())
        self.system.on_frame({})
        self.assertEqual('wait_links', self.phase())
        self.assertFalse(self.system.pipeline_ready)
        self.assertEqual(0, self.native.count('PostPassResultToOtherPass'))
        self.system.on_frame({})
        result = self.system.snapshot()
        self.assertEqual('ready', self.phase())
        self.assertEqual(1, result['dimension_recovery']['ready_serial'])
        self.assertTrue(result['ready'])
        self.assertIs(payload, self.system.payload)
        self.assertEqual(identity, self.system.identity)
        self.assertEqual(7, self.system.generation)
        self.assertEqual(pages, self.system.pages)
        self.assertEqual(attempts, self.system.attempts)
        self.assertEqual(pages, [args[1] for args in self.native.arguments('AddActorBlockGeometry')])
        self.assertEqual(list(LINKS), self.native.arguments('PostPassResultToOtherPass'))
        self.assertEqual(2, self.native.count('CreateClientEntityByTypeStr'))
        self.assertEqual(3, self.native.count('CreateEngineSfxFromEditor'))
        self.assertEqual(['old-base', 'old-bit64', 'old-bit128'],
                         [args[0] for args in self.native.arguments('DestroyEntity')])
        self.assertEqual('all', self.system.mode)
        self.assertEqual((4, True, True, True), (self.system.consumer_mode,
                         self.system.shape_enabled, self.system.restore_enabled,
                         self.system.pipeline_enabled))
        self.assertFalse(result['dimension_recovery']['pixel_verified'])
        self.assertFalse(result['dimension_recovery']['runtime_file_writes'])

    def test_duplicate_finish_and_old_pair_cannot_republish_a_later_serial(self):
        self.begin()
        self.system.on_dimension_finish(self.event())
        self.drive()
        self.system.on_dimension_start(self.event())  # Redelivery after successful recovery.
        self.assertEqual(1, self.system.dimension_recovery['serial'])
        self.begin(1, 0)
        self.system.on_dimension_finish(self.event(0, 1))
        self.assertEqual('wait_camera_request', self.phase())
        self.assertIsNone(self.system.dimension_recovery['ready_serial'])
        self.drive()
        self.assertEqual(2, self.system.dimension_recovery['ready_serial'])
        self.assertEqual([1, 2], [row['serial'] for row in self.system.dimension_recovery['history']])
        self.assertEqual(6, self.native.count('PostPassResultToOtherPass'))

    def test_superseding_transition_fails_instead_of_publishing_old_work(self):
        self.begin()
        self.system.on_dimension_start(self.event(1, 2))
        self.system.on_dimension_finish(self.event())
        self.assert_failed()
        self.assertEqual(0, self.native.count('CreateClientEntityByTypeStr'))

    def test_reentrant_dimension_start_during_native_link_cannot_publish(self):
        self.begin()
        for _ in range(3):
            self.system.on_frame({})
        self.assertEqual('wait_links', self.phase())
        original_link = self.native.post.PostPassResultToOtherPass

        def supersede_during_first_link(*args):
            accepted = original_link(*args)
            if self.native.count('PostPassResultToOtherPass') == 1:
                self.system.on_dimension_start(self.event(1, 2))
            return accepted

        with mock.patch.object(self.native.post, 'PostPassResultToOtherPass',
                               side_effect=supersede_during_first_link):
            self.system.on_frame({})
        self.assert_failed()
        self.assertEqual(1, self.system.dimension_recovery['serial'])
        self.assertEqual([0, 1], self.system.dimension_recovery['pair'])

    def test_native_dimension_change_during_last_configuration_cannot_publish(self):
        self.begin()
        for _ in range(3):
            self.system.on_frame({})
        self.assertEqual('wait_links', self.phase())
        original_enable = self.native.post.SetEnableByName

        def change_dimension_at_last_enable(name, enabled):
            accepted = original_enable(name, enabled)
            if name == PROCESSES[-1]:
                self.native.dimension = 2
            return accepted

        with mock.patch.object(self.native.post, 'SetEnableByName',
                               side_effect=change_dimension_at_last_enable):
            self.system.on_frame({})
        self.assert_failed()
        self.assertEqual(1, self.system.dimension_recovery['serial'])
        self.assertIn('Native dimension changed', self.system.dimension_recovery['error'])

    def test_missing_post_processes_are_reinstalled_then_all_links_recreated(self):
        self.native.post.order = []
        self.native.post.enabled = {}
        self.begin()
        self.drive()
        self.assertEqual('ready', self.phase())
        self.assertEqual(list(PROCESSES), self.native.post.order)
        self.assertEqual(3, self.native.count('AddPostProcess'))
        self.assertEqual(list(LINKS), self.native.arguments('PostPassResultToOtherPass'))

    def test_partial_or_reordered_processes_fail_without_new_registration(self):
        for order in ([PROCESSES[0]], list(reversed(PROCESSES))):
            with self.subTest(order=order):
                self.setUp()
                self.native.post.order = order
                self.begin()
                self.drive()
                self.assert_failed()
                self.assertEqual(0, self.native.count('AddPostProcess'))
                self.assertEqual(0, self.native.count('PostPassResultToOtherPass'))

    def test_native_rejections_or_exceptions_never_publish_ready(self):
        cases = [('SetCameraPos', [False]), ('SetCameraPos', [None]),
                 ('SetCameraRotation', [RuntimeError('camera rejected')]),
                 ('CreateClientEntityByTypeStr', [None]), ('AddActorBlockGeometry', [False]),
                 ('AddActorBlockGeometry', [None]), ('SetActorBlockGeometryVisible', [False]),
                 ('SetActorBlockGeometryVisible', [None]), ('CreateEngineSfxFromEditor', [None]),
                 ('SetMixColor', [False]), ('SetParameter', [False]),
                 ('SetEnableByName', [False]), ('PostPassResultToOtherPass', [True, False]),
                 ('PostPassResultToOtherPass', [True, None]),
                 ('Play', [False])]
        for method, responses in cases:
            with self.subTest(method=method, responses=responses):
                self.setUp()
                self.native.responses[method] = responses
                self.begin()
                self.drive()
                self.assert_failed()

    def test_transient_actor_uniform_rejection_recovers_without_new_actors(self):
        # Four _actor_uniforms calls occur during creation; reject only the last
        # one so _publish must retry readiness on the already-created writer.
        self.native.responses['SetEntityExtraUniforms'] = [True]*12+[False]
        self.begin()
        self.drive()
        self.assertEqual('ready', self.phase())
        self.assertEqual(2, self.native.count('CreateClientEntityByTypeStr'))
        self.assertEqual(3, self.native.count('AddActorBlockGeometry'))

    def test_persistent_uniform_rejection_times_out_and_never_links(self):
        self.native.responses['SetEntityExtraUniforms'] = [False]*100
        self.begin()
        for _ in range(6):
            self.system.on_frame({})
        self.assertEqual('wait_links', self.phase())
        self.assertEqual(0, self.native.count('PostPassResultToOtherPass'))
        self.native.now += self.runtime.RECOVERY_TIMEOUT+1
        self.system.on_frame({})
        self.assert_failed()

    def test_changed_payload_identity_is_rejected_before_ready_publication(self):
        self.begin()
        self.system.identity['adler32'] ^= 1
        self.drive()
        self.assert_failed()

    def test_changed_dimension_during_deferred_work_never_publishes(self):
        self.begin()
        self.native.dimension = 2
        self.system.on_frame({})
        self.assert_failed()
        self.assertEqual(0, self.native.count('CreateClientEntityByTypeStr'))

    def test_missing_finish_event_expires_without_native_mutation(self):
        self.system.on_dimension_start(self.event())
        self.native.now += self.runtime.RECOVERY_TIMEOUT+1
        self.system.on_frame({})
        self.assert_failed()
        self.assertEqual(0, self.native.count('CreateClientEntityByTypeStr'))
        self.assertEqual(0, self.native.count('SetCameraPos'))

    def test_destroy_unregisters_each_lifecycle_event_exactly_once(self):
        listened = self.native.arguments('ListenForEvent')
        self.system.Destroy()
        self.system.Destroy()
        removed = self.native.arguments('UnListenForEvent')
        self.assertEqual(3, len(listened))
        self.assertCountEqual(listened, removed)
        self.assertEqual({'GameRenderTickEvent', 'DimensionChangeClientEvent',
                          'DimensionChangeFinishClientEvent'}, {row[2] for row in removed})


if __name__ == '__main__':
    unittest.main()
