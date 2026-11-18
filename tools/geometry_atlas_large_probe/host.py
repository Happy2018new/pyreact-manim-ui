"""Owner-bound passive host; the existing launcher enforces noactivation and 60 FPS."""
import importlib.util
from pathlib import Path
import sys

SOURCE = Path(__file__).resolve().parents[1] / 'runtime_packet_probe/host.py'
SPEC = importlib.util.spec_from_file_location('large_atlas_owned_host', SOURCE)
owned_host = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(owned_host)
owned_host.OWNER = 'manim-geometry-atlas-large-r1'

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'resize':
        from resize_owned import main
        raise SystemExit(main(owned_host.OWNER))
    raise SystemExit(owned_host.main())
