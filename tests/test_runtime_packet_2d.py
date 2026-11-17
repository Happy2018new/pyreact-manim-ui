"""Exact desktop GPU diagnostics for the independent two-dimensional atlas.

These tests exercise the generated uniforms and explicit texture connections.
They do not establish Minecraft support, engine limits, or mobile performance.
"""
from contextlib import contextmanager
import importlib.util
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools/runtime_packet_probe"
sys.path.insert(0, str(PROBE))
sys.path.insert(0, str(ROOT / "src"))
from atlas2d_assets import atlas2d_config, build_atlas2d_assets
from verify_spatial import expected_words, verify_spatial


PHONE = (720, 1080)


class SpatialVerifierTests(unittest.TestCase):
    def receipt(self, start=0, count=3, shift=0):
        return {"transport": "atlas2d", "screen_size": list(PHONE), "expected_seed": 12345,
                "aggregate": {"pages": 8, "words": expected_words(12345, 8),
                              "words_per_page": 8, "display_rect_norm": [0, 0, 1, 1],
                              "query": [8, start, count, shift]}}

    def synthetic(self, receipt):
        """Draw from integer words without consulting verifier group coordinates."""
        image = Image.new("RGBA", PHONE, (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        aggregate = receipt["aggregate"]
        pages, start, count, shift = map(int, aggregate["query"])
        for row in range(count):
            page = start + row
            for cell in range(24):
                value = 0
                if page < pages:
                    word = aggregate["words"][page][(cell // 3 + shift) % 8]
                    value = (word >> (16 - (cell % 3) * 8)) & 255
                draw.rectangle((cell * PHONE[0] // 24, row * PHONE[1] // count,
                                (cell + 1) * PHONE[0] // 24 - 1,
                                (row + 1) * PHONE[1] // count - 1),
                               fill=(value, value, value, 255))
        return image

    def test_every_page_window_and_tail_padding_are_checked(self):
        verified = []
        for start in (0, 3, 6):
            with self.subTest(start=start):
                receipt = self.receipt(start=start, shift=-1)
                result = verify_spatial(receipt, self.synthetic(receipt))
                length = min(3, 8 - start)
                self.assertTrue(result["passed"])
                self.assertTrue(result["exact_equal"])
                self.assertEqual(result["checked_cells"], 3 * 24)
                self.assertEqual(result["payload_bytes"], length * 24)
                self.assertEqual(result["verified_page_indices"], list(range(start, start + length)))
                self.assertEqual(result["observed_payload_sha256"], result["expected_payload_sha256"])
                verified.extend(result["verified_page_indices"])
                if start == 6:
                    self.assertFalse(result["results"][-1]["payload"])
                    self.assertEqual(result["results"][-1]["observed"], [[0, 0, 0]] * 24)
        self.assertEqual(verified, list(range(8)))

    def test_corrupt_payload_or_padding_byte_fails(self):
        receipt = self.receipt(start=6)
        for row in (0, 2):
            with self.subTest(row=row):
                image = self.synthetic(receipt)
                center = (PHONE[0] // 48, (2 * row + 1) * PHONE[1] // 6)
                pixel = image.getpixel(center)
                image.putpixel(center, ((pixel[0] + 1) % 256, *pixel[1:]))
                result = verify_spatial(receipt, image)
                self.assertFalse(result["passed"])
                self.assertEqual(result["failed_cells"], 1)
                self.assertGreater(result["max_error"], 0)

    def test_alpha_corruption_seed_mismatch_and_wrong_capture_size_are_rejected(self):
        receipt = self.receipt()
        image = self.synthetic(receipt)
        center = (PHONE[0] // 48, PHONE[1] // 6)
        image.putpixel(center, (*image.getpixel(center)[:3], 254))
        self.assertFalse(verify_spatial(receipt, image)["passed"])
        with self.assertRaisesRegex(ValueError, "dimensions"):
            verify_spatial(receipt, image.resize((1080, 720)))
        receipt["expected_seed"] += 1
        with self.assertRaisesRegex(ValueError, "expected seed"):
            verify_spatial(receipt, image)


class SpatialAdapterTests(unittest.TestCase):
    def setUp(self):
        # Reuse only the SDK doubles and setup, without inheriting its test cases.
        spec = importlib.util.spec_from_file_location(
            "_atlas2d_runtime_harness", ROOT / "tests/test_runtime_packet_runtime.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.harness = module.RuntimePacketRuntimeTests()
        self.harness.setUp()
        self.addCleanup(self.harness.doCleanups)
        self.spatial = self.harness.load_module(
            "_runtime_packet_behavior_test.spatial_runtime", "spatial_runtime.py")

    def test_finish_restores_two_dimensional_uniforms_and_snapshot_carries_layout(self):
        config = atlas2d_config(257, screen_size=PHONE)
        probe = self.spatial.SpatialProbe(self.harness.post, config, 12345)
        probe.finish()
        post = self.harness.post
        for name, value in zip(config["producer_names"], config["page_uniforms"]):
            self.assertEqual(post.parameters[(name, "page")], value)
        self.assertEqual(post.parameters[(config["display_name"], "atlas_layout")],
                         config["display_layout"])
        self.assertEqual(post.parameters[(config["display_name"], "display_rect")],
                         config["display_rect_norm"])
        probe.select(256, 128, 3)
        snapshot = probe.snapshot()
        self.assertTrue(snapshot["ready"])
        self.assertTrue(all(snapshot["connections"]))
        self.assertEqual(len(snapshot["connections"]), 257)
        self.assertEqual(snapshot["aggregate"]["query"], [257.0, 256.0, 128.0, 3.0])
        self.assertEqual(snapshot["aggregate"]["words"], expected_words(12345, 257))
        self.assertEqual(snapshot["aggregate"]["layout"], config["layout"])
        self.assertEqual(snapshot["screen_size"], list(PHONE))
        self.assertEqual(snapshot["transport"], "atlas2d")
        self.assertFalse(snapshot["gpu_verified"])

    def test_split_snapshot_falls_back_to_physical_screen_without_mutating_input(self):
        from uniform_split_assets import uniform_split_config

        config = uniform_split_config(4, screen_size=PHONE)
        config.pop("target_pixels", None)
        probe = self.spatial.SpatialProbe(self.harness.post, config, 12345)
        snapshot = probe.finish()
        self.assertNotIn("target_pixels", config)
        self.assertEqual(snapshot["target_pixels"], list(PHONE))
        self.assertEqual(snapshot["screen_size"], list(PHONE))
        self.assertEqual(snapshot["transport"], "uniform_split")
        self.assertIsNone(snapshot["aggregate"]["query"])
        self.assertEqual(snapshot["rectangles_norm"], config["rectangles_norm"])
        self.assertEqual(snapshot["aggregate"]["words"], expected_words(12345, 4))
        for name, rectangle in zip(config["producer_names"], config["metadata_values"]):
            self.assertEqual(self.harness.post.parameters[(name, "tile")], rectangle)
        with self.assertRaisesRegex(RuntimeError, "no atlas query"):
            probe.select()

    def test_select_default_count_fits_small_atlas_and_caps_large_atlas(self):
        for pages in (1, 4, 128, 257):
            with self.subTest(pages=pages):
                config = atlas2d_config(pages, screen_size=PHONE)
                probe = self.spatial.SpatialProbe(self.harness.post, config, 12345)
                probe.finish()
                probe.select()
                expected = [float(pages), 0., float(min(128, pages)), 0.]
                self.assertEqual(probe.snapshot()["aggregate"]["query"], expected)
                self.assertEqual(self.harness.post.parameters[(config["display_name"], "query")], expected)


class Atlas2dConfigTests(unittest.TestCase):
    def test_phone_layout_has_real_texels_for_each_word_at_all_research_scales(self):
        for screen in (PHONE, (1280, 720), (1920, 1080), (2400, 1080)):
            for pages in (1, 1024, 2048, 4096, 8192, 16384):
                with self.subTest(screen=screen, pages=pages):
                    config = atlas2d_config(pages, screen_size=screen)
                    layout = config["atlas_layout"]
                    columns, rows = layout["columns"], layout["rows"]
                    self.assertGreaterEqual(columns * rows, pages)
                    self.assertEqual(layout["logical_width"], columns * 8)
                    self.assertEqual(layout["logical_height"], rows)
                    self.assertEqual(layout["capacity_pages"], columns * rows)
                    self.assertEqual(layout["empty_pages"], columns * rows - pages)
                    self.assertIn(layout["texels_per_word"], (1, 2, 4))
                    self.assertEqual(config["target_pixels"], [
                        columns * 8 * layout["texels_per_word"],
                        rows * layout["texels_per_word"]])
                    self.assertTrue(all(actual <= limit for actual, limit in
                                        zip(config["target_pixels"], screen)))
                    target = config["processes"][0]["pass_array"][0]["render_target"]
                    # The engine can narrow ratios to float32 before flooring
                    # the physical size. A one-pixel loss drops dense words.
                    actual_pixels = [math.floor(struct.unpack("f", struct.pack(
                        "f", target[key]))[0] * screen[index])
                        for index, key in enumerate(("width", "height"))]
                    self.assertEqual(actual_pixels, config["target_pixels"])
                    if pages >= 1024:
                        self.assertGreater(columns, 1)
                        self.assertGreater(rows, 1)
                    self.assertEqual(config["words_per_page"], 8)
                    self.assertEqual(config["query"], [float(pages), 0.0,
                                                       float(min(pages, 128)), 0.0])
                    self.assertEqual(config["display_layout"],
                                     [float(columns), float(rows), 0.0, 0.0])

    def test_process_contract_keeps_metadata_and_payload_within_three_uniforms(self):
        config = atlas2d_config(257, screen_size=PHONE)
        columns = config["atlas_layout"]["columns"]
        rows = config["atlas_layout"]["rows"]
        names = [process["name"] for process in config["processes"]]
        self.assertEqual(len(names), 258)
        self.assertEqual(len(set(names)), len(names))
        self.assertEqual(config["producer_names"], names[:-1])
        self.assertEqual(config["display_name"], names[-1])
        self.assertEqual(config["connections"], [
            [names[index], 0, names[index + 1], 0, 3] for index in range(257)])
        self.assertEqual(config["parameter_names"], ["page", "packet0", "packet1"])
        for page, process in enumerate(config["processes"][:-1]):
            parameters = process["paras"]
            expected = [float(page), 257.0, float(columns), float(rows)]
            self.assertEqual(parameters[0]["value"], expected)
            self.assertEqual(config["page_uniforms"][page], expected)
            self.assertEqual([parameter["name"] for parameter in parameters],
                             ["page", "packet0", "packet1"])
            self.assertEqual([int(value * 16777216) for parameter in parameters[1:]
                              for value in parameter["value"]], config["words"][page])
            target = process["pass_array"][0]["render_target"]
            self.assertEqual([round(target[key] * PHONE[index])
                              for index, key in enumerate(("width", "height"))],
                             config["target_pixels"])
        self.assertEqual([item["name"] for item in config["processes"][-1]["paras"]],
                         ["query", "display_rect", "atlas_layout"])
        for filename in ("atlas2d.fragment", "atlas2d_display.fragment"):
            self.assertNotIn("EXTRA_VECTOR4", (PROBE / filename).read_text(encoding="utf-8"))

    def test_default_namespaces_are_unique_and_legacy_namespace_cannot_collide(self):
        first = atlas2d_config(4)
        second = atlas2d_config(4)
        self.assertTrue(set(first["producer_names"]).isdisjoint(second["producer_names"]))
        self.assertNotIn("pmanim_packet_aggregate_4_page_00", first["producer_names"])

    def test_invalid_counts_sizes_density_and_unreadable_windows_fail_explicitly(self):
        for pages in (0, -1, 16385, True, 1.0):
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                atlas2d_config(pages)
        for screen in ((0, 1080), (720, -1), (float("nan"), 1080),
                       (720, float("inf")), (8, 8)):
            with self.subTest(screen=screen), self.assertRaises(ValueError):
                atlas2d_config(8192, screen_size=screen)
        for density in (0, 3, 8, True, 1.0):
            with self.subTest(density=density), self.assertRaises(ValueError):
                atlas2d_config(4, texels_per_word=density)
        for count in (0, -1, 16385, True):
            with self.subTest(count=count), self.assertRaises(ValueError):
                atlas2d_config(4, display_count=count)
        with self.assertRaises(ValueError):
            atlas2d_config(1024, screen_size=PHONE, display_rect=(0, 0, 0.01, 1))
        with self.assertRaises(ValueError):
            atlas2d_config(1024, screen_size=PHONE, display_rect=(0, 0, 1, 0.01))

    def test_asset_builder_preserves_existing_materials_and_requires_owned_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            resource = parent / "resource_pack"
            resource.mkdir()
            sentinel = resource / "keep.txt"
            sentinel.write_bytes(b"untouched")
            with self.assertRaises(ValueError):
                build_atlas2d_assets(resource)
            self.assertEqual(sentinel.read_bytes(), b"untouched")
            (parent / ".pmanim_packet_probe.json").write_text(json.dumps({
                "kind": "pmanim_runtime_packet_probe"}), encoding="utf-8")
            materials = resource / "materials/postprocess.material"
            materials.parent.mkdir()
            materials.write_text(json.dumps({"existing": {"kept": True}}), encoding="utf-8")
            config = build_atlas2d_assets(resource, page_count=4, screen_size=PHONE)
            result = json.loads(materials.read_text(encoding="utf-8"))
            self.assertEqual(result["existing"], {"kept": True})
            for process in (config["processes"][0], config["processes"][-1]):
                material = result[process["pass_array"][0]["material"]]
                self.assertEqual([entry["samplerIndex"] for entry in material["samplerStates"]],
                                 [0, 1, 3])
                self.assertTrue(all(entry["textureFilter"] == "Point"
                                    for entry in material["samplerStates"]))
            for filename in ("atlas2d.fragment", "atlas2d_display.fragment"):
                self.assertEqual((resource / "shaders/glsl" / filename).read_bytes(),
                                 (PROBE / filename).read_bytes())
            self.assertFalse((resource / "graphics_settings/post_process.json").exists())


@unittest.skipUnless(importlib.util.find_spec("moderngl"), "optional desktop OpenGL diagnostic")
class Atlas2dGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import moderngl
        from pyreact_manim.compiler.desktop import desktop_fragment

        cls.gl = moderngl
        cls.context = moderngl.create_standalone_context(require=330)
        vertex = """#version 330
in vec2 position;
out vec2 uv;
void main() { uv = position * 0.5 + 0.5; gl_Position = vec4(position, 0.0, 1.0); }
"""
        cls.programs = [cls.context.program(vertex_shader=vertex, fragment_shader=desktop_fragment(
            (PROBE / filename).read_text(encoding="utf-8")))
            for filename in ("atlas2d.fragment", "atlas2d_display.fragment")]
        cls.vertices = cls.context.buffer(struct.pack("8f", -1, -1, 1, -1, -1, 1, 1, 1))
        cls.arrays = [cls.context.simple_vertex_array(program, cls.vertices, "position")
                      for program in cls.programs]

    @classmethod
    def tearDownClass(cls):
        for array in cls.arrays:
            array.release()
        cls.vertices.release()
        for program in cls.programs:
            program.release()
        cls.context.release()

    @contextmanager
    def accumulated(self, config, wrong_link=None, limit_pages=None, prefill=False):
        """Use two targets to model the sequential pass graph with bounded memory."""
        context = self.context
        targets, framebuffers = [], []
        blank = context.texture((1, 1), 4, bytes([0, 0, 0, 255]))
        try:
            target = config["processes"][0]["pass_array"][0]["render_target"]
            actual = tuple(max(1, math.floor(struct.unpack("f", struct.pack(
                "f", target[key]))[0] * config["screen_size"][index]))
                           for index, key in enumerate(("width", "height")))
            self.assertEqual(list(actual), config["target_pixels"])
            for _ in range(2):
                texture = context.texture(actual, 4)
                texture.filter = (self.gl.NEAREST, self.gl.NEAREST)
                texture.repeat_x = texture.repeat_y = False
                targets.append(texture)
                framebuffer = context.framebuffer(color_attachments=[texture])
                framebuffers.append(framebuffer)
                if prefill:
                    framebuffer.clear(1.0, 0.25, 0.5, 1.0)
            context.disable(self.gl.BLEND)
            previous = targets[1] if prefill else blank
            program = self.programs[0]
            program["TEXTURE_3"].value = 3
            limit = config["pages"] if limit_pages is None else limit_pages
            for page, process in enumerate(config["processes"][:limit]):
                framebuffers[page % 2].use()
                (blank if wrong_link == page - 1 else previous).use(3)
                for index, parameter in enumerate(process["paras"], 1):
                    program["EXTRA_VECTOR%d" % index].value = parameter["value"]
                self.arrays[0].render(self.gl.TRIANGLE_STRIP)
                previous = targets[page % 2]
            yield previous, framebuffers[(limit - 1) % 2], blank
        finally:
            for framebuffer in reversed(framebuffers):
                framebuffer.release()
            for texture in reversed(targets):
                texture.release()
            blank.release()

    def display(self, config, atlas, blank, query=None, physical_size=None):
        query = config["query"] if query is None else [config["pages"], *query]
        size = (24, int(query[2])) if physical_size is None else physical_size
        final = self.context.simple_framebuffer(size, components=4)
        try:
            final.use()
            atlas.use(3)
            blank.use(1)
            program = self.programs[1]
            program["TEXTURE_1"].value = 1
            program["TEXTURE_3"].value = 3
            for index, parameter in enumerate(config["processes"][-1]["paras"], 1):
                value = query if parameter["name"] == "query" else parameter["value"]
                program["EXTRA_VECTOR%d" % index].value = value
            self.arrays[1].render(self.gl.TRIANGLE_STRIP)
            rgba = final.read(components=4, alignment=1)
            if physical_size is not None:
                return rgba
            rows = []
            for row in reversed(range(size[1])):
                output = []
                for column in range(24):
                    offset = (row * 24 + column) * 4
                    pixel = rgba[offset:offset + 4]
                    self.assertEqual(pixel, pixel[:1] * 3 + b"\xff")
                    output.append(pixel[0])
                rows.append(output)
            return rows
        finally:
            final.release()

    def assert_every_byte_in_windows(self, config, atlas, blank):
        count = int(config["query"][2])
        seen = []
        for start in range(0, config["pages"], count):
            output = self.display(config, atlas, blank, query=(start, count, 0))
            length = min(count, config["pages"] - start)
            self.assertEqual(output[:length], config["expected_bytes"][start:start + length])
            self.assertEqual(output[length:], [[0] * 24] * (count - length))
            seen.extend(range(start, start + length))
        self.assertEqual(seen, list(range(config["pages"])))

    def test_all_bytes_of_1024_2048_4096_8192_pages_at_720_by_1080(self):
        for pages in (1024, 2048, 4096, 8192):
            with self.subTest(pages=pages):
                config = atlas2d_config(pages, screen_size=PHONE, display_rect=(0, 0, 1, 1))
                with self.accumulated(config) as (atlas, _, blank):
                    self.assert_every_byte_in_windows(config, atlas, blank)

    def test_dense_one_texel_words_retrieve_every_byte_at_8192_pages(self):
        config = atlas2d_config(8192, screen_size=PHONE, texels_per_word=1,
                                display_rect=(0, 0, 1, 1))
        self.assertEqual(config["atlas_layout"]["texels_per_word"], 1)
        with self.accumulated(config) as (atlas, _, blank):
            self.assert_every_byte_in_windows(config, atlas, blank)

    def test_incomplete_final_window_preserves_last_page_and_clears_padding(self):
        config = atlas2d_config(257, screen_size=PHONE, texels_per_word=2,
                                display_rect=(0, 0, 1, 1))
        with self.accumulated(config) as (atlas, _, blank):
            self.assert_every_byte_in_windows(config, atlas, blank)
            last = self.display(config, atlas, blank, query=(256, 128, 0))
            self.assertEqual(last[0], config["expected_bytes"][-1])
            self.assertEqual(last[1:], [[0] * 24] * 127)

    def test_uint24_boundaries_and_nonwrapping_queries_include_last_page(self):
        words = [[0, 1, 255, 256, 65535, 65536, 8388607, 8388608],
                 [8388609, 16777213, 16777214, 16777215, 254, 257, 65534, 65537]]
        config = atlas2d_config(2, screen_size=PHONE, words=words, display_rect=(0, 0, 1, 1))
        with self.accumulated(config) as (atlas, _, blank):
            for start, count, shift in ((0, 2, 0), (1, 3, 7), (-1, 4, -1), (2, 2, 9)):
                with self.subTest(start=start, count=count, shift=shift):
                    expected = []
                    for page in range(start, start + count):
                        if not 0 <= page < 2:
                            expected.append([0] * 24)
                            continue
                        row = config["expected_bytes"][page]
                        expected.append([row[((cell // 3 + shift) % 8) * 3 + cell % 3]
                                         for cell in range(24)])
                    self.assertEqual(self.display(config, atlas, blank, query=(start, count, shift)),
                                     expected)

    def test_page_zero_clears_previous_generation_and_unused_page_cells(self):
        config = atlas2d_config(31, screen_size=PHONE, display_rect=(0, 0, 1, 1))
        with self.accumulated(config, limit_pages=1, prefill=True) as (_, framebuffer, __):
            rgba = framebuffer.read(components=4, alignment=1)
            layout = config["atlas_layout"]
            width, height = config["target_pixels"]
            for page in range(layout["capacity_pages"]):
                for word in range(8):
                    x = int(((page % layout["columns"]) * 8 + word + 0.5) /
                            layout["logical_width"] * width)
                    y = int((page // layout["columns"] + 0.5) /
                            layout["logical_height"] * height)
                    offset = (y * width + x) * 4
                    expected = bytes(config["expected_bytes"][0][word * 3:word * 3 + 3]
                                     if page == 0 else [0, 0, 0]) + b"\xff"
                    self.assertEqual(rgba[offset:offset + 4], expected)
        # Empty cells also remain clear after every producer has run.
        self.assertGreater(config["atlas_layout"]["empty_pages"], 0)
        with self.accumulated(config) as (_, framebuffer, __):
            rgba = framebuffer.read(components=4, alignment=1)
            page = config["pages"]
            x = int(((page % layout["columns"]) * 8 + 0.5) / layout["logical_width"] * width)
            y = int((page // layout["columns"] + 0.5) / layout["logical_height"] * height)
            self.assertEqual(rgba[(y * width + x) * 4:(y * width + x) * 4 + 4], b"\0\0\0\xff")

    def test_wrong_internal_and_final_texture_sources_are_detected(self):
        config = atlas2d_config(257, screen_size=PHONE, display_rect=(0, 0, 1, 1), display_count=257)
        first_surviving = 129
        with self.accumulated(config, wrong_link=first_surviving - 1) as (atlas, _, blank):
            output = self.display(config, atlas, blank)
            self.assertEqual(output[:first_surviving], [[0] * 24] * first_surviving)
            self.assertEqual(output[first_surviving:], config["expected_bytes"][first_surviving:])
            self.assertNotEqual(output, config["expected_bytes"])
            final_wrong = self.display(config, blank, blank)
            self.assertEqual(final_wrong, [[0] * 24] * config["pages"])
            self.assertNotEqual(final_wrong, config["expected_bytes"])

    def test_actual_720_by_1080_display_centers_return_all_window_bytes(self):
        config = atlas2d_config(257, screen_size=PHONE)
        start, count, shift = 129, 128, 3
        with self.accumulated(config) as (atlas, _, blank):
            rgba = self.display(config, atlas, blank, query=(start, count, shift), physical_size=PHONE)
        left, top, rect_width, rect_height = config["display_rect_norm"]
        width, height = PHONE
        self.assertEqual(rgba[:4], b"\0\0\0\xff")
        self.assertEqual(rgba[-4:], b"\0\0\0\xff")
        for row in range(count):
            for cell in range(24):
                x = int((left + (cell + 0.5) * rect_width / 24) * width)
                y = height - 1 - int((top + (row + 0.5) * rect_height / count) * height)
                offset = (y * width + x) * 4
                value = config["expected_bytes"][start + row][((cell // 3 + shift) % 8) * 3 + cell % 3]
                self.assertEqual(rgba[offset:offset + 4], bytes([value]) * 3 + b"\xff")


if __name__ == "__main__":
    unittest.main()
