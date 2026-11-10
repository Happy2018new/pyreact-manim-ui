"""Inspect an owner-bound MC player and capture its current window via MCDK."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--seek", type=float)
    parser.add_argument("--select", type=int)
    parser.add_argument("--play", action="store_true")
    parser.add_argument("--hide", action="store_true")
    parser.add_argument("--flip-y", type=int, choices=(0, 1))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    os.environ["MCDEV_SESSION_FILE"] = str(Path(args.session).resolve())
    os.environ["MCDEV_OWNER"] = args.owner
    sys.path.insert(0, str(ROOT / ".agents/skills/pyreact-debugging/scripts"))
    from _session import load_session
    from _background_policy import require_background_session
    from mcdk import Client, return_value
    session = load_session(live=True)
    if Path(session["project"]).resolve() != ROOT:
        raise ValueError("This probe only operates on the current project")
    require_background_session(session)
    code = ["import json", "import mod.client.extraClientApi as api",
            "player = api.GetSystem('pyreact_manim_ui', 'player')",
            "assert player is not None, 'Manim player did not initialize'"]
    if args.select is not None:
        code.append("player.select_scene(%r)" % args.select)
    if args.flip_y is not None:
        code.extend(["player.flip_y = %r" % bool(args.flip_y), "player._last_parameters = None"])
    if args.seek is not None:
        code.extend(["player.show()", "player.seek(%r)" % args.seek])
    if args.play:
        code.append("player.toggle_play()")
    if args.hide:
        code.append("player.hide()")
    code.append("_result = json.dumps(player.snapshot())")
    with Client() as client:
        result = return_value(client.call("execute_code", {
            "code": "\n".join(code), "is_client": True, "direct_return": True,
        }))
    if isinstance(result, str):
        result = json.loads(result)
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
