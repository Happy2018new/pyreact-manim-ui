"""Launch an owned MC development instance with the native global cap at 60 FPS.

The options file belongs to the development client globally, not to a managed
APPDATA sandbox. If it needs changing while a Minecraft process is running,
this tool refuses; it never closes or restarts another process.
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SETTING = b"gfx_max_framerate"


def native_options_path():
    """Use Windows' roaming known folder, not a redirected APPDATA variable."""
    if os.name != "nt":
        raise OSError("The development launcher currently requires Windows")
    buffer = ctypes.create_unicode_buffer(32768)
    result = ctypes.windll.shell32.SHGetFolderPathW(None, 26, None, 0, buffer)
    if result:
        raise OSError("Cannot locate the Windows roaming data directory")
    return Path(buffer.value) / "MinecraftPE_Netease/minecraftpe/options.txt"


def running_game_pids():
    """Enumerate native Minecraft processes without opening or controlling them."""
    if os.name != "nt":
        raise OSError("Minecraft process discovery currently requires Windows")

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    result = []
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        available = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while available:
            if entry.szExeFile.casefold() == "minecraft.windows.exe":
                result.append(entry.th32ProcessID)
            available = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        error = ctypes.get_last_error()
        if error != 18:  # ERROR_NO_MORE_FILES is the normal end of the snapshot.
            raise ctypes.WinError(error)
    finally:
        kernel.CloseHandle(snapshot)
    return sorted(result)


def capped_options(original):
    """Replace only the numeric FPS value, preserving all unrelated bytes."""
    pattern = re.compile(
        rb"(?m)^((?:\xef\xbb\xbf)?[ \t]*gfx_max_framerate[ \t]*:[ \t]*)([^\r\n]*)"
    )
    matches = list(pattern.finditer(original))
    if len(matches) != 1:
        raise ValueError("Native options must contain exactly one gfx_max_framerate field")
    match = matches[0]
    value = re.fullmatch(rb"([+-]?\d+(?:\.\d+)?)([ \t]*)", match.group(2))
    if value is None:
        raise ValueError("Invalid gfx_max_framerate value in native options")
    if value.group(1) == b"60":
        return original
    start = match.start(2)
    end = start + len(value.group(1))
    return original[:start] + b"60" + original[end:]


def _require_stopped(process_query):
    pids = process_query()
    if pids:
        raise RuntimeError(
            "The global development-client FPS cap is not 60, but Minecraft is running "
            "(PID %s). Close the relevant development clients and rerun this launcher; "
            "the change needs a restart. No process was stopped and no option was changed."
            % ", ".join(str(pid) for pid in pids)
        )


def _write_options_in_place(options_path, original, updated, process_query):
    """Preserve EFS/file identity when Windows rejects the same-directory rename."""
    _require_stopped(process_query)
    with options_path.open("r+b") as stream:
        # Validate using the very handle that will be written, after reopening.
        if stream.read() != original:
            raise RuntimeError("Native options changed concurrently; in-place update refused")
        stream.seek(0)
        written = stream.write(updated)
        if written != len(updated):
            raise OSError("Short write while updating native options")
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())


def ensure_fps_60(options_path, backup_dir, process_query=running_game_pids):
    """Back up each change; prefer replacement, with a narrow EFS-compatible path."""
    options_path = Path(options_path)
    backup_dir = Path(backup_dir)
    if not options_path.is_file():
        raise FileNotFoundError(
            "Native development-client options.txt is missing; configure the client before "
            "using this launcher: " + str(options_path)
        )
    original = options_path.read_bytes()
    updated = capped_options(original)
    if updated == original:
        return {"changed": False, "fps": 60, "options": str(options_path), "backup": None}
    _require_stopped(process_query)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = backup_dir / ("options-" + stamp + "-" + uuid.uuid4().hex + ".txt")
    with backup.open("xb") as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".options-fps60-", suffix=".tmp", dir=options_path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        # Check again immediately before replacement: a game or editor may have
        # started while the backup was being written.
        _require_stopped(process_query)
        if options_path.read_bytes() != original:
            raise RuntimeError("Native options changed concurrently; backup retained, options not replaced")
        try:
            os.replace(temporary, options_path)
        except OSError as error:
            # This native options file can be EFS-encrypted. Windows then may
            # report ERROR_NOT_SAME_DEVICE for a same-directory replacement.
            # Do not weaken handling of access-denied, sharing or other errors.
            if getattr(error, "winerror", None) != 17:
                raise
            try:
                _write_options_in_place(options_path, original, updated, process_query)
            except (OSError, RuntimeError) as failure:
                raise RuntimeError(
                    "In-place FPS update failed; backup retained at %s: %s" % (backup, failure)
                ) from failure
        else:
            temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"changed": True, "fps": 60, "options": str(options_path), "backup": str(backup)}


def background_arguments(config_path):
    """Require the same suspended-child guard contract as the source project."""
    config_path = Path(config_path).resolve()
    if not config_path.is_file():
        raise FileNotFoundError("Background test tools are not configured: " + str(config_path) +
                                "; see tools/background-tools.example.json")
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    required = ("mcdk", "mcdk_sha256", "guard_dll", "guard_sha256")
    if not isinstance(config, dict) or any(not isinstance(config.get(key), str) or not config[key]
                                          for key in required):
        raise ValueError("Background tools need mcdk/mcdk_sha256/guard_dll/guard_sha256")
    mcdk = str((config_path.parent / config["mcdk"]).resolve())
    guard = str((config_path.parent / config["guard_dll"]).resolve())
    sys.path.insert(0, str(ROOT / ".agents/skills/pyreact-debugging/scripts"))
    from instances import noactivate_contract
    args = SimpleNamespace(mcdk=mcdk, noactivate_dll=guard,
                           noactivate_sha256=config["guard_sha256"],
                           noactivate_mcdk_sha256=config["mcdk_sha256"])
    noactivate_contract(args, mcdk)  # Verify pinned PE bytes and guard exports before any mutation.
    return ["--mcdk", mcdk, "--noactivate-dll", guard,
            "--noactivate-sha256", config["guard_sha256"],
            "--noactivate-mcdk-sha256", config["mcdk_sha256"]]


def launch(owner, *, game_exe=None, background_config=ROOT / "background-tools.local.json"):
    background = background_arguments(background_config)
    settings = ensure_fps_60(native_options_path(), ROOT / ".runtime/options-backups")
    runtime = ROOT / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    receipt = runtime / "latest-launch.private.json"
    errors = runtime / "latest-launch.stderr.private.log"
    command = [
        sys.executable, "-B", "-X", "utf8",
        str(ROOT / ".agents/skills/pyreact-debugging/scripts/instances.py"),
        "start", "--project", str(ROOT), "--owner", owner, "--preset", "ui", "--wait", "120",
    ]
    if game_exe:
        command.extend(["--game-exe", game_exe])
    command.extend(background)
    environment = dict(os.environ)
    environment.pop("MCDEV_ALLOW_USER_FOREGROUND", None)
    with receipt.open("wb") as output, errors.open("wb") as error_output:
        process = subprocess.run(
            command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=output, stderr=error_output,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    try:
        result = json.loads(receipt.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        result = {"state": "unreadable_launch_receipt"}
    if not isinstance(result, dict):
        result = {"state": "invalid_launch_receipt"}
    # Never echo the raw launch JSON, nested diagnostics, or a session token.
    summary = {
        "state": result.get("state", "failed"), "session_file": result.get("session_file"),
        "receipt": str(receipt), "stderr": str(errors), "fps": 60,
        "options_changed": settings["changed"], "options_backup": settings["backup"],
        "background_only": True,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if process.returncode == 0 and result.get("state") == "ready" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True, help="Unique owner used for all subsequent instance commands")
    parser.add_argument("--game-exe", help="Optional override; otherwise use the repository .mcdev.json")
    parser.add_argument("--background-config", type=Path, default=ROOT / "background-tools.local.json",
                        help="Pinned patched MCDK and focus guard config; foreground fallback is forbidden")
    args = parser.parse_args()
    try:
        return launch(args.owner, game_exe=args.game_exe, background_config=args.background_config)
    except (OSError, ValueError, RuntimeError) as error:
        print("[start_dev] " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
