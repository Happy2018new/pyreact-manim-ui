"""Fresh stock/carrier comparison packages built from the frozen integrated probe."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAMESPACE = uuid.UUID('5b241c5b-ce07-41de-a0bc-9cf96a226859')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')


def build(output, game_exe, variant, include_enchanted=False):
    if variant not in ('stock', 'carrier'):
        raise ValueError('First comparison is exact stock versus unchanged carrier only')
    integrated = module('native_compat_integrated_builder', HERE.parent/'weather_stencil_integrated_probe/build_probe.py')
    output = integrated.build(output, game_exe, include_ui=False, include_outline=True)
    resource = output/'resource_pack'
    receipt_path = output/'probe_resources.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    original_sfx = resource/'materials/sfx.material'
    carrier_sfx = original_sfx.read_bytes()
    native_sfx_path = Path(game_exe).resolve().parent/'data/resource_packs/vanilla_netease/materials/sfx.material'
    native_sfx = native_sfx_path.read_bytes()
    if variant == 'stock':
        # Stock baseline uses the actual installed native material definitions.
        # No block geometry is built in this baseline, so the experimental
        # terrain overrides are absent too.
        original_sfx.write_bytes(native_sfx)
        (resource/'materials/terrain.material').unlink()
    fixtures = {}
    frame = module('native_compat_frameani_builder', HERE.parent/'integrated_frameani_fixture/build_fixture.py')
    fixtures['frameani'] = frame.install(output, game_exe)
    if include_enchanted:
        enchanted = module('native_compat_enchanted_builder', HERE.parent/'integrated_enchanted_ui_fixture/build_fixture.py')
        fixtures['enchanted'] = enchanted.install(output)
    for folder in ('behavior_pack', 'resource_pack'):
        path = output/folder/'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['header']['name'] = 'Native stencil compatibility '+variant+' '+folder
        manifest['header']['uuid'] = str(uuid.uuid5(NAMESPACE, variant+'/'+folder+'/header'))
        for index, value in enumerate(manifest['modules']):
            value['uuid'] = str(uuid.uuid5(NAMESPACE, variant+'/'+folder+'/'+str(index)))
        write_json(path, manifest)
    receipt.update(native_compatibility={'variant': variant, 'fixtures': fixtures,
        'baseline_commit': '0c8800c', 'sfx_material_sha256': hashlib.sha256(original_sfx.read_bytes()).hexdigest(),
        'native_sfx_material_path': str(native_sfx_path), 'native_sfx_material_sha256': hashlib.sha256(native_sfx).hexdigest(),
        'unmodified_carrier_sfx_sha256': hashlib.sha256(carrier_sfx).hexdigest(),
        'stock_removes_experimental_terrain_material': variant == 'stock',
        'capacity_tested': 65536, 'alpha_packing': False, 'native_verified': False})
    write_json(receipt_path, receipt)
    write_json(output/'native_compat_build.json', {
        'variant': variant, 'fixtures': fixtures, 'builder_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'files': {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for folder in ('behavior_pack','resource_pack') for path in (output/folder).rglob('*') if path.is_file()}})
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--game-exe', type=Path, required=True)
    parser.add_argument('--variant', choices=('stock','carrier'), required=True)
    parser.add_argument('--include-enchanted', action='store_true')
    args = parser.parse_args()
    print(build(args.output, args.game_exe, args.variant, args.include_enchanted))
