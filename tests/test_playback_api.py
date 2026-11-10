"""Business playback behavior against a renderer contract without ModSDK."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


RUNTIME = Path(__file__).resolve().parents[1] / "behavior_pack/manim_ui"
PACKAGE = "_manim_api_under_test"
SCENES = [
    {"name": "glyphs", "title": "Text", "duration": 4.0},
    {"name": "formula", "title": "Formula", "duration": 9.0},
]


class Renderer:
    def __init__(self, clock):
        self.clock = clock
        self.installed = set()
        self.visible = set()
        self.install_calls = []
        self.drawn = []
        self.fail_install = set()
        self.fail_enable = False
        self.fail_draw = False
        self.releases = 0

    def install_scene(self, scene):
        name = scene["name"]
        self.install_calls.append(name)
        reused = name in self.installed
        self.clock[0] += 0.02 if reused else 0.3
        if name in self.fail_install:
            return False, reused
        self.installed.add(name)
        return True, reused

    def set_scene_visible(self, scene, enabled):
        name = scene["name"]
        if enabled:
            if self.fail_enable:
                return False
            self.visible.add(name)
        else:
            self.visible.discard(name)
        return True

    def render_scene(self, scene, position):
        self.drawn.append((scene["name"], position))
        self.clock[0] += 0.01
        return not self.fail_draw

    def release_scenes(self):
        self.releases += 1
        self.visible.clear()


class PlaybackApiTests(unittest.TestCase):
    def setUp(self):
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(RUNTIME)]
        patcher = patch.dict(sys.modules, {PACKAGE: package})
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location(PACKAGE + ".playback", RUNTIME / "playback.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.clock = [10.0]
        self.renderer = Renderer(self.clock)
        self.player = self.module.PlaybackController(SCENES, self.renderer, lambda: self.clock[0])

    def test_name_selection_has_no_eager_installs_or_demo_index_requirement(self):
        self.assertEqual(self.player.scene_names(), ("glyphs", "formula"))
        self.assertEqual(self.renderer.install_calls, [])
        self.assertTrue(self.player.load("formula"))
        self.assertEqual(self.renderer.install_calls, ["formula"])
        self.assertEqual(self.player.snapshot()["scene"], "formula")
        self.assertEqual(self.player.snapshot()["duration"], 9.0)
        self.assertEqual(self.renderer.visible, {"formula"})
        self.assertFalse(self.player.snapshot()["playing"])

    def test_play_pause_seek_replay_stop_and_resume(self):
        self.assertTrue(self.player.play("glyphs"))
        started = self.clock[0]
        self.clock[0] += 1.0
        self.assertTrue(self.player.play("glyphs"))  # Idempotent, no new anchor.
        self.assertEqual(self.renderer.install_calls, ["glyphs"])
        self.clock[0] = started + 1.5
        self.assertTrue(self.player.pause())
        self.assertAlmostEqual(self.player.snapshot()["position"], 1.5)
        self.assertEqual(self.renderer.drawn[-1], ("glyphs", 1.5))
        self.assertTrue(self.player.pause())
        self.clock[0] += 50
        self.player.frame()
        self.assertEqual(self.player.snapshot()["position"], 1.5)

        self.assertTrue(self.player.seek(2.5))
        self.assertFalse(self.player.snapshot()["playing"])
        self.assertTrue(self.player.replay())
        self.assertEqual(self.player.snapshot()["position"], 0)
        self.assertTrue(self.player.snapshot()["playing"])
        self.assertTrue(self.player.stop())
        self.assertEqual(self.player.snapshot()["position"], 0)
        self.assertFalse(self.player.snapshot()["playing"])
        self.assertFalse(self.player.snapshot()["visible"])
        self.assertEqual(self.renderer.visible, set())
        self.assertTrue(self.player.stop())
        self.assertTrue(self.player.play())
        self.assertEqual(self.renderer.install_calls, ["glyphs"])

    def test_switch_and_reuse_timing_separate_install_cost_from_total_api_time(self):
        self.player.load("glyphs")
        self.player.load("formula")
        self.player.load("glyphs")
        records = self.player.load_timings()
        self.assertEqual([r["operation"] for r in records], ["first_install", "switch_install", "reuse"])
        self.assertEqual([r["reused"] for r in records], [False, False, True])
        self.assertEqual([r["previous_scene"] for r in records], ["", "glyphs", "formula"])
        for record, expected in zip(records, (0.3, 0.3, 0.02)):
            self.assertTrue(record["success"])
            self.assertAlmostEqual(record["install_seconds"], expected)
            self.assertAlmostEqual(record["total_seconds"], expected + 0.01)
        records[0]["scene"] = "mutated"
        self.assertEqual(self.player.load_timings()[0]["scene"], "glyphs")
        state = self.player.snapshot()
        state["last_load"]["success"] = False
        self.assertTrue(self.player.snapshot()["last_load"]["success"])
        for _ in range(40):
            self.player.load("glyphs")
        self.assertEqual(len(self.player.load_timings()), 32)

    def test_failed_install_keeps_previous_timeline_and_reports_failed_load(self):
        self.player.play("glyphs")
        self.player.seek(1.75)
        self.renderer.fail_install.add("formula")
        self.assertFalse(self.player.play("formula"))
        state = self.player.snapshot()
        self.assertEqual((state["scene"], state["position"]), ("glyphs", 1.75))
        self.assertFalse(state["visible"])
        self.assertFalse(state["playing"])
        self.assertFalse(state["last_load"]["success"])
        self.assertIn("formula", state["error"])
        self.assertTrue(self.player.play())
        self.assertEqual(self.player.snapshot()["error"], "")
        self.assertEqual(self.renderer.visible, {"glyphs"})

    def test_failed_initial_install_does_not_create_a_timeline(self):
        self.renderer.fail_install.add("glyphs")
        self.assertFalse(self.player.load("glyphs"))
        self.assertIsNone(self.player.timeline)
        self.assertFalse(self.player.snapshot()["last_load"]["success"])
        self.renderer.fail_install.clear()
        self.assertTrue(self.player.play("glyphs"))

    def test_enable_and_parameter_failure_do_not_report_a_successful_load(self):
        self.renderer.fail_enable = True
        self.assertFalse(self.player.load("glyphs"))
        self.assertFalse(self.player.snapshot()["last_load"]["success"])
        self.renderer.fail_enable = False
        self.renderer.fail_draw = True
        self.assertFalse(self.player.load("glyphs"))
        state = self.player.snapshot()
        self.assertFalse(state["playing"])
        self.assertFalse(state["visible"])
        self.assertEqual(self.renderer.visible, set())
        self.assertIn("parameter", state["error"])
        self.renderer.fail_draw = False
        self.assertTrue(self.player.play())

    def test_unknown_name_does_not_replace_or_hide_the_current_scene(self):
        self.player.play("formula")
        self.assertFalse(self.player.play("missing"))
        self.assertEqual(self.player.snapshot()["scene"], "formula")
        self.assertTrue(self.player.snapshot()["playing"])
        self.assertEqual(self.renderer.visible, {"formula"})
        self.assertEqual(self.renderer.install_calls, ["formula"])

    def test_dispose_is_terminal_and_cleans_observers_and_renderer_once(self):
        self.player.play("glyphs")
        received = []
        unsubscribe = self.player.subscribe(received.append)
        self.player.notify()
        self.assertTrue(self.player.dispose())
        self.assertFalse(self.player.dispose())
        self.assertEqual(self.renderer.releases, 1)
        self.assertEqual(self.renderer.visible, set())
        self.assertTrue(self.player.snapshot()["disposed"])
        for action in (self.player.play, self.player.pause, self.player.replay,
                       self.player.stop, self.player.show, self.player.hide):
            self.assertFalse(action())
        self.assertFalse(self.player.load("formula"))
        self.assertFalse(self.player.seek(1))
        self.player.frame()
        self.player.notify()
        unsubscribe()
        unsubscribe()
        late_unsubscribe = self.player.subscribe(received.append)
        late_unsubscribe()
        self.assertEqual(len(received), 1)
        self.assertEqual(self.player._subscribers, [])

    def test_duplicate_callback_subscriptions_have_independent_lifetimes(self):
        received = []
        first = self.player.subscribe(received.append)
        second = self.player.subscribe(received.append)
        self.player.notify()
        self.assertEqual(len(received), 2)
        second()
        second()
        self.player.notify()
        self.assertEqual(len(received), 3)
        first()
        self.player.notify()
        self.assertEqual(len(received), 3)

    def test_observer_failure_does_not_block_other_subscribers(self):
        def failing(_state):
            raise RuntimeError("observer failed")
        received = []
        self.player.subscribe(failing)
        self.player.subscribe(received.append)
        with patch.object(self.module.traceback, "print_exc") as report:
            self.player.notify()
        report.assert_called_once()
        self.assertEqual(len(received), 1)

    def test_seek_rejects_nonfinite_input_before_pausing_a_running_scene(self):
        self.player.play("glyphs")
        with self.assertRaises(ValueError):
            self.player.seek(float("nan"))
        self.assertTrue(self.player.snapshot()["playing"])

    def test_empty_scene_set_and_duplicate_names_are_explicit(self):
        empty = self.module.PlaybackController([], self.renderer, lambda: self.clock[0])
        self.assertEqual(empty.scene_names(), ())
        self.assertFalse(empty.play())
        self.assertFalse(empty.load("missing"))
        with self.assertRaises(ValueError):
            self.module.PlaybackController([SCENES[0], SCENES[0]], self.renderer, lambda: 0)


if __name__ == "__main__":
    unittest.main()
