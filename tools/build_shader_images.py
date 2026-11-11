"""Build an ordinary PNG atlas and four ShaderImage paperdoll slots.

Optional --manifest accepts {"id": {"file": "relative/image.png", "title": "标题"}}.
Paths are relative to the manifest. With no manifest, use original procedural
demo cards. Only image-owned outputs and the pmanim_image material are changed.
The shared geometry.pmanim_canvas is provided by tools/build_canvas.py.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import pprint
import re
import sys

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from shader_image.defaults import checkerboard, default_images


SLOT_COUNT = 4
GUTTER = 2
MAX_ATLAS_SIZE = 2048
MAX_IMAGES = 64
NAME = re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
MATERIAL_KEY = "pmanim_image:entity_static"
OWNERSHIP_FILE = "tools/shader_image/generated/ownership.json"
OWNED_FILES = frozenset((
    "resource_pack/shaders/glsl/pmanim_image.vertex",
    "resource_pack/shaders/glsl/pmanim_image.fragment",
    "resource_pack/textures/manim/images_atlas.png",
    "resource_pack/textures/manim/images_checker.png",
    "resource_pack/render_controllers/pmanim_image.render_controllers.json",
    "behavior_pack/manim_ui/images/generated.py",
    "tools/shader_image/generated/materials.json",
    "tools/shader_image/generated/manifest.json",
) + tuple("resource_pack/entity/pmanim_image_%d.entity.json" % slot for slot in range(SLOT_COUNT))
  + tuple("behavior_pack/entities/pmanim_image_%d.json" % slot for slot in range(SLOT_COUNT)))


def json_bytes(value, sort_keys=True):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=sort_keys) + "\n").encode("utf-8")


def png_bytes(image):
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=False)
    return stream.getvalue()


def digest(contents):
    return hashlib.sha256(contents).hexdigest()


def checked_path(output, relative):
    target = output / relative
    resolved = target.resolve()
    if not resolved.is_relative_to(output) or resolved != target:
        raise ValueError("Image output escapes its directory or traverses a symbolic link: " + relative)
    return target


def load_images(manifest=None):
    if manifest is None:
        return default_images(), {"kind": "original_procedural", "generator": "tools/shader_image/defaults.py"}
    path = Path(manifest).resolve()
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, dict) or not entries or len(entries) > MAX_IMAGES:
        raise ValueError("Image manifest must contain 1 to %d named images" % MAX_IMAGES)
    images = {}
    for key, entry in sorted(entries.items()):
        if not NAME.fullmatch(key) or not isinstance(entry, dict) or set(entry) != {"file", "title"}:
            raise ValueError("Each image needs a valid id and exactly file/title fields: " + key)
        if not isinstance(entry["file"], str) or not entry["file"] or not isinstance(entry["title"], str) or not entry["title"]:
            raise ValueError("Image file and title must be nonempty strings: " + key)
        image_path = (path.parent / entry["file"]).resolve()
        with Image.open(image_path) as source:
            if source.format != "PNG":
                raise ValueError("ShaderImage inputs must be ordinary PNG images: " + key)
            if getattr(source, "n_frames", 1) != 1:
                raise ValueError("Animated PNG is unsupported; select a single PNG frame: " + key)
            if max(source.size) > MAX_ATLAS_SIZE - GUTTER * 2:
                raise ValueError("Image exceeds the %d-pixel atlas budget: " % MAX_ATLAS_SIZE + key)
            images[key] = (source.convert("RGBA"), entry["title"])
    return images, {"kind": "png_manifest", "entries": entries}


def power_of_two(value):
    return 1 << (value - 1).bit_length()


def pack_images(images):
    """Deterministic shelf packing; keep original pixels and two-pixel gutters."""
    width = min(MAX_ATLAS_SIZE, power_of_two(sum(image.width + GUTTER * 2 for image, _ in images.values())))
    x, y, row_height = 0, 0, 0
    positions = {}
    for key, (image, _) in sorted(images.items()):
        padded_width, padded_height = image.width + GUTTER * 2, image.height + GUTTER * 2
        if padded_width > width or padded_height > MAX_ATLAS_SIZE:
            raise ValueError("Image exceeds the atlas budget: " + key)
        if x + padded_width > width:
            x, y, row_height = 0, y + row_height, 0
        positions[key] = (x + GUTTER, y + GUTTER)
        x += padded_width
        row_height = max(row_height, padded_height)
    height = power_of_two(y + row_height)
    if height > MAX_ATLAS_SIZE:
        raise ValueError("Images do not fit the %d x %d atlas budget" % (MAX_ATLAS_SIZE, MAX_ATLAS_SIZE))
    atlas = Image.new("RGBA", (width, height))
    metadata = {}
    for key, (image, title) in sorted(images.items()):
        x, y = positions[key]
        atlas.paste(image, (x, y))
        metadata[key] = {"uv": (x / float(width), y / float(height), image.width / float(width), image.height / float(height)),
                         "size": image.size, "title": title}
    return atlas, metadata


def image_material():
    return {"vertexShader": "shaders/pmanim_image.vertex", "fragmentShader": "shaders/pmanim_image.fragment",
            "+states": ["DisableCulling", "DisableDepthTest", "DisableDepthWrite", "Blending"],
            "blendSrc": "One", "blendDst": "OneMinusSrcAlpha",
            "alphaSrc": "One", "alphaDst": "OneMinusSrcAlpha",
            "samplerStates": [{"samplerIndex": 0, "textureWrap": "Clamp", "textureFilter": "Point"}]}


def entity_definitions(slot):
    identifier = "pmanim:image_%d" % slot
    client = {"format_version": "1.10.0", "minecraft:client_entity": {"description": {
        "identifier": identifier, "materials": {"default": "pmanim_image"},
        "geometry": {"default": "geometry.pmanim_canvas"},
        "textures": {"default": "textures/manim/images_atlas"},
        "render_controllers": ["controller.render.pmanim_image"]}}}
    behavior = {"format_version": "1.16.0", "minecraft:entity": {
        "description": {"identifier": identifier, "is_spawnable": False, "is_summonable": False, "is_experimental": False},
        "components": {"minecraft:physics": {"has_gravity": False, "has_collision": False}}}}
    return client, behavior


def read_ownership(output):
    path = checked_path(output, OWNERSHIP_FILE)
    if not path.exists():
        return {"files": {}, "material_sha256": None}
    previous = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(previous, dict) or previous.get("generator") != "tools/build_shader_images.py" or previous.get("schema_version") != 1:
        raise ValueError("Unknown image ownership manifest")
    files = previous.get("files")
    if not isinstance(files, dict) or not set(files).issubset(OWNED_FILES):
        raise ValueError("Image ownership manifest contains an unowned path")
    checksums = list(files.values()) + [previous.get("material_sha256")]
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in checksums):
        raise ValueError("Invalid image ownership checksum")
    return previous


def prepare_material(output, previous):
    path = checked_path(output, "resource_pack/materials/entity.material")
    document = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"materials": {"version": "1.0.0"}}
    if not isinstance(document, dict) or not isinstance(document.get("materials"), dict):
        raise ValueError("Expected entity.material to contain a materials object")
    material = image_material()
    current = document["materials"].get(MATERIAL_KEY)
    previous_checksum = previous["material_sha256"]
    if current is not None and previous_checksum is not None and digest(json_bytes(current)) != previous_checksum:
        raise ValueError("Previously generated image material was modified; preserve it for review")
    if current is not None and previous_checksum is None and current != material:
        raise ValueError("Refusing to replace an unowned image material")
    document["materials"][MATERIAL_KEY] = material
    # Preserve unrelated entries' nested order: the canvas builder hashes its
    # material objects without sorting, so reordering them breaks ownership.
    return path, json_bytes(document, sort_keys=False)


def build(root=ROOT, output=None, manifest=None):
    root = Path(root).resolve()
    output = Path(output).resolve() if output is not None else root
    images, provenance = load_images(manifest)
    atlas, metadata = pack_images(images)
    template = (root / "tools/shader_image/pmanim_image.fragment").read_text(encoding="utf-8")
    if template.count("@ATLAS_WIDTH@") != 1 or template.count("@ATLAS_HEIGHT@") != 1:
        raise ValueError("Image shader atlas-size placeholders are missing")
    fragment = template.replace("@ATLAS_WIDTH@", str(atlas.width)).replace("@ATLAS_HEIGHT@", str(atlas.height))
    vertex = (root / "tools/canvas/pmanim_canvas.vertex").read_bytes()
    if b"EXTRA_ACTOR_UNIFORM3" not in vertex or b"gl_Position.xy" not in vertex:
        raise ValueError("The measured NDC canvas vertex contract is missing")
    generated = ("# -*- coding: utf-8 -*-\n# Generated by tools/build_shader_images.py; Python 2 runtime metadata only.\n"
                 "SLOT_COUNT = %d\nATLAS_SIZE = %r\nIMAGES = %s\n" %
                 (SLOT_COUNT, atlas.size, pprint.pformat(metadata, width=110, sort_dicts=True)))
    plans = {
        "resource_pack/shaders/glsl/pmanim_image.vertex": vertex,
        "resource_pack/shaders/glsl/pmanim_image.fragment": fragment.encode("utf-8"),
        "resource_pack/textures/manim/images_atlas.png": png_bytes(atlas),
        "resource_pack/textures/manim/images_checker.png": png_bytes(checkerboard()),
        "behavior_pack/manim_ui/images/generated.py": generated.encode("utf-8"),
        "resource_pack/render_controllers/pmanim_image.render_controllers.json": json_bytes({
            "format_version": "1.8.0", "render_controllers": {"controller.render.pmanim_image": {
                "geometry": "Geometry.default", "materials": [{"*": "Material.default"}], "textures": ["Texture.default"]}}}),
        "tools/shader_image/generated/materials.json": json_bytes({"materials": {"version": "1.0.0", MATERIAL_KEY: image_material()}}),
        "tools/shader_image/generated/manifest.json": json_bytes({
            "schema_version": 1, "atlas_size": atlas.size, "gutter": GUTTER, "inputs": provenance,
            "images": {key: dict(entry, rgba_sha256=digest(images[key][0].tobytes())) for key, entry in metadata.items()}}),
    }
    for slot in range(SLOT_COUNT):
        client, behavior = entity_definitions(slot)
        plans["resource_pack/entity/pmanim_image_%d.entity.json" % slot] = json_bytes(client)
        plans["behavior_pack/entities/pmanim_image_%d.json" % slot] = json_bytes(behavior)
    previous = read_ownership(output)
    owned = {relative: digest(contents) for relative, contents in plans.items()}
    # Preflight every existing file and material before changing any resource.
    for relative, checksum in previous["files"].items():
        target = checked_path(output, relative)
        if target.exists() and digest(target.read_bytes()) != checksum:
            raise ValueError("Previously generated image resource was modified; preserve it for review: " + relative)
    for relative, contents in plans.items():
        target = checked_path(output, relative)
        if relative not in previous["files"] and target.exists() and target.read_bytes() != contents:
            raise ValueError("Refusing to replace an unowned image resource: " + relative)
    material_path, material_contents = prepare_material(output, previous)
    ownership = {"schema_version": 1, "generator": "tools/build_shader_images.py", "files": owned,
                 "material_sha256": digest(json_bytes(image_material()))}
    ownership_path = checked_path(output, OWNERSHIP_FILE)
    for relative, contents in plans.items():
        target = checked_path(output, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
    material_path.parent.mkdir(parents=True, exist_ok=True)
    material_path.write_bytes(material_contents)
    # This builder has a fixed output set; an older tracked file may disappear
    # in future versions only if it is still in the explicit ownership allowlist.
    stale = sorted(set(previous["files"]) - set(plans))
    for relative in stale:
        target = checked_path(output, relative)
        if target.exists():
            target.unlink()
    ownership_path.parent.mkdir(parents=True, exist_ok=True)
    ownership_path.write_bytes(json_bytes(ownership))
    return {"images": list(metadata), "atlas_size": atlas.size, "entities": SLOT_COUNT,
            "files_written": len(plans) + 2, "stale_files_removed": len(stale), "output": str(output)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="JSON mapping image ids to file/title entries")
    parser.add_argument("--output", type=Path, help="Optional isolated BP/RP output directory")
    arguments = parser.parse_args()
    print(json.dumps(build(output=arguments.output, manifest=arguments.manifest), ensure_ascii=False, indent=2))
