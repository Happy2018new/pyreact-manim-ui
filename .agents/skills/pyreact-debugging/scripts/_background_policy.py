"""Project rule: observe protected game windows without acquiring focus."""
from pathlib import Path

from _window import background_guard_state, foreground_policy_satisfied


def require_protected_session(session):
    protection = session.get("noactivation") if isinstance(session, dict) else None
    if not isinstance(protection, dict) or protection.get("requested") is not True:
        raise RuntimeError("Background-only testing requires a noactivation-protected owned session")


def require_background_session(session):
    """Observe protected windows; explicit opt-in permits user-owned foreground."""
    require_protected_session(session)
    pid = session["game_pid"]
    guard = background_guard_state(pid, Path(session["game_executable"]).name)
    windows = guard.get("windows", [])
    if (not foreground_policy_satisfied(guard, pid)
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
