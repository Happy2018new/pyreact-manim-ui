"""Native UI canvas ownership, failure handling and Pyreact lifecycle."""
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_canvas_under_test"
SCENES = [{"name": "glyph", "title": "Glyph", "duration": 4.0},
          {"name": "runtime_shapes", "title": "Shape", "duration": 4.0}]


class CanvasTests(unittest.TestCase):
    def setUp(self):
        api = types.ModuleType("mod.client.extraClientApi")
        mod, client = types.ModuleType("mod"), types.ModuleType("mod.client")
        mod.client, client.extraClientApi = client, api
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(ROOT / "behavior_pack/manim_ui")]
        pyreact = types.ModuleType(PACKAGE + ".pyreact")
        primitives = types.ModuleType(PACKAGE + ".pyreact.primitives")
        primitives.Primitive = type("Primitive", (object,), {})
        modules = {"mod": mod, "mod.client": client, "mod.client.extraClientApi": api,
                   PACKAGE: package, PACKAGE + ".pyreact": pyreact,
                   PACKAGE + ".pyreact.primitives": primitives}
        for name in tuple(sys.modules):
            if name.startswith(PACKAGE + "."):
                del sys.modules[name]
        patcher = patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.canvas = importlib.import_module(PACKAGE + ".canvas")
        self.primitive_module = importlib.import_module(PACKAGE + ".canvas_primitive")
        self.clock = [0.0]
        self.actor = Mock()
        self.actor.SetEntityUIExtraUniforms.return_value = True
        self.game = Mock()
        self.game.GetScreenSize.return_value = (640, 360)
        self.game.GetScreenViewInfo.return_value = (1280, 720, 0, 0)

    def renderer(self):
        renderer = self.canvas.CanvasRenderer(SCENES, self.actor, self.game)
        self.addCleanup(renderer.detach)
        return renderer

    @staticmethod
    def control():
        control = Mock()
        control.GetGlobalPosition.return_value = (64.0, 36.0)
        control.GetSize.return_value = (320.0, 180.0)
        control.asNeteasePaperDoll().RenderEntity.return_value = True
        return control

    def mounted_player(self):
        renderer = self.renderer()
        renderer.attach(self.control())
        renderer.update_layout()
        player = self.canvas.PlaybackController(SCENES, renderer, lambda: self.clock[0])
        return player

    def test_two_slots_are_distinct_third_fails_and_released_slot_reuses(self):
        first, second, third = self.renderer(), self.renderer(), self.renderer()
        first.attach(self.control())
        second.attach(self.control())
        self.assertEqual((first.slot, second.slot), (0, 1))
        with self.assertRaises(RuntimeError):
            third.attach(self.control())
        first.detach()
        third.attach(self.control())
        self.assertEqual(third.slot, 0)

    def test_play_before_mount_or_layout_fails_without_gpu_calls(self):
        renderer = self.renderer()
        player = self.canvas.PlaybackController(SCENES, renderer, lambda: self.clock[0])
        self.assertFalse(player.play("glyph"))
        renderer.attach(self.control())
        self.assertFalse(player.play("glyph"))
        self.actor.SetEntityUIExtraUniforms.assert_not_called()

    def test_repeated_frames_only_upload_time_and_cache_screen_metrics(self):
        player = self.mounted_player()
        self.assertTrue(player.play("glyph"))
        self.actor.reset_mock()
        for frame in range(1, 11):
            self.clock[0] = frame / 60.0
            player.frame()
        self.game.GetScreenSize.assert_called_once()
        self.game.GetScreenViewInfo.assert_called_once()
        calls = self.actor.SetEntityUIExtraUniforms.call_args_list
        self.assertEqual(len(calls), 10)
        self.assertTrue(all(call.args[1] == 1 for call in calls))

    def test_runtime_parameters_are_validated_atomically_and_remain_independent(self):
        first, second = self.mounted_player(), self.mounted_player()
        first.load("runtime_shapes")
        second.load("runtime_shapes")
        self.actor.reset_mock()
        self.assertTrue(first.renderer.set_shape(morph=0.65, progress=0.37,
            scale=0.92, color=(0.8, 0.2, 0.4), rotation=1.25))
        self.assertEqual(second.renderer.shape_snapshot()["morph"], 0.0)
        self.assertTrue(all(call.args[0].startswith("pmanim:canvas_0_")
            for call in self.actor.SetEntityUIExtraUniforms.call_args_list))
        saved = first.renderer.shape_snapshot()
        for changes in ({"scale": 0}, {"morph": 2}, {"rotation": float("nan")},
                        {"stroke_width": -1}, {"color": (1, 2, 3)}, {"unknown": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                first.renderer.set_shape(**changes)
            self.assertEqual(first.renderer.shape_snapshot(), saved)

    def test_failed_upload_never_reports_playing_and_hide_does_not_need_failed_uniform(self):
        player = self.mounted_player()
        self.actor.SetEntityUIExtraUniforms.side_effect = lambda _id, index, _value: index != 3
        self.assertFalse(player.play("glyph"))
        self.assertFalse(player.snapshot()["playing"])
        self.assertFalse(player.snapshot()["visible"])
        self.assertIn("failed", player.snapshot()["error"])
        # Initial opacity was already zero, so hiding may reuse its successful
        # cached upload. No failed prerequisite may expose nonzero opacity.
        opacity_calls = [call for call in self.actor.SetEntityUIExtraUniforms.call_args_list
                         if call.args[1] == 1]
        self.assertTrue(opacity_calls)
        self.assertTrue(all(call.args[2][-1] == 0 for call in opacity_calls))

    def test_unmount_releases_callback_and_slot_then_remount_works(self):
        renderer = self.renderer()
        player = self.canvas.PlaybackController(SCENES, renderer, lambda: self.clock[0])
        primitive = self.primitive_module.ManimCanvas
        host = Mock()
        fiber = types.SimpleNamespace(primitive_state={})
        props = {"player": player, "scene": "glyph", "autoPlay": True}
        control = self.control()
        primitive.apply_props(host, fiber, control, None, props)
        self.assertIsNone(player.timeline)
        node = types.SimpleNamespace(fiber=fiber, inherited_opacity=0.6)
        primitive.apply_layout(host, node)
        self.assertIsNone(player.timeline)
        self.game.GetScreenSize.assert_not_called()
        primitive._frame(fiber, 0.0)
        self.game.GetScreenSize.assert_called_once()
        self.assertTrue(player.timeline.playing)
        primitive.unmount(host, fiber)
        host.pyreact_unregister_animation_frame.assert_called_once()
        self.assertIsNone(renderer.slot)
        self.assertFalse(player.timeline.playing)
        control.SetVisible.assert_called_with(False)
        primitive.apply_props(host, fiber, self.control(), None, props)
        primitive.apply_layout(host, node)
        primitive._frame(fiber, 0.0)
        self.assertTrue(player.timeline.playing)
        primitive.unmount(host, fiber)

    def test_resize_updates_ndc_opacity_and_does_not_reload_entity(self):
        player = self.mounted_player()
        player.load("glyph")
        control = player.renderer.control
        control.GetGlobalPosition.return_value = (320, 180)
        control.GetSize.return_value = (160, 90)
        self.assertTrue(player.renderer.update_layout(0.4))
        self.assertEqual(player.renderer._rectangle, (0, 0, 0.5, 0.5))
        self.assertEqual(player.renderer._pixel_height, 180)
        control.asNeteasePaperDoll().RenderEntity.assert_called_once()
        self.assertEqual(self.actor.SetEntityUIExtraUniforms.call_args.args[2][-1], 0.4)

    def test_invalid_opacity_does_not_change_last_accepted_opacity(self):
        player = self.mounted_player()
        player.renderer.update_layout(0.35)
        for value in (-0.1, 1.1, float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                player.renderer.update_layout(value)
        self.assertEqual(player.renderer._opacity, 0.35)

    def test_page_dispose_before_primitive_unmount_is_safe(self):
        renderer = self.renderer()
        player = self.canvas.PlaybackController(SCENES, renderer, lambda: self.clock[0])
        primitive = self.primitive_module.ManimCanvas
        host = Mock()
        fiber = types.SimpleNamespace(primitive_state={})
        primitive.apply_props(host, fiber, self.control(), None, {"player": player})
        player.dispose()
        primitive._frame(fiber, 0)
        primitive.unmount(host, fiber)
        self.assertTrue(player.disposed)
        self.assertEqual(self.canvas._SLOT_OWNERS, [None, None])
        host.pyreact_unregister_animation_frame.assert_called_once()

    def test_player_replacement_restores_control_visibility_without_ignoring_style(self):
        primitive = self.primitive_module.ManimCanvas
        host = Mock()
        for visible in (True, False):
            with self.subTest(visible=visible):
                first = self.canvas.PlaybackController(SCENES, self.renderer(), lambda: self.clock[0])
                second = self.canvas.PlaybackController(SCENES, self.renderer(), lambda: self.clock[0])
                fiber = types.SimpleNamespace(primitive_state={"_visible": visible})
                control = self.control()
                primitive.apply_props(host, fiber, control, None, {"player": first})
                primitive.apply_props(host, fiber, control, {"player": first}, {"player": second})
                primitive.apply_layout(host, types.SimpleNamespace(fiber=fiber, inherited_opacity=1))
                primitive._frame(fiber, 0)
                control.SetVisible.assert_called_with(visible)
                self.assertIsNone(first.renderer.slot)
                primitive.unmount(host, fiber)

    def test_callback_changes_do_not_force_screen_metric_refresh(self):
        primitive = self.primitive_module.ManimCanvas
        player = self.mounted_player()
        old = {"player": player, "onReady": lambda p: None}
        new = {"player": player, "onReady": lambda p: None}
        self.assertFalse(primitive.props_affect_layout(old, new, None))

    def test_layout_measurement_waits_for_next_frame_viewport_and_only_runs_once(self):
        renderer = self.renderer()
        player = self.canvas.PlaybackController(SCENES, renderer, lambda: self.clock[0])
        primitive = self.primitive_module.ManimCanvas
        fiber = types.SimpleNamespace(primitive_state={})
        primitive.apply_props(Mock(), fiber, self.control(), None, {"player": player})
        primitive.apply_layout(Mock(), types.SimpleNamespace(fiber=fiber, inherited_opacity=0.5))
        # The native resize becomes observable after the layout callback.
        self.game.GetScreenSize.return_value = (800, 450)
        self.game.GetScreenViewInfo.return_value = (1600, 900, 0, 0)
        primitive._frame(fiber, 0)
        self.assertEqual(renderer._screen, (800, 450, 2.0))
        for _ in range(10):
            primitive._frame(fiber, 0)
        self.game.GetScreenSize.assert_called_once()
        primitive.unmount(Mock(), fiber)

    def test_hide_survives_failed_uniform_and_show_restores_current_style_visibility(self):
        player = self.mounted_player()
        renderer = player.renderer
        visible = [True]
        renderer._visibility_source = lambda: visible[0]
        self.assertTrue(player.play("glyph"))
        renderer.control.reset_mock()
        self.actor.SetEntityUIExtraUniforms.return_value = False
        self.assertTrue(player.hide())
        renderer.control.SetVisible.assert_called_with(False)
        self.assertFalse(player.visible)
        # A style transition cannot expose hidden content while the GPU upload
        # remains broken, even if Pyreact itself wrote SetVisible(True).
        visible[0] = False
        renderer.sync_visibility()
        visible[0] = True
        renderer.control.SetVisible(True)
        renderer.sync_visibility()
        renderer.control.SetVisible.assert_called_with(False)
        # Recovery reads the CURRENT style, not the style captured at hide.
        visible[0] = False
        self.actor.SetEntityUIExtraUniforms.return_value = True
        self.assertTrue(player.show())
        renderer.control.SetVisible.assert_called_with(False)
        visible[0] = True
        renderer.sync_visibility()
        renderer.control.SetVisible.assert_called_with(True)

    def test_layout_upload_failure_reports_error_and_explicit_play_recovers_without_relayout(self):
        renderer = self.renderer()
        player = self.canvas.PlaybackController(SCENES, renderer, lambda: self.clock[0])
        primitive = self.primitive_module.ManimCanvas
        fiber = types.SimpleNamespace(primitive_state={})
        control = self.control()
        primitive.apply_props(Mock(), fiber, control, None, {"player": player, "autoPlay": True})
        node = types.SimpleNamespace(fiber=fiber, inherited_opacity=1)
        primitive.apply_layout(Mock(), node)
        primitive._frame(fiber, 0)
        control.GetGlobalPosition.return_value = (80, 40)
        self.actor.SetEntityUIExtraUniforms.return_value = False
        primitive.apply_layout(Mock(), node)
        primitive._frame(fiber, 0)
        self.assertTrue(fiber.primitive_state["_manim_canvas"]["layout_ready"])
        self.assertFalse(player.snapshot()["playing"])
        self.assertFalse(player.snapshot()["visible"])
        self.assertIn("layout", player.snapshot()["error"])
        control.SetVisible.assert_called_with(False)
        self.actor.SetEntityUIExtraUniforms.return_value = True
        self.assertTrue(player.play())
        self.clock[0] = 0.5
        primitive._frame(fiber, 0.5)
        self.assertAlmostEqual(player.timeline.position, 0.5)
        self.assertEqual(player.error, "")
        control.SetVisible.assert_called_with(True)
        primitive.unmount(Mock(), fiber)

    def test_initial_load_failure_does_not_spin_and_business_play_resumes_host_clock(self):
        renderer = self.renderer()
        player = self.canvas.PlaybackController(SCENES, renderer, lambda: self.clock[0])
        primitive = self.primitive_module.ManimCanvas
        fiber = types.SimpleNamespace(primitive_state={})
        control = self.control()
        control.asNeteasePaperDoll().RenderEntity.return_value = False
        primitive.apply_props(Mock(), fiber, control, None, {"player": player, "scene": "glyph"})
        primitive.apply_layout(Mock(), types.SimpleNamespace(fiber=fiber, inherited_opacity=1))
        primitive._frame(fiber, 0)
        for _ in range(10):
            primitive._frame(fiber, 0)
        control.asNeteasePaperDoll().RenderEntity.assert_called_once()
        self.assertTrue(fiber.primitive_state["_manim_canvas"]["slot"]["active"])
        control.asNeteasePaperDoll().RenderEntity.return_value = True
        self.assertTrue(player.play("glyph"))
        self.clock[0] = 0.5
        primitive._frame(fiber, 0.5)
        self.assertTrue(player.timeline.playing)
        self.assertAlmostEqual(player.timeline.position, 0.5)
        primitive.unmount(Mock(), fiber)

    def test_native_hidden_zero_size_does_not_prevent_initial_layout(self):
        renderer = self.renderer()
        control = self.control()
        visible = [True]
        control.SetVisible.side_effect = lambda value: visible.__setitem__(0, value)
        control.GetSize.side_effect = lambda: (320, 180) if visible[0] else (0, 0)
        renderer.attach(control)
        self.assertTrue(visible[0])
        self.assertTrue(renderer.update_layout())
        player = self.canvas.PlaybackController(SCENES, renderer, lambda: self.clock[0])
        self.assertTrue(player.play("glyph"))

    def test_hidden_resize_uses_committed_geometry_instead_of_native_zero_size(self):
        renderer = self.renderer()
        player = self.canvas.PlaybackController(SCENES, renderer, lambda: self.clock[0])
        primitive = self.primitive_module.ManimCanvas
        fiber = types.SimpleNamespace(native_path="/root/card/canvas", primitive_state={
            "_visible": True, "_layout_applied": (320, 180, 10, 20, 1)})
        host = Mock()
        host.GetBaseUIControl("/root/card").GetGlobalPosition.return_value = (54, 16)
        control = self.control()
        visible = [True]
        control.SetVisible.side_effect = lambda value: visible.__setitem__(0, value)
        control.GetSize.side_effect = lambda: (320, 180) if visible[0] else (0, 0)
        primitive.apply_props(host, fiber, control, None, {"player": player})
        node = types.SimpleNamespace(fiber=fiber, inherited_opacity=1)
        primitive.apply_layout(host, node)
        primitive._frame(fiber, 0)
        self.assertTrue(player.hide())
        self.assertFalse(visible[0])
        fiber.primitive_state["_layout_applied"] = (160, 90, 20, 40, 1)
        primitive.apply_layout(host, node)
        primitive._frame(fiber, 0)
        self.assertTrue(renderer.ready)
        self.assertEqual(renderer._aspect, 160 / 90)
        self.assertEqual(renderer._pixel_height, 180)
        self.assertAlmostEqual(renderer._rectangle[0], 2 * 74 / 640 - 1)
        self.assertFalse(visible[0])
        self.assertTrue(player.show())
        self.assertTrue(visible[0])
        control.GetSize.assert_not_called()
        primitive.unmount(host, fiber)


if __name__ == "__main__":
    unittest.main()
