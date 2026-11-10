"""Verify UI probe isolation/cleanup and fixture translation without ModSDK."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools/ui_canvas_probe"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Screen:
    def __init__(self, *_args):
        self.controls = {}

    def GetBaseUIControl(self, path):
        return self.controls.get(path)


class UiCanvasProbeTests(unittest.TestCase):
    def setUp(self):
        api = types.ModuleType("mod.client.extraClientApi")
        api.GetScreenNodeCls = lambda: Screen
        self.actor = Mock()
        self.actor.SetEntityUIExtraUniforms.return_value = True
        factory = Mock()
        factory.CreateActorRender.return_value = self.actor
        self.game = Mock()
        self.game.GetScreenSize.return_value = (640.0, 360.0)
        factory.CreateGame.return_value = self.game
        api.GetEngineCompFactory = lambda: factory
        api.GetLevelId = lambda: "level"
        mod = types.ModuleType("mod")
        client = types.ModuleType("mod.client")
        mod.client = client
        client.extraClientApi = api
        with patch.dict(sys.modules, {"mod": mod, "mod.client": client,
                                     "mod.client.extraClientApi": api}):
            module = load_module("_ui_canvas_probe", PROBE / "canvas_probe.py")
            self.probe = module.CanvasProbe("probe", "test", {})

    def test_progress_updates_only_its_slot_identifier(self):
        self.assertTrue(self.probe.set_state("left", 0.5, 0.25, (1, 0, 0)))
        calls = self.actor.SetEntityUIExtraUniforms.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual({call.args[0] for call in calls}, {"pmanim_probe:left"})
        self.assertFalse(self.probe.set_state("unknown", 0, 1, (1, 1, 1)))
        self.assertEqual(self.actor.SetEntityUIExtraUniforms.call_count, 2)

    def test_destroy_hides_every_probe_identifier_and_rejects_later_uploads(self):
        self.probe.Destroy()
        calls = self.actor.SetEntityUIExtraUniforms.call_args_list
        self.assertEqual({call.args[0] for call in calls}, {
            "pmanim_probe:left", "pmanim_probe:right",
            "pmanim_probe:left_glyph", "pmanim_probe:right_glyph",
        })
        self.assertTrue(all(call.args[2] == (0, 0, 0, 0) for call in calls))
        self.assertIsNone(self.probe.actor)
        self.assertFalse(self.probe.set_state("left", 0, 1, (1, 1, 1)))
        self.assertFalse(self.probe.show_glyph("left", 0))

    def test_resource_and_raw_paths_target_different_native_controls(self):
        normal, raw = Mock(), Mock()
        self.probe.controls = {"/normal": normal, "/raw": raw}
        self.assertTrue(self.probe.set_image("textures/ui/generated"))
        self.assertTrue(self.probe.set_image("D:/temp/generated.png", raw_path=True))
        normal.asImage().SetSprite.assert_called_once_with("textures/ui/generated")
        raw.asImage().SetSprite.assert_called_once_with("D:/temp/generated.png")

    def test_layout_maps_control_rectangle_using_logical_screen_units(self):
        canvas = Mock()
        canvas.GetGlobalPosition.return_value = (64.0, 36.0)
        canvas.GetSize.return_value = (320.0, 180.0)
        self.probe.controls = {"/left/canvas": canvas}
        self.assertTrue(self.probe.sync_layout())
        calls = self.actor.SetEntityUIExtraUniforms.call_args_list
        self.assertEqual({call.args[0] for call in calls}, {
            "pmanim_probe:left", "pmanim_probe:left_glyph"})
        self.assertTrue(all(call.args[1:] == (3, (-0.8, 0.8, 1.0, 1.0)) for call in calls))

    def test_fixture_shader_has_no_framebuffer_dependency_and_fails_on_unknown_contract(self):
        builder = load_module("_ui_canvas_probe_builder", PROBE / "build_probe.py")
        source = (ROOT / "resource_pack/shaders/glsl/manimgl_o_to_b.fragment").read_text(encoding="utf-8")
        translated = builder.glyph_fragment(source)
        self.assertNotIn("TEXTURE_2", translated)
        self.assertNotIn("vec4 original", translated)
        self.assertIn("texture2D(TEXTURE_0, tc)", translated)
        self.assertIn("alpha * clamp(EXTRA_ACTOR_UNIFORM1.w", translated)
        self.assertNotIn("EXTRA_VECTOR", translated)
        with self.assertRaises(ValueError):
            builder.glyph_fragment(source.replace("coverage * 1.06", "coverage * 1.07"))


if __name__ == "__main__":
    unittest.main()
