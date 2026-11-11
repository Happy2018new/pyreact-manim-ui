"""PNG atlas fidelity, slot wiring, reproducibility and image-only ownership."""

import ast
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_shader_images_for_tests", ROOT / "tools/build_shader_images.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def metadata(output):
    source = (output / "behavior_pack/manim_ui/images/generated.py").read_text(encoding="utf-8")
    return {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(source).body if isinstance(node, ast.Assign)}


class ShaderImageBuildTests(unittest.TestCase):
    def test_defaults_rebuild_byte_for_byte_and_match_shipped_owned_assets(self):
        with tempfile.TemporaryDirectory(prefix="shader-image-") as directory:
            output = Path(directory)
            report = builder.build(output=output)
            self.assertEqual(report["images"], ["aurora", "prism", "sunrise"])
            self.assertEqual(report["atlas_size"], (1024, 512))
            self.assertEqual(report["entities"], 4)
            first = snapshot(output)
            builder.build(output=output)
            self.assertEqual(first, snapshot(output))
            for relative in builder.OWNED_FILES:
                with self.subTest(resource=relative):
                    self.assertEqual((ROOT / relative).read_bytes(), (output / relative).read_bytes())

    def test_atlas_pixels_and_chinese_metadata_preserve_each_original_image(self):
        with tempfile.TemporaryDirectory(prefix="shader-image-") as directory:
            output = Path(directory)
            builder.build(output=output)
            config = metadata(output)
            self.assertEqual(config["SLOT_COUNT"], 4)
            with Image.open(output / "resource_pack/textures/manim/images_atlas.png") as atlas:
                self.assertEqual(atlas.mode, "RGBA")
                self.assertEqual(atlas.size, config["ATLAS_SIZE"])
                for key, (image, title) in builder.default_images().items():
                    entry = config["IMAGES"][key]
                    self.assertEqual(entry["title"], title)
                    self.assertTrue(any(ord(character) > 127 for character in title))
                    self.assertEqual(entry["size"], image.size)
                    u, v, width, height = entry["uv"]
                    x, y = round(u * atlas.width), round(v * atlas.height)
                    self.assertEqual((round(width * atlas.width), round(height * atlas.height)), image.size)
                    self.assertEqual(atlas.crop((x, y, x + image.width, y + image.height)).tobytes(), image.tobytes())
                    self.assertEqual(atlas.getpixel((x - 1, y))[3], 0)
                    self.assertEqual(atlas.getpixel((x, y - 1))[3], 0)
                    alpha = image.getchannel("A")
                    self.assertEqual(alpha.getpixel((0, 0)), 0)
                    self.assertTrue(any(0 < value < 255 for value in alpha.getdata()))

    def test_four_independent_entities_share_image_material_atlas_and_canvas_geometry(self):
        with tempfile.TemporaryDirectory(prefix="shader-image-") as directory:
            output = Path(directory)
            builder.build(output=output)
            seen = set()
            for slot in range(4):
                client = json.loads((output / ("resource_pack/entity/pmanim_image_%d.entity.json" % slot)).read_text())
                server = json.loads((output / ("behavior_pack/entities/pmanim_image_%d.json" % slot)).read_text())
                description = client["minecraft:client_entity"]["description"]
                identifier = "pmanim:image_%d" % slot
                self.assertEqual(description["identifier"], identifier)
                self.assertEqual(server["minecraft:entity"]["description"]["identifier"], identifier)
                self.assertFalse(server["minecraft:entity"]["description"]["is_spawnable"])
                self.assertEqual(description["materials"], {"default": "pmanim_image"})
                self.assertEqual(description["geometry"], {"default": "geometry.pmanim_canvas"})
                self.assertEqual(description["textures"], {"default": "textures/manim/images_atlas"})
                self.assertEqual(description["render_controllers"], ["controller.render.pmanim_image"])
                seen.add(identifier)
            self.assertEqual(len(seen), 4)
            self.assertEqual((output / "resource_pack/shaders/glsl/pmanim_image.vertex").read_bytes(),
                             (ROOT / "tools/canvas/pmanim_canvas.vertex").read_bytes())
            controller = json.loads((output / "resource_pack/render_controllers/pmanim_image.render_controllers.json").read_text())
            self.assertEqual(controller["render_controllers"]["controller.render.pmanim_image"]["textures"], ["Texture.default"])
            material = json.loads((output / "resource_pack/materials/entity.material").read_text())["materials"][builder.MATERIAL_KEY]
            self.assertEqual((material["blendSrc"], material["blendDst"]), ("One", "OneMinusSrcAlpha"))
            self.assertEqual((material["alphaSrc"], material["alphaDst"]), ("One", "OneMinusSrcAlpha"))
            self.assertEqual(material["samplerStates"][0]["textureFilter"], "Point")

    def test_custom_manifest_resolves_relative_png_and_preserves_partial_alpha_and_hidden_rgb(self):
        with tempfile.TemporaryDirectory(prefix="shader-image-") as directory:
            root = Path(directory)
            source = Image.new("RGBA", (3, 1))
            source.putdata(((255, 30, 40, 0), (15, 240, 60, 127), (10, 20, 230, 255)))
            source.save(root / "input.png")
            manifest = root / "images.json"
            manifest.write_text(json.dumps({"sample": {"file": "input.png", "title": "透明样本"}}, ensure_ascii=False), encoding="utf-8")
            output = root / "output"
            builder.build(output=output, manifest=manifest)
            config = metadata(output)
            self.assertEqual(set(config["IMAGES"]), {"sample"})
            self.assertEqual(config["IMAGES"]["sample"]["size"], (3, 1))
            with Image.open(output / "resource_pack/textures/manim/images_atlas.png") as atlas:
                u, v, _, _ = config["IMAGES"]["sample"]["uv"]
                x, y = round(u * atlas.width), round(v * atlas.height)
                self.assertEqual(atlas.crop((x, y, x + 3, y + 1)).tobytes(), source.tobytes())
            report = json.loads((output / "tools/shader_image/generated/manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(report["inputs"]["entries"]["sample"]["file"], "input.png")
            self.assertEqual(report["images"]["sample"]["rgba_sha256"], builder.digest(source.tobytes()))

    def test_replacing_manifest_drops_old_metadata_without_touching_other_resources_or_materials(self):
        with tempfile.TemporaryDirectory(prefix="shader-image-") as directory:
            root = Path(directory)
            output = root / "output"
            material_path = output / "resource_pack/materials/entity.material"
            material_path.parent.mkdir(parents=True)
            existing = {"version": "1.0.0", "pmanim_canvas:entity_static": {"sentinel": 41},
                        "pmanim_image_external:entity_static": {"sentinel": 71}}
            material_path.write_text(json.dumps({"materials": existing, "extra_document_key": 91}))
            unrelated = output / "resource_pack/textures/manim/images_external.png"
            unrelated.parent.mkdir(parents=True)
            unrelated.write_bytes(b"another tool owns this resource")
            builder.build(output=output)
            Image.new("RGB", (1, 2), (255, 0, 0)).save(root / "custom.png")
            manifest = root / "images.json"
            manifest.write_text(json.dumps({"custom": {"file": "custom.png", "title": "Custom"}}))
            builder.build(output=output, manifest=manifest)
            self.assertEqual(set(metadata(output)["IMAGES"]), {"custom"})
            self.assertEqual(unrelated.read_bytes(), b"another tool owns this resource")
            actual = json.loads(material_path.read_text())
            self.assertEqual(actual["extra_document_key"], 91)
            self.assertEqual({key: actual["materials"][key] for key in existing}, existing)

    def test_canvas_and_image_builders_can_rebuild_in_either_order(self):
        spec = importlib.util.spec_from_file_location("canvas_builder_image_integration", ROOT / "tools/build_canvas.py")
        canvas = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(canvas)
        with tempfile.TemporaryDirectory(prefix="shader-image-") as directory:
            output = Path(directory)
            canvas.build(output=output)
            builder.build(output=output)
            # Canvas hashes materials without sorting. Reformatting unrelated
            # material fields would look like user edits and fail this rebuild.
            canvas.build(output=output)
            builder.build(output=output)
            self.assertIn(builder.MATERIAL_KEY, json.loads((output / "resource_pack/materials/entity.material").read_text())["materials"])

    def test_modified_owned_resource_or_material_is_rejected_before_any_write(self):
        for target in ("resource_pack/shaders/glsl/pmanim_image.fragment", "resource_pack/materials/entity.material"):
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="shader-image-") as directory:
                output = Path(directory)
                builder.build(output=output)
                path = output / target
                if target.endswith("entity.material"):
                    contents = json.loads(path.read_text())
                    contents["materials"][builder.MATERIAL_KEY]["blendSrc"] = "SourceAlpha"
                    path.write_text(json.dumps(contents))
                else:
                    path.write_text("user modified shader")
                before = snapshot(output)
                with self.assertRaisesRegex(ValueError, "modified"):
                    builder.build(output=output)
                self.assertEqual(before, snapshot(output))

    def test_unowned_collision_is_rejected_before_material_or_atlas_write(self):
        for target in ("resource_pack/shaders/glsl/pmanim_image.fragment", "resource_pack/materials/entity.material"):
            with self.subTest(target=target), tempfile.TemporaryDirectory(prefix="shader-image-") as directory:
                output = Path(directory)
                path = output / target
                path.parent.mkdir(parents=True)
                content = (json.dumps({"materials": {builder.MATERIAL_KEY: {"sentinel": 42}}})
                           if target.endswith("entity.material") else "another tool owns this")
                path.write_text(content)
                before = snapshot(output)
                with self.assertRaisesRegex(ValueError, "unowned"):
                    builder.build(output=output)
                self.assertEqual(before, snapshot(output))

    def test_traversing_or_foreign_ownership_record_is_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory(prefix="shader-image-") as directory:
            output = Path(directory)
            builder.build(output=output)
            path = output / builder.OWNERSHIP_FILE
            original = json.loads(path.read_text())
            for relative in ("../outside.txt", "resource_pack/materials/entity.material", "resource_pack/shaders/glsl/pmanim_canvas.vertex"):
                malicious = dict(original, files={relative: "0" * 64})
                path.write_text(json.dumps(malicious))
                before = snapshot(output)
                with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "unowned"):
                    builder.build(output=output)
                self.assertEqual(before, snapshot(output))

    def test_invalid_manifest_or_non_png_fails_before_writing_outputs(self):
        with tempfile.TemporaryDirectory(prefix="shader-image-") as directory:
            root = Path(directory)
            Image.new("RGB", (2, 2)).save(root / "input.jpg")
            path = root / "manifest.json"
            cases = ([], {}, {"../escape": {"file": "input.jpg", "title": "Bad"}},
                     {"valid": {"file": "input.jpg", "title": "JPEG"}},
                     {"valid": {"file": "input.jpg", "title": ""}},
                     {"valid": {"file": "input.jpg", "title": "Extra", "resize": 1}})
            for entry in cases:
                path.write_text(json.dumps(entry))
                with self.subTest(entry=entry), self.assertRaises(ValueError):
                    builder.build(output=root / "output", manifest=path)
                self.assertFalse((root / "output").exists())

    def test_atlas_budget_rejects_oversized_source_before_writing_outputs(self):
        with tempfile.TemporaryDirectory(prefix="shader-image-") as directory:
            root = Path(directory)
            Image.new("RGBA", (2045, 1)).save(root / "wide.png")
            path = root / "manifest.json"
            path.write_text(json.dumps({"wide": {"file": "wide.png", "title": "Too wide"}}))
            with self.assertRaisesRegex(ValueError, "budget"):
                builder.build(output=root / "output", manifest=path)
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()
