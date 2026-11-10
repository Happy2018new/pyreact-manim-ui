"""Compile shipped fragments across GLSL dialects without drawing or starting MC.

The default desktop renderer targets 330, which accepts identifiers such as
``sample`` that later versions reserve. Check the source language version too;
creating a newer GL context while keeping ``#version 330`` misses this failure.
Engine includes are still adapted, so this is not Minecraft acceptance.
"""

import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pyreact_manim.compiler.desktop import VERTEX, desktop_fragment

HAS_GL = importlib.util.find_spec("moderngl") is not None


@unittest.skipUnless(HAS_GL, "Requires optional moderngl and desktop OpenGL 4.5")
class ShaderDialectChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import moderngl
        cls.context = moderngl.create_standalone_context(require=450)

    @classmethod
    def tearDownClass(cls):
        cls.context.release()

    def compile_fragments(self, version):
        paths = sorted((ROOT / "resource_pack/shaders/glsl").glob("*.fragment"))
        self.assertTrue(paths, "No deployed fragment shaders found")
        directive = "#version %d" % version
        vertex = VERTEX.replace("#version 330", directive, 1)
        for path in paths:
            with self.subTest(shader=path.name, glsl=version):
                fragment = desktop_fragment(path.read_text(encoding="utf-8"))
                fragment = fragment.replace("#version 330", directive, 1)
                program = self.context.program(vertex_shader=vertex, fragment_shader=fragment)
                program.release()

    def test_glsl_330(self):
        self.compile_fragments(330)

    def test_glsl_400(self):
        self.compile_fragments(400)

    def test_glsl_450(self):
        self.compile_fragments(450)


if __name__ == "__main__":
    unittest.main()
