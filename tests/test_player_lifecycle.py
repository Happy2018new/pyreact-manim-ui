"""Exercise player failure/recovery through a small, stateful SDK boundary.

These are host-side behavior checks, not proof of native UI or shader behavior.
The actual player and timeline files are loaded without importing the Py2 UI
framework; mocks are limited to the external SDK, navigation and clock.
"""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


RUNTIME = Path(__file__).resolve().parents[1] / "behavior_pack/manim_ui"
PACKAGE = "_manim_player_under_test"
SCENES = [
    {"name": "first", "title": "First", "duration": 4.0,
     "post_name": "first_post", "material": "first_material", "texture": "first_texture"},
    {"name": "second", "title": "Second", "duration": 9.0,
     "post_name": "second_post", "material": "second_material", "texture": "second_texture"},
]


class FakePostProcess:
    def __init__(self):
        self.installed = {}
        self.enabled = set()
        self.fail_install = set()
        self.fail_enable = set()
        self.fail_parameter = False
        self.parameters = {}

    def GetPostProcessOrder(self):
        return list(self.installed)

    def AddPostProcess(self, definition):
        name = definition["name"]
        if name in self.fail_install:
            return False
        self.installed[name] = definition
        # The public SDK starts a process when adding it.
        self.enabled.add(name)
        return True

    def SetEnableByName(self, name, enabled):
        if name not in self.installed or (enabled and name in self.fail_enable):
            return False
        if enabled:
            self.enabled.add(name)
        else:
            self.enabled.discard(name)
        return True

    def SetParameter(self, name, parameter, value):
        if name not in self.installed or self.fail_parameter:
            return False
        self.parameters[(name, parameter)] = tuple(value)
        return True


class FakeClientSystem:
    def __init__(self, namespace, system_name):
        self.registered = []
        self.unregistered = []

    def ListenForEvent(self, *registration):
        self.registered.append(registration)

    def UnListenForEvent(self, *registration):
        self.unregistered.append(registration)


class PlayerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.post = FakePostProcess()
        self.now = 100.0
        # JSON UI dimensions can be scaled logical coordinates. Shader pixel
        # parameters must use the physical viewport, including after a resize.
        self.logical_screen_size = (640, 360)
        self.physical_viewport = (1920, 1080)
        self.game = types.SimpleNamespace(
            GetScreenSize=Mock(side_effect=lambda: self.logical_screen_size),
            GetScreenViewInfo=Mock(side_effect=lambda: self.physical_viewport + (0, 0)),
        )
        factory = types.SimpleNamespace(
            CreatePostProcess=lambda _level: self.post,
            CreateGame=lambda _level: self.game,
        )
        api = types.ModuleType("mod.client.extraClientApi")
        api.GetClientSystemCls = lambda: FakeClientSystem
        api.GetEngineCompFactory = lambda: factory
        api.GetLevelId = lambda: "test_level"
        api.GetEngineNamespace = lambda: "engine"
        api.GetEngineSystemName = lambda: "system"
        api.GetPlatform = lambda: 0
        api.GetMinecraftEnum = lambda: types.SimpleNamespace(
            KeyBoardType=types.SimpleNamespace(KEY_F8=119))
        self.top_ui = "hud_screen"
        api.GetTopUI = lambda: self.top_ui
        mod = types.ModuleType("mod")
        mod.__path__ = []
        mod_client = types.ModuleType("mod.client")
        mod_client.__path__ = []
        mod.client = mod_client
        mod_client.extraClientApi = api
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(RUNTIME)]
        generated = types.ModuleType(PACKAGE + ".generated_scenes")
        generated.SCENES = SCENES
        pyreact = types.ModuleType(PACKAGE + ".pyreact")
        pyreact.runtime_init = lambda _player, debug=False: None
        self.pyreact = pyreact
        self.navigation_error = None
        self.navigation_pages = set()
        self.navigation_pushes = []
        pyreact.navigator = types.SimpleNamespace(
            is_ready=True, is_transitioning=False,
            contains=self.navigation_pages.__contains__, push=self._push_navigation,
        )
        panel = types.ModuleType(PACKAGE + ".panel")
        panel.PlayerPanel = lambda **props: props
        modules = {
            "mod": mod, "mod.client": mod_client, "mod.client.extraClientApi": api,
            PACKAGE: package, PACKAGE + ".generated_scenes": generated,
            PACKAGE + ".pyreact": pyreact, PACKAGE + ".panel": panel,
        }
        patcher = patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._load("timeline")
        self.module = self._load("client")
        self.module.get_playback_clock = lambda platform=None: lambda: self.now
        self.player = self.module.ManimClient("tests", "player")

    def _load(self, name):
        spec = importlib.util.spec_from_file_location(PACKAGE + "." + name, RUNTIME / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def _push_navigation(self, element, key=None, on_error=None, **kwargs):
        self.navigation_pushes.append(key)
        if self.navigation_error is not None:
            on_error(self.navigation_error)
            return False
        self.navigation_pages.add(key)
        return True

    def test_failed_scene_install_preserves_a_recoverable_scene_and_duration(self):
        self.assertTrue(self.player.select_scene(0))
        self.player.toggle_play()
        self.now += 1.0
        self.player.on_frame()
        self.post.fail_install.add("second_post")

        self.assertFalse(self.player.select_scene(1))
        state = self.player.snapshot()
        self.assertEqual((state["scene"], state["duration"]), ("first", 4.0))
        self.assertAlmostEqual(state["position"], 1.0)
        self.assertFalse(state["playing"])
        self.assertFalse(state["visible"])
        self.assertIn("second", state["error"])

        # A later Play must resume the still-selected scene, never send its
        # timeline to the failed scene's shader.
        self.player.toggle_play()
        self.now += 0.5
        self.player.on_frame()
        self.assertEqual(self.post.enabled, {"first_post"})
        self.assertAlmostEqual(self.post.parameters[("first_post", "playback")][0], 1.5)
        self.assertNotIn(("second_post", "playback"), self.post.parameters)

    def test_failed_enable_does_not_start_an_invisible_animation(self):
        self.player.select_scene(0)
        self.player.hide()
        self.post.fail_enable.add("first_post")
        self.player.toggle_play()
        self.now += 10
        self.player.on_frame()
        state = self.player.snapshot()
        self.assertFalse(state["visible"])
        self.assertFalse(state["playing"])
        self.assertEqual(state["position"], 0.0)
        self.assertTrue(state["error"])
        self.assertEqual(self.post.enabled, set())

    def test_seek_pauses_and_keeps_the_requested_frame_until_resumed(self):
        self.player.select_scene(0)
        self.player.toggle_play()
        self.now += 0.25
        self.player.seek(2.5)
        self.now += 30
        self.player.on_frame()
        state = self.player.snapshot()
        self.assertFalse(state["playing"])
        self.assertEqual(state["position"], 2.5)
        self.assertEqual(self.post.parameters[("first_post", "playback")][0], 2.5)

        self.player.toggle_play()
        self.now += 0.5
        self.player.on_frame()
        self.assertEqual(self.player.snapshot()["position"], 3.0)

    def test_parameter_failure_stops_playback_and_disables_the_process(self):
        self.player.select_scene(0)
        self.player.toggle_play()
        self.post.fail_parameter = True
        self.now += 0.5
        self.player.on_frame()
        state = self.player.snapshot()
        self.assertFalse(state["visible"])
        self.assertFalse(state["playing"])
        self.assertTrue(state["error"])
        self.assertEqual(self.post.enabled, set())

    def test_navigation_failure_does_not_leave_a_canvas_without_controls(self):
        self.navigation_error = RuntimeError("native mount failed")
        self.player.on_ui_ready()
        state = self.player.snapshot()
        self.assertFalse(state["visible"])
        self.assertEqual(self.post.enabled, set())
        self.assertIn("native mount failed", state["error"])

    def test_reopen_preserves_selected_scene_and_paused_position(self):
        self.player.on_ui_ready()
        self.player.select_scene(1)
        self.player.seek(3.5)
        self.player.hide()  # The panel cleanup after Esc.
        self.navigation_pages.clear()
        self.now += 100

        self.player.on_key({"key": "119", "isDown": "0", "screenName": "hud_screen"})
        self.assertEqual(len(self.navigation_pushes), 2)
        state = self.player.snapshot()
        self.assertEqual((state["scene"], state["position"]), ("second", 3.5))
        self.assertFalse(state["playing"])

    def test_reopen_does_not_duplicate_existing_or_pending_navigation(self):
        event = {"key": "119", "isDown": "0", "screenName": "hud_screen"}
        self.player.on_ui_ready()
        self.player.on_key(event)
        self.player.on_ui_ready()  # UI rebuild preserves the restored page.
        self.assertEqual(len(self.navigation_pushes), 1)

        self.navigation_pages.clear()
        self.pyreact.navigator.is_transitioning = True
        self.player.on_key(event)
        self.assertEqual(len(self.navigation_pushes), 1)
        self.pyreact.navigator.is_transitioning = False
        self.pyreact.navigator.is_ready = False
        self.player.on_key(event)
        self.assertEqual(len(self.navigation_pushes), 1)

    def test_reopen_only_responds_to_f8_release_from_the_uncovered_hud(self):
        for event in (
            {"key": "119", "isDown": "1", "screenName": "hud_screen"},
            {"key": "118", "isDown": "0", "screenName": "hud_screen"},
            {"key": "119", "isDown": "0", "screenName": "netease_chat_screen"},
            {},
        ):
            self.player.on_key(event)
        self.assertEqual(self.navigation_pushes, [])
        self.top_ui = "inventory_screen"
        self.player.on_key({"key": "119", "isDown": "0", "screenName": "hud_screen"})
        self.assertEqual(self.navigation_pushes, [])

    def test_shader_viewport_uses_physical_pixels_at_mount_and_after_resize(self):
        self.player.on_ui_ready()
        self.assertEqual(self.player.viewport, self.physical_viewport)
        self.assertNotEqual(self.player.viewport, self.logical_screen_size)
        expected_height = 1080 * (360 - 170) / 360
        self.assertAlmostEqual(self.post.parameters[("first_post", "playback")][2], expected_height)
        options = self.post.parameters[("first_post", "options")]
        self.assertAlmostEqual(options[1] * 360, 55)
        self.assertAlmostEqual((1 - options[1] - options[2]) * 360, 115)

        self.logical_screen_size = (480, 360)
        self.physical_viewport = (1440, 1080)
        self.player.on_resize({})
        self.player.on_frame()
        self.assertEqual(self.player.viewport, self.physical_viewport)
        self.assertNotEqual(self.player.viewport, self.logical_screen_size)
        playback = self.post.parameters[("first_post", "playback")]
        self.assertAlmostEqual(playback[1], 1440 / expected_height)
        self.assertAlmostEqual(playback[2], expected_height)

    def test_tiny_logical_screen_keeps_a_positive_canvas_and_resizes_its_margins(self):
        self.logical_screen_size = (320, 180)
        self.physical_viewport = (640, 360)
        self.player.on_ui_ready()
        playback = self.post.parameters[("first_post", "playback")]
        options = self.post.parameters[("first_post", "options")]
        self.assertAlmostEqual(options[2], 0.35)
        self.assertAlmostEqual(playback[2], 360 * 0.35)
        self.assertAlmostEqual(playback[1], 640 / (360 * 0.35))
        self.assertAlmostEqual(options[1] / (1 - options[1] - options[2]), 55 / 115)
        self.assertAlmostEqual(self.player.snapshot()["ui_scale"], 180 * 0.65 / 170)

        self.logical_screen_size = (640, 360)
        self.player.on_resize({})
        self.player.on_frame()
        options = self.post.parameters[("first_post", "options")]
        self.assertAlmostEqual(options[1], 55 / 360)
        self.assertAlmostEqual(options[2], 190 / 360)
        self.assertEqual(self.player.snapshot()["ui_scale"], 1)

    def test_resize_waits_for_new_physical_size_and_coalesces_event_bursts(self):
        self.logical_screen_size = (320, 180)
        self.physical_viewport = (640, 360)
        self.player.on_ui_ready()
        old_reads = self.game.GetScreenViewInfo.call_count
        old_logical_reads = self.game.GetScreenSize.call_count

        # Native APIs still expose the previous dimensions inside this event.
        event = {"beforeX": 320, "beforeY": 180, "afterX": 640, "afterY": 360}
        self.player.on_resize(event)
        self.player.on_resize(event)
        # Synchronous control updates in the same event turn are not a native
        # render tick and must not consume the pending viewport refresh.
        self.player.seek(0.5)
        self.player.show()
        self.assertEqual(self.game.GetScreenViewInfo.call_count, old_reads)
        self.assertEqual(self.game.GetScreenSize.call_count, old_logical_reads)
        self.assertEqual(self.player.viewport, (640, 360))

        self.logical_screen_size = (640, 360)
        self.physical_viewport = (1280, 720)
        self.player.on_frame()
        self.assertEqual(self.player.viewport, (1280, 720))
        self.assertEqual(self.game.GetScreenViewInfo.call_count, old_reads + 1)
        self.assertEqual(self.game.GetScreenSize.call_count, old_logical_reads + 1)
        playback = self.post.parameters[("first_post", "playback")]
        self.assertAlmostEqual(playback[2], 720 * 190 / 360)
        self.assertAlmostEqual(playback[1], 1280 / playback[2])
        for _ in range(5):
            self.player.on_frame()
        self.assertEqual(self.game.GetScreenViewInfo.call_count, old_reads + 1)
        self.assertEqual(self.game.GetScreenSize.call_count, old_logical_reads + 1)

    def test_resize_refreshes_while_closed_and_reopen_uses_the_new_viewport(self):
        self.player.on_ui_ready()
        self.player.hide()
        self.navigation_pages.clear()
        previous_parameters = dict(self.post.parameters)
        old_reads = self.game.GetScreenViewInfo.call_count
        self.player.on_resize({})
        self.physical_viewport = (640, 360)
        self.logical_screen_size = (320, 180)
        self.player.on_frame()
        self.assertFalse(self.player.visible)
        self.assertEqual(self.player.viewport, (640, 360))
        self.assertEqual(self.game.GetScreenViewInfo.call_count, old_reads + 1)
        self.assertEqual(self.post.parameters, previous_parameters)
        self.assertEqual(self.post.enabled, set())

        self.player.show()
        playback = self.post.parameters[("first_post", "playback")]
        self.assertAlmostEqual(playback[2], 360 * 0.35)
        self.assertAlmostEqual(playback[1], 640 / (360 * 0.35))
        self.assertEqual(self.game.GetScreenViewInfo.call_count, old_reads + 1)

    def test_orientation_change_is_uploaded_while_the_timeline_is_paused(self):
        self.player.on_ui_ready()
        self.player.flip_y = False
        self.player.on_frame()
        self.assertEqual(self.post.parameters[("first_post", "options")][0], 0)

    def test_panel_remount_restores_canvas_and_replaces_its_subscription(self):
        # Run the actual component's effect; the harness only substitutes
        # framework construction and schedules mount/cleanup in lifecycle order.
        effects = []
        state_updates = []

        def use_state(initial):
            updates = []
            state_updates.append(updates)
            return initial, updates.append

        self.pyreact.Component = lambda component: component
        self.pyreact.use_state = use_state
        self.pyreact.use_effect = lambda effect, _deps: effects.append(effect)
        self.pyreact.Color = lambda *channels: channels
        for name in ("Panel", "Label", "Button", "Slider", "Style"):
            setattr(self.pyreact, name, lambda **props: props)
        self.pyreact.AlignItems = types.SimpleNamespace(center="center")
        self.pyreact.FlexDirection = types.SimpleNamespace(row="row")
        self.pyreact.FlexWrap = types.SimpleNamespace(wrap="wrap")
        self.pyreact.JustifyContent = types.SimpleNamespace(center="center")
        self.pyreact.Position = types.SimpleNamespace(absolute="absolute")
        panel = self._load("panel")
        self.player.select_scene(0)
        self.player.seek(1.5)

        panel.PlayerPanel(player=self.player)
        disconnect = effects[-1]()
        self.assertTrue(state_updates[0][-1]["visible"])
        disconnect()
        self.assertFalse(self.player.snapshot()["visible"])
        old_update_count = len(state_updates[0])

        panel.PlayerPanel(player=self.player)
        replacement_disconnect = effects[-1]()
        self.assertTrue(self.player.snapshot()["visible"])
        self.assertEqual(state_updates[1][-1]["position"], 1.5)
        replacement_update_count = len(state_updates[1])
        self.player.notify()
        self.assertEqual(len(state_updates[0]), old_update_count)
        self.assertEqual(len(state_updates[1]), replacement_update_count + 1)
        replacement_disconnect()

    def test_destroy_stops_effect_unsubscribes_events_and_drops_observers(self):
        self.player.select_scene(0)
        self.player.toggle_play()
        received = []
        unsubscribe = self.player.subscribe(received.append)
        self.player.notify()
        self.assertEqual(len(received), 1)
        registered = list(self.player.registered)

        self.player.Destroy()
        self.assertFalse(self.player.snapshot()["playing"])
        self.assertFalse(self.player.snapshot()["visible"])
        self.assertEqual(self.post.enabled, set())
        self.assertCountEqual(self.player.unregistered, registered)
        self.player.notify()
        unsubscribe()  # Late component cleanup remains safe after system teardown.
        self.assertEqual(len(received), 1)


if __name__ == "__main__":
    unittest.main()
