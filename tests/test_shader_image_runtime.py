"""Image transforms, four-slot ownership, failure recovery and Pyreact teardown."""
import importlib
import math
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_shader_image_runtime_under_test"
IMAGES = {
    "aurora": {"size": (400, 200), "uv": (0.0, 0.0, 0.5, 0.5), "title": "Aurora"},
    "sunrise": {"size": (200, 400), "uv": (0.5, 0.0, 0.25, 0.5), "title": "Sunrise"},
    "prism": {"size": (256, 256), "uv": (0.0, 0.5, 0.5, 0.5), "title": "Prism"},
}


class ShaderImageRuntimeTests(unittest.TestCase):
    def setUp(self):
        api = types.ModuleType("mod.client.extraClientApi")
        mod, client = types.ModuleType("mod"), types.ModuleType("mod.client")
        mod.client, client.extraClientApi = client, api
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(ROOT / "behavior_pack/manim_ui")]
        pyreact = types.ModuleType(PACKAGE + ".pyreact")
        primitives = types.ModuleType(PACKAGE + ".pyreact.primitives")
        primitives.Primitive = type("Primitive", (object,), {})
        generated = types.ModuleType(PACKAGE + ".images.generated")
        generated.IMAGES, generated.SLOT_COUNT = IMAGES, 4
        modules = {"mod": mod, "mod.client": client, "mod.client.extraClientApi": api,
                   PACKAGE: package, PACKAGE + ".pyreact": pyreact,
                   PACKAGE + ".pyreact.primitives": primitives,
                   PACKAGE + ".images.generated": generated}
        for name in tuple(sys.modules):
            if name.startswith(PACKAGE + "."):
                del sys.modules[name]
        patcher = patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.images = importlib.import_module(PACKAGE + ".images")
        self.model = importlib.import_module(PACKAGE + ".images.model")
        self.renderer_module = importlib.import_module(PACKAGE + ".images.renderer")
        self.clock = [0.0]
        self.actor = Mock()
        self.actor.SetEntityUIExtraUniforms.return_value = True
        self.game = Mock()
        self.game.GetScreenSize.return_value = (640, 360)

    def controller(self, **config):
        renderer = self.images.ImageRenderer(IMAGES, self.actor, self.game)
        controller = self.images.ImageController(IMAGES, renderer, lambda: self.clock[0], **config)
        self.addCleanup(controller.dispose)
        return controller

    @staticmethod
    def control():
        control = Mock()
        control.GetGlobalPosition.return_value = (64, 36)
        control.GetSize.return_value = (320, 180)
        control.asNeteasePaperDoll().RenderEntity.return_value = True
        return control

    def mounted(self, **config):
        controller = self.controller(**config)
        controller.mount(self.control())
        self.assertTrue(controller.update_layout())
        return controller

    def primitive_mount(self, controller=None, fiber=None, callback=None):
        controller = controller or self.controller()
        fiber = fiber or types.SimpleNamespace(primitive_state={})
        host, control = Mock(), self.control()
        primitive = self.images.ShaderImage
        primitive.apply_props(host, fiber, control, None,
                              {"controller": controller, "onReady": callback})
        return controller, primitive, host, fiber, control

    def test_four_independent_slots_exhaust_then_reuse_without_affecting_canvas(self):
        controllers = [self.mounted() for _ in range(4)]
        self.assertEqual([controller.renderer.slot for controller in controllers], list(range(4)))
        extra = self.controller()
        with self.assertRaisesRegex(RuntimeError, "four simultaneous"):
            extra.mount(self.control())
        canvas = importlib.import_module(PACKAGE + ".canvas")
        canvas_renderer = canvas.CanvasRenderer([{"name": "glyph"}], self.actor, self.game)
        canvas_renderer.attach(self.control())
        self.addCleanup(canvas_renderer.detach)
        self.assertEqual(canvas_renderer.slot, 0)
        controllers[1].unmount()
        extra.mount(self.control())
        self.assertTrue(extra.update_layout())
        self.assertEqual(extra.renderer.slot, 1)
        self.assertEqual(extra.renderer.identifier, "pmanim:image_1")
        self.assertEqual([c.renderer.slot for c in (controllers[0], controllers[2], controllers[3])],
                         [0, 2, 3])

    def test_same_controller_cannot_attach_two_controls(self):
        controller = self.mounted()
        with self.assertRaises(RuntimeError):
            controller.mount(self.control())
        self.assertEqual(controller.renderer.slot, 0)

    def test_fit_uses_cropped_source_aspect_before_scale_flips_rotation(self):
        cases = (("contain", "aurora", (1, 0.5)), ("cover", "aurora", (2, 1)),
                 ("fill", "aurora", (1, 1)), ("contain", "sunrise", (0.5, 1)),
                 ("cover", "sunrise", (1, 2)))
        for fit, source, expected in cases:
            with self.subTest(fit=fit, src=source):
                config = self.model.validate_config(self.model.DEFAULT_CONFIG,
                    {"fit": fit, "src": source}, IMAGES)
                transform, _ = self.model.image_uniforms(config, IMAGES[source], 1.0)
                self.assertEqual(transform[:2], expected)
        config = self.model.validate_config(self.model.DEFAULT_CONFIG,
            {"crop": (0.25, 0.0, 0.5, 1.0), "scale": (2, 3),
             "flip_x": True, "flip_y": True, "rotation": 0.4}, IMAGES)
        transform, uv = self.model.image_uniforms(config, IMAGES["aurora"], 1.0)
        self.assertEqual(transform, (-2, -3, 0.4, 0.15))
        self.assertEqual(uv, (0.125, 0.0, 0.25, 0.5))

    def test_invalid_edits_are_atomic_and_never_upload(self):
        controller = self.mounted(effect="wave")
        controller.play()
        original = controller.snapshot()
        self.actor.reset_mock()
        invalid = ({"scale": (0, 1)}, {"scale": (-1, 1)}, {"scale": (1,)},
                   {"scale": (float("inf"), 1)}, {"rotation": float("nan")},
                   {"scale": (1e308, 1)}, {"scale": (1e-300, 1)},
                   {"crop": (0, 0, 0, 1)}, {"crop": (-0.1, 0, 1, 1)},
                   {"crop": (0, 0, 1e-300, 1e-300)},
                   {"crop": (0.5, 0, 0.6, 1)}, {"crop": (0, 0, 1, 2)},
                   {"opacity": 1.1}, {"strength": -1.1}, {"flip_x": 1},
                   {"effect": "unknown"}, {"fit": "stretch"}, {"src": "absent"},
                   {"src": []}, {"unexpected": True})
        self.clock[0] = 10.0
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                controller.configure(opacity=0.2, **changes) if "opacity" not in changes else controller.configure(**changes)
            self.assertEqual(controller.snapshot(), original)
        self.actor.SetEntityUIExtraUniforms.assert_not_called()

    def test_large_finite_rotation_and_time_upload_bounded_equivalent_phase(self):
        controller = self.mounted(effect="wave", rotation=1e308)
        self.assertTrue(controller.seek(1e308))
        uniforms = controller.renderer._uniforms
        self.assertTrue(0.0 <= uniforms[1][0] < 1.0)
        self.assertTrue(abs(uniforms[2][2]) < 2.0 * math.pi)
        self.assertEqual(controller.snapshot()["config"]["rotation"], 1e308)
        self.assertEqual(controller.time, 1e308)

    def test_source_switch_changes_uniforms_without_entity_reload_and_other_image_stays_same(self):
        first, second = self.mounted(), self.mounted()
        original = second.snapshot()
        self.actor.reset_mock()
        first.configure(src="sunrise", crop=(0, 0.25, 1, 0.5), opacity=0.6)
        self.assertEqual(second.snapshot(), original)
        calls = self.actor.SetEntityUIExtraUniforms.call_args_list
        self.assertTrue(calls)
        self.assertTrue(all(call.args[0] == "pmanim:image_0" for call in calls))
        first.renderer.doll.RenderEntity.assert_called_once()
        second.renderer.doll.RenderEntity.assert_called_once()

    def test_static_and_paused_frames_have_no_uploads_and_no_metric_queries(self):
        controller = self.mounted()
        callback = Mock()
        controller.subscribe(callback)
        controller.play()
        self.actor.reset_mock()
        callback.reset_mock()
        for frame in range(10):
            self.clock[0] = frame / 60.0
            controller.frame()
        self.actor.SetEntityUIExtraUniforms.assert_not_called()
        callback.assert_not_called()
        self.game.GetScreenSize.assert_called_once()
        controller.configure(effect="swirl")
        self.actor.reset_mock()
        for frame in range(10):
            self.clock[0] += 0.02
            controller.frame()
        self.actor.SetEntityUIExtraUniforms.assert_not_called()
        self.assertEqual(controller.time, 0.0)
        controller.configure(effect="wave")
        controller.pause()
        self.actor.reset_mock()
        controller.frame()
        self.actor.SetEntityUIExtraUniforms.assert_not_called()

    def test_wave_only_uploads_time_pause_seek_and_resume_have_continuous_clock(self):
        controller = self.mounted(effect="wave")
        callback = Mock()
        controller.subscribe(callback)
        controller.play()
        self.actor.reset_mock()
        callback.reset_mock()
        for frame in range(1, 11):
            self.clock[0] = frame / 60.0
            controller.frame()
        calls = self.actor.SetEntityUIExtraUniforms.call_args_list
        self.assertEqual(len(calls), 10)
        self.assertTrue(all(call.args[1] == 1 for call in calls))
        callback.assert_not_called()
        self.clock[0] = 0.5
        controller.pause()
        self.assertEqual(controller.time, 0.5)
        self.clock[0] = 2.5
        controller.frame()
        self.assertEqual(controller.time, 0.5)
        controller.play()
        self.clock[0] = 3.0
        controller.frame()
        self.assertEqual(controller.time, 1.0)
        controller.seek(7.0)
        self.assertFalse(controller.playing)
        self.assertEqual(controller.time, 7.0)
        with self.assertRaises(ValueError):
            controller.seek(-1)
        self.assertEqual(controller.time, 7.0)

    def test_initial_failed_uniform_never_reveals_and_requires_explicit_retry(self):
        controller = self.controller()
        control = self.control()
        controller.mount(control)
        self.actor.SetEntityUIExtraUniforms.side_effect = lambda _id, index, _data: index != 3
        self.assertFalse(controller.update_layout())
        self.assertFalse(controller.visible)
        self.assertFalse(controller.playing)
        self.assertIn("failed", controller.error)
        control.SetVisible.assert_called_with(False)
        uploads = self.actor.SetEntityUIExtraUniforms.call_args_list
        self.assertTrue(all(call.args[2][2] == 0 for call in uploads if call.args[1] == 1))
        self.actor.reset_mock()
        for _ in range(10):
            controller.frame()
        controller.update_layout()
        self.actor.SetEntityUIExtraUniforms.assert_not_called()
        self.actor.SetEntityUIExtraUniforms.side_effect = None
        self.assertTrue(controller.retry())
        self.assertEqual(controller.error, "")
        self.assertTrue(controller.visible)
        control.SetVisible.assert_called_with(True)

    def test_entity_install_failure_does_not_spin_and_play_recovers(self):
        controller, primitive, host, fiber, control = self.primitive_mount()
        control.asNeteasePaperDoll().RenderEntity.return_value = False
        primitive.apply_layout(host, types.SimpleNamespace(fiber=fiber, inherited_opacity=1.0))
        for _ in range(10):
            primitive._frame(fiber, 0.0)
        control.asNeteasePaperDoll().RenderEntity.assert_called_once()
        self.assertTrue(controller.error)
        self.assertFalse(controller.visible)
        control.asNeteasePaperDoll().RenderEntity.return_value = True
        self.assertTrue(controller.play())
        primitive._frame(fiber, 0.0)
        self.assertTrue(controller.visible)
        self.assertTrue(controller.playing)

    def test_resize_refreshes_only_on_next_frame_and_uses_committed_hidden_geometry(self):
        fiber = types.SimpleNamespace(native_path="/root/card/image", primitive_state={
            "_visible": True, "_layout_applied": (320, 180, 10, 20, 1)})
        controller, primitive, host, fiber, control = self.primitive_mount(fiber=fiber)
        host.GetBaseUIControl("/root/card").GetGlobalPosition.return_value = (54, 16)
        node = types.SimpleNamespace(fiber=fiber, inherited_opacity=0.5)
        primitive.apply_layout(host, node)
        self.game.GetScreenSize.assert_not_called()
        self.game.GetScreenSize.return_value = (800, 450)
        primitive._frame(fiber, 0.0)
        self.assertAlmostEqual(controller.renderer._rectangle[0], 2 * 64 / 800 - 1)
        self.assertEqual(controller.renderer._uniforms[1][2], 0.5)
        self.assertTrue(controller.configure(opacity=0.4))
        self.assertAlmostEqual(controller.renderer._uniforms[1][2], 0.2)
        fiber.primitive_state["_visible"] = False
        controller.frame()
        control.GetSize.return_value = (0, 0)
        fiber.primitive_state["_layout_applied"] = (160, 90, 20, 40, 1)
        primitive.apply_layout(host, node)
        primitive._frame(fiber, 0.0)
        self.assertTrue(controller.renderer.ready)
        self.assertAlmostEqual(controller.renderer._rectangle[0], 2 * 74 / 800 - 1)
        control.SetVisible.assert_called_with(False)
        control.GetSize.assert_not_called()
        controller.renderer.doll.RenderEntity.assert_called_once()
        fiber.primitive_state["_visible"] = True
        controller.frame()
        control.SetVisible.assert_called_with(True)

    def test_style_changes_cannot_reveal_failed_image(self):
        controller = self.mounted()
        visible = [True]
        controller.renderer._visibility_source = lambda: visible[0]
        self.actor.SetEntityUIExtraUniforms.return_value = False
        self.assertFalse(controller.configure(rotation=0.4))
        visible[0] = False
        controller.frame()
        visible[0] = True
        controller.renderer.control.SetVisible(True)
        controller.frame()
        controller.renderer.control.SetVisible.assert_called_with(False)

    def test_sdk_exception_stops_wave_hides_and_never_retries_implicitly(self):
        controller = self.mounted(effect="wave")
        controller.play()
        self.actor.SetEntityUIExtraUniforms.side_effect = RuntimeError("device upload failed")
        self.clock[0] = 0.25
        with patch.object(self.renderer_module.traceback, "print_exc") as report:
            controller.frame()
            self.assertTrue(report.called)
        self.assertFalse(controller.playing)
        self.assertFalse(controller.visible)
        self.assertIn("device upload failed", controller.error)
        controller.renderer.control.SetVisible.assert_called_with(False)
        self.actor.reset_mock()
        for _ in range(5):
            controller.frame()
        self.actor.SetEntityUIExtraUniforms.assert_not_called()
        self.actor.SetEntityUIExtraUniforms.side_effect = None
        self.assertTrue(controller.retry())

    def test_dispose_after_native_control_removed_always_releases_slot_and_callback(self):
        controller, primitive, host, fiber, control = self.primitive_mount()
        primitive.apply_layout(host, types.SimpleNamespace(fiber=fiber, inherited_opacity=1.0))
        primitive._frame(fiber, 0.0)
        control.SetVisible.side_effect = RuntimeError("native control removed")
        self.actor.SetEntityUIExtraUniforms.side_effect = RuntimeError("renderer removed")
        with patch.object(self.renderer_module.traceback, "print_exc") as report:
            self.assertTrue(controller.dispose())
            self.assertTrue(report.called)
        host.pyreact_unregister_animation_frame.assert_called_once()
        self.assertEqual(self.renderer_module._SLOT_OWNERS, [None] * 4)
        self.assertEqual(fiber.primitive_state, {})
        self.assertTrue(controller.disposed)

    def test_dispose_does_not_notify_reentrant_observer_during_teardown(self):
        controller = self.mounted()
        callback = Mock(side_effect=controller.dispose)
        controller.subscribe(callback)
        self.assertTrue(controller.dispose())
        callback.assert_not_called()
        self.assertTrue(controller.disposed)
        self.assertEqual(self.renderer_module._SLOT_OWNERS, [None] * 4)

    def test_unmount_and_dispose_unregister_callback_release_slot_and_support_remount(self):
        callback = Mock()
        controller, primitive, host, fiber, control = self.primitive_mount(callback=callback)
        node = types.SimpleNamespace(fiber=fiber, inherited_opacity=1.0)
        primitive.apply_layout(host, node)
        primitive._frame(fiber, 0.0)
        callback.assert_called_once_with(controller)
        controller.play()
        primitive.unmount(host, fiber)
        host.pyreact_unregister_animation_frame.assert_called_once()
        self.assertIsNone(controller.renderer.slot)
        self.assertFalse(controller.playing)
        control.SetVisible.assert_called_with(False)
        self.assertEqual(fiber.primitive_state, {})
        primitive.apply_props(host, fiber, self.control(), None, {"controller": controller})
        primitive.apply_layout(host, node)
        primitive._frame(fiber, 0.0)
        self.assertTrue(controller.visible)
        controller.dispose()
        self.assertEqual(host.pyreact_unregister_animation_frame.call_count, 2)
        primitive.unmount(host, fiber)
        self.assertEqual(host.pyreact_unregister_animation_frame.call_count, 2)
        self.assertEqual(self.renderer_module._SLOT_OWNERS, [None] * 4)
        self.assertFalse(controller.configure(rotation=1))
        with self.assertRaises(RuntimeError):
            controller.mount(self.control())

    def test_configuration_before_mount_and_reset_restore_constructor_defaults(self):
        controller = self.controller(src="prism", scale=(2, 1), effect="swirl")
        controller.configure(src="sunrise", rotation=1.2)
        self.actor.SetEntityUIExtraUniforms.assert_not_called()
        controller.seek(2.5)
        controller.reset()
        state = controller.snapshot()
        self.assertEqual(state["config"]["src"], "prism")
        self.assertEqual(state["config"]["scale"], (2, 1))
        self.assertEqual(state["config"]["rotation"], 0)
        self.assertEqual(state["time"], 0)
        self.assertFalse(state["playing"])
        state["config"]["rotation"] = 5
        self.assertEqual(controller.snapshot()["config"]["rotation"], 0)

    def test_subscriber_tokens_are_independent_and_unsubscribe_is_idempotent(self):
        controller = self.controller()
        callback = Mock()
        first = controller.subscribe(callback)
        second = controller.subscribe(callback)
        first()
        first()
        controller.configure(rotation=1)
        callback.assert_called_once()
        second()
        controller.configure(rotation=2)
        callback.assert_called_once()
        self.assertFalse(self.images.ShaderImage.props_affect_layout(
            {"controller": controller, "onReady": Mock()},
            {"controller": controller, "onReady": Mock()}, None))


if __name__ == "__main__":
    unittest.main()
