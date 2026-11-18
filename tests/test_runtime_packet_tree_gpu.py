"""Real desktop OpenGL correctness checks for the 36-byte private RT tree.

These tests never launch Minecraft. Desktop textures persist between draws;
the local-update case does not establish native dirty-subtree caching, native
RT allocation, ModSDK scheduling, performance, or per-frame freshness.
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
from tree_assets import tree_config


PHONE = (720, 1080)


def independent_words(generation, pages):
    """Generate uint24 integers without any runtime dataset or verifier."""
    state = (0xB736D1 + generation * 0x45D9F3B) & 0xFFFFFFFF
    result = []
    for _ in range(pages * 12):
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        result.append(state >> 8)
    if generation == 0:
        result[:12] = [0, 1, 255, 256, 65535, 65536, 8388607, 8388608,
                       8388609, 16777213, 16777214, 16777215]
    return [result[start:start + 12] for start in range(0, len(result), 12)]


def independent_bytes(words):
    return b"".join(word.to_bytes(3, "big") for page in words for word in page)


def detailed_scene(size, phase):
    """Bottom-up, payload-independent RGBA8 pixels, including varying alpha."""
    width, height = size
    y, x = np.indices((height, width), dtype=np.uint32)
    return np.stack(((17 * x + 31 * y + 6 * (x ^ y) + 53 * phase) & 255,
                     (43 * x + 11 * y + 4 * (x ^ (y * 5)) + 71 * phase) & 255,
                     (5 * x + 67 * y + 19 * ((x // 3) ^ y) + 97 * phase) & 255,
                     (x + 3 * y + 29 * phase) & 255), axis=-1).astype(np.uint8)


@unittest.skipUnless(importlib.util.find_spec("moderngl"), "optional desktop OpenGL diagnostic")
class RuntimePacketTreeGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import moderngl
        from pyreact_manim.compiler.desktop import desktop_fragment

        cls.gl = moderngl
        cls.context = moderngl.create_standalone_context(require=330)
        cls.vertices = cls.context.buffer(struct.pack("8f", -1, -1, 1, -1, -1, 1, 1, 1))
        cls.programs, cls.arrays = {}, {}
        vertex = """#version 330
in vec2 position;
out vec2 uv;
void main() { uv = position * 0.5 + 0.5; gl_Position = vec4(position, 0.0, 1.0); }
"""
        for kind, filename in (("save", "isolated_copy.fragment"),
                               ("leaf", "tree_leaf.fragment"),
                               ("merge", "tree_merge.fragment"),
                               ("consumer", "tree_consumer.fragment")):
            program = cls.context.program(vertex_shader=vertex, fragment_shader=desktop_fragment(
                (PROBE / filename).read_text(encoding="utf-8")))
            cls.programs[kind] = program
            cls.arrays[kind] = cls.context.simple_vertex_array(program, cls.vertices, "position")

    @classmethod
    def tearDownClass(cls):
        for array in cls.arrays.values():
            array.release()
        for program in cls.programs.values():
            program.release()
        cls.vertices.release()
        cls.context.release()

    def assert_pixels_equal(self, actual, expected, label):
        self.assertEqual(actual.shape, expected.shape, label)
        unequal = actual != expected
        if np.any(unequal):
            position = tuple(np.argwhere(unequal)[0])
            self.fail("%s: %d channel errors; first at %s: %d != %d" % (
                label, np.count_nonzero(unequal), position, actual[position], expected[position]))

    @contextmanager
    def graph(self, length=1000, size=PHONE):
        """Allocate every configured RT independently and follow real links."""
        config = tree_config(payload_bytes=length, screen_size=size)
        targets, framebuffers, textures = {}, {}, []
        processes = {item["name"]: item for item in config["processes"]}
        leaf_indices = {name: index for index, name in enumerate(config["leaf_names"])}
        incoming = {name: [] for name in processes}
        for source, source_pass, dest, dest_pass, slot in config["connections"]:
            self.assertEqual((source_pass, dest_pass), (0, 0))
            self.assertIn(slot, range(3, 8))
            incoming[dest].append((source, slot))
        descendants, completed = {}, set()
        for process in config["processes"]:
            name = process["name"]
            self.assertTrue(all(source in completed for source, _ in incoming[name]),
                            "all configured texture edges must point forward")
            if name in leaf_indices:
                descendants[name] = {leaf_indices[name]}
            else:
                descendants[name] = set().union(*(descendants[source] for source, _ in incoming[name]))
            completed.add(name)

        def texture(dimensions, data=None):
            result = self.context.texture(tuple(dimensions), 4, data, dtype="f1")
            result.filter = (self.gl.NEAREST, self.gl.NEAREST)
            result.repeat_x = result.repeat_y = False
            textures.append(result)
            return result

        try:
            scene = texture(size)
            decoy = texture(size, detailed_scene(size, 193).tobytes())
            blank = texture((1, 1), bytes(4))
            for process in config["processes"]:
                name = process["name"]
                target = process["pass_array"][0]["render_target"]
                dimensions = tuple(max(1, math.floor(struct.unpack("f", struct.pack(
                    "f", target[key]))[0] * size[index]))
                                   for index, key in enumerate(("width", "height")))
                if name in leaf_indices:
                    self.assertEqual(dimensions, (12, 1))
                    self.assertEqual([item["name"] for item in process["paras"]],
                                     ["packet0", "packet1", "packet2"])
                elif name in config["merge_parameters"]:
                    self.assertEqual(dimensions, tuple(map(int, config["merge_parameters"][name]["node"][:2])))
                else:
                    self.assertEqual(dimensions, tuple(size))
                targets[name] = texture(dimensions)
                framebuffers[name] = self.context.framebuffer(color_attachments=[targets[name]])
                framebuffers[name].clear(0.82, 0.37, 0.19, 0.13)
            self.assertEqual(targets[config["root_name"]].size, tuple(config["target_pixels"]))
            yield {"config": config, "scene": scene, "decoy": decoy, "blank": blank,
                   "targets": targets, "framebuffers": framebuffers, "size": tuple(size),
                   "processes": processes, "leaf_indices": leaf_indices, "incoming": incoming,
                   "descendants": descendants, "initialized": set()}
        finally:
            for framebuffer in reversed(list(framebuffers.values())):
                framebuffer.release()
            for item in reversed(textures):
                item.release()

    @staticmethod
    def read(graph, name):
        framebuffer = graph["framebuffers"][name]
        width, height = framebuffer.size
        return np.frombuffer(framebuffer.read(components=4, alignment=1), dtype=np.uint8).reshape(
            height, width, 4).copy()

    def draw_process(self, graph, name, words, query, previous, disconnect=()):
        config = graph["config"]
        kind = ("save" if name == config["saved_scene_name"] else
                "consumer" if name == config["display_name"] else
                "leaf" if name in graph["leaf_indices"] else "merge")
        framebuffer = graph["framebuffers"][name]
        framebuffer.use()
        self.context.viewport = (0, 0, *framebuffer.size)
        previous.use(0)
        graph["decoy"].use(1)
        for slot in range(3, 8):
            graph["blank"].use(slot)
        for source, slot in graph["incoming"][name]:
            self.assertIn(source, graph["initialized"])
            if (name, slot) not in disconnect:
                graph["targets"][source].use(slot)
        program = self.programs[kind]
        for slot in (0, 1, 3, 4, 5, 6, 7):
            uniform = "TEXTURE_%d" % slot
            if uniform in program:
                program[uniform].value = slot
        for index, parameter in enumerate(graph["processes"][name].get("paras", []), 1):
            value = parameter["value"]
            if kind == "leaf":
                offset = (index - 1) * 4
                value = [word / 16777216.0 for word in words[graph["leaf_indices"][name]][offset:offset + 4]]
            elif kind == "consumer" and parameter["name"] == "query":
                value = query
            program["EXTRA_VECTOR%d" % index].value = value
        self.arrays[kind].render(self.gl.TRIANGLE_STRIP)
        graph["initialized"].add(name)

    def execute(self, graph, scene, words, mode=0, start=0, count=None, salt=7,
                disconnect=(), dirty_leaves=None):
        count = min(graph["config"]["payload_bytes"], 3072) if count is None else count
        query = [float(mode), float(start), float(count), float(salt)]
        graph["scene"].write(scene.tobytes())
        self.context.disable(self.gl.BLEND | self.gl.DEPTH_TEST | self.gl.CULL_FACE)
        previous = graph["scene"]
        for process in graph["config"]["processes"]:
            name = process["name"]
            index = graph["leaf_indices"].get(name)
            if index is not None and dirty_leaves is not None and index not in dirty_leaves:
                self.assertIn(name, graph["initialized"], "cannot reuse an uninitialized desktop RT")
            else:
                self.draw_process(graph, name, words, query, previous, disconnect)
            previous = graph["targets"][name]
        return self.read(graph, graph["config"]["display_name"])

    def consumer(self, graph, words, mode, start, count, salt=7):
        config = graph["config"]
        self.draw_process(graph, config["display_name"], words,
                          [float(mode), float(start), float(count), float(salt)],
                          graph["targets"][config["root_name"]])
        return self.read(graph, config["display_name"])

    def assert_diagnostic(self, graph, actual, scene, data, mode, start=0, count=None, salt=7):
        """Check every query's full 3x3 RGBA patch and every exterior pixel."""
        count = min(len(data), 3072) if count is None else count
        width, height = graph["size"]
        left, top, rect_width, rect_height = graph["config"]["display_rect_norm"]
        y, x = np.indices((height, width))
        px = ((x + 0.5) / width - left) / rect_width
        py = ((height - y - 0.5) / height - top) / rect_height
        outside = (px < 0) | (px >= 1) | (py < 0) | (py >= 1)
        self.assert_pixels_equal(actual[outside], scene[outside], "exterior complete RGBA")
        rows = (count + 23) // 24
        offsets = np.arange(rows * 24)
        columns, row = offsets % 24, offsets // 24
        centers_x = ((left + (columns + 0.5) * rect_width / 24) * width).astype(int)
        centers_y = height - 1 - ((top + (row + 0.5) * rect_height / rows) * height).astype(int)
        self.assertGreaterEqual(rect_width * width / 24, 3)
        self.assertGreaterEqual(rect_height * height / rows, 3)
        observed = actual[centers_y[:, None, None] + np.arange(-1, 2)[None, :, None],
                          centers_x[:, None, None] + np.arange(-1, 2)[None, None, :]]
        source = np.frombuffer(data, dtype=np.uint8)
        valid = (offsets < count) & (start + offsets < len(source))
        indices = start + offsets[valid]
        if mode == 2:
            indices = (indices + source[indices].astype(np.int64) + salt) % len(source)
        values = np.zeros(len(offsets), dtype=np.uint8)
        values[valid] = source[indices]
        expected = np.column_stack((values, values, values, np.full(len(values), 255, dtype=np.uint8)))
        self.assert_pixels_equal(observed, np.broadcast_to(expected[:, None, None, :], observed.shape),
                                 "all query and zero-padding 3x3 RGBA patches")
        return set(range(start, start + int(np.count_nonzero(valid))))

    def assert_root_storage(self, graph, words):
        root = self.read(graph, graph["config"]["root_name"])
        storage = independent_bytes(words)
        pixels = root[:, :, :3].reshape(-1).tobytes()
        self.assert_pixels_equal(np.frombuffer(pixels[:len(storage)], dtype=np.uint8),
                                 np.frombuffer(storage, dtype=np.uint8), "root byte order")
        self.assert_pixels_equal(np.frombuffer(pixels[len(storage):], dtype=np.uint8),
                                 np.zeros(len(pixels) - len(storage), dtype=np.uint8),
                                 "root rectangle padding")
        self.assertTrue(np.all(root[:, :, 3] == 255))

    def test_multilevel_nonfull_tree_preserves_rgba_and_all_identity_dependent_bytes(self):
        with self.graph() as graph:
            config = graph["config"]
            self.assertGreater(len(config["leaf_names"]), 5)
            self.assertGreaterEqual(len(config["levels"]), 4)
            fanins = [len(graph["incoming"][name]) for name in config["merge_parameters"]]
            self.assertIn(5, fanins)
            self.assertTrue(any(fanin < 5 for fanin in fanins))
            scene = detailed_scene(PHONE, 0)
            for channel in range(4):
                self.assertEqual(set(np.unique(scene[:, :, channel])), set(range(256)))
            words = independent_words(0, config["pages"])
            data = independent_bytes(words)[:config["payload_bytes"]]
            self.assertTrue(any(independent_bytes(words)[len(data):]))
            hidden = self.execute(graph, scene, words)
            self.assert_pixels_equal(hidden, scene, "hidden complete C0")
            self.assert_pixels_equal(self.read(graph, config["saved_scene_name"]), scene, "saved complete C0")
            self.assert_root_storage(graph, words)
            for mode, salt in ((1, 7), (2, 0), (2, 7), (2, 255)):
                with self.subTest(mode=mode, salt=salt):
                    actual = self.consumer(graph, words, mode, 0, len(data), salt)
                    self.assertEqual(self.assert_diagnostic(graph, actual, scene, data, mode,
                                                           count=len(data), salt=salt), set(range(len(data))))

    def test_private_tree_is_independent_of_scene_rgba(self):
        with self.graph() as graph:
            words = independent_words(9, graph["config"]["pages"])
            roots = []
            for phase in (11, 87):
                scene = detailed_scene(PHONE, phase)
                actual = self.execute(graph, scene, words, mode=2)
                self.assert_diagnostic(graph, actual, scene, independent_bytes(words)[:1000], 2)
                roots.append(self.read(graph, graph["config"]["root_name"]))
            self.assert_pixels_equal(roots[0], roots[1], "scene-independent private tree")

    def test_disconnecting_nonfirst_merge_sampler_only_loses_its_subtree(self):
        with self.graph() as graph:
            config = graph["config"]
            chosen = next((name, source, slot) for name in config["merge_parameters"]
                          for source, slot in graph["incoming"][name] if slot == 5)
            dest, source, slot = chosen
            lost_leaves = graph["descendants"][source]
            self.assertTrue(lost_leaves)
            self.assertNotIn(0, lost_leaves)
            words = independent_words(5, config["pages"])
            original = independent_bytes(words)[:1000]
            expected = bytearray(original)
            for leaf in lost_leaves:
                first, last = leaf * 36, min((leaf + 1) * 36, len(expected))
                expected[first:last] = bytes(last - first)
            self.assertNotEqual(bytes(expected), original)
            scene = detailed_scene(PHONE, 13)
            actual = self.execute(graph, scene, words, mode=1, disconnect={(dest, slot)})
            self.assert_diagnostic(graph, actual, scene, bytes(expected), 1)

    def test_32_partial_leaf_updates_reuse_existing_desktop_resources(self):
        """Only changed leaf RTs redraw here; no native caching claim follows."""
        with self.graph(size=(240, 240)) as graph:
            pages = graph["config"]["pages"]
            words = independent_words(0, pages)
            self.execute(graph, detailed_scene(graph["size"], 0), words)
            for generation in range(1, 33):
                with self.subTest(generation=generation):
                    dirty = {(generation * 7) % pages, (generation * 11 + 5) % pages, pages - 1}
                    self.assertLess(len(dirty), pages)
                    unchanged = next(index for index in range(pages) if index not in dirty)
                    name = graph["config"]["leaf_names"][unchanged]
                    before = self.read(graph, name)
                    replacement = independent_words(generation, pages)
                    for index in dirty:
                        self.assertNotEqual(words[index], replacement[index])
                        words[index] = replacement[index]
                    scene = detailed_scene(graph["size"], generation)
                    data = independent_bytes(words)[:1000]
                    actual = self.execute(graph, scene, words, mode=1, dirty_leaves=dirty)
                    self.assert_diagnostic(graph, actual, scene, data, 1)
                    self.assert_pixels_equal(self.read(graph, name), before, "unchanged leaf RT")
                    self.assert_root_storage(graph, words)
                    self.assert_diagnostic(graph, self.consumer(graph, words, 2, 0, len(data)),
                                           scene, data, 2)
                    hidden = self.consumer(graph, words, 0, 0, len(data))
                    self.assert_pixels_equal(hidden, scene, "partial-update hidden complete C0")

    def test_64kib_all_identity_dependent_queries_and_padded_root(self):
        with self.graph(length=65536) as graph:
            config = graph["config"]
            self.assertEqual(config["pages"], 1821)
            self.assertGreater(config["target_pixels"][0], 12)
            words = independent_words(17, config["pages"])
            storage = independent_bytes(words)
            self.assertEqual(len(storage), 65556)
            self.assertTrue(any(storage[65536:]), "logical padding storage must not be silently all zero")
            data = storage[:65536]
            scene = detailed_scene(PHONE, 37)
            self.assert_pixels_equal(self.execute(graph, scene, words), scene, "large hidden complete C0")
            self.assert_root_storage(graph, words)
            for mode in (1, 2):
                seen = set()
                for start in range(0, len(data), 3072):
                    count = min(3072, len(data) - start)
                    with self.subTest(mode=mode, start=start):
                        actual = self.consumer(graph, words, mode, start, count, salt=257)
                        verified = self.assert_diagnostic(graph, actual, scene, data, mode,
                                                          start, count, salt=257)
                        self.assertFalse(seen.intersection(verified))
                        seen.update(verified)
                self.assertEqual(seen, set(range(65536)))
            self.assert_pixels_equal(self.read(graph, config["saved_scene_name"]), scene,
                                     "large data tree must not modify saved C0")


if __name__ == "__main__":
    unittest.main()
