"""Deploy compiled scenes into this repository's small standalone demo addon."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import pprint
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
TITLES = {
    "manimgl_o_to_b": "字形变换：O → B",
    "manimgl_c_to_s": "字形变换：C → S",
    "manimgl_8_to_1": "多轮廓预览：8 → 1",
    "manimgl_ui_to_ux": "多字符预览：UI → UX",
    "manimgl_ai_to_ui": "单词变换：AI → UI",
    "manimgl_hello_to_world": "单词变换：HELLO → WORLD",
    "manimgl_code_to_math": "单词变换：CODE → MATH",
    "basic_geometry": "二维图形：变形、旋转与缩放",
    "axes_sine": "坐标轴：绘制曲线与沿路径运动",
}


def validate_manifest(manifest):
    """Check the runtime contract before planning any deployment writes."""
    if not isinstance(manifest, dict):
        raise ValueError("Compiled scene manifest must be an object")
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] not in (1, 2):
        raise ValueError("Unsupported compiled scene schema_version; expected 1 or 2")
    name = manifest.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", name):
        raise ValueError("Invalid resource identifier: " + repr(name))
    duration = manifest.get("duration")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise ValueError("Scene duration must be a finite positive number")
    if not 0 < duration <= 86400 or not math.isfinite(duration):
        raise ValueError("Scene duration must be finite and within (0, 86400]")
    texture = manifest.get("texture")
    if not isinstance(texture, dict):
        raise ValueError("Compiled scene texture metadata must be an object")
    if type(texture.get("sampler")) is not int or texture["sampler"] != 2:
        raise ValueError("This runtime requires texture sampler 2")
    if texture.get("encoding") != "rg16_unorm":
        raise ValueError("This runtime requires rg16_unorm texture encoding")
    if texture.get("filter") != "Point":
        raise ValueError("Data texture filtering must be Point")
    for label in ("texture", "shader"):
        artifact = manifest.get(label)
        if not isinstance(artifact, dict):
            raise ValueError(label + " artifact metadata must be an object")
        if not isinstance(artifact.get("path"), str) or not artifact["path"]:
            raise ValueError(label + " artifact path must be a nonempty string")
        digest = artifact.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(label + " artifact sha256 is invalid")


def artifact_path(directory, relative, digest):
    candidate = (directory / relative).resolve()
    if not candidate.is_relative_to(directory.resolve()):
        raise ValueError("Artifact must remain inside the compiled scene directory")
    if hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
        raise ValueError("Compiled artifact checksum mismatch: " + relative)
    return candidate


def deploy(scene_directories):
    scene_directories = list(scene_directories)
    if not scene_directories:
        raise ValueError("At least one compiled scene is required; existing deployment was preserved")
    resource = ROOT / "resource_pack"
    scenes = []
    materials = {}
    plans = []
    for directory in scene_directories:
        directory = Path(directory).resolve()
        manifest = json.loads((directory / "scene.json").read_text(encoding="utf-8"))
        validate_manifest(manifest)
        name = manifest["name"]
        if any(scene["name"] == name for scene in scenes):
            raise ValueError("Duplicate scene: " + name)
        texture = artifact_path(directory, manifest["texture"]["path"], manifest["texture"]["sha256"])
        shader = artifact_path(directory, manifest["shader"]["path"], manifest["shader"]["sha256"])
        material = "pmanim_" + name
        plans.extend([(texture, resource / "textures/manim" / (name + ".png")),
                      (shader, resource / "shaders/glsl" / (name + ".fragment"))])
        scenes.append({
            "name": name, "title": TITLES.get(name, name.replace("_", " ")),
            "duration": manifest["duration"], "material": material,
            "post_name": material, "texture": "textures/manim/" + name,
        })
        materials[material] = {
            "vertexShader": "shaders/uv_fullscreen.vertex",
            "fragmentShader": "shaders/" + name + ".fragment",
            "vertexFields": [{"field": "Position"}, {"field": "UV0"}],
            "samplerStates": [{"samplerIndex": index, "textureWrap": "Clamp", "textureFilter": "Point"}
                              for index in range(3)],
            "states": ["DisableDepthTest"], "msaaSupport": "Both",
        }
    for source, destination in plans:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    material_path = resource / "materials/postprocess.material"
    material_path.parent.mkdir(parents=True, exist_ok=True)
    material_path.write_text(json.dumps(materials, indent=2) + "\n", encoding="utf-8")
    config = ROOT / "behavior_pack/manim_ui/generated_scenes.py"
    config.write_text("# -*- coding: utf-8 -*-\n# Generated by tools/deploy_demo.py.\nSCENES = " +
                      pprint.pformat(scenes, width=100, sort_dicts=True) + "\n", encoding="utf-8")
    return {"scenes": [scene["name"] for scene in scenes], "files_copied": len(plans),
            "materials": str(material_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenes", nargs="+", help="Compiled scene directories")
    args = parser.parse_args()
    print(json.dumps(deploy(args.scenes), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
