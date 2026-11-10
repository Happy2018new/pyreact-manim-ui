"""Compile exported Manim geometry to portable MC rendering artifacts."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pyreact_manim.compiler import compile_scene


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Exported scene JSON")
    parser.add_argument("--output", required=True, type=Path, help="Artifact output directory")
    args = parser.parse_args()
    scene = json.loads(args.input.read_text(encoding="utf-8-sig"))
    print(compile_scene(scene, args.output))


if __name__ == "__main__":
    main()
