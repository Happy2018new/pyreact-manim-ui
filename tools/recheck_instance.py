"""Revalidate a slow, already-started owned instance without starting another game."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--owner", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / ".agents/skills/pyreact-debugging/scripts"))
    from _session import load_session, write_json, file_lock
    from instances import ReadinessClient, verify_startup_endpoint
    from mcdk import return_value
    from _window import background_guard_state, foreground_policy_satisfied
    data = load_session(args.session, args.owner)
    if Path(data["project"]).resolve() != ROOT:
        raise ValueError("Readiness probe project mismatch")
    if data["state"] not in ("failed", "starting", "ready"):
        raise ValueError("Cannot revive a stopped instance")
    with file_lock(Path(data["session_file"]).with_suffix(".lock")):
        verify_startup_endpoint(data)
        with ReadinessClient(data, time.monotonic() + 30) as client:
            identity = return_value(client.call("execute_code", {
                "code": "import os\n_result = {'pid': os.getpid(), 'appdata': os.environ.get('APPDATA')}",
                "is_client": True, "direct_return": True,
            }))
            if identity != {"pid": data["game_pid"], "appdata": data["appdata"]}:
                raise RuntimeError("Game identity/data root mismatch")
            for side in (True, False):
                marker = return_value(client.call("execute_code", {
                    "code": "import sys\n_result = getattr(sys, '_pyreact_mcdk_session', None)",
                    "is_client": side, "direct_return": True,
                }))
                if marker != data["token"]:
                    raise RuntimeError("Game runtime session marker mismatch")
        verify_startup_endpoint(data)
        if data.get("noactivation"):
            guard = background_guard_state(data["game_pid"], Path(data["game_executable"]).name)
            if not foreground_policy_satisfied(guard, data["game_pid"]) or not guard["window_noactivate"]:
                raise RuntimeError("Owned instance noactivation contract no longer holds")
        data.setdefault("readiness_rechecks", []).append({
            "time": time.time(), "previous_state": data["state"],
            "previous_error": data.get("error"), "client_server_markers_verified": True,
        })
        data.update(state="ready", ready=True)
        data.pop("error", None)
        write_json(data["session_file"], data)
    print(json.dumps({"state": data["state"], "ready": data["ready"],
                      "session_file": data["session_file"], "game_pid": data["game_pid"]}, indent=2))


if __name__ == "__main__":
    main()
