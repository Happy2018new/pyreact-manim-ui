"""Owner-bound host for the large scene codec. No launch is implicit."""
import importlib.util
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('scene_large_owned_host',ROOT/'tools/runtime_packet_probe/host.py')
owned_host=importlib.util.module_from_spec(spec)
spec.loader.exec_module(owned_host)
owned_host.OWNER='manim-scene-codec-large'

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='resize':
        resize_spec=importlib.util.spec_from_file_location('scene_large_resize',ROOT/'tools/geometry_atlas_large_probe/resize_owned.py')
        resize=importlib.util.module_from_spec(resize_spec)
        resize_spec.loader.exec_module(resize)
        raise SystemExit(resize.main(owned_host.OWNER))
    raise SystemExit(owned_host.main())
