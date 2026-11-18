"""Real desktop GPU checks for payload RTs isolated from scene RGBA.

The fixture executes the configured forward pass graph with OpenGL textures.
It does not launch Minecraft, emulate ModSDK scheduling, or establish native
client support, mobile behavior, performance, or per-frame freshness.
"""
from contextlib import contextmanager
import importlib.util
import math
from pathlib import Path
import struct
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools/runtime_packet_probe"
sys.path.insert(0, str(PROBE))
sys.path.insert(0, str(ROOT / "src"))

from isolated_assets import isolated_config


PHONE = (720, 1080)
PAYLOAD_BYTES = 96


def payload_words(generation, pages=4):
    """Independent integer oracle; no production dataset or pixel verifier."""
    state = (0x95AB37 + generation * 0x45D9F3B) & 0xFFFFFFFF
    words = []
    for _ in range(pages * 8):
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        words.append(state >> 8)
    if generation == 0:
        words[:8] = [0, 1, 255, 256, 65535, 65536, 8388609, 16777215]
    return [words[start:start + 8] for start in range(0, pages * 8, 8)]


def payload_bytes(words):
    return b"".join(word.to_bytes(3, "big") for page in words for word in page)


def detailed_scene(size, phase):
    """Bottom-up RGBA pixels with independent details and nonconstant alpha."""
    width, height = size
    y, x = np.indices((height, width), dtype=np.uint32)
    return np.stack(((17 * x + 31 * y + 6 * (x ^ y) + 53 * phase) & 255,
                     (43 * x + 11 * y + 4 * (x ^ (y * 5)) + 71 * phase) & 255,
                     (5 * x + 67 * y + 19 * ((x // 3) ^ y) + 97 * phase) & 255,
                     (x + 3 * y + 29 * phase) & 255), axis=-1).astype(np.uint8)


@unittest.skipUnless(importlib.util.find_spec("moderngl"), "optional desktop OpenGL diagnostic")
class IsolatedPacketGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import moderngl
        from pyreact_manim.compiler.desktop import desktop_fragment

        cls.gl = moderngl
        cls.context = moderngl.create_standalone_context(require=330)
        cls.programs = {}
        cls.arrays = {}
        cls.vertices = cls.context.buffer(struct.pack("8f", -1, -1, 1, -1, -1, 1, 1, 1))
        vertex = """#version 330
in vec2 position;
out vec2 uv;
void main() { uv = position * 0.5 + 0.5; gl_Position = vec4(position, 0.0, 1.0); }
"""
        for key, filename in (("save", "isolated_copy.fragment"),
                              ("producer", "atlas2d.fragment"),
                              ("consumer", "isolated_consumer.fragment")):
            program = cls.context.program(vertex_shader=vertex, fragment_shader=desktop_fragment(
                (PROBE / filename).read_text(encoding="utf-8")))
            cls.programs[key] = program
            cls.arrays[key] = cls.context.simple_vertex_array(program, cls.vertices, "position")

    @classmethod
    def tearDownClass(cls):
        for array in cls.arrays.values():
            array.release()
        for program in cls.programs.values():
            program.release()
        cls.vertices.release()
        cls.context.release()

    def assert_rgba_equal(self, actual, expected, label):
        self.assertEqual(actual.shape, expected.shape, label)
        unequal = actual != expected
        if np.any(unequal):
            y, x, channel = np.argwhere(unequal)[0]
            self.fail("%s: %d channel errors; first at (%d,%d), channel %d: %d != %d" % (
                label, np.count_nonzero(unequal), x, y, channel,
                actual[y, x, channel], expected[y, x, channel]))

    @contextmanager
    def graph(self, size=PHONE):
        """Allocate distinct RTs and use actual config links, without feedback."""
        config = isolated_config(screen_size=size)
        self.assertEqual(config["pages"], 4)
        self.assertEqual(config["payload_bytes"], PAYLOAD_BYTES)
        names = [process["name"] for process in config["processes"]]
        self.assertEqual(names, [config["saved_scene_name"], *config["producer_names"],
                                 config["display_name"]])
        targets, framebuffers, textures = {}, {}, []

        def texture(dimensions, data=None):
            result = self.context.texture(tuple(dimensions), 4, data, dtype="f1")
            result.filter = (self.gl.NEAREST, self.gl.NEAREST)
            result.repeat_x = result.repeat_y = False
            textures.append(result)
            return result

        try:
            scene = texture(size)
            # TEXTURE1 is deliberately different. Restoration must use the
            # explicitly saved C0 on TEXTURE4, not this implicit scene buffer.
            decoy = texture(size, detailed_scene(size, 193).tobytes())
            blank = texture((1, 1), bytes(4))
            for process in config["processes"]:
                target = process["pass_array"][0]["render_target"]
                dimensions = tuple(max(1, math.floor(struct.unpack("f", struct.pack(
                    "f", target[key]))[0] * size[index]))
                                   for index, key in enumerate(("width", "height")))
                name = process["name"]
                if name in config["producer_names"]:
                    self.assertEqual(list(dimensions), config["target_pixels"])
                else:
                    self.assertEqual(dimensions, tuple(size))
                targets[name] = texture(dimensions)
                framebuffers[name] = self.context.framebuffer(color_attachments=[targets[name]])
            graph = {"config": config, "scene": scene, "decoy": decoy, "blank": blank,
                     "targets": targets, "framebuffers": framebuffers, "size": tuple(size)}
            yield graph
        finally:
            for framebuffer in reversed(list(framebuffers.values())):
                framebuffer.release()
            for item in reversed(textures):
                item.release()

    def execute(self, graph, scene_pixels, words, mode, salt=7, disconnect=()):
        config = graph["config"]
        graph["scene"].write(scene_pixels.tobytes())
        self.context.disable(self.gl.BLEND | self.gl.DEPTH_TEST | self.gl.CULL_FACE)
        previous = graph["scene"]
        completed = set()
        for process in config["processes"]:
            name = process["name"]
            if name == config["saved_scene_name"]:
                kind = "save"
            elif name == config["display_name"]:
                kind = "consumer"
            else:
                kind = "producer"
            framebuffer = graph["framebuffers"][name]
            framebuffer.use()
            self.context.viewport = (0, 0, *framebuffer.size)
            previous.use(0)
            graph["decoy"].use(1)
            for slot in range(3, 8):
                graph["blank"].use(slot)
            for source, source_pass, dest, dest_pass, slot in config["connections"]:
                if dest != name:
                    continue
                self.assertEqual((source_pass, dest_pass), (0, 0))
                self.assertIn(source, completed, "connections must point forward")
                if (dest, slot) not in disconnect:
                    graph["targets"][source].use(slot)
            program = self.programs[kind]
            for slot in (0, 1, 3, 4):
                uniform = "TEXTURE_%d" % slot
                if uniform in program:
                    program[uniform].value = slot
            for index, parameter in enumerate(process.get("paras", []), 1):
                value = parameter["value"]
                if kind == "producer" and parameter["name"] in ("packet0", "packet1"):
                    page = config["producer_names"].index(name)
                    start = 0 if parameter["name"] == "packet0" else 4
                    value = [word / 16777216.0 for word in words[page][start:start + 4]]
                elif kind == "consumer" and parameter["name"] == "query":
                    value = [float(mode), 0.0, float(PAYLOAD_BYTES), float(salt)]
                program["EXTRA_VECTOR%d" % index].value = value
            self.arrays[kind].render(self.gl.TRIANGLE_STRIP)
            previous = graph["targets"][name]
            completed.add(name)
        return self.read(graph, config["display_name"])

    @staticmethod
    def read(graph, name):
        framebuffer = graph["framebuffers"][name]
        width, height = framebuffer.size
        return np.frombuffer(framebuffer.read(components=4, alignment=1), dtype=np.uint8).reshape(
            height, width, 4).copy()

    @staticmethod
    def region(config, size):
        width, height = size
        y, x = np.indices((height, width))
        left, top, rect_width, rect_height = config["display_rect_norm"]
        point_x = ((x + 0.5) / width - left) / rect_width
        point_y = ((height - y - 0.5) / height - top) / rect_height
        inside = ((point_x >= 0) & (point_x < 1) & (point_y >= 0) & (point_y < 1))
        indices = (np.floor(point_y * 4).astype(np.int64) * 24
                   + np.floor(point_x * 24).astype(np.int64))
        return inside, indices

    def expected(self, graph, scene, words, mode, salt=7):
        expected = scene.copy()
        if mode == 0:
            return expected
        data = np.frombuffer(payload_bytes(words), dtype=np.uint8)
        inside, indices = self.region(graph["config"], graph["size"])
        selected = indices[inside]
        self.assertEqual(set(selected), set(range(PAYLOAD_BYTES)))
        if mode == 2:
            selected = (selected + data[selected].astype(np.int64) + salt) % PAYLOAD_BYTES
        values = data[selected]
        expected[inside] = np.column_stack((values, values, values, np.full(len(values), 255)))
        return expected

    def test_saved_scene_and_hidden_consumer_restore_every_rgba_byte(self):
        scene = detailed_scene(PHONE, 0)
        for channel in range(4):
            self.assertEqual(set(np.unique(scene[:, :, channel])), set(range(256)))
        with self.graph() as graph:
            result = self.execute(graph, scene, payload_words(0), mode=0)
            self.assert_rgba_equal(self.read(graph, graph["config"]["saved_scene_name"]),
                                   scene, "saved complete C0")
            self.assert_rgba_equal(result, scene, "hidden consumer complete C0")

    def test_identity_and_dependent_cover_all_96_bytes_and_cross_pages(self):
        words = payload_words(0)
        data = payload_bytes(words)
        with self.graph() as graph:
            scene = detailed_scene(PHONE, 3)
            for mode, salt in ((1, 7), (2, 0), (2, 7), (2, 255)):
                with self.subTest(mode=mode, salt=salt):
                    if mode == 2:
                        targets = [(i + data[i] + salt) % PAYLOAD_BYTES for i in range(PAYLOAD_BYTES)]
                        self.assertTrue(any(i // 24 != target // 24 for i, target in enumerate(targets)))
                    actual = self.execute(graph, scene, words, mode, salt)
                    self.assert_rgba_equal(actual, self.expected(graph, scene, words, mode, salt),
                                           "full diagnostic and untouched exterior")

    def test_payload_and_private_atlas_do_not_depend_on_scene_rgba(self):
        words = payload_words(9)
        with self.graph() as graph:
            inside, _ = self.region(graph["config"], PHONE)
            atlases, diagnostics = [], []
            for phase in (11, 87):
                scene = detailed_scene(PHONE, phase)
                actual = self.execute(graph, scene, words, mode=2)
                self.assert_rgba_equal(actual, self.expected(graph, scene, words, 2), "scene isolation")
                atlases.append(self.read(graph, graph["config"]["producer_names"][-1]))
                diagnostics.append(actual[inside])
            self.assert_rgba_equal(atlases[0], atlases[1], "scene-independent private RT")
            np.testing.assert_array_equal(diagnostics[0], diagnostics[1])

    def test_32_generations_replace_the_same_gpu_targets_without_stale_bytes(self):
        with self.graph(size=(240, 160)) as graph:
            previous_payload = None
            for generation in range(32):
                with self.subTest(generation=generation):
                    words = payload_words(generation)
                    self.assertNotEqual(payload_bytes(words), previous_payload)
                    previous_payload = payload_bytes(words)
                    scene = detailed_scene(graph["size"], generation)
                    for mode in (1, 2, 0):
                        result = self.execute(graph, scene, words, mode, salt=7 + generation)
                        self.assert_rgba_equal(result, self.expected(
                            graph, scene, words, mode, 7 + generation), "generation %d mode %d" % (
                                generation, mode))

    def test_disconnected_final_data_breaks_diagnostics_but_preserves_scene(self):
        scene, words = detailed_scene(PHONE, 13), payload_words(5)
        with self.graph() as graph:
            disconnect = {(graph["config"]["display_name"], 3)}
            inside, _ = self.region(graph["config"], PHONE)
            for mode in (1, 2):
                actual = self.execute(graph, scene, words, mode, disconnect=disconnect)
                self.assertTrue(np.any(actual[inside] != self.expected(graph, scene, words, mode)[inside]))
                np.testing.assert_array_equal(actual[~inside], scene[~inside])
            self.assert_rgba_equal(self.execute(graph, scene, words, 0, disconnect=disconnect),
                                   scene, "hidden mode survives absent payload")

    def test_disconnected_saved_scene_cannot_restore_from_implicit_buffers(self):
        scene, words = detailed_scene(PHONE, 19), payload_words(7)
        with self.graph() as graph:
            disconnect = {(graph["config"]["display_name"], 4)}
            actual = self.execute(graph, scene, words, 0, disconnect=disconnect)
            self.assert_rgba_equal(actual, np.zeros_like(scene), "missing saved C0 yields zero RGBA")
            self.assertFalse(np.array_equal(actual, scene))
            actual = self.execute(graph, scene, words, 2, disconnect=disconnect)
            inside, _ = self.region(graph["config"], PHONE)
            expected = self.expected(graph, scene, words, 2)
            np.testing.assert_array_equal(actual[inside], expected[inside])
            np.testing.assert_array_equal(actual[~inside], np.zeros_like(actual[~inside]))

    def test_disconnected_internal_producer_link_loses_earlier_pages(self):
        scene, words = detailed_scene(PHONE, 23), payload_words(11)
        with self.graph() as graph:
            disconnect = {(graph["config"]["producer_names"][2], 3)}
            actual = self.execute(graph, scene, words, 1, disconnect=disconnect)
            inside, indices = self.region(graph["config"], PHONE)
            earlier = inside & (indices < 48)
            later = inside & (indices >= 48)
            np.testing.assert_array_equal(actual[earlier, :3], np.zeros_like(actual[earlier, :3]))
            np.testing.assert_array_equal(actual[later], self.expected(graph, scene, words, 1)[later])
            np.testing.assert_array_equal(actual[~inside], scene[~inside])
            self.assertFalse(np.array_equal(actual, self.expected(graph, scene, words, 1)))

    def test_64kib_all_identity_and_dependent_bytes_with_compact_gpu_readout(self):
        """Bound desktop memory with two atlas RTs; this is not a native run.

        Producer sizes come from the 720x1080 config. Only the diagnostic
        consumer output is compacted to 24x2731 so all 65,536 queries and the
        eight zero padding cells can be checked in one draw per query mode.
        """
        length = 65536
        config = isolated_config(screen_size=PHONE, payload_bytes=length)
        self.assertEqual(config["pages"], 2731)
        words = payload_words(17, config["pages"])
        stored_bytes = payload_bytes(words)
        self.assertEqual(len(stored_bytes), length + 8)
        self.assertTrue(any(stored_bytes[length:]), "padding storage is intentionally nonzero")
        data = np.frombuffer(stored_bytes[:length], dtype=np.uint8)
        resources = []
        framebuffers = []

        def texture(size, pixels=None):
            result = self.context.texture(tuple(size), 4, pixels, dtype="f1")
            result.filter = (self.gl.NEAREST, self.gl.NEAREST)
            result.repeat_x = result.repeat_y = False
            resources.append(result)
            return result

        def target(size):
            result = texture(size)
            framebuffer = self.context.framebuffer(color_attachments=[result])
            framebuffers.append(framebuffer)
            return result, framebuffer

        try:
            scene = detailed_scene(PHONE, 37)
            scene_texture = texture(PHONE, scene.tobytes())
            saved, saved_framebuffer = target(PHONE)
            blank = texture((1, 1), bytes(4))
            self.context.disable(self.gl.BLEND | self.gl.DEPTH_TEST | self.gl.CULL_FACE)
            saved_framebuffer.use()
            self.context.viewport = (0, 0, *PHONE)
            scene_texture.use(0)
            self.programs["save"]["TEXTURE_0"].value = 0
            self.arrays["save"].render(self.gl.TRIANGLE_STRIP)
            self.assertEqual(saved_framebuffer.read(components=4, alignment=1), scene.tobytes())

            dimensions = tuple(config["target_pixels"])
            pairs = [target(dimensions), target(dimensions)]
            program = self.programs["producer"]
            program["TEXTURE_3"].value = 3
            previous = blank
            for page, page_words in enumerate(words):
                output, framebuffer = pairs[page % 2]
                framebuffer.use()
                self.context.viewport = (0, 0, *dimensions)
                previous.use(3)
                program["EXTRA_VECTOR1"].value = config["page_uniforms"][page]
                for uniform, offset in (("EXTRA_VECTOR2", 0), ("EXTRA_VECTOR3", 4)):
                    program[uniform].value = [word / 16777216.0 for word in page_words[offset:offset + 4]]
                self.arrays["producer"].render(self.gl.TRIANGLE_STRIP)
                previous = output

            # Independently inspect all storage words, including the nonzero
            # tail. The consumer must enforce logical array length itself.
            width, height = dimensions
            atlas = np.frombuffer(pairs[(config["pages"] - 1) % 2][1].read(
                components=4, alignment=1), dtype=np.uint8).reshape(height, width, 4)
            columns = int(config["display_layout"][0])
            page_indices = np.arange(config["pages"])
            xs = (page_indices[:, None] % columns) * 8 + np.arange(8)
            ys = page_indices[:, None] // columns
            self.assertEqual(atlas[ys, xs, :3].tobytes(), stored_bytes)

            rows = (length + 23) // 24
            _, output_framebuffer = target((24, rows))
            consumer = self.programs["consumer"]
            consumer["TEXTURE_3"].value = 3
            consumer["TEXTURE_4"].value = 4
            consumer["EXTRA_VECTOR2"].value = (0.0, 0.0, 1.0, 1.0)
            consumer["EXTRA_VECTOR3"].value = config["display_layout"]
            for mode in (1, 2):
                with self.subTest(mode=mode):
                    output_framebuffer.use()
                    self.context.viewport = (0, 0, 24, rows)
                    previous.use(3)
                    saved.use(4)
                    salt = 257
                    consumer["EXTRA_VECTOR1"].value = (float(mode), 0.0, float(length), float(salt))
                    self.arrays["consumer"].render(self.gl.TRIANGLE_STRIP)
                    observed = np.frombuffer(output_framebuffer.read(
                        components=4, alignment=1), dtype=np.uint8).reshape(rows, 24, 4)[::-1].reshape(-1, 4)
                    indices = np.arange(length)
                    if mode == 2:
                        indices = (indices + data.astype(np.int64) + salt) % length
                        self.assertTrue(np.any(indices // 24 != np.arange(length) // 24))
                    expected = np.zeros((rows * 24, 4), dtype=np.uint8)
                    expected[:, 3] = 255
                    expected[:length, :3] = data[indices, None]
                    np.testing.assert_array_equal(observed, expected)
            self.assertEqual(saved_framebuffer.read(components=4, alignment=1), scene.tobytes(),
                             "large payload passes must not modify saved scene RGBA")
        finally:
            for framebuffer in reversed(framebuffers):
                framebuffer.release()
            for resource in reversed(resources):
                resource.release()


if __name__ == "__main__":
    unittest.main()
