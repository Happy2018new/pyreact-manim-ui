"""Compile the repository's static Python examples and deploy the demo addon."""
import argparse
import json
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_definitions(path):
    """Load an explicit nonempty scene list before building or deploying."""
    definitions = runpy.run_path(str(path)).get("SCENES")
    if not isinstance(definitions, (list, tuple)) or not definitions:
        raise ValueError("Examples must define a nonempty SCENES list or tuple")
    if any(not isinstance(definition, dict) for definition in definitions):
        raise ValueError("Each SCENES entry must be an ExportSettings dictionary")
    return definitions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--examples", type=Path, default=ROOT / "examples/text_transforms.py")
    parser.add_argument("--render-reference", action="store_true")
    parser.add_argument("--skip-2d", action="store_true", help="Only build the text definitions")
    args = parser.parse_args()
    definitions = load_definitions(args.examples)
    from pyreact_manim.reference import ExportSettings, export_text_transform
    from pyreact_manim.compiler import compile_scene
    from deploy_demo import deploy

    outputs = []
    for definition in definitions:
        settings = ExportSettings(render_reference=args.render_reference, **definition)
        exported = export_text_transform(ROOT / ".runtime/reference" / settings.name, settings)
        scene = json.loads(exported["scene"].read_text(encoding="utf-8"))
        output = ROOT / ".runtime/compiled" / settings.name
        compile_scene(scene, output)
        outputs.append(output)
    if not args.skip_2d:
        scenes = runpy.run_path(str(ROOT / "examples/basic_2d.py"))["build_scenes"]()
        for definition in scenes:
            scene = definition.export()
            output = ROOT / ".runtime/compiled" / scene["name"]
            compile_scene(scene, output)
            outputs.append(output)
    result = deploy(outputs)
    from build_canvas import build as build_canvas
    result["canvas"] = build_canvas()
    from build_showcase import build as build_showcase
    result["showcase"] = build_showcase()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
