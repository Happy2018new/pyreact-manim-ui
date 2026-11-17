"""Run-state and resource ownership regressions; no real ModSDK or game access."""
import importlib.util
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools/runtime_packet_probe"


class Clock:
    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now


class FakeBase:
    def __init__(self, *args):
        self.events = []

    def ListenForEvent(self, *args):
        self.events.append(args)

    def UnListenForEvent(self, *args):
        self.events.remove(args)


class FakeScreen:
    def __init__(self):
        self.values = []
        self.configurations = []
        self.writes = []
        self.removed = False
        self.write_error = None

    def configure(self, count, mode=0, seed=12345, carriers=True):
        self.configurations.append((count, mode, seed, carriers))
        return self.snapshot()

    def write(self, seed):
        self.writes.append(seed)
        if self.write_error is not None:
            raise self.write_error
        return .125, .25

    def snapshot(self):
        return {"ready": True, "removed": self.removed}

    def SetRemove(self):
        self.removed = True


class FakeUniformUISlice:
    def __init__(self, index, lifecycle):
        self.index, self.lifecycle = index, lifecycle
        self.visible, self.removed = True, False

    def SetScreenVisible(self, enabled):
        self.lifecycle.append((self.index, "visible", enabled))
        self.visible = enabled

    def SetRemove(self):
        self.lifecycle.append((self.index, "remove"))
        self.removed = True


class FakePost:
    """Track engine-side effects, including AddPostProcess's initial enable."""
    def __init__(self):
        self.present = []
        self.enabled = {}
        self.parameters = {}
        self.enable_calls = []
        self.parameter_calls = []
        self.connection_calls = []
        self.add_calls = []
        self.fail_enable = {}
        self.fail_parameter = {}
        self.fail_add = {}
        self.fail_connection = False

    @staticmethod
    def outcome(fault):
        if isinstance(fault, Exception):
            raise fault
        return not fault

    def GetPostProcessOrder(self):
        return list(self.present)

    def AddPostProcess(self, definition):
        name = definition["name"]
        self.add_calls.append(name)
        # A failing SDK call can still have side effects. The caller must retain
        # the attempted name so cleanup does not abandon an enabled process.
        self.present.append(name)
        self.enabled[name] = bool(definition.get("enable"))
        return self.outcome(self.fail_add.get(name))

    def SetEnableByName(self, name, enabled):
        self.enable_calls.append((name, enabled))
        if not self.outcome(self.fail_enable.get((name, enabled))):
            return False
        self.enabled[name] = enabled
        return True

    def SetParameter(self, name, key, value):
        self.parameter_calls.append((name, key, list(value)))
        if not self.outcome(self.fail_parameter.get((name, key))):
            return False
        self.parameters[(name, key)] = list(value)
        return True

    def PostPassResultToOtherPass(self, *connection):
        self.connection_calls.append(list(connection))
        return not self.fail_connection


def aggregate_config(pages=2):
    producers = ["probe_page_%d" % page for page in range(pages)]
    display = "probe_display"
    query = [float(pages), 0., 0., 0.]
    rectangle = [.05, .05, .9, .9]
    processes = [{"name": name, "enable": False, "paras": [
        {"name": "page", "value": [float(page), float(pages), 8., 0.]}
    ]} for page, name in enumerate(producers)]
    processes.append({"name": display, "enable": False, "paras": [
        {"name": "query", "value": query},
        {"name": "display_rect", "value": rectangle}]})
    connections = [[producers[page - 1], 0, producers[page], 0, 3]
                   for page in range(1, pages)]
    connections.append([producers[-1], 0, display, 0, 3])
    return {"pages": pages, "processes": processes, "producer_names": producers,
            "display_name": display, "connections": connections, "query": query,
            "display_rect_norm": rectangle, "target_pixels": [32, pages * 4], "words_per_page": 8}


class RuntimePacketRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.trace_output = io.StringIO()
        stderr_patch = patch("sys.stderr", self.trace_output)
        stderr_patch.start()
        self.addCleanup(stderr_patch.stop)
        self.clock = Clock()
        self.post = FakePost()
        self.screens = []
        api = types.ModuleType("mod.client.extraClientApi")
        api.GetScreenNodeCls = lambda: FakeBase
        api.GetClientSystemCls = lambda: FakeBase
        api.GetEngineNamespace = lambda: "fake_engine"
        api.GetEngineSystemName = lambda: "fake_system"
        api.GetLevelId = lambda: "fake_level"
        api.GetEngineCompFactory = lambda: types.SimpleNamespace(
            CreatePostProcess=lambda level: self.post,
            CreateGame=lambda level: types.SimpleNamespace(GetFps=lambda: 60.))
        api.RegisterUI = lambda *args: True

        def create_ui(*args):
            screen = FakeScreen()
            self.screens.append(screen)
            return screen

        api.CreateUI = create_ui
        package_name = "_runtime_packet_behavior_test"
        package = types.ModuleType(package_name)
        package.__path__ = [str(PROBE)]
        mod = types.ModuleType("mod")
        mod.__path__ = []
        client = types.ModuleType("mod.client")
        client.__path__ = []
        mod.client = client
        client.extraClientApi = api
        modules = {"mod": mod, "mod.client": client, "mod.client.extraClientApi": api,
                   package_name: package}
        self.module_patch = patch.dict(sys.modules, modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.runtime = self.load_module(package_name + ".runtime", "runtime.py")
        self.aggregate = self.load_module(package_name + ".aggregate_runtime", "aggregate_runtime.py")
        # Replace only these modules' clock reference, not Python's global time.
        self.runtime.time = self.clock
        self.aggregate.time = self.clock
        self.system = self.runtime.ProbeSystem("probe", "test")

    @staticmethod
    def load_module(name, filename):
        spec = importlib.util.spec_from_file_location(name, PROBE / filename)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    def ui_run(self, seconds=8., dynamic=True):
        self.system.open()
        self.system.start(1, 0, seconds=seconds, dynamic=dynamic)
        return self.system.screen

    def installed_aggregate(self):
        self.system.setup_aggregate(aggregate_config(), seed=321)
        self.system.aggregation.finish()
        return self.system.aggregation

    def frame(self, now):
        self.clock.now = now
        self.system.on_frame({})

    def test_completed_run_includes_6984ms_interval_crossing_deadline(self):
        self.ui_run()
        self.frame(1.000)
        self.frame(1.016)
        self.frame(8.000)
        result = self.system.last_run
        self.assertIsNone(self.system.run)
        self.assertEqual("completed", result["status"])
        self.assertTrue(result["success"])
        self.assertIsNone(result["error"])
        self.assertEqual(2, result["interval_ms"]["count"])
        self.assertAlmostEqual(6984., result["interval_ms"]["max"])
        self.assertEqual(2, result["upload_ms"]["count"])
        self.assertAlmostEqual(8., result["elapsed"])
        self.assertIs(result["gpu_verified"], False)

    def test_baseline_removes_renderers_writes_nothing_and_counts_deadline_interval(self):
        aggregation = self.installed_aggregate()
        old_screen = FakeScreen()
        self.system.screen = old_screen
        parameters = list(self.post.parameter_calls)
        words = [list(row) for row in aggregation.words]
        with patch.object(aggregation, "write", side_effect=AssertionError("Baseline wrote payload")) as writer:
            started = self.system.start_baseline(seconds=8.)
            self.assertTrue(started["started"])
            self.assertEqual(self.system.run["kind"], "baseline")
            self.assertFalse(self.system.run["dynamic"])
            self.assertFalse(aggregation.enabled)
            self.assertFalse(any(self.post.enabled.values()))
            self.assertTrue(old_screen.removed)
            self.assertIsNone(self.system.screen)
            self.frame(1.)
            self.frame(1.016)
            self.frame(8.)
            writer.assert_not_called()
        result = self.system.last_run
        self.assertIsNone(self.system.run)
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["kind"], "baseline")
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["interval_ms"]["count"], 2)
        self.assertAlmostEqual(result["interval_ms"]["max"], 6984.)
        self.assertEqual(result["measured_frames"], 2)
        self.assertEqual(result["upload_ms"]["max"], 0.)
        self.assertEqual(result["generation_ms"]["max"], 0.)
        self.assertFalse(result["gpu_verified"])
        self.assertEqual(self.post.parameter_calls, parameters)
        self.assertEqual(aggregation.words, words)
        self.assertEqual(old_screen.writes, [])

    def test_baseline_rejects_existing_run_without_disabling_or_removing_its_renderer(self):
        screen = self.ui_run(seconds=8.)
        run = self.system.run
        previous_result = self.system.last_run
        with self.assertRaisesRegex(RuntimeError, "active benchmark"):
            self.system.start_baseline(seconds=2.)
        self.assertIs(self.system.run, run)
        self.assertIs(self.system.last_run, previous_result)
        self.assertIs(self.system.screen, screen)
        self.assertFalse(screen.removed)
        self.assertEqual(self.post.enable_calls, [])

    def test_disable_uniform_ui_hides_before_removing_all_slices_and_is_idempotent(self):
        uniform_ui = self.load_module("_runtime_packet_behavior_test.uniform_ui_runtime",
                                      "uniform_ui_runtime.py")
        config = {"transport": "uniform_ui", "pages": 3, "words_per_page": 8,
                  "identifiers": ["slice_0", "slice_1", "slice_2"]}
        factory = types.SimpleNamespace(CreateActorRender=lambda entity: object(),
                                        CreateGame=lambda level: object())
        with patch.object(self.runtime.api, "GetEngineCompFactory", return_value=factory):
            aggregation = uniform_ui.UniformUIProbe(config)
        lifecycle = []
        screens = [FakeUniformUISlice(index, lifecycle) for index in range(3)]
        aggregation.screens = list(screens)
        aggregation.ready, aggregation.enabled = True, True
        self.system.aggregation = aggregation
        with patch.object(aggregation, "set_enabled", wraps=aggregation.set_enabled) as enable:
            self.system._disable_aggregate()
            enable.assert_called_once_with(False)
            # Every slice is hidden before the first owned node is removed.
            self.assertEqual(lifecycle[:3], [(index, "visible", False) for index in range(3)])
            self.assertTrue(all(screen.removed and not screen.visible for screen in screens))
            self.assertEqual(aggregation.screens, [None, None, None])
            self.assertTrue(aggregation.closed)
            self.assertFalse(aggregation.ready)
            self.assertFalse(aggregation.enabled)
            previous = list(lifecycle)
            self.system._disable_aggregate()
            self.system.close()
            self.assertEqual(lifecycle, previous)
            enable.assert_called_once_with(False)

    def test_disable_already_hidden_uniform_ui_still_removes_owned_slices(self):
        lifecycle = []
        screens = [FakeUniformUISlice(index, lifecycle) for index in range(2)]
        uniform_ui = self.load_module("_runtime_packet_behavior_test.uniform_ui_runtime",
                                      "uniform_ui_runtime.py")
        factory = types.SimpleNamespace(CreateActorRender=lambda entity: object(),
                                        CreateGame=lambda level: object())
        config = {"transport": "uniform_ui", "pages": 2, "words_per_page": 8,
                  "identifiers": ["slice_0", "slice_1"]}
        with patch.object(self.runtime.api, "GetEngineCompFactory", return_value=factory):
            aggregation = uniform_ui.UniformUIProbe(config)
        aggregation.screens, aggregation.ready = list(screens), True
        self.assertIs(aggregation.enabled, False)
        self.system.aggregation = aggregation
        with patch.object(aggregation, "set_enabled", wraps=aggregation.set_enabled) as enable:
            self.system._disable_aggregate()
            enable.assert_not_called()
        self.assertTrue(all(screen.removed for screen in screens))
        self.assertTrue(aggregation.closed)

    def test_disable_normal_aggregate_retains_ready_state_and_can_be_enabled_again(self):
        aggregation = self.installed_aggregate()
        # A generic close method must not change regular atlas ownership.
        with patch.object(aggregation, "close", create=True) as close:
            self.system._disable_aggregate()
            self.system._disable_aggregate()
            close.assert_not_called()
        self.assertIs(self.system.aggregation, aggregation)
        self.assertTrue(aggregation.ready)
        self.assertFalse(aggregation.enabled)
        self.assertIsNone(aggregation.error)
        aggregation.set_enabled(True)
        self.assertTrue(aggregation.enabled)
        self.assertTrue(all(self.post.enabled[name] for name in aggregation.names))

    def test_no_samples_cannot_be_reported_as_success(self):
        self.ui_run(seconds=2.)
        self.frame(10.)
        self.assertFalse(self.system.last_run["success"])
        self.assertEqual("failed", self.system.last_run["status"])
        self.assertIn("without measured", self.system.last_run["error"])
        self.assertEqual(0, self.system.last_run["upload_ms"]["count"])

    def test_start_rejects_invalid_durations_and_clears_stale_result(self):
        self.system.open()
        for seconds in (0., 1., -1., float("nan"), float("inf"), -float("inf")):
            with self.subTest(seconds=seconds), self.assertRaises((ValueError, RuntimeError)):
                self.system.start(1, 0, seconds=seconds)
            self.assertIsNone(self.system.run)
        self.system.last_run = {"status": "completed", "success": True}
        self.system.start(1, 0, seconds=2.)
        self.assertIsNone(self.system.last_run)
        self.assertEqual("running", self.system.run["status"])
        self.assertFalse(self.system.run["success"])
        self.assertIsNone(self.system.run["error"])

    def test_ui_writer_failure_terminates_with_error_and_traceback(self):
        screen = self.ui_run()
        screen.write_error = RuntimeError("injected UI upload failure")
        self.frame(1.1)
        self.assertIsNone(self.system.run)
        result = self.system.last_run
        self.assertEqual("failed", result["status"])
        self.assertFalse(result["success"])
        self.assertIn("injected UI upload failure", str(result["error"]))
        self.assertIn("Traceback", self.trace_output.getvalue())
        self.assertIn("injected UI upload failure", self.trace_output.getvalue())
        writes = list(screen.writes)
        self.frame(8.)
        self.assertEqual(writes, screen.writes)
        self.assertIs(result, self.system.last_run)

    def test_partial_aggregate_upload_failure_disables_atlas_and_rejects_restart(self):
        for fault in (True, RuntimeError("injected aggregate upload failure")):
            with self.subTest(fault=fault):
                self.post.fail_parameter.clear()
                aggregation = self.installed_aggregate()
                first, second = aggregation.config["producer_names"]
                previous_words = [list(row) for row in aggregation.words]
                previous_parameter = list(self.post.parameters[(first, "packet0")])
                self.system.start_aggregate(seconds=2.)
                self.post.fail_parameter[(second, "packet0")] = fault
                self.frame(self.clock.now + 1.1)

                # The first page really changed before the later SDK failure,
                # so retaining a ready atlas would expose mixed generations.
                self.assertNotEqual(previous_parameter,
                                    self.post.parameters[(first, "packet0")])
                self.assertEqual(previous_words, aggregation.words)
                self.assertFalse(aggregation.ready)
                self.assertIs(aggregation.enabled, False)
                self.assertIsNotNone(aggregation.error)
                self.assertFalse(any(self.post.enabled[name] for name in aggregation.names))
                self.assertEqual([], aggregation.cleanup_errors)
                self.assertIsNone(self.system.run)
                self.assertEqual("failed", self.system.last_run["status"])
                self.assertFalse(self.system.last_run["success"])
                self.assertIn("Traceback", self.trace_output.getvalue())
                self.assertIn("upload fail", self.system.last_run["error"])

                calls = list(self.post.parameter_calls)
                with self.assertRaises(RuntimeError):
                    self.system.start_aggregate(seconds=2.)
                self.assertEqual(calls, self.post.parameter_calls)
                self.assertIsNone(self.system.run)

    def test_close_marks_active_run_aborted_and_removes_ui(self):
        screen = self.ui_run()
        self.frame(1.1)
        self.system.close()
        self.assertIsNone(self.system.run)
        self.assertEqual("aborted", self.system.last_run["status"])
        self.assertFalse(self.system.last_run["success"])
        self.assertTrue(screen.removed)
        self.assertIsNone(self.system.screen)

    def test_active_benchmark_rejects_ui_open_configure_and_aggregate_setup(self):
        screen = self.ui_run()
        run = self.system.run
        configurations = list(screen.configurations)
        for operation in (self.system.open, lambda: self.system.configure(2),
                          lambda: self.system.setup_aggregate(aggregate_config())):
            with self.subTest(operation=operation), self.assertRaises(RuntimeError):
                operation()
            self.assertIs(run, self.system.run)
            self.assertIs(screen, self.system.screen)
            self.assertFalse(screen.removed)
            self.assertEqual(configurations, screen.configurations)
            self.assertEqual([], self.post.add_calls)

    def test_open_and_configure_disable_existing_aggregate(self):
        aggregation = self.installed_aggregate()
        self.system.open()
        self.assertFalse(aggregation.enabled)
        self.assertFalse(any(self.post.enabled.values()))
        # Direct aggregate enable is public; configure must restore UI-only mode.
        aggregation.set_enabled(True)
        self.system.configure(1)
        self.assertFalse(aggregation.enabled)
        self.assertFalse(any(self.post.enabled.values()))

    def test_setup_aggregate_removes_ui_before_aggregate_use(self):
        self.system.open()
        screen = self.system.screen
        self.system.setup_aggregate(aggregate_config())
        self.assertTrue(screen.removed)
        self.assertIsNone(self.system.screen)

    def test_aggregate_benchmark_requires_finished_enabled_error_free_probe(self):
        self.system.setup_aggregate(aggregate_config())
        aggregation = self.system.aggregation
        with self.assertRaises(RuntimeError):
            self.system.start_aggregate(seconds=2.)
        with self.assertRaises(RuntimeError):
            aggregation.set_enabled(True)
        aggregation.finish()
        aggregation.set_enabled(False)
        with self.assertRaises(RuntimeError):
            self.system.start_aggregate(seconds=2.)
        aggregation.set_enabled(True)
        aggregation.error = "previous setup failure"
        with self.assertRaises(RuntimeError):
            self.system.start_aggregate(seconds=2.)
        with self.assertRaises(RuntimeError):
            aggregation.set_enabled(True)
        self.assertIsNone(self.system.run)

    def test_finished_aggregate_run_can_complete_without_claiming_gpu_verification(self):
        aggregation = self.installed_aggregate()
        self.system.start_aggregate(seconds=2.)
        self.frame(1.)
        self.frame(1.02)
        self.frame(2.)
        self.assertTrue(self.system.last_run["success"])
        self.assertEqual("completed", self.system.last_run["status"])
        snapshot = aggregation.snapshot()
        self.assertTrue(snapshot["ready"])
        self.assertTrue(snapshot["enabled"])
        self.assertIsNone(snapshot["error"])
        self.assertIs(snapshot["gpu_verified"], False)
        self.assertEqual(2, len(snapshot["aggregate"]["words"]))
        self.assertTrue(all(len(row) == 8 for row in snapshot["aggregate"]["words"]))

    def test_finish_reuploads_query_rectangle_and_page_parameters_on_reuse(self):
        config = aggregate_config()
        first = self.aggregate.AggregateProbe(self.post, config, 10)
        first.finish()
        first.select(1, 5, 2)
        first.set_enabled(False)
        self.post.parameters[(config["display_name"], "display_rect")] = [0, 0, .1, .1]
        for name in config["producer_names"]:
            self.post.parameters[(name, "page")] = [9, 9, 9, 9]
        added = list(self.post.add_calls)
        second = self.aggregate.AggregateProbe(self.post, config, 20)
        self.assertFalse(second.ready)
        second.finish()
        self.assertEqual(added, self.post.add_calls)
        self.assertEqual(config["query"], self.post.parameters[(config["display_name"], "query")])
        self.assertEqual(config["display_rect_norm"],
                         self.post.parameters[(config["display_name"], "display_rect")])
        for page, name in enumerate(config["producer_names"]):
            self.assertEqual([page, 2., 8., 0.], self.post.parameters[(name, "page")])
        self.assertEqual(config["query"], second.snapshot()["aggregate"]["query"])

    def test_constructor_failure_cleans_every_attempted_process_and_retains_probe(self):
        for failure_kind in ("enable", "registration"):
            with self.subTest(failure_kind=failure_kind):
                post = FakePost()
                config = aggregate_config()
                failing_name = config["producer_names"][1]
                if failure_kind == "enable":
                    post.fail_enable[(failing_name, True)] = True
                else:
                    post.fail_add[failing_name] = True
                with self.assertRaises(RuntimeError) as raised:
                    self.aggregate.AggregateProbe(post, config, 10)
                probe = raised.exception.aggregate_probe
                self.assertFalse(probe.ready)
                self.assertIsNotNone(probe.error)
                self.assertFalse(any(post.enabled.values()))
                for name in config["producer_names"]:
                    self.assertIn((name, False), post.enable_calls)

    def test_system_retains_failed_constructor_probe_for_cleanup_retry(self):
        config = aggregate_config()
        first, second = config["producer_names"]
        self.post.fail_enable[(second, True)] = True
        self.post.fail_enable[(first, False)] = True
        with self.assertRaises(RuntimeError) as raised:
            self.system.setup_aggregate(config)
        self.assertIs(raised.exception.aggregate_probe, self.system.aggregation)
        self.assertTrue(self.system.aggregation.cleanup_errors)
        self.post.fail_enable.clear()
        self.system.close()
        self.assertFalse(any(self.post.enabled.values()))

    def test_finish_failure_records_error_and_disables_all_processes(self):
        for failure_kind in ("parameter", "connection"):
            with self.subTest(failure_kind=failure_kind):
                post = FakePost()
                config = aggregate_config()
                probe = self.aggregate.AggregateProbe(post, config, 10)
                if failure_kind == "parameter":
                    post.fail_parameter[(config["display_name"], "query")] = True
                else:
                    post.fail_connection = True
                with self.assertRaises(RuntimeError):
                    probe.finish()
                self.assertFalse(probe.ready)
                self.assertFalse(probe.enabled)
                self.assertIsNotNone(probe.error)
                self.assertFalse(any(post.enabled.values()))
                with self.assertRaises(RuntimeError):
                    probe.set_enabled(True)

    def test_disable_attempts_all_names_when_one_sdk_call_raises(self):
        probe = self.installed_aggregate()
        first = probe.names[0]
        self.post.fail_enable[(first, False)] = RuntimeError("injected disable failure")
        before = len(self.post.enable_calls)
        with self.assertRaises(RuntimeError):
            probe.set_enabled(False)
        self.assertEqual([(name, False) for name in probe.names], self.post.enable_calls[before:])
        self.assertTrue(probe.cleanup_errors)
        self.assertTrue(self.post.enabled[first])
        self.assertFalse(any(self.post.enabled[name] for name in probe.names[1:]))
        self.post.fail_enable.clear()
        probe.set_enabled(False)
        self.assertFalse(any(self.post.enabled.values()))
        self.assertEqual([], probe.cleanup_errors)


if __name__ == "__main__":
    unittest.main()
