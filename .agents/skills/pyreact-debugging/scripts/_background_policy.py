"""Project rule: observe protected game windows without acquiring focus."""
from pathlib import Path

from _window import background_guard_state


def require_protected_session(session):
    protection = session.get("noactivation") if isinstance(session, dict) else None
    if not isinstance(protection, dict) or protection.get("requested") is not True:
        raise RuntimeError("Background-only testing requires a noactivation-protected owned session")


def require_background_session(session):
    """Reject absent/minimized/foreground windows; never repair them by activation."""
    require_protected_session(session)
    pid = session["game_pid"]
    guard = background_guard_state(pid, Path(session["game_executable"]).name)
    foreground = guard.get("foreground", {})
    windows = guard.get("windows", [])
    if (type(foreground.get("pid")) is not int or foreground["pid"] == pid
            or guard.get("background_safe") is not True
            or guard.get("window_noactivate") is not True or not windows):
        raise RuntimeError("Owned game is not protected in the background; no activation fallback is allowed")
    for window in windows:
        if (window.get("pid") != pid or window.get("noactivate") is not True
                or window.get("minimized") is not False):
            raise RuntimeError("Owned background window is missing, minimized, or unprotected")
    return guard


def require_passive_tool(name, arguments):
    if name == "mc_input" and arguments.get("op") not in ("/help", "/state"):
        raise RuntimeError("Background-only testing disables desktop input; use SDK/UI callbacks and passive capture")
