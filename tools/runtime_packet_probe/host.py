"""Explicit owner-bound launcher/caller for the isolated runtime packet study."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".agents/skills/pyreact-debugging/scripts"
OWNER = "manim-runtime-packets"


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("launch", "call", "capture", "stop", "resize"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--code", type=Path)
    parser.add_argument("--label", default="state")
    parser.add_argument("--timeout", type=float, default=40.)
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--force", action="store_true", help="stop only: terminate the verified owned instance")
    args = parser.parse_args()
    if args.force and args.action != "stop":
        parser.error("--force is only valid with stop")
    project = args.project.resolve()
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(SCRIPTS))
    if args.action == "launch":
        if (evidence / "launch.private.json").exists() or (evidence / "launch.json").exists():
            raise ValueError("Preserve the existing instance receipt; choose a fresh evidence directory")
        if not (project / "probe_resources.json").is_file():
            raise ValueError("Expected generated research project")
        starter = load_file("packet_start_dev", ROOT / "tools/start_dev.py")
        background = starter.background_arguments(ROOT / "background-tools.local.json")
        settings = starter.ensure_fps_60(starter.native_options_path(), evidence / "options-backups")
        environment = dict(os.environ)
        environment.pop("MCDEV_ALLOW_USER_FOREGROUND", None)
        command = [sys.executable, "-B", "-X", "utf8", str(SCRIPTS / "instances.py"),
                   "start", "--project", str(project), "--owner", OWNER,
                   "--preset", "ui", "--wait", "120"] + background
        with (evidence / "launch.private.json").open("wb") as output, (evidence / "launch.stderr.log").open("wb") as error:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output, stderr=error,
                                    env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
        receipt = json.loads((evidence / "launch.private.json").read_text(encoding="utf-8-sig"))
        summary = {"state": receipt.get("state"), "session_file": receipt.get("session_file"),
                   "fps": settings["fps"], "background_only": True}
        (evidence / "launch.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary))
        return result.returncode
    summary = json.loads((evidence / "launch.json").read_text(encoding="utf-8"))
    os.environ["MCDEV_SESSION_FILE"] = summary["session_file"]
    os.environ["MCDEV_OWNER"] = OWNER
    from _session import load_session
    from _background_policy import require_background_session
    session = load_session(live=args.action != "stop")
    if Path(session["project"]).resolve() != project:
        raise ValueError("Project mismatch")
    if args.action == "stop":
        # A failed launch or an assertion dialog need not have a protected game
        # window. Cleanup uses owner/project plus verified process identities;
        # it does not send input to or activate that dialog.
        from instances import stop
        result = stop(session, args.force)
        print(json.dumps({"state": result["state"]}))
        return 0
    require_background_session(session)
    if args.action == 'resize':
        import ctypes
        if args.width <= 0 or args.height <= 0:
            raise ValueError('Client dimensions must be positive')
        user = ctypes.WinDLL('user32', use_last_error=True)
        setter = user.SetThreadDpiAwarenessContext
        setter.argtypes = [ctypes.c_void_p]
        setter.restype = ctypes.c_void_p
        previous = setter(ctypes.c_void_p(-4))
        if not previous:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            resize = load_file('packet_resize', SCRIPTS / 'resize_window.py')
            sys.argv = ['resize_window.py', '--size', '%dx%d' % (args.width, args.height),
                        '--no-center']
            return resize.main()
        finally:
            setter(previous)
    if args.action == "call":
        from mcdk import Client, return_value
        code = "import json\nimport mod.client.extraClientApi as api\nprobe=api.GetSystem('pmanim_packet_probe','probe')\n"
        code += args.code.read_text(encoding="utf-8")
        with Client(timeout=args.timeout) as client:
            result = return_value(client.call("execute_code", {
                "code": code, "is_client": True, "direct_return": True}))
        if isinstance(result, str):
            result = json.loads(result)
        require_background_session(load_session(live=True))
        (evidence / (args.label + ".state.json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"saved": args.label + ".state.json", "keys": list(result) if isinstance(result, dict) else None,
                          "running": result.get('running') if isinstance(result, dict) else None}, ensure_ascii=False))
        return 0
    # Reuse the established passive WGC helper and identity guards for this
    # explicitly generated research project, without editing production tools.
    capture = load_file("packet_capture", ROOT / "tools/capture_owned.py")
    capture.ROOT = project
    output = evidence / (args.label + ".png")
    sys.argv = ["capture_owned.py", "--session", summary["session_file"], "--owner", OWNER,
                "--helper", str(ROOT.parent / "better-building-editor/tools/data/snow-passive-startup-r12-v6/inputs/capture/native_wgc_capture.exe"),
                "--output", str(output)]
    capture.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
