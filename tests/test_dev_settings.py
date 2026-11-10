"""FPS setup checks operate only on temporary files; no client is launched."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


TOOL = Path(__file__).resolve().parents[1] / "tools/start_dev.py"
SPEC = importlib.util.spec_from_file_location("manim_start_dev", TOOL)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DevSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.options = self.root / "options.txt"
        self.backups = self.root / "backups"

    def test_changes_only_the_fps_digits_preserving_bom_spacing_and_line_endings(self):
        original = b"\xef\xbb\xbfgfx_max_framerate:0  \r\nname:\xe4\xb8\xad\r\nlast:keep\nraw:\xff"
        expected = b"\xef\xbb\xbfgfx_max_framerate:60  \r\nname:\xe4\xb8\xad\r\nlast:keep\nraw:\xff"
        self.options.write_bytes(original)
        result = MODULE.ensure_fps_60(self.options, self.backups, lambda: [])
        self.assertTrue(result["changed"])
        self.assertEqual(self.options.read_bytes(), expected)
        self.assertEqual(Path(result["backup"]).read_bytes(), original)
        self.assertEqual(list(self.root.glob(".options-fps60-*.tmp")), [])

    def test_repeated_setup_is_idempotent_and_does_not_create_another_backup(self):
        self.options.write_bytes(b"first:1\ngfx_max_framerate:0\nlast:2\n")
        first = MODULE.ensure_fps_60(self.options, self.backups, lambda: [])
        after_first = self.options.stat().st_mtime_ns
        second = MODULE.ensure_fps_60(self.options, self.backups, lambda: [999])
        self.assertFalse(second["changed"])
        self.assertIsNone(second["backup"])
        self.assertEqual(self.options.stat().st_mtime_ns, after_first)
        self.assertEqual(list(self.backups.iterdir()), [Path(first["backup"])])

    def test_a_later_actual_change_creates_a_new_backup_without_overwriting(self):
        self.options.write_bytes(b"gfx_max_framerate:0\n")
        first = MODULE.ensure_fps_60(self.options, self.backups, lambda: [])
        self.options.write_bytes(b"gfx_max_framerate:144\n")
        second = MODULE.ensure_fps_60(self.options, self.backups, lambda: [])
        self.assertNotEqual(first["backup"], second["backup"])
        self.assertEqual(Path(first["backup"]).read_bytes(), b"gfx_max_framerate:0\n")
        self.assertEqual(Path(second["backup"]).read_bytes(), b"gfx_max_framerate:144\n")

    def test_running_game_blocks_mutation_and_does_not_create_a_backup(self):
        original = b"gfx_max_framerate:0\r\n"
        self.options.write_bytes(original)
        with self.assertRaisesRegex(RuntimeError, "Minecraft is running"):
            MODULE.ensure_fps_60(self.options, self.backups, lambda: [42])
        self.assertEqual(self.options.read_bytes(), original)
        self.assertFalse(self.backups.exists())

    def test_game_starting_during_backup_is_detected_before_replacement(self):
        original = b"gfx_max_framerate:0\n"
        self.options.write_bytes(original)
        answers = iter(([], [42]))
        with self.assertRaisesRegex(RuntimeError, "Minecraft is running"):
            MODULE.ensure_fps_60(self.options, self.backups, lambda: next(answers))
        self.assertEqual(self.options.read_bytes(), original)
        self.assertEqual(len(list(self.backups.iterdir())), 1)
        self.assertEqual(list(self.root.glob(".options-fps60-*.tmp")), [])

    def test_concurrent_options_edit_is_not_overwritten(self):
        self.options.write_bytes(b"gfx_max_framerate:0\n")
        calls = []

        def process_query():
            calls.append(None)
            if len(calls) == 2:
                self.options.write_bytes(b"gfx_max_framerate:120\nuser_change:yes\n")
            return []

        with self.assertRaisesRegex(RuntimeError, "changed concurrently"):
            MODULE.ensure_fps_60(self.options, self.backups, process_query)
        self.assertEqual(self.options.read_bytes(), b"gfx_max_framerate:120\nuser_change:yes\n")

    @staticmethod
    def windows_error(code):
        error = OSError("Simulated Windows filesystem error")
        error.winerror = code
        return error

    def test_only_winerror_17_uses_in_place_update_and_preserves_file_identity(self):
        original = b"gfx_max_framerate:0\r\nkeep:\xff\r\n"
        self.options.write_bytes(original)
        file_identity = self.options.stat().st_ino
        with patch.object(MODULE.os, "replace", side_effect=self.windows_error(17)):
            result = MODULE.ensure_fps_60(self.options, self.backups, lambda: [])
        self.assertTrue(result["changed"])
        self.assertEqual(self.options.read_bytes(), b"gfx_max_framerate:60\r\nkeep:\xff\r\n")
        self.assertEqual(self.options.stat().st_ino, file_identity)
        self.assertEqual(Path(result["backup"]).read_bytes(), original)
        self.assertEqual(list(self.root.glob(".options-fps60-*.tmp")), [])

    def test_other_replace_errors_are_propagated_without_in_place_writes(self):
        for error in (self.windows_error(5), self.windows_error(32), OSError("generic failure")):
            with self.subTest(error=error):
                original = b"gfx_max_framerate:0\n"
                self.options.write_bytes(original)
                with patch.object(MODULE.os, "replace", side_effect=error):
                    with self.assertRaises(OSError) as caught:
                        MODULE.ensure_fps_60(self.options, self.backups, lambda: [])
                self.assertIs(caught.exception, error)
                self.assertEqual(self.options.read_bytes(), original)

    def test_in_place_fallback_rechecks_game_processes(self):
        original = b"gfx_max_framerate:0\n"
        self.options.write_bytes(original)
        queries = iter(([], [], [42]))
        with patch.object(MODULE.os, "replace", side_effect=self.windows_error(17)):
            with self.assertRaisesRegex(RuntimeError, "Minecraft is running"):
                MODULE.ensure_fps_60(self.options, self.backups, lambda: next(queries))
        self.assertEqual(self.options.read_bytes(), original)
        self.assertEqual(len(list(self.backups.iterdir())), 1)

    def test_in_place_fallback_checks_the_reopened_file_before_writing(self):
        original = b"gfx_max_framerate:0\n"
        concurrent = b"gfx_max_framerate:144\nuser_change:yes\n"
        self.options.write_bytes(original)

        def failed_replace(_source, _destination):
            self.options.write_bytes(concurrent)
            raise self.windows_error(17)

        with patch.object(MODULE.os, "replace", side_effect=failed_replace):
            with self.assertRaisesRegex(RuntimeError, "changed concurrently"):
                MODULE.ensure_fps_60(self.options, self.backups, lambda: [])
        self.assertEqual(self.options.read_bytes(), concurrent)
        self.assertEqual(next(self.backups.iterdir()).read_bytes(), original)

    def test_in_place_write_failure_reports_the_retained_backup(self):
        original = b"gfx_max_framerate:0\n"
        self.options.write_bytes(original)
        with patch.object(MODULE.os, "replace", side_effect=self.windows_error(17)):
            with patch.object(MODULE, "_write_options_in_place", side_effect=OSError("disk write failed")):
                with self.assertRaisesRegex(RuntimeError, "backup retained at") as caught:
                    MODULE.ensure_fps_60(self.options, self.backups, lambda: [])
        backup = next(self.backups.iterdir())
        self.assertIn(str(backup), str(caught.exception))
        self.assertIn("disk write failed", str(caught.exception))
        self.assertEqual(backup.read_bytes(), original)

    def test_missing_ambiguous_or_invalid_setting_is_rejected(self):
        for content in (b"other:1\n", b"gfx_max_framerate:0\ngfx_max_framerate:60\n",
                        b"gfx_max_framerate:unlimited\n"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                MODULE.capped_options(content)
        with self.assertRaises(FileNotFoundError):
            MODULE.ensure_fps_60(self.options, self.backups, lambda: [])
        self.assertFalse(self.backups.exists())


if __name__ == "__main__":
    unittest.main()
