"""Offline pixel checks for the deployed ShaderImage fragment.

These checks use isolated desktop OpenGL and analytic color landmarks. They
verify fragment math and blending, not Minecraft texture import or paperdolls.
"""

import importlib.util
import math
from pathlib import Path
import re
import struct
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pyreact_manim.compiler.desktop import VERTEX, desktop_fragment


HAS_GL = importlib.util.find_spec("moderngl") is not None
SHADER = ROOT / "resource_pack/shaders/glsl/pmanim_image.fragment"


@unittest.skipUnless(HAS_GL, "Requires optional moderngl and desktop OpenGL 4.5")
class ShaderImageGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import moderngl

        cls.gl = moderngl
        cls.context = moderngl.create_standalone_context(require=450)
        cls.source = SHADER.read_text(encoding="utf-8")
        size = re.search(r"const\s+vec2\s+IMAGE_ATLAS_SIZE\s*=\s*vec2\(\s*"
                         r"([\d.]+)\s*,\s*([\d.]+)\s*\)", cls.source)
        if size is None:
            raise AssertionError("Generated image shader must declare atlas dimensions")
        cls.atlas_size = tuple(int(float(value)) for value in size.groups())
        cls.program = cls.context.program(vertex_shader=VERTEX,
                                          fragment_shader=desktop_fragment(cls.source))
        cls.vertices = cls.context.buffer(struct.pack("8f", -1, -1, 1, -1, -1, 1, 1, 1))
        cls.vertex_array = cls.context.simple_vertex_array(cls.program, cls.vertices, "position")

    @classmethod
    def tearDownClass(cls):
        cls.vertex_array.release()
        cls.vertices.release()
        cls.program.release()
        cls.context.release()

    def atlas(self, pixels, surrounding=(255, 0, 255, 255)):
        """Place a small image amid hostile neighbors, avoiding real art inputs."""
        width, height = self.atlas_size
        texture = np.empty((height, width, 4), dtype=np.uint8)
        texture[:] = surrounding
        pixels = np.asarray(pixels, dtype=np.uint8)
        h, w = pixels.shape[:2]
        texture[2:2 + h, 2:2 + w] = pixels
        return texture, (2.0 / width, 2.0 / height, float(w) / width, float(h) / height)

    def render(self, texture, crop, *, size=(64, 64), aspect=1.0,
               display=(1.0, 1.0), rotation=0.0, opacity=1.0,
               effect=0, strength=0.0, timestamp=0.0, background=None):
        context = self.context
        atlas = context.texture(self.atlas_size, 4, texture.tobytes())
        framebuffer = context.simple_framebuffer(size, components=4)
        try:
            atlas.filter = (self.gl.NEAREST, self.gl.NEAREST)
            atlas.repeat_x = atlas.repeat_y = False
            atlas.use(0)
            self.program["TEXTURE_0"].value = 0
            self.program["EXTRA_ACTOR_UNIFORM1"].value = (timestamp, aspect, opacity, float(effect))
            self.program["EXTRA_ACTOR_UNIFORM2"].value = (*display, rotation, strength)
            self.program["EXTRA_ACTOR_UNIFORM4"].value = crop
            framebuffer.use()
            context.disable(self.gl.BLEND)
            framebuffer.clear(*(background or (0.0, 0.0, 0.0, 0.0)))
            if background is not None:
                context.enable(self.gl.BLEND)
                context.blend_func = (self.gl.ONE, self.gl.ONE_MINUS_SRC_ALPHA)
            self.vertex_array.render(self.gl.TRIANGLE_STRIP)
            pixels = framebuffer.read(components=4, alignment=1)
            return np.frombuffer(pixels, dtype=np.uint8).reshape(size[1], size[0], 4)[::-1].copy()
        finally:
            context.disable(self.gl.BLEND)
            framebuffer.release()
            atlas.release()

    def quadrants(self):
        pixels = np.empty((16, 16, 4), dtype=np.uint8)
        pixels[:8, :8] = (255, 0, 0, 255)
        pixels[:8, 8:] = (0, 255, 0, 255)
        pixels[8:, :8] = (0, 0, 255, 255)
        pixels[8:, 8:] = (255, 255, 0, 255)
        return self.atlas(pixels)

    def assertPixel(self, frame, x, y, expected, tolerance=1):
        actual = frame[y, x].astype(int)
        self.assertTrue(np.all(np.abs(actual - expected) <= tolerance),
                        "pixel (%d, %d): %s != %s" % (x, y, actual.tolist(), expected))

    def test_fragment_compiles_under_glsl_330_400_and_450(self):
        for version in (330, 400, 450):
            with self.subTest(version=version):
                directive = "#version %d" % version
                program = self.context.program(
                    vertex_shader=VERTEX.replace("#version 330", directive, 1),
                    fragment_shader=desktop_fragment(self.source).replace("#version 330", directive, 1))
                program.release()

    def test_identity_preserves_orientation_and_color(self):
        frame = self.render(*self.quadrants())
        for x, y, expected in ((16, 16, (255, 0, 0, 255)), (48, 16, (0, 255, 0, 255)),
                               (16, 48, (0, 0, 255, 255)), (48, 48, (255, 255, 0, 255))):
            self.assertPixel(frame, x, y, expected)

    def test_contain_extents_letterbox_square_in_wide_canvas(self):
        # A square image fits a 2:1 canvas at width=height=1 canvas-height unit.
        frame = self.render(*self.quadrants(), size=(128, 64), aspect=2.0)
        self.assertTrue(np.all(frame[:, :32] == 0))
        self.assertTrue(np.all(frame[:, 96:] == 0))
        self.assertPixel(frame, 48, 16, (255, 0, 0, 255))
        self.assertPixel(frame, 80, 48, (255, 255, 0, 255))

    def test_cover_extents_crop_vertical_edges_of_square(self):
        # Covering the same canvas needs 2x2 units, so only image y=.25..75 is visible.
        pixels = np.empty((16, 16, 4), dtype=np.uint8)
        pixels[:] = (255, 0, 0, 255)
        pixels[4:12] = (0, 255, 0, 255)
        frame = self.render(*self.atlas(pixels), size=(128, 64), aspect=2.0, display=(2.0, 2.0))
        self.assertPixel(frame, 8, 8, (0, 255, 0, 255))
        self.assertPixel(frame, 120, 56, (0, 255, 0, 255))
        self.assertTrue(np.all(frame[:, :, 3] == 255))

    def test_rotation_uses_inverse_mapping_and_rotates_nonsquare_bounds(self):
        frame = self.render(*self.quadrants(), display=(0.5, 1.0), rotation=math.pi / 2)
        self.assertTrue(np.all(frame[:16] == 0))
        self.assertTrue(np.all(frame[48:] == 0))
        self.assertPixel(frame, 16, 24, (0, 0, 255, 255))
        self.assertPixel(frame, 48, 24, (255, 0, 0, 255))
        self.assertPixel(frame, 16, 40, (255, 255, 0, 255))
        self.assertPixel(frame, 48, 40, (0, 255, 0, 255))

    def test_negative_display_extents_mirror_each_axis(self):
        atlas, crop = self.quadrants()
        ordinary = self.render(atlas, crop)
        horizontal = self.render(atlas, crop, display=(-1.0, 1.0))
        vertical = self.render(atlas, crop, display=(1.0, -1.0))
        np.testing.assert_array_equal(horizontal, ordinary[:, ::-1])
        np.testing.assert_array_equal(vertical, ordinary[::-1])

    def test_final_crop_never_reads_neighboring_atlas_cells(self):
        pixels = np.empty((4, 4, 4), dtype=np.uint8)
        pixels[:] = (0, 255, 0, 255)
        frame = self.render(*self.atlas(pixels), size=(97, 97))
        np.testing.assert_array_equal(frame, np.broadcast_to((0, 255, 0, 255), frame.shape))

    def test_crop_smaller_than_one_texel_samples_its_midpoint(self):
        atlas, _ = self.atlas(np.full((1, 1, 4), (0, 255, 0, 255), dtype=np.uint8))
        width, height = self.atlas_size
        crop = (2.4 / width, 2.4 / height, 0.2 / width, 0.2 / height)
        frame = self.render(atlas, crop)
        np.testing.assert_array_equal(frame, np.broadcast_to((0, 255, 0, 255), frame.shape))

    def test_bilinear_interpolation_premultiplies_before_filtering(self):
        # Fully transparent blue must not leak into the 50% red edge.
        pixels = np.array([[(255, 0, 0, 255), (0, 0, 255, 0)]] * 2, dtype=np.uint8)
        atlas, crop = self.atlas(pixels)
        frame = self.render(atlas, crop, size=(1, 1))
        self.assertPixel(frame, 0, 0, (128, 0, 0, 128))
        faded = self.render(atlas, crop, size=(1, 1), opacity=0.4)
        self.assertPixel(faded, 0, 0, (51, 0, 0, 51))
        white = self.render(atlas, crop, size=(1, 1), background=(1.0, 1.0, 1.0, 1.0))
        self.assertPixel(white, 0, 0, (255, 127, 127, 255))

    def test_semitransparency_and_zero_opacity_preserve_premultiplied_contract(self):
        atlas, crop = self.atlas(np.full((2, 2, 4), (80, 160, 240, 128), dtype=np.uint8))
        frame = self.render(atlas, crop, size=(1, 1))
        self.assertPixel(frame, 0, 0, (40, 80, 120, 128))
        invisible = self.render(atlas, crop, opacity=0.0)
        self.assertTrue(np.all(invisible == 0))

    def test_wave_zero_strength_is_identity_and_displacement_is_bounded(self):
        pixels = np.empty((64, 64, 4), dtype=np.uint8)
        pixels[:, :, 0] = np.arange(64, dtype=np.uint8)[None, :] * 4
        pixels[:, :, 1:] = (64, 128, 255)
        atlas, crop = self.atlas(pixels)
        ordinary = self.render(atlas, crop)
        identity = self.render(atlas, crop, effect=1, timestamp=0.17)
        np.testing.assert_array_equal(identity, ordinary)
        wave = self.render(atlas, crop, effect=1, strength=1.0)
        later = self.render(atlas, crop, effect=1, strength=1.0, timestamp=0.25)
        delta = np.abs(wave[:, 8:-8, 0].astype(int) - ordinary[:, 8:-8, 0].astype(int))
        self.assertGreater(delta.max(), 5)
        self.assertLessEqual(delta.max(), 11)  # 0.04 local UV * 64 texels * 4 red levels.
        self.assertGreater(np.abs(later[:, 8:-8, 0].astype(int) - wave[:, 8:-8, 0].astype(int)).max(), 5)
        np.testing.assert_array_equal(wave[:, 8:-8, 1:], ordinary[:, 8:-8, 1:])
        capped = self.render(atlas, crop, effect=1, strength=3.0)
        np.testing.assert_array_equal(capped, wave)

    def test_wave_outside_local_image_is_transparent(self):
        atlas, crop = self.atlas(np.full((16, 16, 4), (0, 255, 0, 255), dtype=np.uint8))
        wave = self.render(atlas, crop, effect=1, strength=1.0)
        # Three full waves across y: near y=1/12 shift right, near y=1/4 shift left.
        self.assertPixel(wave, 63, 5, (0, 0, 0, 0))
        self.assertPixel(wave, 0, 5, (0, 255, 0, 255))
        self.assertPixel(wave, 0, 15, (0, 0, 0, 0))
        self.assertPixel(wave, 63, 15, (0, 255, 0, 255))

    def test_swirl_is_identity_at_zero_strength_and_outside_center_radius(self):
        atlas, crop = self.quadrants()
        ordinary = self.render(atlas, crop, size=(100, 100))
        identity = self.render(atlas, crop, size=(100, 100), effect=2)
        np.testing.assert_array_equal(identity, ordinary)
        swirl = self.render(atlas, crop, size=(100, 100), effect=2, strength=1.0)
        coordinates = (np.arange(100) + 0.5) / 100.0 - 0.5
        radius = np.hypot(coordinates[:, None], coordinates[None, :])
        np.testing.assert_array_equal(swirl[radius >= 0.5], ordinary[radius >= 0.5])
        # Near (u=.665,v=.545), inverse swirl maps the yellow quadrant into red.
        self.assertPixel(ordinary, 66, 54, (255, 255, 0, 255))
        self.assertPixel(swirl, 66, 54, (255, 0, 0, 255))
        self.assertGreater(np.count_nonzero(swirl != ordinary), 100)


if __name__ == "__main__":
    unittest.main()
