"""A rejected build must never replace a previously usable demo deployment."""

import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pyreact_manim.compiler import compile_scene


def load_tool(name):
    spec = importlib.util.spec_from_file_location("review_" + name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deploy_tool = load_tool("deploy_demo")
build_tool = load_tool("build_demo")


def scene(name):
    path = {"id": "triangle", "contours": [[[0, 0], [1, 0], [0, 1]]],
            "fill": [1, 1, 1, 1], "stroke": [0, 0, 0, 0], "stroke_width": 0}
    return {"schema_version": 1, "name": name, "duration": 1, "width": 8, "height": 8,
            "background": [0, 0, 0],
            "frames": [{"time": 0, "paths": [path]}, {"time": 1, "paths": [copy.deepcopy(path)]}]}


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="manim-deploy-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.compiled = self.root / "compiled"
        self.other = self.root / "other"
        compile_scene(scene("primary"), self.compiled)
        compile_scene(scene("secondary"), self.other)
        self.manifest = json.loads((self.other / "scene.json").read_text(encoding="utf-8"))
        self.patch = patch.object(deploy_tool, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        (self.root / "behavior_pack/manim_ui").mkdir(parents=True)
        deploy_tool.deploy([self.compiled])

    def deployment(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for folder in ("resource_pack", "behavior_pack")
                for path in (self.root / folder).rglob("*") if path.is_file()}

    def write_manifest(self, value):
        (self.other / "scene.json").write_text(json.dumps(value), encoding="utf-8")

    def assert_rejected_before_writes(self, directories):
        failure = AssertionError("Deployment attempted an output write before finishing validation")
        with patch.object(deploy_tool.shutil, "copyfile", side_effect=failure), \
                patch.object(Path, "write_text", side_effect=failure), \
                patch.object(Path, "mkdir", side_effect=failure):
            with self.assertRaises(ValueError):
                deploy_tool.deploy(directories)

    def test_valid_manifest_deploys_bytes_and_python_config(self):
        manifest = json.loads((self.compiled / "scene.json").read_text())
        texture = self.root / "resource_pack/textures/manim/primary.png"
        shader = self.root / "resource_pack/shaders/glsl/primary.fragment"
        self.assertEqual(texture.read_bytes(), (self.compiled / manifest["texture"]["path"]).read_bytes())
        self.assertEqual(shader.read_bytes(), (self.compiled / manifest["shader"]["path"]).read_bytes())
        namespace = {}
        config = self.root / "behavior_pack/manim_ui/generated_scenes.py"
        exec(compile(config.read_text(encoding="utf-8"), str(config), "exec"), namespace)
        self.assertEqual(namespace["SCENES"][0]["duration"], 1)

    def test_empty_deployment_preserves_all_existing_outputs(self):
        before = self.deployment()
        self.assert_rejected_before_writes([])
        self.assertEqual(self.deployment(), before)

    def test_invalid_runtime_metadata_is_rejected_before_any_batch_write(self):
        cases = [("duration", value) for value in (float("nan"), float("inf"), 0, -1, True, "2")]
        cases += [("schema_version", value) for value in (3, True, "1", None)]
        cases += [("texture.sampler", value) for value in (0, 3, True, "2", None)]
        cases += [("texture.encoding", value) for value in ("rgba32f", "", None)]
        cases += [("texture.filter", value) for value in ("Linear", "", None)]
        before = self.deployment()
        for key, value in cases:
            with self.subTest(key=key, value=value):
                invalid = copy.deepcopy(self.manifest)
                if "." in key:
                    parent, child = key.split(".")
                    invalid[parent][child] = value
                else:
                    invalid[key] = value
                self.write_manifest(invalid)
                self.assert_rejected_before_writes([self.compiled, self.other])
                self.assertEqual(self.deployment(), before)

    def test_artifact_mismatch_cannot_partially_replace_deployment(self):
        before = self.deployment()
        invalid = copy.deepcopy(self.manifest)
        invalid["shader"]["sha256"] = "0" * 64
        self.write_manifest(invalid)
        self.assert_rejected_before_writes([self.compiled, self.other])
        self.assertEqual(self.deployment(), before)

    def test_build_rejects_zero_scene_definitions_before_export(self):
        examples = self.root / "examples.py"
        before = self.deployment()
        for body in ("SCENES = ()\n", "SCENES = []\n", "OTHER = 1\n", "SCENES = [None]\n"):
            with self.subTest(body=body):
                examples.write_text(body, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "SCENES"):
                    build_tool.load_definitions(examples)
                self.assertEqual(self.deployment(), before)


if __name__ == "__main__":
    unittest.main()
