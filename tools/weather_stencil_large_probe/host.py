"""Owner-bound, noactivation host for the sequential bulk stencil research."""
import importlib.util
import os
from pathlib import Path
import sys
import time

SOURCE=Path(__file__).resolve().parents[1]/'ui_alpha_probe/host.py'
spec=importlib.util.spec_from_file_location('bulk_stencil_owned_host',SOURCE)
alpha=importlib.util.module_from_spec(spec)
spec.loader.exec_module(alpha)
alpha.owned_host.OWNER='manim-stencil-bulk'

if __name__=='__main__':
    os.environ['MCDEV_ALLOW_USER_FOREGROUND']='1'
    if len(sys.argv)>1 and sys.argv[1]=='launch':
        raise SystemExit(alpha.launch())
    if len(sys.argv)>1 and sys.argv[1]=='resize':
        original=list(sys.argv)
        project=original[original.index('--project')+1]
        evidence=original[original.index('--evidence')+1]
        result=alpha.owned_host.main()
        if result:
            raise SystemExit(result)
        # The inherited resize retains the old origin. Large windows also need
        # a verified position inside the physical monitor work area.
        import center
        sys.argv=['center.py','--project',project,'--evidence',evidence,
                  '--label','center_after_resize_%d'%time.time_ns()]
        center.main()
        raise SystemExit(0)
    raise SystemExit(alpha.owned_host.main())
