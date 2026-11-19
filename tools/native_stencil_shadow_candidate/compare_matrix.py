"""Compare saved255/191/63 candidate evidence without any game operations."""
import argparse
import importlib.util
import json
from pathlib import Path


SPEC = importlib.util.spec_from_file_location('saved_shadow_mask_matrix_oracle', Path(__file__).with_name('verify.py'))
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for mask in (255, 191, 63):
        parser.add_argument('--evidence-%d' % mask, type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify.compare_matrix({mask: getattr(args, 'evidence_%d' % mask) for mask in (255, 191, 63)})
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))
    if not result['operational_complete']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
