"""Build isolated UI/paperdoll feasibility resources; never launch Minecraft."""
import argparse
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def control(kind, size, offset=(0, 0), layer=0, **extra):
    result = {"type": kind, "size": list(size), "offset": list(offset),
              "anchor_from": "top_left", "anchor_to": "top_left", "layer": layer}
    result.update(extra)
    return result


def image(size, offset, color, layer=0):
    return control("image", size, offset, layer, texture="textures/ui/white_bg", color=color,
                   keep_ratio=False)


def window(offset):
    return control("panel", (216, 126), offset, clips_children=True, controls=[
        {"back": image((216, 126), (0, 0), [0.08, 0.15, 0.25])},
        {"grid_v": image((12, 126), (102, 0), [0.17, 0.30, 0.43])},
        {"grid_h": image((216, 12), (0, 57), [0.17, 0.30, 0.43])},
        {"canvas": control("custom", (264, 154), (-24, -14), 3,
                           renderer="netease_paper_doll_renderer", rotation="none",
                           init_rot_x=0.0, init_rot_y=0.0, init_rot_z=0.0,
                           screen_scale=1.0, enable_scissor_test=True)},
        {"occluder": image((25, 126), (166, 0), [0.95, 0.30, 0.05], 12)},
    ])


def write_ui(resource):
    write_json(resource / "ui/ui_canvas_probe.json", {
        "namespace": "manim_canvas_probe",
        "main": control("screen", ("100%", "100%"), controls=[
            {"left": window((28, 60))}, {"right": window((272, 60))},
            {"normal": control("image", (64, 64), (28, 210), 2,
                               texture="textures/ui/white_bg", force_texture_reload=True)},
            {"raw": control("image", (64, 64), (110, 210), 2,
                            texture="textures/ui/white_bg", texture_file_system="RawPath",
                            force_texture_reload=True)},
            {"marker": image((30, 30), (450, 220), [0.2, 0.9, 0.2], 20)},
        ]),
    })
    write_json(resource / "ui/_ui_defs.json", {"ui_defs": ["ui/ui_canvas_probe.json"]})


def write_geometry(resource):
    write_json(resource / "models/entity/manim_canvas_probe.geo.json", {
        "format_version": "1.12.0", "minecraft:geometry": [{
            "description": {"identifier": "geometry.manim_canvas_probe", "texture_width": 16,
                            "texture_height": 16, "visible_bounds_width": 8,
                            "visible_bounds_height": 8, "visible_bounds_offset": [0, 0.5, 0]},
            "bones": [{"name": "root", "pivot": [0, 0, 0], "cubes": [{
                "origin": [-16, 0, 0], "size": [32, 18, 0],
                "uv": {"south": {"uv": [0, 0], "uv_size": [16, 16]}},
            }]}],
        }],
    })
    write_json(resource / "render_controllers/manim_canvas_probe.render_controllers.json", {
        "format_version": "1.8.0", "render_controllers": {
            "controller.render.manim_canvas_probe": {
                "geometry": "Geometry.default", "materials": [{"*": "Material.default"}],
                "textures": ["Texture.default"],
            },
        },
    })


def write_entities(resource, behavior):
    for slot in ("left", "right", "left_glyph", "right_glyph"):
        identifier = "pmanim_probe:" + slot
        is_glyph = slot.endswith("_glyph")
        material = "manim_canvas_glyph" if is_glyph else "manim_canvas_probe"
        texture = "textures/manim/manimgl_o_to_b" if is_glyph else "textures/ui/white_bg"
        write_json(resource / ("entity/manim_canvas_probe_" + slot + ".entity.json"), {
            "format_version": "1.10.0", "minecraft:client_entity": {"description": {
                "identifier": identifier, "materials": {"default": material},
                "geometry": {"default": "geometry.manim_canvas_probe"},
                "textures": {"default": texture},
                "render_controllers": ["controller.render.manim_canvas_probe"],
            }},
        })
        write_json(behavior / ("entities/manim_canvas_probe_" + slot + ".json"), {
            "format_version": "1.16.0", "minecraft:entity": {
                "description": {"identifier": identifier, "is_spawnable": False,
                                "is_summonable": False, "is_experimental": False},
                "components": {"minecraft:physics": {"has_gravity": False,
                                                        "has_collision": False}},
            },
        })


def write_materials(resource):
    write_json(resource / "materials/entity.material", {"materials": {
        "version": "1.0.0", "manim_canvas_probe:entity_static": {
            "vertexShader": "shaders/manim_canvas_probe.vertex",
            "fragmentShader": "shaders/manim_canvas_probe.fragment",
            "+states": ["DisableCulling", "DisableDepthTest", "DisableDepthWrite", "Blending"],
            "blendSrc": "SourceAlpha", "blendDst": "OneMinusSrcAlpha",
        },
        "manim_canvas_glyph:manim_canvas_probe": {
            "fragmentShader": "shaders/manim_canvas_glyph.fragment",
        },
    }})


def glyph_fragment(source):
    """Bridge the fixed O-to-B fixture, fail closed if its generator changes."""
    replacements = (
        ("uniform sampler2D TEXTURE_0;\n", ""),
        ("TEXTURE_2", "TEXTURE_0"),
        ("EXTRA_VECTOR1", "EXTRA_ACTOR_UNIFORM1"),
        ("EXTRA_VECTOR2", "EXTRA_ACTOR_UNIFORM2"),
        ("vec3 color = vec3(0.0, 0.0, 0.0);", "vec3 color = vec3(0.0);\n    float alpha = 0.0;"),
        ("color = mix(color, fill.rgb, coverage * 1.06);",
         "alpha = clamp(coverage * 1.06, 0.0, 1.0);\n        color = fill.rgb;"),
        ("vec4 original = texture2D(TEXTURE_0, uv);\n    gl_FragColor = mix(original, vec4(color, 1.0), clamp(EXTRA_ACTOR_UNIFORM1.w, 0.0, 1.0));",
         "gl_FragColor = vec4(color, alpha * clamp(EXTRA_ACTOR_UNIFORM1.w, 0.0, 1.0));"),
    )
    for before, after in replacements:
        if before not in source:
            raise ValueError("O-to-B probe contract changed: " + before[:80])
        source = source.replace(before, after)
    return source


def build(output):
    output = output.resolve()
    resource = output / "resource_pack"
    behavior = output / "behavior_pack"
    write_ui(resource)
    write_geometry(resource)
    write_entities(resource, behavior)
    write_materials(resource)
    for source, relative in (
        (HERE / "canvas_probe.py", "behavior_pack/manim_ui/canvas_probe.py"),
        (HERE / "manim_canvas_probe.vertex", "resource_pack/shaders/glsl/manim_canvas_probe.vertex"),
        (HERE / "manim_canvas_probe.fragment", "resource_pack/shaders/glsl/manim_canvas_probe.fragment"),
    ):
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    source = (ROOT / "resource_pack/shaders/glsl/manimgl_o_to_b.fragment").read_text(encoding="utf-8")
    (resource / "shaders/glsl/manim_canvas_glyph.fragment").write_text(glyph_fragment(source), encoding="utf-8")
    texture_target = resource / "textures/manim/manimgl_o_to_b.png"
    texture_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "resource_pack/textures/manim/manimgl_o_to_b.png", texture_target)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/ui-canvas-probe")
    args = parser.parse_args()
    print(build(args.output))
