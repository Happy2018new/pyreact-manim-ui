"""Owner-bound 60 FPS launch, passive capture and finite native compatibility calls."""
import importlib.util
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
OWNER = 'manim-native-stencil-compat'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


integrated = module('native_stencil_compat_owned_host', HERE.parent/'weather_stencil_integrated_probe/host.py')
integrated.alpha.owned_host.OWNER = OWNER


if __name__ == '__main__':
    os.environ['MCDEV_ALLOW_USER_FOREGROUND'] = '1'
    if len(sys.argv) > 1 and sys.argv[1] == 'launch':
        raise SystemExit(integrated.alpha.launch())
    if len(sys.argv) > 1 and sys.argv[1] == 'resize':
        original = list(sys.argv)
        project = original[original.index('--project')+1]
        evidence = original[original.index('--evidence')+1]
        result = integrated.alpha.owned_host.main()
        if result:
            raise SystemExit(result)
        center = module('native_compat_noactivate_center', HERE.parent/'weather_stencil_integrated_probe/center.py')
        center.OWNER = OWNER
        sys.argv = ['center.py','--project',project,'--evidence',evidence,
                    '--label','center_after_resize_%d' % time.time_ns()]
        center.main()
        raise SystemExit(0)
    raise SystemExit(integrated.alpha.owned_host.main())
