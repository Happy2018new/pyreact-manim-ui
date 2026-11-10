"""The authored film coexists with the generic transparent-canvas compiler."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_canvas


class ShowcaseBuildTests(unittest.TestCase):
    def test_authored_film_is_not_fed_to_generic_shader_rewriter(self):
        scenes = build_canvas.read_scenes(ROOT / "behavior_pack/manim_ui/generated_scenes.py")
        film = next(scene for scene in scenes if scene["name"] == "client_showcase")
        self.assertIs(film["canvas_compatible"], False)
        with tempfile.TemporaryDirectory() as temporary:
            result = build_canvas.build(output=temporary)
            self.assertNotIn("client_showcase", result["scenes"])
            self.assertIn("runtime_shapes", result["scenes"])

    def test_shader_has_current_typography_and_resource_digest(self):
        import hashlib
        import json
        meta = json.loads((ROOT / "tools/showcase/typography.json").read_text(encoding="utf-8"))
        shader = (ROOT / "resource_pack/shaders/glsl/client_showcase.fragment").read_bytes()
        texture = (ROOT / "resource_pack/textures/manim/client_showcase.png").read_bytes()
        self.assertEqual(hashlib.sha256(shader).hexdigest(), meta["shader_sha256"])
        self.assertEqual(hashlib.sha256(texture).hexdigest(), meta["sha256"])
        self.assertNotIn(b"__TYPOGRAPHY_CONSTANTS__", shader)
        self.assertEqual(meta["duration"], 41.0)


if __name__ == "__main__":
    unittest.main()
