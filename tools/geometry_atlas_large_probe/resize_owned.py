"""Center an owned normal window without activation, using the protected skill helper."""
import argparse
import contextlib
import ctypes
import io
import json
import os
from pathlib import Path
import sys


def main(owner):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('resize',))
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--width', type=int, default=2560)
    parser.add_argument('--height', type=int, default=1440)
    parser.add_argument('--label', default='resize')
    args = parser.parse_args()
    if args.width < 4 or args.height < 4:
        raise ValueError('Client dimensions are too small')
    root = Path(__file__).resolve().parents[2]
    launch = json.loads((args.evidence / 'launch.json').read_text(encoding='utf-8'))
    os.environ['MCDEV_SESSION_FILE'] = launch['session_file']
    os.environ['MCDEV_OWNER'] = owner
    sys.path.insert(0, str(root / '.agents/skills/pyreact-debugging/scripts'))
    from _session import load_session
    from _background_policy import require_background_session
    session = load_session(live=True)
    if Path(session['project']).resolve() != args.project.resolve():
        raise ValueError('Project mismatch')
    require_background_session(session)
    setter = ctypes.WinDLL('user32', use_last_error=True).SetThreadDpiAwarenessContext
    setter.argtypes, setter.restype = [ctypes.c_void_p], ctypes.c_void_p
    previous = setter(ctypes.c_void_p(-4))
    if not previous:
        raise ctypes.WinError(ctypes.get_last_error())
    reports = []
    try:
        import resize_window
        # The helper skips centering if size is unchanged, so nudge by2px first.
        for width in (args.width-2, args.width):
            sys.argv = ['resize_window.py', '--size', '%dx%d' % (width,args.height)]
            output = io.TextIOWrapper(io.BytesIO(),encoding='utf-8')
            with contextlib.redirect_stdout(output):
                result = resize_window.main()
            output.flush()
            reports.append(json.loads(output.buffer.getvalue().decode('utf-8')))
            if result:
                raise RuntimeError('Protected resize failed')
    finally:
        setter(previous)
    print(json.dumps({'preparation': reports[0], 'result': reports[1]}))
    return 0
