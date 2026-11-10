"""Build transparent UI canvas resources from the deployed scene shaders.

The compiler's opaque postprocess output remains unchanged. This adapter
accepts its known schema 1/2 blend operations and rejects unknown structures.
"""

import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import pprint
import re


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "pmanim_canvas"
NAME = re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
OWNERSHIP_FILE = "tools/canvas/generated_files.json"
OWNED_PATTERNS = tuple(re.compile(pattern + r"\Z") for pattern in (
    r"resource_pack/shaders/glsl/pmanim_canvas\.vertex",
    r"resource_pack/shaders/glsl/pmanim_canvas_[a-z][a-z0-9_]{0,47}\.fragment",
    r"resource_pack/entity/pmanim_canvas_[01]_[a-z][a-z0-9_]{0,47}\.entity\.json",
    r"behavior_pack/entities/pmanim_canvas_[01]_[a-z][a-z0-9_]{0,47}\.json",
    r"resource_pack/models/entity/pmanim_canvas\.geo\.json",
    r"resource_pack/render_controllers/pmanim_canvas\.render_controllers\.json",
    r"behavior_pack/manim_ui/generated_canvas\.py",
))
MATERIAL_NAME = re.compile(r"pmanim_canvas(?:_[a-z][a-z0-9_]{0,47}:pmanim_canvas|:entity_static)\Z")
COMPOSITE_HELPER = """
// Accumulate all paths and strokes in premultiplied form. The material uses
// SourceAlpha blending, so convert to straight alpha only at the final output.
void canvasOver(inout vec3 premultiplied, inout float alpha, vec3 rgb, float coverage) {
    float a = clamp(coverage, 0.0, 1.0);
    premultiplied = rgb * a + premultiplied * (1.0 - a);
    alpha = a + alpha * (1.0 - a);
}
"""
RUNTIME_FRAGMENT = """// __multiversion__
// Parameterized runtime shapes: no per-value shader or atlas compilation.
precision highp float;
#include "fragmentVersionCentroidUV.h"
uniform vec4 EXTRA_ACTOR_UNIFORM1; // time_seconds, aspect, pixel_height, opacity
uniform vec4 EXTRA_ACTOR_UNIFORM2; // circle-to-box morph, reveal, stroke width, scale
uniform vec4 EXTRA_ACTOR_UNIFORM4; // red, green, blue, rotation radians

float boxDistance(vec2 p, vec2 halfSize) {
    vec2 delta = abs(p) - halfSize;
    return length(max(delta, vec2(0.0))) + min(max(delta.x, delta.y), 0.0);
}

void main() {
    float aspect = max(EXTRA_ACTOR_UNIFORM1.y, 0.001);
    float pixelHeight = max(EXTRA_ACTOR_UNIFORM1.z, 1.0);
    float opacity = clamp(EXTRA_ACTOR_UNIFORM1.w, 0.0, 1.0);
    float morph = clamp(EXTRA_ACTOR_UNIFORM2.x, 0.0, 1.0);
    float progress = clamp(EXTRA_ACTOR_UNIFORM2.y, 0.0, 1.0);
    float strokeWidth = max(EXTRA_ACTOR_UNIFORM2.z, 0.0);
    float scale = max(EXTRA_ACTOR_UNIFORM2.w, 0.001);
    float phase = EXTRA_ACTOR_UNIFORM1.x * 1.5707963267948966;
    vec2 drift = vec2(0.035 * sin(phase), 0.02 * (cos(phase) - 1.0));
    vec2 p = (uv - vec2(0.5)) * vec2(aspect, 1.0) - drift;
    float angle = EXTRA_ACTOR_UNIFORM4.w;
    float c = cos(angle), s = sin(angle);
    vec2 q = vec2(c * p.x + s * p.y, -s * p.x + c * p.y) / scale;
    float circle = length(q) - 0.32;
    float rectangle = boxDistance(q, vec2(0.36, 0.25));
    float distanceToShape = mix(circle, rectangle, morph) * scale;
    if (strokeWidth > 0.0) distanceToShape = abs(distanceToShape) - strokeWidth * 0.5;
    float aa = 1.0 / pixelHeight;
    float coverage = 1.0 - smoothstep(-aa, aa, distanceToShape);
    if (progress <= 0.0) coverage = 0.0;
    else if (progress < 1.0) {
        // Clockwise reveal beginning at the top, in the rotated shape's frame.
        float turn = fract(atan(q.y, q.x) / 6.283185307179586 + 1.25);
        float angularAA = aa / max(length(p), aa) / 6.283185307179586;
        coverage *= 1.0 - smoothstep(progress - angularAA, progress + angularAA, turn);
    }
    gl_FragColor = vec4(clamp(EXTRA_ACTOR_UNIFORM4.rgb, 0.0, 1.0), coverage * opacity);
}
"""


def transparent_fragment(source):
    """Adapt only known emitted operations; never silently lose path alpha."""
    required = ("// __multiversion__", '#include "fragmentVersionCentroidUV.h"',
                "uniform sampler2D TEXTURE_0;", "uniform sampler2D TEXTURE_2;", "void main() {")
    if any(source.count(part) != 1 for part in required):
        raise ValueError("Unsupported compiler shader header")
    source = source.replace("uniform sampler2D TEXTURE_0;\n", "", 1)
    source = source.replace("TEXTURE_2", "TEXTURE_0")
    source = source.replace("EXTRA_VECTOR1", "EXTRA_ACTOR_UNIFORM1")
    source = source.replace("EXTRA_VECTOR2", "EXTRA_ACTOR_UNIFORM2")
    source, count = re.subn(r"vec3 color = vec3\([^;\n]+\);",
                            "vec3 canvasPremultiplied = vec3(0.0);\n    float canvasAlpha = 0.0;", source)
    if count != 1:
        raise ValueError("Unsupported compiler background initialization")
    operations = (
        ("color = mix(color, fill.rgb, fill.a * fillCoverage);", "fill.rgb", "fill.a * fillCoverage"),
        ("color = mix(color, stroke.rgb, stroke.a * strokeCoverage);", "stroke.rgb", "stroke.a * strokeCoverage"),
        ("color = mix(color, fill.rgb, coverage * 1.06);", "fill.rgb", "coverage * 1.06"),
    )
    converted = 0
    for before, rgb, alpha in operations:
        converted += source.count(before)
        source = source.replace(before, "canvasOver(canvasPremultiplied, canvasAlpha, " + rgb + ", " + alpha + ");")
    if not converted or "color = mix" in source:
        raise ValueError("Unsupported compiler path composition")
    old_output = ("vec4 original = texture2D(TEXTURE_0, uv);\n    "
                  "gl_FragColor = mix(original, vec4(color, 1.0), clamp(EXTRA_ACTOR_UNIFORM1.w, 0.0, 1.0));")
    if source.count(old_output) != 1:
        raise ValueError("Unsupported compiler fragment output")
    output = ("vec3 straightColor = canvasAlpha > 0.0 ? canvasPremultiplied / canvasAlpha : vec3(0.0);\n    "
              "gl_FragColor = vec4(straightColor, canvasAlpha * clamp(EXTRA_ACTOR_UNIFORM1.w, 0.0, 1.0));")
    source = source.replace(old_output, output)
    source = source.replace("void main() {", COMPOSITE_HELPER + "\nvoid main() {", 1)
    if re.search(r"\bcolor\b", re.sub(r"//[^\n]*", "", source)):
        raise ValueError("Unrecognized compiler color expression remains")
    return source


def read_scenes(path):
    module = ast.parse(Path(path).read_text(encoding="utf-8"))
    definitions = [node for node in module.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "SCENES" for target in node.targets)]
    if len(definitions) != 1:
        raise ValueError("Expected exactly one generated SCENES declaration")
    scenes = ast.literal_eval(definitions[0].value)
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("At least one deployed scene is required")
    names = set()
    for scene in scenes:
        name = scene.get("name")
        duration = scene.get("duration")
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in names or name == "runtime_shapes":
            raise ValueError("Invalid or duplicate scene name")
        if isinstance(duration, bool) or not isinstance(duration, (float, int)) or not math.isfinite(duration) or duration <= 0:
            raise ValueError("Invalid scene duration")
        if scene.get("texture") != "textures/manim/" + name or not isinstance(scene.get("title"), str):
            raise ValueError("Unexpected deployed texture/title contract")
        names.add(name)
    return scenes


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def digest(contents):
    return hashlib.sha256(contents).hexdigest()


def checked_output_path(output, relative):
    """Validate final absolute file paths before any output write or unlink."""
    target = output / relative
    resolved = target.resolve()
    if not resolved.is_relative_to(output) or resolved != target:
        raise ValueError("Canvas output escapes its directory or traverses a symbolic link: " + relative)
    return target


def previous_ownership(output):
    path = checked_output_path(output, OWNERSHIP_FILE)
    if not path.exists():
        return {"files": {}, "materials": {}}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("generator") != "tools/build_canvas.py" or manifest.get("schema_version") != 1:
        raise ValueError("Unknown canvas ownership manifest")
    for group in ("files", "materials"):
        records = manifest.get(group)
        if not isinstance(records, dict):
            raise ValueError("Invalid canvas ownership records")
        for key, checksum in records.items():
            valid = (any(pattern.fullmatch(key) for pattern in OWNED_PATTERNS) if group == "files"
                     else MATERIAL_NAME.fullmatch(key))
            if not valid or not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
                raise ValueError("Canvas ownership manifest contains an unowned path or material")
    return manifest


def geometry():
    return {"format_version": "1.12.0", "minecraft:geometry": [{
        "description": {"identifier": "geometry." + PREFIX, "texture_width": 16, "texture_height": 16,
                        "visible_bounds_width": 8, "visible_bounds_height": 8, "visible_bounds_offset": [0, 0.5, 0]},
        "bones": [{"name": "root", "pivot": [0, 0, 0], "cubes": [{
            "origin": [-16, 0, 0], "size": [32, 18, 0],
            "uv": {"south": {"uv": [0, 0], "uv_size": [16, 16]}}}]}],
    }]}


def entity_definitions(name, slot, texture):
    identifier = "pmanim:canvas_" + str(slot) + "_" + name
    client = {"format_version": "1.10.0", "minecraft:client_entity": {"description": {
        "identifier": identifier, "materials": {"default": PREFIX + "_" + name},
        "geometry": {"default": "geometry." + PREFIX}, "textures": {"default": texture},
        "render_controllers": ["controller.render." + PREFIX],
    }}}
    behavior = {"format_version": "1.16.0", "minecraft:entity": {
        "description": {"identifier": identifier, "is_spawnable": False,
                        "is_summonable": False, "is_experimental": False},
        "components": {"minecraft:physics": {"has_gravity": False, "has_collision": False}},
    }}
    return identifier, client, behavior


def build(root=ROOT, output=None):
    root = Path(root).resolve()
    output = Path(output).resolve() if output is not None else root
    resource = output / "resource_pack"
    behavior = output / "behavior_pack"
    scenes = [scene for scene in read_scenes(root / "behavior_pack/manim_ui/generated_scenes.py")
              if scene.get("canvas_compatible", True)]
    vertex = (root / "tools/canvas/pmanim_canvas.vertex").read_bytes()
    if b"EXTRA_ACTOR_UNIFORM3" not in vertex or b"gl_Position.xy" not in vertex:
        raise ValueError("The measured NDC canvas vertex contract is missing")
    plans = {resource / "shaders/glsl/pmanim_canvas.vertex": vertex,
             resource / "models/entity/pmanim_canvas.geo.json": json_bytes(geometry()),
             resource / "render_controllers/pmanim_canvas.render_controllers.json": json_bytes({
                 "format_version": "1.8.0", "render_controllers": {"controller.render." + PREFIX: {
                     "geometry": "Geometry.default", "materials": [{"*": "Material.default"}],
                     "textures": ["Texture.default"],
                 }}})}
    materials = {"version": "1.0.0", PREFIX + ":entity_static": {
        "vertexShader": "shaders/pmanim_canvas.vertex",
        "+states": ["DisableCulling", "DisableDepthTest", "DisableDepthWrite", "Blending"],
        "blendSrc": "SourceAlpha", "blendDst": "OneMinusSrcAlpha",
        "samplerStates": [{"samplerIndex": 0, "textureWrap": "Clamp", "textureFilter": "Point"}],
    }}
    manifest = []
    all_scenes = scenes + [{"name": "runtime_shapes", "title": "运行时图元：圆形、矩形与描边",
                           "duration": 4.0, "texture": "textures/ui/white_bg"}]
    for scene in all_scenes:
        name = scene["name"]
        if name == "runtime_shapes":
            fragment = RUNTIME_FRAGMENT
        else:
            texture = root / "resource_pack" / (scene["texture"] + ".png")
            texture_bytes = texture.read_bytes()
            source = (root / "resource_pack/shaders/glsl" / (name + ".fragment")).read_text(encoding="utf-8")
            fragment = transparent_fragment(source)
            if output != root:
                plans[resource / (scene["texture"] + ".png")] = texture_bytes
        fragment_name = PREFIX + "_" + name
        plans[resource / "shaders/glsl" / (fragment_name + ".fragment")] = fragment.encode("utf-8")
        materials[fragment_name + ":" + PREFIX] = {"fragmentShader": "shaders/" + fragment_name + ".fragment"}
        identifiers = []
        for slot in (0, 1):
            identifier, client, server = entity_definitions(name, slot, scene["texture"])
            stem = PREFIX + "_" + str(slot) + "_" + name
            plans[resource / "entity" / (stem + ".entity.json")] = json_bytes(client)
            plans[behavior / "entities" / (stem + ".json")] = json_bytes(server)
            identifiers.append(identifier)
        manifest.append({"name": name, "title": scene["title"], "duration": scene["duration"],
                         "identifiers": identifiers})
    # Entity materials are an engine-recognized file. Preserve unrelated keys.
    material_path = resource / "materials/entity.material"
    existing = json.loads(material_path.read_text(encoding="utf-8")) if material_path.exists() else {"materials": {}}
    existing_materials = existing.setdefault("materials", {})
    previous = previous_ownership(output)
    for key, checksum in previous["materials"].items():
        if key in existing_materials and digest(json_bytes(existing_materials[key])) != checksum:
            raise ValueError("Previously generated material was modified; preserve it for review: " + key)
        if key not in materials:
            existing_materials.pop(key, None)
    for key, value in materials.items():
        if key != "version" and key in existing_materials and key not in previous["materials"] and existing_materials[key] != value:
            raise ValueError("Refusing to replace an unowned material: " + key)
    existing_materials.update(materials)
    plans[material_path] = json_bytes(existing)
    config = "# -*- coding: utf-8 -*-\n# Generated by tools/build_canvas.py.\nCANVAS_SCENES = "
    plans[behavior / "manim_ui/generated_canvas.py"] = (config + pprint.pformat(manifest, width=100, sort_dicts=True) + "\n").encode("utf-8")
    # Only tracked tool outputs can be pruned. Shared scene atlases and the
    # shared entity.material file are never deletion candidates.
    owned = {target.relative_to(output).as_posix(): digest(contents) for target, contents in plans.items()
             if any(pattern.fullmatch(target.relative_to(output).as_posix()) for pattern in OWNED_PATTERNS)}
    stale = []
    for relative, checksum in previous["files"].items():
        target = checked_output_path(output, relative)
        if target.exists() and digest(target.read_bytes()) != checksum:
            raise ValueError("Previously generated resource was modified; preserve it for review: " + relative)
        if relative not in owned and target.exists():
            stale.append(target)
    for target, contents in plans.items():
        relative = target.relative_to(output).as_posix()
        checked_output_path(output, relative)
        if relative in owned and relative not in previous["files"] and target.exists() and target.read_bytes() != contents:
            raise ValueError("Refusing to replace an unowned resource: " + relative)
    ownership = {"generator": "tools/build_canvas.py", "schema_version": 1, "files": owned,
                 "materials": {key: digest(json_bytes(value)) for key, value in materials.items() if key != "version"}}
    for target, contents in plans.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
    for target in stale:
        target.unlink()
    ownership_path = checked_output_path(output, OWNERSHIP_FILE)
    ownership_path.parent.mkdir(parents=True, exist_ok=True)
    ownership_path.write_bytes(json_bytes(ownership))
    return {"scenes": [scene["name"] for scene in manifest], "entities": len(manifest) * 2,
            "files_written": len(plans), "stale_files_removed": len(stale), "output": str(output)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional isolated BP/RP output directory")
    arguments = parser.parse_args()
    print(json.dumps(build(output=arguments.output), ensure_ascii=False, indent=2))
