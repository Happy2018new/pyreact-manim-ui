"""Independent small-uniform draws, byte accuracy and host resource ownership.

Desktop GL explicitly models sequential TEXTURE_0 composition; it does not
assert that a particular Minecraft version binds that texture identically.
"""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools/runtime_packet_probe"
sys.path.insert(0, str(PROBE))
sys.path.insert(0, str(ROOT / "src"))
from uniform_split_assets import (MAX_PAGES, build_uniform_split_assets,
                                  packet_parameters, uniform_split_config)
from aggregate_assets import aggregate_config


class UniformSplitConfigTests(unittest.TestCase):
    def test_requested_scales_have_separate_process_state_and_equal_payload(self):
        for pages in (1, 128, 512, 1024, 2048):
            with self.subTest(pages=pages):
                config = uniform_split_config(pages)
                self.assertEqual(config["screen_size"], [720, 1080])
                self.assertEqual(config["transport"], "uniform_split")
                self.assertEqual(config["parameter_names"], ["tile", "packet0", "packet1"])
                self.assertEqual(config["payload_scalar_slots"], pages * 8)
                self.assertEqual(config["payload_bytes"], pages * 24)
                self.assertEqual(config["parameter_calls_per_update"], pages * 2)
                self.assertEqual(config["fullscreen_passes"], pages)
                self.assertEqual(config["nominal_fragments_per_frame"], pages * 720 * 1080)
                self.assertEqual(config["connections"], [])
                self.assertIsNone(config["display_name"])
                self.assertFalse(config["requires_explicit_connections"])
                self.assertEqual(len(set(config["producer_names"])), pages)
                self.assertEqual(config["expected_bytes"], [
                    list(b"".join(word.to_bytes(3, "big") for word in row))
                    for row in config["words"]])
                for index, process in enumerate(config["processes"]):
                    self.assertEqual(process["name"], config["producer_names"][index])
                    self.assertEqual([p["name"] for p in process["paras"]],
                                     config["parameter_names"])
                    self.assertEqual(process["paras"][0]["value"],
                                     config["rectangles_norm"][index])
                    self.assertEqual([p["value"] for p in process["paras"]][1:],
                                     packet_parameters(config["words"][index]))
                    self.assertEqual(process["pass_array"][0]["render_target"],
                                     {"width": 1.0, "height": 1.0})
                    self.assertNotIn("bindTexture", process["pass_array"][0])
                if pages <= 1024:
                    atlas = aggregate_config(pages, screen_size=(720, 1080))
                    self.assertEqual(config["words"], atlas["words"])
                    self.assertEqual(config["expected_bytes"], atlas["expected_bytes"])

    def test_720_by_1080_tiles_fit_and_support_three_pixel_cell_samples(self):
        for pages in (128, 512, 1024, 2048):
            config = uniform_split_config(pages)
            self.assertGreaterEqual(min(config["cell_pixels"]), 3)
            columns, rows = config["grid_columns"], config["grid_rows"]
            self.assertGreaterEqual(columns * rows, pages)
            previous_right = {}
            for index, (left, top, width, height) in enumerate(config["rectangles_norm"]):
                self.assertGreaterEqual(left, 0)
                self.assertGreaterEqual(top, 0)
                self.assertLessEqual(left + width, 1 + 1e-12)
                self.assertLessEqual(top + height, 1 + 1e-12)
                row = index // columns
                self.assertGreaterEqual(left + 1e-12, previous_right.get(row, 0))
                previous_right[row] = left + width
                self.assertAlmostEqual(width * 720 / 24, config["cell_pixels"][0])
                self.assertAlmostEqual(height * 1080, config["cell_pixels"][1])

    def test_dyadic_payload_and_words_are_copied_from_caller(self):
        words = [[0, 1, 255, 256, 65535, 65536, 8388609, 16777215]]
        config = uniform_split_config(1, words=words)
        words[0][0] = 12345
        self.assertEqual(config["words"][0][0], 0)
        scalars = [value for vector in config["processes"][0]["paras"][1:]
                   for value in vector["value"]]
        restored = [int(struct.unpack("f", struct.pack("f", value))[0] * 16777216)
                    for value in scalars]
        self.assertEqual(restored, config["words"][0])
        for bad in ([0] * 7, [0] * 9, [True] * 8, [1.0] * 8,
                    [-1] * 8, [16777216] * 8):
            with self.subTest(words=bad), self.assertRaises(ValueError):
                packet_parameters(bad)

    def test_bad_config_fails_before_assets_are_written(self):
        for pages in (0, -1, MAX_PAGES + 1, True, 1.0):
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                uniform_split_config(pages)
        for size in ((0, 1080), (720, -1), (float("nan"), 1080),
                     (720, float("inf")), (True, 1080), (720,)):
            with self.subTest(size=size), self.assertRaises(ValueError):
                uniform_split_config(screen_size=size)
        for rect in ((0, 0, 0, 1), (-0.1, 0, 1, 1), (0.2, 0, 0.9, 1),
                     (0, 0, float("nan"), 1), (0, 0, 1)):
            with self.subTest(rect=rect), self.assertRaises(ValueError):
                uniform_split_config(display_rect=rect)
        for values in ({"shader_mode": "invalid"}, {"namespace": "not/a/shader"},
                       {"words": [[0] * 8]}, {"words": [[0] * 7] * 4}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                uniform_split_config(**values)

    def test_shared_and_distinct_builds_preserve_foreign_materials_and_global_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            marker = output / ".pmanim_packet_probe.json"
            marker.write_text(json.dumps({"kind": "pmanim_runtime_packet_probe"}), encoding="utf-8")
            resource = output / "resource_pack"
            material_path = resource / "materials/postprocess.material"
            material_path.parent.mkdir(parents=True)
            material_path.write_text('{"foreign_material": {"preserve": true}}', encoding="utf-8")
            global_path = resource / "graphics_settings/post_process.json"
            global_path.parent.mkdir(parents=True)
            global_path.write_bytes(b"preserve preexisting engine configuration")
            for mode in ("shared", "distinct"):
                config = build_uniform_split_assets(resource, 4, shader_mode=mode)
                materials = json.loads(material_path.read_text(encoding="utf-8"))
                self.assertEqual(materials["foreign_material"], {"preserve": True})
                names = {process["pass_array"][0]["material"] for process in config["processes"]}
                self.assertEqual(len(names), 1 if mode == "shared" else 4)
                fragments, vertices = [], []
                for name in names:
                    material = materials[name]
                    for key, sources in (("fragmentShader", fragments), ("vertexShader", vertices)):
                        shader = resource / material[key].replace("shaders/", "shaders/glsl/", 1)
                        self.assertTrue(shader.is_file())
                        source = shader.read_text(encoding="utf-8")
                        self.assertTrue(source.startswith("// __multiversion__\n"))
                        sources.append(source)
                    self.assertEqual(fragments[-1].count("uniform vec4 EXTRA_VECTOR"), 3)
                    self.assertNotIn("EXTRA_VECTOR4", fragments[-1])
                    self.assertNotIn("TEXTURE_3", fragments[-1])
                self.assertEqual(len(set(fragments)), len(names))
                self.assertEqual(len(set(vertices)), len(names))
            self.assertEqual(global_path.read_bytes(), b"preserve preexisting engine configuration")

    def test_ownership_rejection_and_invalid_payload_do_not_mutate_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            resource = output / "resource_pack"
            with self.assertRaisesRegex(ValueError, "isolated marked"):
                build_uniform_split_assets(resource)
            self.assertFalse(resource.exists())
            marker = output / ".pmanim_packet_probe.json"
            marker.write_text('{"kind": "foreign"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not owned"):
                build_uniform_split_assets(resource)
            marker.write_text('{"kind": "pmanim_runtime_packet_probe"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                build_uniform_split_assets(resource, words=[[0] * 7] * 4)
            self.assertFalse(resource.exists())


@unittest.skipUnless(importlib.util.find_spec("moderngl"), "optional desktop OpenGL diagnostic")
class UniformSplitGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import moderngl
        from pyreact_manim.compiler.desktop import desktop_fragment
        cls.gl = moderngl
        cls.context = moderngl.create_standalone_context(require=330)
        vertex = (PROBE / "uniform_split.vertex").read_text(encoding="utf-8")
        vertex = (vertex.replace("// __multiversion__", "#version 330", 1)
                  .replace('#include "vertexVersionCentroidUV.h"', "out vec2 uv;")
                  .replace("attribute highp", "in"))
        fragment = desktop_fragment((PROBE / "uniform_split.fragment").read_text(encoding="utf-8"))
        cls.programs = [cls.context.program(
            vertex_shader=vertex.replace("#version 330\n", "#version 330\n"
                                         "#define PMANIM_UNIFORM_SPLIT_VARIANT %d\n" % variant, 1),
            fragment_shader=fragment.replace("#version 330\n", "#version 330\n"
                                             "#define PMANIM_UNIFORM_SPLIT_VARIANT %d\n" % variant, 1))
                        for variant in range(4)]
        cls.vertices = cls.context.buffer(struct.pack("20f",
            -1, -1, 0, 0, 0, 1, -1, 0, 1, 0,
            -1, 1, 0, 0, 1, 1, 1, 0, 1, 1))
        cls.arrays = [cls.context.vertex_array(program, [(cls.vertices, "3f 2f", "POSITION", "TEXCOORD_0")])
                      for program in cls.programs]

    @classmethod
    def tearDownClass(cls):
        for array in cls.arrays:
            array.release()
        cls.vertices.release()
        for program in cls.programs:
            program.release()
        cls.context.release()

    def render(self, config, distinct=False, omitted_page=None, blank_before_page=None):
        context, size = self.context, tuple(config["screen_size"])
        background = bytes([19, 53, 117, 211])
        textures = [context.texture(size, 4, background * (size[0] * size[1]))
                    for _ in range(2)]
        frames = [context.framebuffer(color_attachments=[texture]) for texture in textures]
        blank = context.texture((1, 1), 4, bytes([0, 0, 0, 0]))
        try:
            for texture in textures + [blank]:
                texture.filter = (self.gl.NEAREST, self.gl.NEAREST)
                texture.repeat_x = texture.repeat_y = False
            context.disable(self.gl.BLEND)
            current = 0
            for page, process in enumerate(config["processes"]):
                if page == omitted_page:
                    continue
                destination = 1 - current
                frames[destination].use()
                (blank if page == blank_before_page else textures[current]).use(0)
                index = page % len(self.programs) if distinct else 0
                program = self.programs[index]
                program["TEXTURE_0"].value = 0
                for index, parameter in enumerate(process["paras"], 1):
                    program["EXTRA_VECTOR%d" % index].value = parameter["value"]
                self.arrays[page % len(self.programs) if distinct else 0].render(self.gl.TRIANGLE_STRIP)
                current = destination
            rgba = frames[current].read(components=4, alignment=1)
            # Each configured byte is read at its own physical cell center.
            actual = []
            for left, top, width, height in config["rectangles_norm"]:
                y = min(size[1] - 1, int((1 - top - height / 2) * size[1]))
                row = []
                for byte in range(24):
                    x = min(size[0] - 1, int((left + width * (byte + 0.5) / 24) * size[0]))
                    pixel = rgba[(y * size[0] + x) * 4: (y * size[0] + x) * 4 + 4]
                    if pixel not in (background, b"\x00\x00\x00\x00"):
                        self.assertEqual(pixel, bytes([pixel[0]]) * 3 + b"\xff")
                    row.append(pixel[0])
                actual.append(row)
            return actual, rgba[:4], background
        finally:
            blank.release()
            for frame in frames:
                frame.release()
            for texture in textures:
                texture.release()

    def test_every_byte_survives_1_4_16_128_512_1024_2048_independent_draws(self):
        for pages in (1, 4, 16, 128, 512, 1024, 2048):
            with self.subTest(pages=pages):
                config = uniform_split_config(pages)
                actual, outside, background = self.render(config)
                self.assertEqual(actual, config["expected_bytes"])
                self.assertEqual(outside, background)

    def test_four_gpu_programs_retain_independent_uniform_values(self):
        config = uniform_split_config(16, shader_mode="distinct")
        self.assertEqual(self.render(config, distinct=True)[0], config["expected_bytes"])

    def test_omitted_draw_changes_only_its_own_tile(self):
        config = uniform_split_config(16)
        actual, _, background = self.render(config, omitted_page=7)
        expected = list(config["expected_bytes"])
        expected[7] = [background[0]] * 24
        self.assertEqual(actual, expected)

    def test_lost_previous_texture_loses_earlier_tiles(self):
        config = uniform_split_config(16)
        actual, _, _ = self.render(config, blank_before_page=7)
        self.assertEqual(actual[:7], [[0] * 24] * 7)
        self.assertEqual(actual[7:], config["expected_bytes"][7:])

    def test_uint24_boundaries_decode_exactly(self):
        config = uniform_split_config(2, words=[
            [0, 1, 255, 256, 65535, 65536, 8388607, 8388608],
            [8388609, 16777213, 16777214, 16777215, 254, 257, 65534, 65537]])
        self.assertEqual(self.render(config)[0], config["expected_bytes"])


if __name__ == "__main__":
    unittest.main()
