"""Exercise the shipped canvas API in an owned background game, with real frames."""
import argparse
import hashlib
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
    parser.add_argument("--capture-helper", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use a new evidence directory")
    os.environ["MCDEV_SESSION_FILE"] = args.session
    os.environ["MCDEV_OWNER"] = args.owner
    sys.path.insert(0, str(ROOT / ".agents/skills/pyreact-debugging/scripts"))
    from _session import load_session
    from _background_policy import require_background_session
    from mcdk import Client, return_value
    session = load_session(live=True)
    if Path(session["project"]).resolve() != ROOT:
        raise ValueError("Canvas verification project mismatch")
    require_background_session(session)
    args.output.mkdir(parents=True)
    report = {"background_only": True, "physical_input_tested": False,
              "frames": [], "checks": [], "loads": []}
    shader = ROOT / "resource_pack/shaders/glsl/pmanim_canvas_runtime_shapes.fragment"
    report["runtime_shader_before"] = hashlib.sha256(shader.read_bytes()).hexdigest()

    with Client(timeout=50) as client:
        def execute(body):
            code = ("import json\nimport mod.client.extraClientApi as api\n"
                    "from manim_ui import canvas\n"
                    "player = api.GetSystem('pyreact_manim_ui', 'player')\n"
                    "demo = player.canvas_demo\n" + body)
            value = return_value(client.call("execute_code", {
                "code": code, "is_client": True, "direct_return": True}))
            return json.loads(value) if isinstance(value, str) else value

        def state(body=""):
            return execute(body + "\n_result = json.dumps(player.canvas_snapshot())")

        def capture(label):
            output = args.output / (label + ".png")
            result = subprocess.run([
                sys.executable, "-B", "-X", "utf8", str(ROOT / "tools/capture_owned.py"),
                "--session", args.session, "--owner", args.owner,
                "--helper", str(args.capture_helper), "--output", str(output)],
                capture_output=True, text=True, encoding="utf-8", timeout=25,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode:
                (args.output / (label + ".private.log")).write_text(result.stdout + result.stderr, encoding="utf-8")
                raise RuntimeError("Capture failed; inspect the private log")
            return str(output)

        execute("assert player.open_canvas_panel()\n_result = True")
        time.sleep(0.4)
        current = state()
        assert all(current["ready"].values()), current
        names = execute("_result = json.dumps(demo.names)")
        for index, name in enumerate(names):
            current = state("assert demo.load_left(%r)" % name)
            report["loads"].append(current["left"]["last_load"])
            for step, timestamp in enumerate((0.0, current["left"]["duration"] / 2, current["left"]["duration"])):
                current = state("assert demo.left.seek(%r)" % timestamp)
                assert current["left"]["scene"] == name
                assert current["left"]["visible"] and not current["left"]["error"]
                assert current["left"]["position"] == timestamp and not current["left"]["playing"]
                assert current["right"]["scene"] == "runtime_shapes" and current["right"]["position"] == 0.0
                time.sleep(0.15)
                report["frames"].append({"scene": name, "time": timestamp,
                    "capture": capture("scene_%d_step_%d" % (index, step))})
        report["checks"].append("ten compiled canvas scenes: start/mid/end; right state unchanged")
        current = state("assert demo.set_shape(morph=.371, progress=.623, scale=.837, "
                        "rotation=.419, color=(.173, .627, .913))")
        assert current["shape"]["morph"] == .371
        time.sleep(0.15)
        report["frames"].append({"scene": "runtime_shapes", "state": current["shape"],
                                 "capture": capture("runtime-arbitrary")})
        state("assert demo.left.seek(0.0)\nassert demo.right.seek(0.0)\n"
              "assert demo.left.play()\nassert demo.right.play()")
        time.sleep(0.4)
        current = state("demo.left.pause()\ndemo.right.pause()")
        assert current["left"]["position"] > 0 and current["right"]["position"] > 0
        time.sleep(0.2)
        paused = state()
        assert paused["left"]["position"] == current["left"]["position"]
        assert paused["right"]["position"] == current["right"]["position"]
        report["checks"].append("both independent clocks advance and remain stable after pause")
        current = state("assert demo.load_left(%r)" % names[0])
        assert current["left"]["last_load"]["reused"]
        report["reuse"] = current["left"]["last_load"]
        report["fps"] = execute("_result = player.game.GetFps()")
        assert 0 < report["fps"] <= 61.0
        for attempt in range(3):
            execute("assert player.close_canvas_panel()\n_result = True")
            time.sleep(0.25)
            closed = execute("_result = json.dumps({'none': player.canvas_demo is None, "
                             "'slots': [x is None for x in canvas._SLOT_OWNERS], "
                             "'original': player.snapshot()})")
            assert closed["none"] and all(closed["slots"]), closed
            assert closed["original"]["visible"] and not closed["original"]["error"], closed
            if attempt < 2:
                execute("assert player.open_canvas_panel()\n_result = True")
                time.sleep(0.3)
                assert all(state()["ready"].values())
        report["checks"].append("three close/reopen cycles release both slots and restore the original player")
    require_background_session(load_session(live=True))
    report["runtime_shader_after"] = hashlib.sha256(shader.read_bytes()).hexdigest()
    assert report["runtime_shader_before"] == report["runtime_shader_after"]
    report["passed"] = True
    (args.output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "frames": len(report["frames"]), "fps": report["fps"],
                      "report": str((args.output / "report.json").resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
