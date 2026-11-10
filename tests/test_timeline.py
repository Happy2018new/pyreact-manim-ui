"""Behavioral playback tests use the same Python-2-compatible runtime file."""
import importlib.util
from pathlib import Path
import unittest
import types

PATH = Path(__file__).resolve().parents[1] / "behavior_pack/manim_ui/timeline.py"
SPEC = importlib.util.spec_from_file_location("manim_timeline", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
Timeline = MODULE.Timeline


class PlaybackClockTests(unittest.TestCase):
    def test_python_three_uses_elapsed_counter_instead_of_system_time(self):
        elapsed = [100.0]
        fake_time = types.SimpleNamespace(
            perf_counter=lambda: elapsed[0], time=lambda: float("nan"))
        clock = MODULE.get_playback_clock(fake_time, -1)
        timeline = Timeline(4)
        timeline.play(clock())
        elapsed[0] += 1.5
        self.assertEqual(timeline.sample(clock()), 1.5)

    def test_python_two_windows_uses_qpc_clock(self):
        fake_time = types.SimpleNamespace(clock=lambda: 123.0, time=lambda: -1000.0)
        self.assertIs(MODULE.get_playback_clock(fake_time, 0), fake_time.clock)

    def test_python_two_unix_cpu_clock_is_not_treated_as_elapsed_time(self):
        fake_time = types.SimpleNamespace(clock=lambda: 123.0, time=lambda: 1000.0)
        with self.assertRaises(RuntimeError):
            MODULE.get_playback_clock(fake_time, -1)


class TimelineTests(unittest.TestCase):
    def test_pause_does_not_include_time_spent_paused(self):
        timeline = Timeline(4)
        timeline.play(10)
        timeline.pause(11)
        self.assertEqual(timeline.sample(100), 1)
        timeline.play(100)
        self.assertEqual(timeline.sample(101), 2)

    def test_seek_during_play_preserves_new_anchor(self):
        timeline = Timeline(4)
        timeline.play(10)
        timeline.seek(2, 11)
        self.assertEqual(timeline.sample(11.5), 2.5)

    def test_end_stops_and_replay_restarts(self):
        timeline = Timeline(2)
        timeline.play(10)
        self.assertEqual(timeline.sample(15), 2)
        self.assertFalse(timeline.playing)
        timeline.play(20)
        self.assertEqual(timeline.sample(20.5), 0.5)

    def test_speed_change_keeps_current_position(self):
        timeline = Timeline(4)
        timeline.play(10)
        timeline.set_speed(0.5, 11)
        self.assertEqual(timeline.sample(13), 2)

    def test_invalid_times_rejected_and_seek_clamped(self):
        with self.assertRaises(ValueError):
            Timeline(float("nan"))
        timeline = Timeline(4)
        self.assertEqual(timeline.seek(-10, 0), 0)
        self.assertEqual(timeline.seek(100, 0), 4)
        with self.assertRaises(ValueError):
            timeline.seek(float("inf"), 0)


if __name__ == "__main__":
    unittest.main()
