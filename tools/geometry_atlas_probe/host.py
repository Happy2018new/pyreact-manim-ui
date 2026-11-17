"""Owner-bound background-only host for the geometry scene-atlas fixture."""
import importlib.util
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[1]/'runtime_packet_probe/host.py'
spec=importlib.util.spec_from_file_location('geometry_atlas_owned_host',SOURCE)
owned_host=importlib.util.module_from_spec(spec)
spec.loader.exec_module(owned_host)
owned_host.OWNER='manim-geometry-atlas'

if __name__=='__main__':
    raise SystemExit(owned_host.main())
