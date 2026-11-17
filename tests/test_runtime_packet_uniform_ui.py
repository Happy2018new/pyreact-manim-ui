"""Direct UI draw resources, staged lifecycle, upload isolation and byte oracle."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools/runtime_packet_probe"
sys.path.insert(0, str(PROBE))
sys.path.insert(0, str(ROOT / "src"))
from uniform_ui_assets import build_uniform_ui_assets, uniform_ui_config
from uniform_split_assets import packet_parameters
from verify_spatial import expected_words


class UniformUIAssetTests(unittest.TestCase):
    def test_requested_scales_use_at_most_64_slots_per_screen(self):
        for slots in (128, 512, 1024, 2048):
            config = uniform_ui_config(slots)
            self.assertEqual(config['screen_size'], [720, 1080])
            self.assertEqual(config['screen_count'], slots // 64)
            self.assertEqual(config['payload_scalar_slots'], slots * 8)
            self.assertEqual(config['payload_bytes'], slots * 24)
            self.assertEqual(config['fullscreen_passes'], 0)
            self.assertEqual(config['image_carriers'], 0)
            self.assertEqual(len(set(config['identifiers'])), slots)
            self.assertEqual([screen['offset'] for screen in config['screens']], list(range(0, slots, 64)))
            self.assertTrue(all(screen['count'] == 64 for screen in config['screens']))
            self.assertEqual(len(set(screen['key'] for screen in config['screens'])), slots // 64)
            self.assertGreaterEqual(min(config['cell_pixels']), 3.)
        self.assertEqual([64, 1], [screen['count'] for screen in uniform_ui_config(65)['screens']])
        for count in (0, 2049, True, 1.0):
            with self.assertRaises(ValueError):
                uniform_ui_config(count)
        for count in (0, 65, True, 1.0):
            with self.assertRaises(ValueError):
                uniform_ui_config(slots_per_screen=count)

    def test_128_and_2048_assets_have_transparent_small_roots_and_independent_entities(self):
        for slots in (128, 2048):
            with self.subTest(slots=slots), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                (output / '.pmanim_packet_probe.json').write_text(
                    '{"kind":"pmanim_runtime_packet_probe"}', encoding='utf-8')
                resource = output / 'resource_pack'
                defs_path = resource / 'ui/_ui_defs.json'
                defs_path.parent.mkdir(parents=True)
                defs_path.write_text('{"ui_defs":["ui/foreign.json"]}', encoding='utf-8')
                material_path = resource / 'materials/entity.material'
                material_path.parent.mkdir(parents=True)
                material_path.write_text('{"materials":{"version":"1.0.0","foreign":{}}}', encoding='utf-8')
                config = build_uniform_ui_assets(resource, slots)
                definitions = json.loads((resource / 'ui/pmanim_packet_uniform_ui.json').read_text(encoding='utf-8'))
                layers = []
                for screen in config['screens']:
                    root = definitions['main_%03d' % screen['index']]
                    self.assertEqual(root['type'], 'panel')
                    self.assertEqual(root['layer'], screen['root_layer'])
                    self.assertEqual(len(root['controls']), 64)
                    for local, row in enumerate(root['controls']):
                        panel = row['slot_%03d' % local]
                        self.assertFalse(panel['visible'])
                        self.assertEqual(len(panel['controls']), 1)
                        canvas = panel['controls'][0]['canvas']
                        self.assertEqual(canvas['type'], 'custom')
                        self.assertTrue(canvas['enable_scissor_test'])
                        self.assertEqual(canvas['renderer'], 'netease_paper_doll_renderer')
                        layers.append(root['layer'] + panel['layer'] + canvas['layer'])
                self.assertEqual(layers, sorted(set(layers)))
                self.assertNotIn('"image"', json.dumps(definitions))
                self.assertEqual(len(list((resource / 'entity').glob('pmanim_packet_uniform_ui*.json'))), slots)
                self.assertEqual(len(list((output / 'behavior_pack/entities').glob('pmanim_packet_uniform_ui*.json'))), slots)
                last = resource / ('entity/pmanim_packet_uniform_ui_slot_%05d.entity.json' % (slots - 1))
                entity = json.loads(last.read_text(encoding='utf-8'))['minecraft:client_entity']['description']
                self.assertEqual(entity['identifier'], config['identifiers'][-1])
                self.assertIn('foreign', json.loads(material_path.read_text(encoding='utf-8'))['materials'])
                self.assertIn('ui/foreign.json', json.loads(defs_path.read_text(encoding='utf-8'))['ui_defs'])
                self.assertFalse((resource / 'graphics_settings/post_process.json').exists())
                self.assertTrue((output / 'behavior_pack/packet_probe/uniform_ui_runtime.py').is_file())
                before = defs_path.read_bytes()
                build_uniform_ui_assets(resource, slots)
                self.assertEqual(before, defs_path.read_bytes())

    def test_unmarked_or_invalid_outputs_are_not_mutated(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            resource = output / 'resource_pack'
            with self.assertRaises(ValueError):
                build_uniform_ui_assets(resource)
            self.assertFalse(resource.exists())
            marker = output / '.pmanim_packet_probe.json'
            marker.write_text('{"kind":"foreign"}', encoding='utf-8')
            with self.assertRaises(ValueError):
                build_uniform_ui_assets(resource)
            marker.write_text('{"kind":"pmanim_runtime_packet_probe"}', encoding='utf-8')
            with self.assertRaises(ValueError):
                build_uniform_ui_assets(resource, 4096)
            self.assertFalse(resource.exists())


class Control:
    def __init__(self):
        self.visible = False
        self.position = None
        self.size = None
        self.rendered = None

    def SetVisible(self, visible, force):
        self.visible = visible

    def SetPosition(self, position):
        self.position = position

    def SetSize(self, size):
        self.size = size

    def asNeteasePaperDoll(self):
        return self

    def RenderEntity(self, settings):
        self.rendered = settings
        return True


class ScreenBase:
    def __init__(self, namespace, name, param):
        self.nodes = {}
        self.lookups = []
        self.removed = False
        self.visible = False
        for index in range(param['uniform_ui_count']):
            path = '/slot_%03d' % index
            self.nodes[path], self.nodes[path + '/canvas'] = Control(), Control()

    def GetBaseUIControl(self, path):
        self.lookups.append(path)
        return self.nodes.get(path)

    def SetScreenVisible(self, visible):
        self.visible = visible

    def SetRemove(self):
        self.removed = True

    def UpdateScreen(self, force):
        pass


class Actor:
    def __init__(self):
        self.uniforms = {}
        self.calls = []
        self.fail = None

    def SetEntityUIExtraUniforms(self, identifier, uniform, value):
        self.calls.append((identifier, uniform, value))
        if (identifier, uniform) == self.fail:
            return False
        self.uniforms[(identifier, uniform)] = value
        return True


class UniformUIRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.actor = Actor()
        self.registrations, self.creations = [], []
        self.deferred = False
        self.reject_index = None
        api = types.ModuleType('mod.client.extraClientApi')
        api.GetScreenNodeCls = lambda: ScreenBase
        api.GetLevelId = lambda: 'fake_level'
        api.GetEngineCompFactory = lambda: types.SimpleNamespace(
            CreateActorRender=lambda entity: self.actor,
            CreateGame=lambda level: types.SimpleNamespace(GetScreenSize=lambda: (360., 540.)))
        api.RegisterUI = lambda *args: self.registrations.append(args) is None

        def create(namespace, key, params):
            if len(self.creations) == self.reject_index:
                return None
            screen = self.runtime.UniformUISlice(namespace, key, params)
            self.creations.append(screen)
            if not self.deferred:
                screen.Create()
            return screen

        api.CreateUI = create
        mod, client = types.ModuleType('mod'), types.ModuleType('mod.client')
        mod.__path__, client.__path__ = [], []
        mod.client, client.extraClientApi = client, api
        modules = patch.dict(sys.modules, {'mod': mod, 'mod.client': client,
                                           'mod.client.extraClientApi': api})
        modules.start()
        self.addCleanup(modules.stop)
        spec = importlib.util.spec_from_file_location('test_uniform_ui_runtime', PROBE / 'uniform_ui_runtime.py')
        self.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runtime)
        self.runtime.time = types.SimpleNamespace(clock=time.perf_counter)

    def probe(self, count=128):
        probe = self.runtime.UniformUIProbe(uniform_ui_config(count), seed=321)
        probe.create_all()
        probe.finish()
        return probe

    def test_two_screens_cache_controls_and_upload_exact_independent_payload(self):
        probe = self.probe()
        self.assertEqual(len(self.registrations), 2)
        self.assertEqual(len(set(row[1] for row in self.registrations)), 2)
        self.assertTrue(all(screen.visible for screen in self.creations))
        self.assertEqual(sum(len(screen.lookups) for screen in self.creations), 256)
        self.assertEqual(probe.words, expected_words(321, 128))
        for index, identifier in enumerate(probe.config['identifiers']):
            screen = probe.screens[index // 64]
            parent, canvas, doll = screen.controls[index % 64]
            left, top, width, height = probe.config['rectangles_norm'][index]
            self.assertEqual(parent.position, (left * 360, top * 540))
            self.assertEqual(canvas.size, (width * 360, height * 540))
            self.assertTrue(parent.visible)
            self.assertEqual(doll.rendered['entity_identifier'], identifier)
            self.assertEqual(self.actor.uniforms[(identifier, 3)],
                             (2 * left - 1, 1 - 2 * top, 2 * width, 2 * height))
            for uniform, packet in enumerate(packet_parameters(probe.words[index]), 1):
                self.assertEqual(self.actor.uniforms[(identifier, uniform)], tuple(packet))
        calls = len(self.actor.calls)
        probe.write(123)
        self.assertEqual(len(self.actor.calls) - calls, 256)
        self.assertEqual(sum(len(screen.lookups) for screen in self.creations), 256)
        snapshot = probe.snapshot()
        self.assertEqual(snapshot['cached_controls'], 128)
        self.assertEqual(snapshot['source'], 'in_game_python')
        self.assertEqual(snapshot['aggregate']['words'], expected_words(123, 128))
        self.assertFalse(snapshot['gpu_verified'])

    def test_pending_create_callbacks_are_retryable_and_one_screen_is_created_per_call(self):
        self.deferred = True
        probe = self.runtime.UniformUIProbe(uniform_ui_config(128))
        probe.create_next()
        self.assertEqual(len(probe.screens), 1)
        with self.assertRaises(RuntimeError):
            probe.finish()
        probe.create_next()
        with self.assertRaisesRegex(RuntimeError, 'still pending'):
            probe.finish()
        self.assertIsNone(probe.error)
        for screen in probe.screens:
            screen.Create()
        probe.finish()
        self.assertTrue(probe.ready)
        self.assertTrue(probe.enabled)
        self.assertIsNone(probe.create_next())

    def test_upload_failure_hides_every_screen_and_preserves_last_receipt_generation(self):
        probe = self.probe()
        previous = probe.words
        self.actor.fail = (probe.config['identifiers'][70], 1)
        with self.assertRaisesRegex(RuntimeError, 'payload rejected'):
            probe.write(900)
        self.assertFalse(probe.ready)
        self.assertFalse(probe.enabled)
        self.assertFalse(any(screen.visible for screen in probe.screens))
        self.assertEqual(probe.words, previous)
        self.assertIsNotNone(probe.error)
        with self.assertRaises(RuntimeError):
            probe.set_enabled(True)

    def test_create_failure_hides_earlier_screen_and_close_removes_owned_nodes(self):
        self.reject_index = 1
        probe = self.runtime.UniformUIProbe(uniform_ui_config(128))
        probe.create_next()
        with self.assertRaisesRegex(RuntimeError, 'CreateUI rejected'):
            probe.create_next()
        self.assertFalse(probe.screens[0].visible)
        created = list(probe.screens)
        probe.close()
        self.assertTrue(all(screen.removed for screen in created))
        self.assertTrue(probe.closed)
        self.assertEqual(probe.snapshot()['created_screens'], 0)

    def test_invalid_payload_is_rejected_before_any_native_upload(self):
        probe = self.probe()
        before = list(self.actor.calls)
        for words in ([[0] * 7] * 128, [[True] * 8] * 128, [[16777216] * 8] * 128):
            with self.assertRaises(ValueError):
                probe.write(1, provided=words)
        self.assertEqual(self.actor.calls, before)
        self.assertTrue(probe.ready)
        self.assertTrue(probe.enabled)
        probe.set_enabled(False)
        self.assertFalse(any(screen.visible for screen in probe.screens))
        probe.set_enabled(True)
        probe.close()
        self.assertTrue(all(screen.removed for screen in self.creations))


@unittest.skipUnless(importlib.util.find_spec('moderngl'), 'optional desktop OpenGL diagnostic')
class UniformUIGpuTests(unittest.TestCase):
    def test_scissored_direct_draws_decode_every_byte_without_screen_texture(self):
        import moderngl
        from pyreact_manim.compiler.desktop import desktop_fragment
        context = moderngl.create_standalone_context(require=330)
        fragment = desktop_fragment((PROBE / 'uniform_ui.fragment').read_text(encoding='utf-8'))
        vertex = '''#version 330
in vec2 position;
out vec2 uv;
uniform vec4 EXTRA_ACTOR_UNIFORM3;
void main() {
    uv = position * 0.5 + 0.5;
    vec2 clip = EXTRA_ACTOR_UNIFORM3.xy + uv *
                vec2(EXTRA_ACTOR_UNIFORM3.z, -EXTRA_ACTOR_UNIFORM3.w);
    gl_Position = vec4(clip, 0, 1);
}
'''
        program = context.program(vertex_shader=vertex, fragment_shader=fragment)
        buffer = context.buffer(struct.pack('8f', -1, -1, 1, -1, -1, 1, 1, 1))
        array = context.simple_vertex_array(program, buffer, 'position')
        frame = context.simple_framebuffer((720, 1080), components=4)
        try:
            context.disable(moderngl.BLEND)
            for count in (128, 512, 1024, 2048):
                config = uniform_ui_config(count)
                frame.use()
                frame.clear(0.1, 0.2, 0.3, 1.)
                words = expected_words(12345, count)
                for rect, row in zip(config['rectangles_norm'], words):
                    left, top, width, height = rect
                    program['EXTRA_ACTOR_UNIFORM3'].value = (2 * left - 1, 1 - 2 * top, 2 * width, 2 * height)
                    for uniform, packet in enumerate(packet_parameters(row), 1):
                        program['EXTRA_ACTOR_UNIFORM%d' % uniform].value = packet
                    # Actual MC scissor and its logical-to-physical rounding
                    # remain an engine test; this allows the whole intended tile.
                    context.scissor = (int(left * 720), int((1 - top - height) * 1080),
                                       int(width * 720) + 2, int(height * 1080) + 2)
                    array.render(moderngl.TRIANGLE_STRIP)
                context.scissor = None
                rgba = frame.read(components=4, alignment=1)
                for rect, row in zip(config['rectangles_norm'], words):
                    left, top, width, height = rect
                    y = int((1 - top - height / 2) * 1080)
                    expected = b''.join(word.to_bytes(3, 'big') for word in row)
                    for cell, value in enumerate(expected):
                        x = int((left + width * (cell + 0.5) / 24) * 720)
                        self.assertEqual(rgba[(y * 720 + x) * 4:(y * 720 + x) * 4 + 4],
                                         bytes([value]) * 3 + b'\xff')
        finally:
            frame.release()
            array.release()
            buffer.release()
            program.release()
            context.release()


if __name__ == '__main__':
    unittest.main()
