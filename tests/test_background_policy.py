"""Background policy regressions use mocks only; never touch a real game window."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents/skills/pyreact-debugging/scripts"
sys.path.insert(0, str(SCRIPTS))
import _background_policy as policy
import _session
import mcdk
import resize_window


def load_tool(name):
    spec = importlib.util.spec_from_file_location("background_test_" + name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def session(protected=True):
    return {"project": str(ROOT), "game_pid": 123, "game_identity": "owned-creation",
            "game_executable": "D:/game/Minecraft.Windows.exe",
            "noactivation": {"requested": protected}}


def guard():
    return {"background_safe": True, "window_noactivate": True,
            "foreground": {"pid": 456},
            "windows": [{"pid": 123, "hwnd": 789, "noactivate": True,
                         "minimized": False, "width": 1280, "height": 720}]}


class BackgroundPolicyTests(unittest.TestCase):
    def test_all_desktop_input_is_rejected_before_binding_or_rpc(self):
        client = object.__new__(mcdk.Client)
        client._verify_binding = MagicMock()
        client._post = MagicMock()
        for operation in ("/run", "/click", "/key", "/release-all", None):
            with self.subTest(operation=operation), self.assertRaisesRegex(RuntimeError, "disables desktop input"):
                client.call("mc_input", {"op": operation})
        client._verify_binding.assert_not_called()
        client._post.assert_not_called()

    def test_input_help_and_state_remain_passive(self):
        client = object.__new__(mcdk.Client)
        client._verify_binding = MagicMock()
        client._post = MagicMock(return_value={"content": []})
        for operation in ("/help", "/state"):
            client.call("mc_input", {"op": operation})
        self.assertEqual(client._post.call_count, 2)

    def test_raw_rpc_path_cannot_bypass_input_gate(self):
        client = object.__new__(mcdk.Client)
        client.opener = MagicMock()
        with self.assertRaisesRegex(RuntimeError, "disables desktop input"):
            client._post("tools/call", {"name": "mc_input", "arguments": {"op": "/click"}})
        client.opener.open.assert_not_called()

    def test_protection_and_foreground_are_required_without_override(self):
        with patch.object(policy, "background_guard_state", return_value=guard()) as observe:
            with self.assertRaisesRegex(RuntimeError, "noactivation-protected"):
                policy.require_background_session(session(False))
            observe.assert_not_called()
            self.assertEqual(policy.require_background_session(session()), guard())
        for field, value in (("background_safe", False), ("window_noactivate", False)):
            broken = guard()
            broken[field] = value
            with patch.object(policy, "background_guard_state", return_value=broken), self.assertRaises(RuntimeError):
                policy.require_background_session(session())
        broken = guard()
        broken["foreground"]["pid"] = 123
        with patch.dict("os.environ", {"MCDEV_ALLOW_USER_FOREGROUND": "1"}), \
                patch.object(policy, "background_guard_state", return_value=broken), self.assertRaises(RuntimeError):
            policy.require_background_session(session())

    def test_minimized_or_unprotected_window_is_not_repaired(self):
        for field, value in (("minimized", True), ("noactivate", False), ("pid", 999)):
            broken = guard()
            broken["windows"][0][field] = value
            with patch.object(policy, "background_guard_state", return_value=broken), self.assertRaises(RuntimeError):
                policy.require_background_session(session())

    def test_resize_uses_noactivate_and_never_showwindow(self):
        native = MagicMock()
        native.IsIconic.return_value = False
        native.IsZoomed.return_value = False
        native.SetWindowPos.return_value = True
        with patch.object(resize_window, "user32", native), \
                patch.object(resize_window, "_window_rect", return_value=(10, 20, 1280, 720)), \
                patch.object(resize_window, "_monitor_work_area", return_value=(0, 0, 1920, 1080)), \
                patch.object(resize_window, "_outer_size_for_client", return_value=(656, 519)):
            resize_window._resize_window(789, 640, 480)
        flags = native.SetWindowPos.call_args.args[-1]
        self.assertTrue(flags & resize_window.SWP_NOACTIVATE)
        native.ShowWindow.assert_not_called()

    def test_resize_refuses_minimized_window_before_any_mutation(self):
        native = MagicMock()
        native.IsIconic.return_value = True
        with patch.object(resize_window, "user32", native), self.assertRaisesRegex(RuntimeError, "normal window"):
            resize_window._resize_window(789, 640, 480)
        native.ShowWindow.assert_not_called()
        native.SetWindowPos.assert_not_called()

    def test_resize_default_is_passive_and_explicit_activation_is_rejected(self):
        with patch.object(sys, "argv", ["resize_window.py", "--size", "640x480"]), \
                patch.object(resize_window, "user32", MagicMock()), \
                patch.object(resize_window, "_emit"), \
                patch.object(resize_window, "resize_owned", return_value={"ok": True}) as resize:
            self.assertEqual(resize_window.main(), 0)
        self.assertTrue(resize.call_args.args[0].no_activate)
        with self.assertRaisesRegex(RuntimeError, "Foreground resize is disabled"):
            resize_window.resize_owned(types.SimpleNamespace(no_activate=False), 640, 480)

    def test_capture_and_player_tools_refuse_legacy_sessions_before_dispatch(self):
        for name in ("capture_owned", "live_player", "verify_player"):
            tool = load_tool(name)
            with tempfile.TemporaryDirectory() as temp:
                argv = [name, "--session", "fake.json", "--owner", "test"]
                if name == "capture_owned":
                    argv += ["--helper", "fake.exe", "--output", str(Path(temp) / "frame.png")]
                elif name == "verify_player":
                    argv += ["--output", str(Path(temp) / "verify")]
                with self.subTest(tool=name), patch.object(sys, "argv", argv), patch.dict("os.environ"), \
                        patch.object(_session, "load_session", return_value=session(False)), \
                        patch.object(_session, "process_identity", return_value="owned-creation"), \
                        patch.object(mcdk.Client, "__enter__") as connect, \
                        patch("subprocess.run") as run, \
                        self.assertRaisesRegex(RuntimeError, "noactivation-protected"):
                    tool.main()
                connect.assert_not_called()
                run.assert_not_called()

    def test_capture_records_pre_and_post_background_evidence(self):
        tool = load_tool("capture_owned")
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "frame.png"
            report = {"ok": True, "frame_qpc_100ns": 20, "request_qpc_100ns": 10}
            result = types.SimpleNamespace(returncode=0, stdout=json.dumps(report))
            with patch.object(sys, "argv", ["capture", "--session", "fake", "--owner", "test",
                                           "--helper", "fake.exe", "--output", str(output)]), \
                    patch.object(_session, "load_session", return_value=session()), \
                    patch.object(_session, "process_identity", return_value="owned-creation"), \
                    patch.object(policy, "background_guard_state", return_value=guard()) as observe, \
                    patch("_window._list_windows_windows", return_value=guard()["windows"]), \
                    patch("_window._find_game_window", return_value=guard()["windows"][0]), \
                    patch("subprocess.run", return_value=result), patch("builtins.print"):
                tool.main()
            saved = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(observe.call_count, 2)
            self.assertTrue(saved["background_only"])
            self.assertEqual(saved["background_before"], guard())
            self.assertEqual(saved["background_after"], guard())

    def test_capture_losing_background_protection_preserves_rejected_report(self):
        tool = load_tool("capture_owned")
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "frame.png"
            result = types.SimpleNamespace(returncode=0, stdout=json.dumps(
                {"ok": True, "frame_qpc_100ns": 20, "request_qpc_100ns": 10}))
            lost = guard()
            lost["background_safe"] = False
            lost["foreground"]["pid"] = 123
            with patch.object(sys, "argv", ["capture", "--session", "fake", "--owner", "test",
                                           "--helper", "fake.exe", "--output", str(output)]), \
                    patch.object(_session, "load_session", return_value=session()), \
                    patch.object(_session, "process_identity", return_value="owned-creation"), \
                    patch.object(policy, "background_guard_state", side_effect=[guard(), lost]), \
                    patch("_window._list_windows_windows", return_value=guard()["windows"]), \
                    patch("_window._find_game_window", return_value=guard()["windows"][0]), \
                    patch("subprocess.run", return_value=result) as run, \
                    self.assertRaisesRegex(RuntimeError, "no activation fallback"):
                tool.main()
            self.assertEqual(run.call_count, 1)
            saved = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertFalse(saved["ok"])
            self.assertIn("background_after_error", saved)


if __name__ == "__main__":
    unittest.main()
