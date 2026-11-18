"""Owner-bound passive host for the isolated scene codec experiment."""
import importlib.util
import os
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'runtime_packet_probe/host.py'
spec = importlib.util.spec_from_file_location('scene_codec_owned_host', SOURCE)
owned_host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owned_host)
owned_host.OWNER = 'manim-scene-codec'

if __name__ == '__main__':
    # The user may foreground the owned game. This grants no agent activation
    # or input permission; the underlying host still verifies noactivation.
    os.environ['MCDEV_ALLOW_USER_FOREGROUND'] = '1'
    raise SystemExit(owned_host.main())
