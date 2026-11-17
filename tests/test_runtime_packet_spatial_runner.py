"""Run the spatial case controller against a fake owned host, without Minecraft."""
from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools/runtime_packet_probe"
sys.path.insert(0, str(PROBE))
from atlas2d_assets import atlas2d_config
from verify_spatial import expected_words


def load_runner():
    spec = importlib.util.spec_from_file_location("_spatial_case_runner_test", PROBE / "run_spatial_case.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeAggregation:
    def __init__(self):
        self.config = atlas2d_config(8, screen_size=(240, 90), display_rect=(0, 0, 1, 1), display_count=3)
        self.words = expected_words(12345, 8)
        self.query = list(self.config["query"])
        self.writes, self.selections = [], []
        self.enabled, self.ready, self.error = True, True, None

    def write(self, seed):
        self.writes.append(seed)
        self.words = expected_words(seed, 8)

    def select(self, start, count, word_shift):
        self.selections.append((start, count, word_shift))
        self.query = [8., float(start), float(count), float(word_shift)]

    def snapshot(self):
        return copy.deepcopy({
            "transport": "atlas2d", "shader_mode": "shared", "screen_size": [240, 90],
            "target_pixels": self.config["target_pixels"], "ready": self.ready,
            "enabled": self.enabled, "error": self.error, "gpu_verified": False,
            "aggregate": {"pages": 8, "words": self.words, "words_per_page": 8,
                          "query": self.query, "layout": self.config["layout"],
                          "display_rect_norm": [0, 0, 1, 1]}})


class FakeProbe:
    def __init__(self, scenario="complete"):
        self.aggregation = FakeAggregation()
        self.run, self.last_run = None, None
        self.scenario, self.polls, self.starts, self.aborts = scenario, 0, [], []

    def start_aggregate(self, seconds, dynamic, seed):
        if self.run is not None:
            raise RuntimeError("Benchmark already running")
        self.starts.append((seconds, dynamic, seed))
        self.run = {"seed": seed, "frames": 0, "dynamic": dynamic}
        return {"started": True}

    def snapshot(self):
        if self.run is not None and self.starts:
            self.polls += 1
            if self.scenario != "timeout" and self.polls >= 2:
                run = self.run
                if run["dynamic"]:
                    self.aggregation.write(run["seed"] + 7 * 97)
                self.last_run = {"success": self.scenario != "benchmark_failure", "frames": 7,
                                 "spatial_case_token": run.get("spatial_case_token"),
                                 "status": "completed" if self.scenario != "benchmark_failure" else "failed",
                                 "error": "injected upload failure" if self.scenario == "benchmark_failure" else None}
                self.run = None
        return {"running": self.run is not None, "last_run": self.last_run,
                "aggregation": self.aggregation.snapshot()}

    def _finish_run(self, status, error=None):
        self.aborts.append((status, error))
        self.last_run = {"success": False, "status": status, "error": error}
        self.run = None


class FakeHost:
    def __init__(self, evidence, probe, corruption=False, seed_mismatch=False):
        self.evidence, self.probe = evidence, probe
        self.corruption, self.seed_mismatch = corruption, seed_mismatch
        self.calls, self.captures, self.sleeps, self.clock = [], [], [], 0.
        self.process_timeouts = []
        self.hide_crosshair_calls = []

    def HideCrossHairGUI(self, hidden):
        self.hide_crosshair_calls.append(hidden)
        if self.probe.scenario == "hide_rejected":
            return False
        if self.probe.scenario == "hide_truthy_non_bool":
            return 1
        return True

    def monotonic(self):
        self.clock += 2.
        return self.clock

    def subprocess(self, command, **options):
        action = command[command.index("--project") - 1]
        label = command[command.index("--label") + 1]
        self.calls.append((action, label))
        self.process_timeouts.append(options.get("timeout"))
        if action == "call":
            code = Path(command[command.index("--code") + 1]).read_text(encoding="utf-8")
            namespace = {"json": json, "probe": self.probe, "api": self}
            try:
                exec(code, namespace)
            except (RuntimeError, ValueError) as error:
                raise subprocess.CalledProcessError(1, command, stderr=str(error)) from error
            result = json.loads(namespace["_result"])
            if self.probe.scenario == "foreign_run" and "_start" in label:
                self.probe.run = {"spatial_case_token": "foreign_case", "seed": 888, "frames": 0}
            if self.seed_mismatch and "_frozen" in label:
                result["aggregate"]["words"][0][0] ^= 1
            (self.evidence / (label + ".state.json")).write_text(json.dumps(result), encoding="utf-8")
        elif action == "capture":
            self.captures.append(label)
            if self.probe.scenario == "capture_failure":
                raise subprocess.CalledProcessError(1, command)
            state = self.probe.aggregation.snapshot()
            query, rows = state["aggregate"]["query"], state["aggregate"]["words"]
            _, start, count, shift = map(int, query)
            image = Image.new("RGBA", (240, 90), (0, 0, 0, 255))
            pixels = image.load()
            for y in range(90):
                page = start + (2 * y + 1) * count // 180
                for x in range(240):
                    cell = (2 * x + 1) * 24 // 480
                    word_index = (cell // 3 + shift) % 8
                    value = (rows[page][word_index] >> (16 - 8 * (cell % 3))) & 255 if page < 8 else 0
                    pixels[x, y] = (value, value, value, 255)
            if self.corruption:
                pixels[5, 15] = (255, 0, 255, 255)
            image.save(self.evidence / (label + ".png"))
        else:
            raise AssertionError("Unexpected host action: " + action)
        return types.SimpleNamespace(returncode=0)


class SpatialRunnerTests(unittest.TestCase):
    def run_case(self, extra=(), scenario="complete", corruption=False, seed_mismatch=False, active=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        evidence = Path(directory.name)
        probe = FakeProbe(scenario)
        if active:
            probe.run = {"seed": 888, "frames": 0, "dynamic": True}
        host = FakeHost(evidence, probe, corruption=corruption, seed_mismatch=seed_mismatch)
        runner = load_runner()
        arguments = ["run_spatial_case.py", "--project", str(evidence / "project"),
                     "--evidence", str(evidence), "--name", "mock_case", "--seconds", "2", *extra]
        caught, code = None, None
        with patch.object(sys, "argv", arguments), patch.object(runner.subprocess, "run", host.subprocess), \
                patch.object(runner, "time", types.SimpleNamespace(sleep=host.sleeps.append, monotonic=host.monotonic)), \
                redirect_stdout(io.StringIO()):
            try:
                code = runner.main()
            except (RuntimeError, ValueError, TimeoutError, subprocess.CalledProcessError) as error:
                caught = error
        path = evidence / "mock_case.case.json"
        report = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        return code, caught, report, probe, host

    def test_dynamic_seed_and_all_resident_pages_are_verified_once(self):
        code, error, report, probe, host = self.run_case(extra=("--word-shift", "3"))
        self.assertIsNone(error)
        self.assertEqual(code, 0)
        self.assertEqual(probe.starts, [(2., True, 54321)])
        self.assertEqual(probe.aggregation.writes, [54321, 54321 + 7 * 97])
        self.assertEqual(probe.aggregation.selections, [(0, 3, 3), (3, 3, 3), (6, 3, 3)])
        self.assertTrue(report["all_resident_bytes_verified"])
        self.assertEqual(report["verified_pages"], 8)
        self.assertEqual(report["payload_bytes"], 192)
        self.assertEqual(report["final_seed"], 54321 + 7 * 97)
        self.assertEqual(report["observed_payload_sha256"], report["expected_payload_sha256"])
        self.assertFalse(report["all_render_frames_verified"])
        self.assertTrue(report["native_crosshair_hidden"])
        self.assertTrue(report["whole_payload_simultaneously_resident"])
        self.assertEqual(host.hide_crosshair_calls, [True])
        self.assertIsNone(probe.run)
        self.assertEqual(len(host.captures), 3)

    def test_static_run_keeps_initial_seed(self):
        code, error, report, probe, _ = self.run_case(extra=("--static",))
        self.assertIsNone(error)
        self.assertEqual(code, 0)
        self.assertEqual(probe.aggregation.writes, [54321])
        self.assertEqual(report["final_seed"], 54321)
        self.assertFalse(report["dynamic"])

    def test_verify_only_does_not_start_benchmark(self):
        code, error, report, probe, _ = self.run_case(extra=("--verify-only",))
        self.assertIsNone(error)
        self.assertEqual(code, 0)
        self.assertEqual(probe.starts, [])
        self.assertIsNone(report["run"])
        self.assertFalse(report["dynamic"])

    def test_pixel_failure_persists_partial_report_and_returns_failure(self):
        code, error, report, _, host = self.run_case(extra=("--verify-only",), corruption=True)
        self.assertIsNone(error)
        self.assertEqual(code, 1)
        self.assertFalse(report["all_resident_bytes_verified"])
        self.assertFalse(report["exact_equal"])
        self.assertFalse(report["whole_payload_simultaneously_resident"])
        self.assertTrue(report["native_crosshair_hidden"])
        self.assertEqual(report["verified_pages"], 0)
        self.assertEqual(len(host.captures), 1)
        self.assertGreater(report["windows"][0]["failed_cells"], 0)

    def test_seed_mismatch_prevents_captures(self):
        code, error, report, _, host = self.run_case(extra=("--verify-only",), seed_mismatch=True)
        self.assertTrue(code == 1 or error is not None)
        self.assertEqual(host.captures, [])
        self.assertIsNotNone(report, "seed failures must produce a durable case report")
        self.assertFalse(report["all_resident_bytes_verified"])

    def test_failed_benchmark_is_reported_before_capture(self):
        code, error, report, _, host = self.run_case(scenario="benchmark_failure")
        self.assertTrue(code == 1 or error is not None)
        self.assertEqual(host.captures, [])
        self.assertIsNotNone(report, "benchmark failures must produce a durable case report")
        self.assertFalse(report["all_resident_bytes_verified"])

    def test_verify_only_rejects_active_run_without_overwriting_its_words(self):
        code, error, report, probe, host = self.run_case(extra=("--verify-only",), active=True)
        self.assertTrue(code == 1 or error is not None, "active dynamic runs cannot be treated as frozen")
        self.assertEqual(probe.aggregation.writes, [])
        self.assertEqual(host.captures, [])
        self.assertEqual(host.hide_crosshair_calls, [])
        self.assertFalse(report["native_crosshair_hidden"])

    def test_crosshair_hide_rejection_reports_failure_before_upload(self):
        for scenario in ("hide_rejected", "hide_truthy_non_bool"):
            with self.subTest(scenario=scenario):
                code, error, report, probe, host = self.run_case(extra=("--verify-only",), scenario=scenario)
                self.assertIsNone(error)
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["stage"], "initialization")
                self.assertFalse(report["native_crosshair_hidden"])
                self.assertFalse(report["whole_payload_simultaneously_resident"])
                self.assertEqual(host.hide_crosshair_calls, [True])
                self.assertEqual(probe.aggregation.writes, [])
                self.assertEqual(probe.starts, [])
                self.assertEqual(host.captures, [])

    def test_benchmark_timeout_reports_failure_and_aborts_only_owned_run(self):
        code, error, report, probe, host = self.run_case(scenario="timeout")
        self.assertIsNone(error)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "failed")
        self.assertIn("TimeoutError", report["error"])
        self.assertEqual(report["stage"], "benchmark_wait")
        self.assertEqual(probe.aborts, [("aborted", "Spatial case failed or timed out")])
        self.assertTrue(report["cleanup"]["aborted_owned_run"])
        self.assertIsNone(probe.run)
        self.assertEqual(host.captures, [])
        self.assertTrue(all(timeout is not None and 0 < timeout <= 130 for timeout in host.process_timeouts))

    def test_foreign_run_started_between_initialization_and_benchmark_is_preserved(self):
        code, error, report, probe, host = self.run_case(scenario="foreign_run")
        self.assertIsNone(error)
        self.assertEqual(code, 1)
        self.assertFalse(report["cleanup"]["aborted_owned_run"])
        self.assertEqual(probe.run["spatial_case_token"], "foreign_case")
        self.assertEqual(probe.aborts, [])
        self.assertEqual(host.captures, [])

    def test_capture_subprocess_failure_is_reported(self):
        code, error, report, _, host = self.run_case(extra=("--verify-only",), scenario="capture_failure")
        self.assertIsNone(error)
        self.assertEqual(code, 1)
        self.assertEqual(report["stage"], "window_capture:mock_case_window_000")
        self.assertIn("CalledProcessError", report["error"])
        self.assertEqual(report["verified_pages"], 0)
        self.assertEqual(len(host.captures), 1)


if __name__ == "__main__":
    unittest.main()
