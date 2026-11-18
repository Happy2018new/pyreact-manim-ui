"""Build a separate, paged alpha-atlas experiment without changing the old probe."""
import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = HERE.parent / 'geometry_atlas_probe'


def build(output):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Choose a new isolated output directory; existing evidence is immutable')
    spec = importlib.util.spec_from_file_location('large_atlas_asset_base', BASE / 'build_probe.py')
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    base.build(output)
    package = output / 'behavior_pack/geometry_atlas_probe'
    (package / 'runtime.py').write_bytes((HERE / 'runtime.py').read_bytes())
    mod = (BASE / 'modMain.py').read_text(encoding='utf-8')
    (package / 'modMain.py').write_text(mod.replace('pmanim_geometry_atlas_probe',
        'pmanim_geometry_atlas_large_probe'), encoding='utf-8')
    shaders = output / 'resource_pack/shaders/glsl'
    scatter = (BASE / 'scatter.vertex').read_text(encoding='utf-8')
    scatter = scatter.replace('vec2 grid = vec2(mod(record, columns), floor(record / columns));',
        'record += EXTRA_ACTOR_UNIFORM4.z; // page base, after local bounds check\n'
        '    vec2 grid = vec2(mod(record, columns), floor(record / columns));')
    (shaders / 'scatter.vertex').write_text(scatter, encoding='utf-8')
    (shaders / 'geometry_atlas_consumer.fragment').write_bytes((HERE / 'consumer.fragment').read_bytes())
    process = base.pipeline_config()
    process['paras'][0]['range'] = [0., 2097152.]
    process['paras'][1]['range'] = [0., 2097152.]
    process['paras'][2]['range'] = [0., 2097152.]
    (package / 'pipeline_config.py').write_text('# -*- coding: utf-8 -*-\nPROCESS = ' + repr(process) + '\n', encoding='utf-8')
    (package / 'pipeline.json').write_text(json.dumps(process, indent=2), encoding='utf-8')
    config = json.loads((ROOT / '.mcdev.json').read_text(encoding='utf-8'))
    config['included_mod_dirs'] = ['./']
    (output / '.mcdev.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    metadata = {'kind': 'geometry_atlas_large_probe_v1', 'runtime_file_writes': False,
        'page_bytes': 65536, 'max_bytes': 2097152, 'max_pages': 32,
        'source_layout': {'columns': 2048, 'left': 8, 'top': 32, 'cell': 1},
        'screen_size': [2560, 1440], 'diagnostic': {'left': 16, 'top': 128, 'columns': 2048,
        'bytes_per_native_pixel': 1, 'outside_rgb': [8, 16, 32]},
        'border_guard_rect_native': [0, 128, 2560, 1408],
        'runtime': {'system_namespace': 'pmanim_geometry_atlas_large_probe', 'system_name': 'probe'},
        'build_reuses': str(BASE), 'old_probe_sources_modified': False}
    (output / 'probe_resources.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(build(parser.parse_args().output))
