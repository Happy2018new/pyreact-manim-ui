"""Move the verified owned normal window inside its work area without activation."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OWNER = 'manim-stencil-bulk'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--label', default='center')
    args = parser.parse_args()
    receipt = json.loads((args.evidence/'launch.json').read_text(encoding='utf-8'))
    os.environ.update(MCDEV_SESSION_FILE=receipt['session_file'], MCDEV_OWNER=OWNER,
                      MCDEV_ALLOW_USER_FOREGROUND='1')
    sys.path.insert(0, str(ROOT/'.agents/skills/pyreact-debugging/scripts'))
    from _session import load_session, desktop_lock
    from _background_policy import require_background_session
    import resize_window as resize
    session = load_session(live=True)
    if Path(session['project']).resolve() != args.project.resolve():
        raise ValueError('Project mismatch')
    user = ctypes.WinDLL('user32', use_last_error=True)
    setter = user.SetThreadDpiAwarenessContext
    setter.argtypes, setter.restype = [ctypes.c_void_p], ctypes.c_void_p
    previous = setter(ctypes.c_void_p(-4))
    if not previous:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        with desktop_lock():
            before = require_background_session(load_session(live=True))
            windows = [item for item in resize._list_windows() if item['pid'] == session['game_pid']]
            if len(windows) != 1:
                raise RuntimeError('Expected exactly one owned visible window')
            hwnd = windows[0]['hwnd']
            if user.IsIconic(hwnd) or user.IsZoomed(hwnd):
                raise RuntimeError('Only an owned normal window may be positioned')
            old = resize._window_rect(hwnd, include_frame=True)
            left, top, right, bottom = resize._monitor_work_area(hwnd)
            x, y = left+(right-left-old[2])//2, top+(bottom-top-old[3])//2
            if x < left or y < top:
                raise RuntimeError('Owned window does not fit monitor work area')
            # No resize, z-order change, activation, input, or restore operation.
            if not resize.user32.SetWindowPos(hwnd, 0, x, y, 0, 0, 1|4|16|512):
                raise ctypes.WinError(ctypes.get_last_error())
            after = require_background_session(load_session(live=True))
            result = {'owner': OWNER, 'session': session['id'], 'game_pid': session['game_pid'],
                      'before_outer': old, 'after_outer': resize._window_rect(hwnd, include_frame=True),
                      'work_area': [left, top, right, bottom], 'activated': False,
                      'background_before': before, 'background_after': after}
    finally:
        setter(previous)
    path = args.evidence/(args.label+'.json')
    with path.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
