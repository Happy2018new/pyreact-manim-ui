"""Owner-bound passive host for the finite UI sampler experiment."""
import importlib.util
import os
from pathlib import Path
import sys

SOURCE=Path(__file__).resolve().parents[1]/'ui_alpha_probe/host.py'
spec=importlib.util.spec_from_file_location('texture_owned_host',SOURCE)
alpha=importlib.util.module_from_spec(spec)
spec.loader.exec_module(alpha)
alpha.owned_host.OWNER='manim-ui-texture-binding'

if __name__=='__main__':
    os.environ['MCDEV_ALLOW_USER_FOREGROUND']='1'
    if len(sys.argv)>1 and sys.argv[1]=='launch':
        raise SystemExit(alpha.launch())
    raise SystemExit(alpha.owned_host.main())
