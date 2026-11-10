"""Transport-format and pixel-evidence guards for the isolated runtime probe."""

import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock
import zlib

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools/runtime_probe"
sys.path.insert(0, str(PROBE))
import runtime_data as rd
import prepare as probe_prepare
import verify_capture as verify


class RuntimeProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="manim-runtime-probe-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "resource_pack"
        probe_prepare.prepare(self.root)

    def test_png_roundtrip_and_crc_preserve_all_256_values(self):
        values = rd.generate_values(12345)
        rgba = rd.rgba_for_values(values)
        png = rd.encode_png(rgba)
        with Image.open(io.BytesIO(png)) as image:
            self.assertEqual(image.size, (16, 16))
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.tobytes(), rgba)
        offset = 8
        while offset < len(png):
            length = struct.unpack(">I", png[offset:offset + 4])[0]
            data = png[offset + 4:offset + 8 + length]
            crc = struct.unpack(">I", png[offset + 8 + length:offset + 12 + length])[0]
            self.assertEqual(zlib.crc32(data) & 0xffffffff, crc)
            offset += length + 12
        self.assertEqual(len(values), 256)
        self.assertEqual(values, rd.generate_values(12345))
        self.assertNotEqual(values, rd.generate_values(54321))

    def test_write_is_owned_and_never_marks_gpu_success(self):
        with self.assertRaises(ValueError):
            rd.write_dataset(self.root.parent, "fresh", 1)
        for slot in ("../escape", "valid\n", "../resource_pack/fresh", "C:\\escape"):
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                rd.write_dataset(self.root, slot, 1)
        result = rd.write_dataset(self.root, "fresh", 1)
        self.assertFalse(result["gpu_verified"])
        self.assertEqual(result["point_count"], 128)
        with Image.open(result["absolute_png"]) as image:
            self.assertEqual(image.tobytes(), rd.rgba_for_values(result["values"]))

    def test_changed_seed_replaces_owned_path_with_different_content(self):
        first = rd.write_dataset(self.root, "fresh", 12345)
        second = rd.write_dataset(self.root, "fresh", 54321)
        self.assertEqual(first["texture"], second["texture"])
        self.assertNotEqual(first["png_crc32"], second["png_crc32"])
        saved = json.loads(Path(second["absolute_png"]).with_suffix(".receipt.json").read_text())
        self.assertEqual(saved, second)

    def test_hashes_are_host_only_and_reject_overwritten_runtime_bytes(self):
        first = rd.write_dataset(self.root, "fresh", 12345)
        self.assertNotIn("png_sha256", first)
        self.assertEqual(len(first["png_crc32"]), 8)
        fingerprints = verify.host_fingerprints(first, first["absolute_png"])
        self.assertEqual(fingerprints["host_png_sha256"],
                         "4d94704055c36a461251059b6ea57fd279a441984480aeb32ffbdfb886b4c845")
        rd.write_dataset(self.root, "fresh", 54321)
        with self.assertRaises(ValueError):
            verify.host_fingerprints(first, first["absolute_png"])

    def test_api_success_is_not_pixel_success_and_failed_add_is_not_enabled(self):
        post = Mock()
        post.AddPostProcess.return_value = True
        post.SetEnableByName.return_value = True
        result = rd.install_effect(post, "test", rd.TEXTURE_DIRECTORY + "/fresh")
        self.assertTrue(result["enabled"])
        self.assertFalse(result["gpu_verified"])
        post.reset_mock()
        post.AddPostProcess.return_value = False
        result = rd.install_effect(post, "failed", rd.TEXTURE_DIRECTORY + "/fresh")
        self.assertFalse(result["enabled"])
        post.SetEnableByName.assert_not_called()

    def test_material_and_effect_bind_matching_shader_and_texture_slot(self):
        material = json.loads((self.root / "materials/postprocess.material").read_text())[rd.MATERIAL]
        fragment = self.root / (material["fragmentShader"].replace("shaders/", "shaders/glsl/"))
        self.assertTrue(fragment.is_file())
        self.assertIn("uniform sampler2D TEXTURE_2", fragment.read_text())
        self.assertEqual(material["samplerStates"][2]["textureFilter"], "Point")
        effect = rd.effect_definition("test", rd.TEXTURE_DIRECTORY + "/placeholder")
        self.assertFalse(effect["pass_array"][0]["depth_enable"])
        self.assertEqual(effect["pass_array"][0]["material"], rd.MATERIAL)
        self.assertEqual(len(effect["paras"][0]["value"]), 4)

    def test_pixel_verifier_rejects_stale_data_and_placeholder(self):
        first = rd.write_dataset(self.root, "first", 12345)
        second = rd.write_dataset(self.root, "second", 54321)
        with Image.open(first["absolute_png"]) as tiny:
            screenshot = tiny.resize((640, 480), Image.Resampling.NEAREST)
        matched = verify.compare_capture(screenshot, first)
        self.assertTrue(matched["gpu_data_verified"])
        self.assertEqual(matched["exact_texels"], 256)
        self.assertFalse(verify.compare_capture(screenshot, second)["gpu_data_verified"])
        flipped = screenshot.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        self.assertFalse(verify.compare_capture(flipped, first)["gpu_data_verified"])
        self.assertTrue(verify.compare_capture(flipped, first, flip_y=True)["gpu_data_verified"])
        with Image.open(self.root / rd.TEXTURE_DIRECTORY / "placeholder.png") as baseline:
            self.assertFalse(verify.compare_capture(baseline, first)["gpu_data_verified"])

    def test_prepare_refuses_unowned_existing_directory(self):
        target = self.root.parent / "not_a_probe"
        target.mkdir()
        (target / "important.txt").write_text("preserve me")
        with self.assertRaises(ValueError):
            probe_prepare.prepare(target)
        self.assertEqual((target / "important.txt").read_text(), "preserve me")
        (target / rd.MARKER).write_text(json.dumps({"probe": "someone_else"}))
        with self.assertRaises(ValueError):
            probe_prepare.prepare(target)


if __name__ == "__main__":
    unittest.main()
