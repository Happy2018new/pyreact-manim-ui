"""Background, owner-bound showcase state and actual-frame acceptance."""
import argparse
import json
import math
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
    parser.add_argument("--capture-helper", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--times", help="Comma-separated capture times; defaults to six chapter samples")
    parser.add_argument("--skip-playback", action="store_true", help="Capture targeted frames without repeating the full film")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use a fresh evidence directory")
    os.environ["MCDEV_SESSION_FILE"] = str(Path(args.session).resolve())
    os.environ["MCDEV_OWNER"] = args.owner
    sys.path.insert(0, str(ROOT / ".agents/skills/pyreact-debugging/scripts"))
    from _session import load_session
    from _background_policy import require_background_session
    from mcdk import Client, return_value
    session = load_session(live=True)
    if Path(session["project"]).resolve() != ROOT:
        raise ValueError("Showcase verification project mismatch")
    report = {"background_only": True, "physical_input_tested": False,
              "background_before": require_background_session(session), "frames": [], "playback": []}
    args.output.mkdir(parents=True)
    with Client(timeout=50) as client:
        def execute(body):
            value = return_value(client.call("execute_code", {
                "code": "import json\nimport mod.client.extraClientApi as api\n"
                        "player=api.GetSystem('pyreact_manim_ui','player')\n" + body,
                "is_client": True, "direct_return": True,
            }))
            return json.loads(value) if isinstance(value, str) else value

        original = execute("player.pause()\n_result=json.dumps(player.snapshot())")
        accepted = execute("_result=player.open_showcase()")
        assert accepted, "Showcase page did not accept navigation"
        time.sleep(1.5)
        state = execute("_result=json.dumps(player.snapshot())")
        assert state["scene"] == "client_showcase" and not state["error"], state
        report["initial"] = state
        report["load_timings"] = execute("_result=json.dumps(player.load_timings())")
        duration = state["duration"]
        timestamps = ([float(value) for value in args.times.split(",")] if args.times
                      else [duration * ratio for ratio in (0.1,0.2,0.32,0.47,0.72,0.97)])
        if any(not math.isfinite(value) or not 0 <= value <= duration for value in timestamps):
            raise ValueError("Capture times must be finite and within the film")
        for timestamp in timestamps:
            current = execute("player.seek(%r)\n_result=json.dumps({'state':player.snapshot(),"
                              "'canvas':player.canvas,'fps':player.game.GetFps()})" % timestamp)
            assert current["canvas"] == [0.0, 1.0], current
            assert current["state"]["position"] == timestamp and not current["state"]["error"], current
            time.sleep(0.4)
            output = args.output / ("game-%06d.png" % round(timestamp*1000))
            capture = subprocess.run([
                sys.executable, "-B", "-X", "utf8", str(ROOT / "tools/capture_owned.py"),
                "--session", args.session, "--owner", args.owner,
                "--helper", args.capture_helper, "--output", str(output)],
                capture_output=True, text=True, encoding="utf-8", timeout=25,
                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            if capture.returncode:
                raise RuntimeError(capture.stderr or capture.stdout)
            current["capture"] = str(output)
            report["frames"].append(current)
            (args.output / "checkpoint.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
            print(json.dumps({"frame":timestamp,"fps":current["fps"]}),flush=True)
        if not args.skip_playback:
            assert execute("_result=player.replay_showcase()")
            for _ in range(int(duration / 6.0)+1):
                time.sleep(6.0)
                current = execute("_result=json.dumps({'state':player.snapshot(),'fps':player.game.GetFps()})")
                assert not current["state"]["error"], current
                report["playback"].append(current)
                print(json.dumps({"playing":current["state"]["playing"],
                                  "position":current["state"]["position"],"fps":current["fps"]}),flush=True)
            assert report["playback"][-1]["state"]["position"] == duration
            assert not report["playback"][-1]["state"]["playing"]
        assert execute("_result=player.close_showcase()")
        time.sleep(0.5)
        restored = execute("_result=json.dumps(player.snapshot())")
        assert restored["scene"] == original["scene"] and restored["position"] == original["position"], restored
        assert not restored["playing"]
        report["restored"] = restored
    report["background_after"] = require_background_session(load_session(live=True))
    report["passed"] = True
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"passed":True,"report":str(args.output / "report.json")}),flush=True)


if __name__ == "__main__":
    main()
