"""Verify player state through an owner-bound game; optionally capture real frames.

State checks exercise the player API, not mouse hit-testing or pixel parity.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture-helper", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use a new evidence directory: " + str(args.output))
    os.environ["MCDEV_SESSION_FILE"] = str(Path(args.session).resolve())
    os.environ["MCDEV_OWNER"] = args.owner
    sys.path.insert(0, str(ROOT / ".agents/skills/pyreact-debugging/scripts"))
    from _session import load_session
    from _background_policy import require_background_session
    from mcdk import Client, return_value
    session = load_session(live=True)
    if Path(session["project"]).resolve() != ROOT:
        raise ValueError("Player verification project mismatch")
    before_guard = require_background_session(session)
    args.output.mkdir(parents=True)
    report = {"kind": "live_player_api_and_capture", "mouse_input_verified": False,
              "pixel_parity_verified": False, "frames": [], "fps": [], "playback_samples": [], "checks": [],
              "background_only": True, "background_before": before_guard}

    with Client() as client:
        def execute(body):
            code = ("import json\nimport mod.client.extraClientApi as api\n"
                    "player = api.GetSystem('pyreact_manim_ui', 'player')\n" + body)
            value = return_value(client.call("execute_code", {
                "code": code, "is_client": True, "direct_return": True,
            }))
            return json.loads(value) if isinstance(value, str) else value

        def state(body=""):
            return execute(body + "\n_result = json.dumps(player.snapshot())")

        report["viewport"] = execute(
            "_result = json.dumps({'logical': player.game.GetScreenSize(), "
            "'physical': player.game.GetScreenViewInfo(), 'used': player.viewport, 'canvas': player.canvas})")
        assert list(report["viewport"]["used"]) == list(report["viewport"]["physical"][:2]), report["viewport"]
        scenes = execute("_result = json.dumps(player.scenes)")
        for index, scene in enumerate(scenes):
            state("assert player.select_scene(%d)" % index)
            for step, timestamp in enumerate((0.0, scene["duration"] / 2, scene["duration"])):
                current = state("player.seek(%r)" % timestamp)
                assert current["visible"] and not current["error"] and current["flip_y"]
                assert current["position"] == timestamp and not current["playing"]
                time.sleep(0.3)
                frame = {"state": current, "fps": execute("_result = player.game.GetFps()")}
                if args.capture_helper:
                    output = args.output / ("scene_%d_step_%d.png" % (index, step))
                    capture = subprocess.run([
                        sys.executable, "-B", "-X", "utf8", str(ROOT / "tools/capture_owned.py"),
                        "--session", args.session, "--owner", args.owner,
                        "--helper", str(args.capture_helper), "--output", str(output),
                    ], capture_output=True, text=True, encoding="utf-8", timeout=25,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    if capture.returncode:
                        raise RuntimeError(capture.stderr or capture.stdout)
                    frame["capture"] = str(output)
                report["frames"].append(frame)
        report["checks"].append("all scenes: install, seek start/midpoint/endpoint, visible, paused, no reported error")
        for index, scene in enumerate(scenes):
            state("assert player.select_scene(%d)\nplayer.seek(0.0)\nplayer.toggle_play()" % index)
            time.sleep(0.3)
            current = state("player.toggle_play()")
            fps = execute("_result = player.game.GetFps()")
            assert not current["playing"] and not current["error"]
            assert 0.0 < current["position"] < scene["duration"], current
            assert 0.0 < fps <= 61.0, fps
            report["playback_samples"].append({"state": current, "fps": fps})
        report["checks"].append("all scenes advance during playback and pause without reported errors; FPS samples respect cap")
        state("player.select_scene(0)\nplayer.seek(0.0)\nplayer.toggle_play()")
        time.sleep(0.65)
        paused = state("player.toggle_play()")
        assert not paused["playing"] and 0.1 < paused["position"] < 2.0, paused
        time.sleep(0.3)
        stable = state()
        assert stable["position"] == paused["position"], (paused, stable)
        report["checks"].append("play advances; pause keeps the same position")
        state("player.seek(2.0)\nplayer.toggle_play()")
        time.sleep(0.25)
        replay = state("player.toggle_play()")
        assert 0.0 < replay["position"] < 1.5, replay
        report["checks"].append("play at endpoint restarts at the beginning")
        hidden = state("player.hide()")
        assert not hidden["visible"] and not hidden["playing"], hidden
        execute("from manim_ui import pyreact\npyreact.navigator.pop()\n_result = True")
        time.sleep(0.4)
        closed = execute("_result = json.dumps({'subscribers': len(player._subscribers), 'top': api.GetTopUI()})")
        assert closed["subscribers"] == 0, closed
        state("player.on_key({'key': player._reopen_key, 'isDown': '0', 'screenName': api.GetTopUI()})")
        time.sleep(0.4)
        remounted = state()
        subscribers = execute("_result = len(player._subscribers)")
        assert remounted["visible"] and not remounted["error"] and subscribers == 1, remounted
        report["checks"].append("hide stops playback; navigator pop cleans subscriptions; synthetic F8 release on actual HUD reopens with one subscription")
        for _ in range(4):
            report["fps"].append(execute("_result = player.game.GetFps()"))
            time.sleep(1.0)
        assert all(0 < fps <= 61 for fps in report["fps"]), report["fps"]
        report["checks"].append("four FPS samples at or below the configured 60 FPS cap (1 FPS rounding tolerance)")
        state("player.select_scene(0)\nplayer.seek(1.0)")

    report["background_after"] = require_background_session(load_session(live=True))
    report["passed"] = True
    output = args.output / "report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "frames": len(report["frames"]),
                      "fps": report["fps"], "background_only": report["background_only"],
                      "report": str(output.resolve())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
