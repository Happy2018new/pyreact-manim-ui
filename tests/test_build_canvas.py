"""Canvas generation contracts and optional real desktop-GL alpha checks."""

import ast
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pyreact_manim.compiler.desktop import VERTEX, desktop_fragment

SPEC = importlib.util.spec_from_file_location("build_canvas_for_tests", ROOT / "tools/build_canvas.py")
canvas = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canvas)
HAS_GL = importlib.util.find_spec("moderngl") is not None


def fixture(schema):
    fill = ("color = mix(color, fill.rgb, fill.a * fillCoverage);" if schema == 1
            else "color = mix(color, fill.rgb, coverage * 1.06);")
    return """// __multiversion__
precision highp float;
#include "fragmentVersionCentroidUV.h"
uniform sampler2D TEXTURE_0;
uniform sampler2D TEXTURE_2;
uniform vec4 EXTRA_VECTOR1;
uniform vec4 EXTRA_VECTOR2;
void main() {
    vec3 color = vec3(0.1, 0.2, 0.3);
    {
        float fillCoverage = uv.x < 0.75 && uv.y > 0.1 ? 1.0 : 0.0;
        float coverage = fillCoverage * 0.5 / 1.06;
        vec4 fill = vec4(1.0, 0.0, 0.0, 0.5);
        %s
    }
    {
        float fillCoverage = uv.x > 0.25 && uv.y > 0.1 ? 1.0 : 0.0;
        float coverage = fillCoverage * 0.5 / 1.06;
        vec4 fill = vec4(0.0, 0.0, 1.0, 0.5);
        %s
    }
    vec4 original = texture2D(TEXTURE_0, uv);
    gl_FragColor = mix(original, vec4(color, 1.0), clamp(EXTRA_VECTOR1.w, 0.0, 1.0));
}
""" % (fill, fill)


class CanvasBuildTests(unittest.TestCase):
    def make_source(self, root, names):
        scenes = [{"name": name, "title": name, "duration": 2.0, "texture": "textures/manim/" + name}
                  for name in names]
        config = root / "behavior_pack/manim_ui/generated_scenes.py"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("SCENES = " + repr(scenes), encoding="utf-8")
        vertex = root / "tools/canvas/pmanim_canvas.vertex"
        vertex.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "tools/canvas/pmanim_canvas.vertex", vertex)
        for name in names:
            shader = root / "resource_pack/shaders/glsl" / (name + ".fragment")
            shader.parent.mkdir(parents=True, exist_ok=True)
            shader.write_text(fixture(1), encoding="utf-8")
            texture = root / "resource_pack/textures/manim" / (name + ".png")
            texture.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (1, 1)).save(texture)

    def test_all_deployed_scenes_and_slots_have_resolvable_resources(self):
        with tempfile.TemporaryDirectory(prefix="canvas-build-") as temporary:
            output = Path(temporary)
            result = canvas.build(output=output)
            self.assertEqual(result["entities"], 22)
            self.assertEqual(len(result["scenes"]), 11)
            configuration = ast.parse((output / "behavior_pack/manim_ui/generated_canvas.py").read_text(encoding="utf-8"))
            scenes = ast.literal_eval(configuration.body[0].value)
            materials = json.loads((output / "resource_pack/materials/entity.material").read_text())["materials"]
            self.assertEqual(materials["pmanim_canvas:entity_static"]["blendSrc"], "SourceAlpha")
            identifiers = []
            for scene in scenes:
                name = scene["name"]
                shader = output / "resource_pack/shaders/glsl" / ("pmanim_canvas_" + name + ".fragment")
                source = shader.read_text()
                self.assertNotIn("EXTRA_VECTOR", source)
                self.assertNotIn("TEXTURE_2", source)
                if name != "runtime_shapes":
                    self.assertIn("canvasOver(", source)
                    self.assertIn("canvasPremultiplied / canvasAlpha", source)
                    self.assertTrue((output / "resource_pack/textures/manim" / (name + ".png")).is_file())
                for slot, identifier in enumerate(scene["identifiers"]):
                    stem = "pmanim_canvas_" + str(slot) + "_" + name
                    client = json.loads((output / "resource_pack/entity" / (stem + ".entity.json")).read_text())
                    server = json.loads((output / "behavior_pack/entities" / (stem + ".json")).read_text())
                    self.assertEqual(client["minecraft:client_entity"]["description"]["identifier"], identifier)
                    self.assertEqual(server["minecraft:entity"]["description"]["identifier"], identifier)
                    identifiers.append(identifier)
            self.assertEqual(len(set(identifiers)), 22)

    def test_rebuild_preserves_other_entity_materials(self):
        with tempfile.TemporaryDirectory(prefix="canvas-build-") as temporary:
            output = Path(temporary)
            materials = output / "resource_pack/materials/entity.material"
            materials.parent.mkdir(parents=True)
            materials.write_text(json.dumps({"materials": {"other:entity_static": {"sentinel": 42},
                                                            "pmanim_canvas_external:entity_static": {"sentinel": 17}}}))
            canvas.build(output=output)
            self.assertEqual(json.loads(materials.read_text())["materials"]["other:entity_static"], {"sentinel": 42})
            self.assertEqual(json.loads(materials.read_text())["materials"]["pmanim_canvas_external:entity_static"], {"sentinel": 17})

    def test_removed_scene_prunes_only_owned_outputs_and_keeps_shared_atlas(self):
        with tempfile.TemporaryDirectory(prefix="canvas-clean-") as temporary:
            root = Path(temporary) / "source"
            output = Path(temporary) / "output"
            self.make_source(root, ["first", "second"])
            canvas.build(root, output)
            sentinel = output / "resource_pack/shaders/glsl/pmanim_canvas_external.fragment"
            sentinel.write_text("not generated by this tool")
            self.make_source(root, ["first"])
            result = canvas.build(root, output)
            self.assertEqual(result["stale_files_removed"], 5)
            self.assertFalse((output / "resource_pack/shaders/glsl/pmanim_canvas_second.fragment").exists())
            self.assertFalse((output / "resource_pack/entity/pmanim_canvas_0_second.entity.json").exists())
            self.assertFalse((output / "behavior_pack/entities/pmanim_canvas_1_second.json").exists())
            self.assertTrue((output / "resource_pack/textures/manim/second.png").exists())
            self.assertEqual(sentinel.read_text(), "not generated by this tool")
            materials = json.loads((output / "resource_pack/materials/entity.material").read_text())["materials"]
            self.assertNotIn("pmanim_canvas_second:pmanim_canvas", materials)
            self.assertIn("pmanim_canvas_first:pmanim_canvas", materials)
            # No tools/ui_canvas_probe source exists in this synthetic repo.
            self.assertFalse((root / "tools/ui_canvas_probe").exists())

    def test_modified_stale_resource_fails_without_any_write_or_delete(self):
        with tempfile.TemporaryDirectory(prefix="canvas-clean-") as temporary:
            root = Path(temporary) / "source"
            output = Path(temporary) / "output"
            self.make_source(root, ["first", "second"])
            canvas.build(root, output)
            stale = output / "resource_pack/shaders/glsl/pmanim_canvas_second.fragment"
            stale.write_text("user edited shader")
            before = {str(path.relative_to(output)): path.read_bytes() for path in output.rglob("*") if path.is_file()}
            self.make_source(root, ["first"])
            with self.assertRaisesRegex(ValueError, "modified"):
                canvas.build(root, output)
            self.assertEqual(before, {str(path.relative_to(output)): path.read_bytes() for path in output.rglob("*") if path.is_file()})

    def test_unowned_or_traversing_cleanup_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="canvas-clean-") as temporary:
            root = Path(temporary) / "source"
            output = Path(temporary) / "output"
            self.make_source(root, ["first"])
            canvas.build(root, output)
            manifest_path = output / canvas.OWNERSHIP_FILE
            original = json.loads(manifest_path.read_text())
            for relative in ("../outside.txt", "resource_pack/textures/manim/first.png"):
                manifest = dict(original)
                manifest["files"] = {relative: "0" * 64}
                manifest_path.write_text(json.dumps(manifest))
                with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "unowned"):
                    canvas.build(root, output)

    def test_existing_unowned_shader_collision_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix="canvas-clean-") as temporary:
            root = Path(temporary) / "source"
            output = Path(temporary) / "output"
            self.make_source(root, ["first"])
            target = output / "resource_pack/shaders/glsl/pmanim_canvas_first.fragment"
            target.parent.mkdir(parents=True)
            target.write_text("another tool owns this")
            with self.assertRaisesRegex(ValueError, "unowned resource"):
                canvas.build(root, output)
            self.assertEqual(target.read_text(), "another tool owns this")

    def test_unknown_composition_is_rejected_before_deployment(self):
        source = fixture(1).replace("fill.a * fillCoverage", "new_blending_rule")
        with self.assertRaisesRegex(ValueError, "composition"):
            canvas.transparent_fragment(source)
        with self.assertRaisesRegex(ValueError, "background"):
            canvas.transparent_fragment(fixture(1).replace("vec3 color = vec3(0.1, 0.2, 0.3);", ""))

    def test_multiple_layers_and_strokes_use_one_final_alpha_conversion(self):
        for schema in (1, 2):
            source = canvas.transparent_fragment(fixture(schema))
            self.assertEqual(source.count("canvasOver(canvasPremultiplied, canvasAlpha,"), 2)
            self.assertEqual(source.count("canvasPremultiplied / canvasAlpha"), 1)
        source = fixture(1).replace("color = mix(color, fill.rgb, fill.a * fillCoverage);",
                                    "color = mix(color, stroke.rgb, stroke.a * strokeCoverage);")
        converted = canvas.transparent_fragment(source)
        self.assertEqual(converted.count("canvasOver(canvasPremultiplied, canvasAlpha, stroke.rgb, stroke.a * strokeCoverage);"), 2)


@unittest.skipUnless(HAS_GL, "Optional desktop GL checks run with .venv-reference Python")
class CanvasGPUChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import moderngl
        cls.gl = moderngl
        cls.context = moderngl.create_standalone_context(require=330)

    @classmethod
    def tearDownClass(cls):
        cls.context.release()

    def render(self, source, uniform1=(0.0, 1.0, 64.0, 1.0), uniform2=None, uniform4=None):
        resources = []
        try:
            program = self.context.program(vertex_shader=VERTEX, fragment_shader=desktop_fragment(source))
            resources.append(program)
            vertices = self.context.buffer(struct.pack("8f", -1, -1, 1, -1, -1, 1, 1, 1))
            resources.append(vertices)
            vao = self.context.simple_vertex_array(program, vertices, "position")
            resources.append(vao)
            for name, value in (("EXTRA_ACTOR_UNIFORM1", uniform1), ("EXTRA_ACTOR_UNIFORM2", uniform2),
                                ("EXTRA_ACTOR_UNIFORM4", uniform4)):
                if value is not None and name in program:
                    program[name].value = value
            framebuffer = self.context.simple_framebuffer((64, 64), components=4)
            resources.append(framebuffer)
            framebuffer.use()
            self.context.disable(self.gl.BLEND)
            vao.render(self.gl.TRIANGLE_STRIP)
            return Image.frombytes("RGBA", (64, 64), framebuffer.read(components=4)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        finally:
            for resource in reversed(resources):
                resource.release()

    def test_source_over_accumulates_paths_and_applies_group_opacity_once(self):
        for schema in (1, 2):
            with self.subTest(schema=schema):
                image = self.render(canvas.transparent_fragment(fixture(schema)), uniform1=(0, 1, 64, 0.5))
                expected = {(32, 32): (85, 0, 170, 96), (8, 32): (255, 0, 0, 64),
                            (56, 32): (0, 0, 255, 64), (32, 2): (0, 0, 0, 0)}
                for point, color in expected.items():
                    self.assertLessEqual(max(abs(a - b) for a, b in zip(image.getpixel(point), color)), 1)

    @unittest.skipUnless(os.environ.get("PMANIM_FULL_CANVAS_GL") == "1",
                         "Set PMANIM_FULL_CANVAS_GL=1 for expensive all-scene shader compilation")
    def test_every_current_scene_canvas_compiles_in_desktop_gl(self):
        for scene in canvas.read_scenes(ROOT / "behavior_pack/manim_ui/generated_scenes.py"):
            with self.subTest(scene=scene["name"]):
                source = (ROOT / "resource_pack/shaders/glsl" / (scene["name"] + ".fragment")).read_text()
                program = self.context.program(vertex_shader=VERTEX,
                                               fragment_shader=desktop_fragment(canvas.transparent_fragment(source)))
                try:
                    self.assertIn("TEXTURE_0", program)
                    self.assertIn("EXTRA_ACTOR_UNIFORM1", program)
                    self.assertIn("EXTRA_ACTOR_UNIFORM2", program)
                finally:
                    program.release()

    def test_unbaked_shape_parameters_change_rendered_geometry_and_color(self):
        common = {"uniform2": (0.371, 1.0, 0.0, 0.837), "uniform4": (0.173, 0.627, 0.913, 0.419)}
        first = self.render(canvas.RUNTIME_FRAGMENT, **common)
        self.assertEqual(first.getpixel((0, 0))[3], 0)
        self.assertEqual(first.getpixel((32, 32)), (44, 160, 233, 255))
        moved = self.render(canvas.RUNTIME_FRAGMENT, uniform1=(1.0, 1.0, 64.0, 1.0), **common)
        self.assertNotEqual(first.tobytes(), moved.tobytes())
        outlined = self.render(canvas.RUNTIME_FRAGMENT, uniform2=(0.371, 1.0, 0.04, 0.837),
                               uniform4=common["uniform4"])
        self.assertEqual(outlined.getpixel((32, 32))[3], 0)
        hidden = self.render(canvas.RUNTIME_FRAGMENT, uniform2=(0.371, 0.0, 0.0, 0.837),
                             uniform4=common["uniform4"])
        self.assertIsNone(hidden.getchannel("A").getbbox())


if __name__ == "__main__":
    unittest.main()
