"""Generate a small isolated packet probe BP/RP; never start the game.

The local Python 2 runtime is copied with the requested slot count. No production
pack is read, copied, or modified. Global engine postprocess settings are omitted.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import uuid
import zlib


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MARKER = ".pmanim_packet_probe.json"
NAMESPACE = uuid.UUID("f694ab6e-b388-4cb8-b552-31ea2fe1b95a")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_pixel(path, rgba):
    """Write one RGBA pixel using only the Python standard library."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    raw = b"\x89PNG\r\n\x1a\n"
    raw += chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    raw += chunk(b"IDAT", zlib.compress(b"\x00" + bytes(rgba)))
    raw += chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def control(kind, size, offset=(0, 0), layer=0, **extra):
    result = {"type": kind, "size": list(size), "offset": list(offset),
              "anchor_from": "top_left", "anchor_to": "top_left", "layer": layer}
    result.update(extra)
    return result


def write_manifests(output):
    for pack, module_type in (("behavior_pack", "data"), ("resource_pack", "resources")):
        write_json(output / pack / "manifest.json", {
            "format_version": 2,
            "header": {"name": "PManim Runtime Packet Probe " + module_type,
                       "description": "Isolated CURRENT_COLOR inheritance and two-pass UI diagnostic",
                       "uuid": str(uuid.uuid5(NAMESPACE, pack)), "version": [0, 0, 1],
                       "min_engine_version": [1, 18, 0]},
            "modules": [{"type": module_type, "uuid": str(uuid.uuid5(NAMESPACE, pack + "/module")),
                         "version": [0, 0, 1]}],
        })


def write_ui(resource, slots, block_fallback=False):
    controls = [{"background": control("image", ("100%", "100%"),
                  texture="textures/pmanim_packet/white", color=[0.08, 0.12, 0.18], keep_ratio=False)}]
    records = []
    for index in range(slots):
        name = "slot_%03d" % index
        # Hidden controls need no off-screen layout range before configure().
        offset = [0, 0]
        size = [270, 16]
        children = [
            {"carrier": control("image", (1, 1), layer=10 + index * 2,
                 texture="textures/pmanim_packet/transparent", color=[1.0, 1.0, 1.0],
                 alpha=1.0, keep_ratio=False)},
            {"canvas": control("custom", size, layer=11 + index * 2,
                 renderer="netease_paper_doll_renderer", rotation="none",
                 init_rot_x=0.0, init_rot_y=0.0, init_rot_z=0.0,
                 screen_scale=1.0, enable_scissor_test=True)},
        ]
        if block_fallback:
            children.append({"block_canvas": control("custom", size, layer=11 + index * 2,
                 renderer="netease_paper_doll_renderer", rotation="none", visible=False,
                 init_rot_x=90.0, init_rot_y=0.0, init_rot_z=0.0,
                 screen_scale=1.0, enable_scissor_test=True)})
        controls.append({name: control("panel", size, offset, visible=False, controls=children)})
        record = {"index": index, "identifier": "pmanim_packet:" + name,
                  "panel_path": "/" + name, "carrier_path": "/" + name + "/carrier",
                  "canvas_path": "/" + name + "/canvas", "offset": offset, "size": size}
        if block_fallback:
            record["block_canvas_path"] = "/" + name + "/block_canvas"
        records.append(record)
    # Static pure RGB blocks allow the host to identify UI postprocessing.
    controls.append({"post_marker": control("image", (24, 24), (16, 4),
                     layer=4, texture="textures/pmanim_packet/white", color=[1.0, 0.0, 0.0])})
    write_json(resource / "ui/pmanim_packet_probe.json", {
        "namespace": "pmanim_packet_probe",
        # Keep the carrier/consumer pairs above ordinary HUD draws. Otherwise
        # another renderer can overwrite CURRENT_COLOR between the two nodes.
        "main": control("screen", ("100%", "100%"), layer=1000, controls=controls),
    })
    write_json(resource / "ui/_ui_defs.json", {"ui_defs": ["ui/pmanim_packet_probe.json"]})
    return records


def write_entities(resource, behavior, slots):
    write_json(resource / "models/entity/pmanim_packet.geo.json", {
        "format_version": "1.12.0", "minecraft:geometry": [{
            "description": {"identifier": "geometry.pmanim_packet", "texture_width": 16,
                "texture_height": 16, "visible_bounds_width": 8, "visible_bounds_height": 8,
                "visible_bounds_offset": [0, 0.5, 0]},
            "bones": [{"name": "root", "pivot": [0, 0, 0], "cubes": [{
                "origin": [-16, 0, 0], "size": [32, 18, 0],
                "uv": {"south": {"uv": [0, 0], "uv_size": [16, 16]}},
            }]}],
        }],
    })
    write_json(resource / "render_controllers/pmanim_packet.render_controllers.json", {
        "format_version": "1.8.0", "render_controllers": {
            "controller.render.pmanim_packet": {
                "geometry": "Geometry.default", "materials": [{"*": "Material.default"}],
                "textures": ["Texture.default"],
            },
        },
    })
    for index in range(slots):
        name = "slot_%03d" % index
        identifier = "pmanim_packet:" + name
        write_json(resource / ("entity/pmanim_packet_" + name + ".entity.json"), {
            "format_version": "1.10.0", "minecraft:client_entity": {"description": {
                "identifier": identifier, "materials": {"default": "pmanim_packet"},
                "geometry": {"default": "geometry.pmanim_packet"},
                "textures": {"default": "textures/pmanim_packet/white"},
                "render_controllers": ["controller.render.pmanim_packet"],
            }},
        })
        write_json(behavior / ("entities/pmanim_packet_" + name + ".json"), {
            "format_version": "1.16.0", "minecraft:entity": {
                "description": {"identifier": identifier, "is_spawnable": False,
                                "is_summonable": False, "is_experimental": False},
                "components": {"minecraft:physics": {"has_gravity": False, "has_collision": False}},
            },
        })


def post_material(fragment):
    return {"vertexShader": "shaders/uv_fullscreen.vertex",
            "fragmentShader": "shaders/" + fragment,
            "vertexFields": [{"field": "Position"}, {"field": "UV0"}],
            "samplerStates": [{"samplerIndex": 0, "textureWrap": "Clamp", "textureFilter": "Point"}],
            "states": ["DisableDepthTest"], "msaaSupport": "Both"}


def write_block_resources(resource, behavior):
    """Use one calibrated native block quad shared by every paperdoll draw."""
    identifier = "pmanim_packet:block_quad"
    write_json(behavior / "netease_blocks/pmanim_packet_quad.json", {
        "format_version": "1.10.0", "minecraft:block": {
            "description": {"identifier": identifier, "register_to_creative_menu": False},
            "components": {"netease:render_layer": {"value": "blend"},
                           "netease:no_crop_face_block": {},
                           "minecraft:block_light_absorption": {"value": 0}},
        },
    })
    write_json(resource / "blocks.json", {"format_version": "1.21.40", identifier: {
        "netease_model": identifier, "sound": "stone",
    }})
    write_json(resource / "models/netease_block/pmanim_packet_quad.json", {
        "format_version": "1.13.0", "netease:block_geometry": {
            "description": {"identifier": identifier, "textures": ["quartz_block_top"],
                            "item_texture": "quartz_block_top", "use_ao": False},
            "bones": [{"name": "packet_plane", "pivot": [0, 0, 0], "cubes": [{
                "origin": [-16, 0, 0], "size": [16, 0, 16],
                "uv": {"up": {"uv": [0, 0], "uv_size": [16, 16]}},
            }]}],
        },
    })
    # Native block render_layer has a fixed material routing table. A dedicated
    # shader still needs these native entry points redirected inside THIS probe
    # pack. Entity and postprocess material dictionaries remain independent.
    materials = {"version": "1.0.0", "pmanim_packet_block:netease_block_as_entity_mesh": {
        "vertexShader": "shaders/glsl/packet_block.vertex",
        "fragmentShader": "shaders/glsl/packet_block.fragment",
        "+defines": ["BLEND"],
        "+states": ["Blending", "DisableCulling", "DisableDepthTest", "DisableDepthWrite"],
        "blendSrc": "SourceAlpha", "blendDst": "OneMinusSrcAlpha",
    }}
    for name in ("netease_block_as_mesh_blend", "netease_block_as_mesh_blend_enable_transparency",
                 "netease_block_as_mesh_blend_far", "netease_block_as_mesh_blend_no_culling"):
        materials[name + ":pmanim_packet_block"] = {}
    write_json(resource / "materials/terrain.material", {"materials": materials})


def write_materials(resource):
    write_json(resource / "materials/entity.material", {"materials": {
        "version": "1.0.0", "pmanim_packet:entity_static": {
            "vertexShader": "shaders/packet_probe.vertex",
            "fragmentShader": "shaders/packet_probe.fragment",
            "+states": ["DisableCulling", "DisableDepthTest", "DisableDepthWrite"],
        },
    }})
    write_json(resource / "materials/postprocess.material", {
        "pmanim_packet_copy": post_material("packet_copy.fragment"),
        "pmanim_packet_post": post_material("packet_post.fragment"),
    })


def post_process_config():
    """Return one AddPostProcess argument, never a global settings override."""
    return {"name": "pmanim_packet_post", "enable": False,
            "paras": [{"name": "invert", "value": 0.0, "range": [0.0, 1.0]}],
            "pass_array": [
                {"render_target": {"width": 1.0, "height": 1.0}, "material": "pmanim_packet_copy", "depth_enable": False},
                {"render_target": {"width": 1.0, "height": 1.0}, "material": "pmanim_packet_post", "depth_enable": False},
            ]}


def runtime_sources(slots):
    """Prepare the complete local runtime before mutating the output tree."""
    sources = {name: (HERE / name).read_text(encoding="utf-8")
               for name in ("runtime.py", "aggregate_runtime.py", "modMain.py",
                            "numeric_payload.py", "numeric_runtime.py")}
    runtime, count = re.subn(r"(?m)^LIMIT[ \t]*=[ \t]*[0-9]+[ \t]*$",
                             "LIMIT = %d" % slots, sources["runtime.py"])
    if count != 1:
        raise ValueError("runtime.py must declare exactly one integer LIMIT for the requested slot count")
    sources["runtime.py"] = runtime
    sources["__init__.py"] = "# -*- coding: utf-8 -*-\n"
    return sources


def write_shaders(resource, block_fallback):
    shaders = ["packet_probe.vertex", "packet_probe.fragment", "packet_copy.fragment", "packet_post.fragment"]
    if block_fallback:
        shaders.extend(("packet_block.vertex", "packet_block.fragment"))
    for filename in shaders:
        destination = resource / "shaders/glsl" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / filename, destination)


def build(output, slots=8, block_fallback=False):
    if not 1 <= slots <= 4096:
        raise ValueError("slots must be in [1, 4096]")
    options = {"block_fallback": bool(block_fallback), "initial_panel_offset": [0, 0]}
    output = Path(output).resolve()
    # Fail closed before writing into an existing production or unrelated tree.
    if output in (ROOT, ROOT / "behavior_pack", ROOT / "resource_pack", HERE):
        raise ValueError("output must be an isolated generated project directory")
    if output.exists() and any(output.iterdir()) and not (output / MARKER).is_file():
        raise ValueError("non-empty output has no probe ownership marker: " + str(output))
    if (output / MARKER).is_file():
        previous = json.loads((output / MARKER).read_text(encoding="utf-8"))
        if (previous.get("kind") != "pmanim_runtime_packet_probe" or previous.get("slots") != slots or
                previous.get("options") != options):
            raise ValueError("existing output belongs to a different probe configuration; use a new directory")
    legacy_post = output / "resource_pack/graphics_settings/post_process.json"
    if legacy_post.exists() or legacy_post.is_symlink():
        raise ValueError("existing probe contains a global postprocess override; use a fresh output directory: " + str(legacy_post))
    scripts = runtime_sources(slots)
    write_json(output / MARKER, {"kind": "pmanim_runtime_packet_probe", "slots": slots,
                                 "options": options, "version": 2})
    resource, behavior = output / "resource_pack", output / "behavior_pack"
    package = behavior / "packet_probe"
    package.mkdir(parents=True, exist_ok=True)
    for filename, source in scripts.items():
        (package / filename).write_text(source, encoding="utf-8")
    write_manifests(output)
    records = write_ui(resource, slots, block_fallback=block_fallback)
    write_entities(resource, behavior, slots)
    if block_fallback:
        write_block_resources(resource, behavior)
    write_materials(resource)
    aggregate_spec = importlib.util.spec_from_file_location("pmanim_packet_aggregate_assets", HERE / "aggregate_assets.py")
    aggregate_module = importlib.util.module_from_spec(aggregate_spec)
    aggregate_spec.loader.exec_module(aggregate_module)
    aggregate = aggregate_module.build_aggregate_assets(resource, page_count=4)
    write_shaders(resource, block_fallback)
    write_pixel(resource / "textures/pmanim_packet/transparent.png", (255, 255, 255, 0))
    write_pixel(resource / "textures/pmanim_packet/white.png", (255, 255, 255, 255))
    write_json(output / "probe_resources.json", {
        "version": 2, "options": options,
        "ui_namespace": "pmanim_packet_probe", "ui_definition": "pmanim_packet_probe.main",
        "runtime": {"package": "packet_probe", "slot_count": slots, "entrypoint": "packet_probe.modMain"},
        "postprocess": {"name": "pmanim_packet_post", "parameter": "invert", "pass_count": 2,
                        "registration": "explicit_AddPostProcess", "process": post_process_config()},
        "uniforms": {"EXTRA_ACTOR_UNIFORM1": ["packed_r", "packed_g", "packed_b", "mode_0_current_1_actor"],
                     "EXTRA_ACTOR_UNIFORM3": ["ndc_left", "ndc_top", "ndc_width", "ndc_height"]},
        "encoding": {"divisor": 16777216, "cell_count": 9,
                     "cell_order": ["r_hi", "r_mid", "r_lo", "g_hi", "g_mid", "g_lo", "b_hi", "b_mid", "b_lo"]},
        "block_probe": {"identifier": "pmanim_packet:block_quad", "geometry_name": "pmanim_packet_quad",
                        "palette_volume": [2, 2, 2], "rotation": [90.0, 0.0, 0.0],
                        "mapping": "native_WORLDVIEWPROJ_XY", "mode": "CURRENT_COLOR_only",
                        "native_material_scope": "block_as_mesh_blend_variants"} if block_fallback else None,
        "slots": records, "aggregate": aggregate,
    })
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slots", type=int, default=8)
    parser.add_argument("--block-fallback", action="store_true",
                        help="include the optional native block canvas and its isolated resources")
    arguments = parser.parse_args()
    print(build(arguments.output, arguments.slots, block_fallback=arguments.block_fallback))
