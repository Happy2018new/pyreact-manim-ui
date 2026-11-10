"""A missing focus guard must never fall back to normal Minecraft startup."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("start_background_test", ROOT / "tools/start_dev.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BackgroundStartupTests(unittest.TestCase):
    def test_missing_guard_configuration_fails_before_settings_or_launch(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "ensure_fps_60") as fps, \
                patch.object(MODULE.subprocess, "run") as run:
            with self.assertRaises(FileNotFoundError):
                MODULE.launch("test", background_config=Path(directory) / "missing.json")
            fps.assert_not_called()
            run.assert_not_called()

    def test_incomplete_pins_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "background.json"
            path.write_text('{"mcdk": "mcdk.exe"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                MODULE.background_arguments(path)

    def test_all_binary_pins_are_validated_before_returning_arguments(self):
        validator = types.SimpleNamespace(noactivate_contract=lambda args, exe: self.assertEqual(args.mcdk, exe))
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {"instances": validator}):
            path = Path(directory) / "background.json"
            path.write_text(json.dumps({"mcdk": "mcdk.exe", "mcdk_sha256": "a" * 64,
                                        "guard_dll": "guard.dll", "guard_sha256": "b" * 64}), encoding="utf-8")
            args = MODULE.background_arguments(path)
            self.assertIn("--noactivate-dll", args)
            self.assertEqual(args[args.index("--noactivate-sha256") + 1], "b" * 64)
            with patch.object(validator, "noactivate_contract", side_effect=ValueError("hash mismatch")):
                with self.assertRaisesRegex(ValueError, "hash mismatch"):
                    MODULE.background_arguments(path)

    def test_launch_removes_foreground_override_and_keeps_noactivate_flags(self):
        received = {}
        def fake_run(command, **kwargs):
            received.update(command=command, env=kwargs["env"])
            kwargs["stdout"].write(b'{"state":"ready","session_file":"safe"}')
            return types.SimpleNamespace(returncode=0)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(MODULE, "ROOT", Path(directory)), \
                patch.object(MODULE, "background_arguments", return_value=["--noactivate-dll", "guard.dll"]), \
                patch.object(MODULE, "native_options_path", return_value=Path(directory) / "options.txt"), \
                patch.object(MODULE, "ensure_fps_60", return_value={"changed": False, "backup": None}), \
                patch.object(MODULE.subprocess, "run", side_effect=fake_run), \
                patch.dict(os.environ, {"MCDEV_ALLOW_USER_FOREGROUND": "1"}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(MODULE.launch("test"), 0)
        self.assertNotIn("MCDEV_ALLOW_USER_FOREGROUND", received["env"])
        self.assertIn("--noactivate-dll", received["command"])


if __name__ == "__main__":
    unittest.main()
