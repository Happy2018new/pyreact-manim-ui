"""Capture an owner-verified Windows game using an existing WGC helper."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / ".agents/skills/pyreact-debugging/scripts"))
    from _session import load_session, process_identity
    from _window import _list_windows_windows, _find_game_window
    from _background_policy import require_background_session
    data = load_session(args.session, args.owner)
    if Path(data["project"]).resolve() != ROOT:
        raise ValueError("Capture project mismatch")
    if process_identity(data["game_pid"]) != data["game_identity"]:
        raise ValueError("Game process creation identity changed")
    before_guard = require_background_session(data)
    window = _find_game_window(_list_windows_windows(), pid=data["game_pid"])
    if window is None or window["minimized"]:
        raise RuntimeError("Owned game window missing or minimized")
    if args.output.exists():
        raise FileExistsError("Capture labels must be unique: " + str(args.output))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(args.helper.resolve()), str(window["hwnd"]),
                             str(data["game_pid"]), str(data["game_identity"]),
                             str(args.output.resolve())], capture_output=True, text=True,
                            encoding="utf-8", timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    report = json.loads(result.stdout)
    if not report["ok"] or report["frame_qpc_100ns"] < report["request_qpc_100ns"]:
        raise RuntimeError("Capture did not return a fresh frame")
    report.update(pid=data["game_pid"], window=window, file=str(args.output.resolve()),
                  background_before=before_guard, background_only=True)
    try:
        latest = load_session(args.session, args.owner)
        if latest["game_pid"] != data["game_pid"] or latest["game_identity"] != data["game_identity"]:
            raise RuntimeError("Owned game identity changed during capture")
        if process_identity(data["game_pid"]) != data["game_identity"]:
            raise RuntimeError("Owned game process exited or changed during capture")
        report["background_after"] = require_background_session(latest)
    except (RuntimeError, ValueError, OSError) as error:
        report.update(ok=False, background_after_error=str(error))
        args.output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                  encoding="utf-8")
        raise
    args.output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                              encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
