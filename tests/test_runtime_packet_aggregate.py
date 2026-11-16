"""Check uint24 transport and explicit atlas accumulation on desktop OpenGL."""
import importlib.util
from pathlib import Path
import struct
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/runtime_packet_probe"))
sys.path.insert(0, str(ROOT / "src"))
from aggregate_assets import aggregate_config, packet_parameters


class AggregateConfigTests(unittest.TestCase):
    def test_all_scales_connect_each_producer_before_consumer(self):
        for pages in (1, 4, 16, 64, 256, 1024):
            config = aggregate_config(pages)
            names = [item["name"] for item in config["processes"]]
            self.assertEqual(len(names), pages + 1)
            self.assertEqual(len(config["connections"]), pages)
            self.assertEqual(config["connections"],
                             [[names[page], 0, names[page + 1], 0, 3] for page in range(pages)])
            for source, source_pass, destination, destination_pass, slot in config["connections"]:
                self.assertLess(names.index(source), names.index(destination))
                self.assertEqual((source_pass, destination_pass, slot), (0, 0, 3))

    def test_parameter_layout_avoids_engine_screen_info_uniform(self):
        for pages in (1, 4, 16, 64, 256, 1024):
            with self.subTest(pages=pages):
                config = aggregate_config(pages)
                self.assertEqual(config["words_per_page"], 8)
                self.assertEqual(config["target_pixels"], [32, pages * 4])
                self.assertEqual(config["parameter_names"], ["page", "packet0", "packet1"])
                self.assertTrue(all(len(row) == 24 for row in config["expected_bytes"]))
                for page, process in enumerate(config["processes"][:-1]):
                    parameters = process["paras"]
                    self.assertEqual([item["name"] for item in parameters],
                                     ["page", "packet0", "packet1"])
                    self.assertEqual(parameters[0]["value"], [float(page), float(pages), 8.0, 0.0])
                    self.assertEqual(parameters[0]["range"], [0.0, 1024.0])
                    self.assertEqual([item["value"] for item in parameters[1:]],
                                     packet_parameters(config["words"][page]))
                self.assertEqual([item["name"] for item in config["processes"][-1]["paras"]],
                                 ["query", "display_rect"])
                query = config["processes"][-1]["paras"][0]
                self.assertEqual(query["value"], config["query"])
                self.assertEqual(query["value"], [float(pages), 0.0, 0.0, 0.0])
                self.assertEqual(query["range"], [0.0, 1024.0])
        for filename in ("aggregate.fragment", "aggregate_display.fragment"):
            source = (ROOT / "tools/runtime_packet_probe" / filename).read_text(encoding="utf-8")
            self.assertNotIn("EXTRA_VECTOR4", source)

    def test_page_count_rejects_values_outside_host_limit(self):
        for pages in (0, -1, 1025, 4096, True, 1.0):
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                aggregate_config(pages)

    def test_dyadic_uint24_survives_float32_at_boundaries(self):
        boundaries = [0, 1, 255, 256, 65535, 65536, 8388607, 8388608,
                      8388609, 16777213, 16777214, 16777215, 254, 257, 65534, 65537]
        for offset in (0, 8):
            words = boundaries[offset:offset + 8]
            normalized = [value for vector in packet_parameters(words) for value in vector]
            restored = [int(struct.unpack("f", struct.pack("f", value))[0] * 16777216)
                        for value in normalized]
            self.assertEqual(restored, words)
        for words in ([16777216] * 8, [-1] * 8, [1.0] * 8, [True] * 8,
                      [0] * 7, [0] * 12):
            with self.subTest(words=words), self.assertRaises(ValueError):
                packet_parameters(words)


@unittest.skipUnless(importlib.util.find_spec("moderngl"), "optional desktop OpenGL diagnostic")
class AggregateGpuTests(unittest.TestCase):
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
        cls.programs = []
        for filename in ("aggregate.fragment", "aggregate_display.fragment"):
            source = (ROOT / "tools/runtime_packet_probe" / filename).read_text(encoding="utf-8")
            cls.programs.append(cls.context.program(vertex_shader=vertex,
                                                    fragment_shader=desktop_fragment(source)))
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

    def render(self, config, query=None, missing_connection=None, display_height=None):
        context = self.context
        textures, framebuffers = [], []
        blank = context.texture((1, 1), 4, bytes([0, 0, 0, 255]))
        textures.append(blank)
        previous = blank
        columns = config["words_per_page"] * 3
        display_height = config["pages"] if display_height is None else display_height
        try:
            context.disable(self.gl.BLEND)
            for page, process in enumerate(config["processes"][:-1]):
                # Match the clamped screen-relative render_target, rather than
                # assuming target_pixels fits in the physical screen.
                ratios = process["pass_array"][0]["render_target"]
                actual_size = tuple(max(1, round(ratios[key] * config["screen_size"][index]))
                                    for index, key in enumerate(("width", "height")))
                texture = context.texture(actual_size, 4)
                texture.filter = (self.gl.NEAREST, self.gl.NEAREST)
                texture.repeat_x = texture.repeat_y = False
                textures.append(texture)
                framebuffer = context.framebuffer(color_attachments=[texture])
                framebuffers.append(framebuffer)
                framebuffer.use()
                (blank if missing_connection == page - 1 else previous).use(3)
                program = self.programs[0]
                program["TEXTURE_3"].value = 3
                # Upload exactly the generated paras, in documented packed order.
                for index, parameter in enumerate(process["paras"], 1):
                    program["EXTRA_VECTOR%d" % index].value = parameter["value"]
                self.arrays[0].render(self.gl.TRIANGLE_STRIP)
                previous = texture
            final = context.simple_framebuffer((columns, display_height), components=4)
            framebuffers.append(final)
            final.use()
            (blank if missing_connection == config["pages"] - 1 else previous).use(3)
            blank.use(1)
            program = self.programs[1]
            program["TEXTURE_1"].value = 1
            program["TEXTURE_3"].value = 3
            for index, parameter in enumerate(config["processes"][-1]["paras"], 1):
                value = parameter["value"]
                if parameter["name"] == "query" and query is not None:
                    value = (config["pages"],) + query
                program["EXTRA_VECTOR%d" % index].value = value
            self.arrays[1].render(self.gl.TRIANGLE_STRIP)
            rgba = final.read(components=4, alignment=1)
            for offset in range(0, len(rgba), 4):
                self.assertEqual(rgba[offset:offset + 4], bytes([rgba[offset]]) * 3 + b"\xff")
            # Framebuffer readback starts at the bottom; display pages start at top.
            return [[rgba[(row * columns + column) * 4] for column in range(columns)]
                    for row in reversed(range(display_height))]
        finally:
            for framebuffer in reversed(framebuffers):
                framebuffer.release()
            for texture in reversed(textures):
                texture.release()

    def test_every_byte_of_1_4_16_64_256_pages_is_retrieved(self):
        for pages in (1, 4, 16, 64, 256):
            with self.subTest(pages=pages):
                config = aggregate_config(pages, display_rect=(0, 0, 1, 1))
                self.assertEqual(self.render(config), config["expected_bytes"])

    def test_queries_retrieve_other_rows_words_and_channels(self):
        for pages in (1, 4, 16, 64, 256):
            config = aggregate_config(pages, display_rect=(0, 0, 1, 1))
            for query in ((pages - 1, 7, 2), (-1, -1, -1), (pages + 1, 9, 4)):
                with self.subTest(pages=pages, query=query):
                    row_shift, word_shift, byte_shift = query
                    expected = []
                    for page in range(pages):
                        row = config["expected_bytes"][(page + row_shift) % pages]
                        expected.append([row[((cell // 3 + word_shift) % 8) * 3 +
                                             (cell + byte_shift) % 3] for cell in range(24)])
                    self.assertEqual(self.render(config, query), expected)

    def test_missing_connections_lose_previous_pages(self):
        for pages in (4, 16, 64, 256):
            with self.subTest(pages=pages):
                config = aggregate_config(pages, display_rect=(0, 0, 1, 1))
                surviving_page = pages // 2
                output = self.render(config, missing_connection=surviving_page - 1)
                self.assertEqual(output[:surviving_page], [[0] * 24] * surviving_page)
                self.assertEqual(output[surviving_page:], config["expected_bytes"][surviving_page:])

    def test_missing_final_connection_loses_all_pages(self):
        for pages in (1, 4, 16, 64, 256):
            with self.subTest(pages=pages):
                config = aggregate_config(pages, display_rect=(0, 0, 1, 1))
                output = self.render(config, missing_connection=pages - 1)
                self.assertEqual(output, [[0] * 24] * pages)
                self.assertNotEqual(output, config["expected_bytes"])

    def test_every_byte_of_1024_pages_at_actual_1305_pixel_height(self):
        config = aggregate_config(1024, screen_size=(2400, 1305), display_rect=(0, 0, 1, 1))
        self.assertEqual(config["target_pixels"], [32, 4096])
        self.assertEqual(config["processes"][0]["pass_array"][0]["render_target"]["height"], 1.0)
        # Physical display rows can repeat a page. Integer center arithmetic also
        # fixes the exact center row (652) to page 512 without float rounding.
        pages_at_pixel_centers = [(2 * row + 1) * 1024 // (2 * 1305) for row in range(1305)]
        self.assertEqual(set(pages_at_pixel_centers), set(range(1024)))
        self.assertEqual(pages_at_pixel_centers[652], 512)
        expected = [config["expected_bytes"][page] for page in pages_at_pixel_centers]
        self.assertEqual(self.render(config, display_height=1305), expected)

    def test_1024_pages_missing_final_connection_at_actual_1305_pixel_height(self):
        config = aggregate_config(1024, screen_size=(2400, 1305), display_rect=(0, 0, 1, 1))
        output = self.render(config, missing_connection=1023, display_height=1305)
        self.assertEqual(output, [[0] * 24] * 1305)

    def test_gpu_uint24_boundaries(self):
        words = [[0, 1, 255, 256, 65535, 65536, 8388607, 8388608],
                 [8388609, 16777213, 16777214, 16777215, 254, 257, 65534, 65537]]
        config = aggregate_config(2, words=words, display_rect=(0, 0, 1, 1))
        self.assertEqual(self.render(config), config["expected_bytes"])


if __name__ == "__main__":
    unittest.main()
