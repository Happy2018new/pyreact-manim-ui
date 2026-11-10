"""Prepare isolated static resources. This script never operates Minecraft."""

import argparse
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import runtime_data


def prepare(output):
    output = Path(output).resolve()
    marker = output / runtime_data.MARKER
    if output.exists() and any(output.iterdir()) and not marker.exists():
        raise ValueError("Refusing to overwrite a non-probe resource pack")
    if marker.exists() and json.loads(marker.read_text(encoding="utf-8")).get("probe") != "pmanim_runtime_data_v1":
        raise ValueError("Existing marker has a different owner")
    output.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"probe": "pmanim_runtime_data_v1"}), encoding="utf-8")
    manifest = {
        "format_version": 2,
        "header": {"name": "Pyreact Manim Runtime Data Probe (developer only)",
                   "description": "Isolated dynamic texture experiment; not production support",
                   "uuid": "4326bf70-5d0b-4b03-8fb1-d126057414f8", "version": [0, 0, 1],
                   "min_engine_version": [1, 18, 0]},
        "modules": [{"type": "resources", "uuid": "aec425e8-6683-431b-937a-a246b0a0956b",
                     "version": [0, 0, 1]}],
    }
    material = {
        runtime_data.MATERIAL: {
            "vertexShader": "shaders/uv_fullscreen.vertex",
            "fragmentShader": "shaders/pmanim_runtime_probe.fragment",
            "vertexFields": [{"field": "Position"}, {"field": "UV0"}],
            "samplerStates": [{"samplerIndex": index, "textureWrap": "Clamp", "textureFilter": "Point"}
                              for index in range(3)],
            "states": ["DisableDepthTest"], "msaaSupport": "Both",
        }
    }
    for relative, value in (("manifest.json", manifest), ("materials/postprocess.material", material)):
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    shader = output / "shaders/glsl/pmanim_runtime_probe.fragment"
    shader.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HERE / "runtime_probe.fragment", shader)
    texture_dir = output / runtime_data.TEXTURE_DIRECTORY
    texture_dir.mkdir(parents=True, exist_ok=True)
    # Blue/magenta baseline cannot be mistaken for runtime-produced B=0 data.
    pixels = bytes(channel for index in range(256)
                   for channel in (255 if index % 2 else 0, 0, 255, 255))
    for slot in ("placeholder", "overwrite"):
        (texture_dir / (slot + ".png")).write_bytes(runtime_data.encode_png(pixels))
    shutil.copyfile(HERE / "runtime_data.py", output.parent / "runtime_data.py")
    return {"resource_pack": str(output), "runtime_module": str(output.parent / "runtime_data.py"),
            "material": runtime_data.MATERIAL, "marker": str(marker),
            "placeholder_texture": runtime_data.TEXTURE_DIRECTORY + "/placeholder"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(prepare(arguments.output), indent=2))
