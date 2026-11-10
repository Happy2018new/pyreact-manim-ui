"""Compile the two-minute film's glyph correspondence and authored geometry."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import pprint
import statistics
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from build_canvas import read_scenes
from presentation.vector_morph import VectorMorphAtlas, render_pairs as render_vector_pairs, shader_source


def vector(values):
    return "vec%d(%s)" % (len(values), ",".join("%.6f" % value for value in values))


def glyph_roles(group):
    """Classify this authored atlas's TeX placements without inventing glyph IDs.

    TeX raw coordinates retain a common baseline before group normalization.
    Rules enclose numerator/denominator rows; smaller raised/lowered ink belongs
    to scripts. Explicit semantic_role fields take precedence for future assets.
    """
    glyphs = group["glyphs"]
    if group["kind"] != "latex":
        return [glyph.get("semantic_role", "text") for glyph in glyphs]
    bounds = group["raw_bounds"]
    raw_height = bounds[3] - bounds[1]
    raw_middle = (bounds[3] + bounds[1]) * 0.5
    ink = [(glyph["center"][0] * raw_height,
            raw_middle - glyph["center"][1] * raw_height,
            glyph["ink_size"][0] * raw_height, glyph["ink_size"][1] * raw_height)
           for glyph in glyphs]
    rules = []
    for index, glyph in enumerate(glyphs):
        if glyph["id"] != "tex_rule":
            continue
        x, y, width, _height = ink[index]
        above = any(abs(px - x) < width / 2 and py < y - 0.5
                    for j, (px, py, _w, _h) in enumerate(ink) if j != index)
        below = any(abs(px - x) < width / 2 and py > y + 0.5
                    for j, (px, py, _w, _h) in enumerate(ink) if j != index)
        rules.append((index, x, y, width, "fraction_rule" if above and below else "radical_rule"))
    roles = []
    for index, glyph in enumerate(glyphs):
        if "semantic_role" in glyph:
            roles.append(glyph["semantic_role"])
            continue
        rule = next((rule for rule in rules if rule[0] == index), None)
        if rule is not None:
            roles.append(rule[4])
            continue
        x, y, _width, height = ink[index]
        fraction = next((rule for rule in sorted(rules, key=lambda rule: rule[3])
                         if rule[4] == "fraction_rule" and abs(x - rule[1]) <= rule[3] / 2
                         and abs(y - rule[2]) > 0.5), None)
        if fraction is not None:
            roles.append("numerator" if y < fraction[2] else "denominator")
        elif height < 6.3 and y + height / 2 < -2.8:
            roles.append("superscript")
        elif height < 6.3 and y - height / 2 > 1.0:
            roles.append("subscript")
        else:
            roles.append("body")
    return roles


def layout(group, center=(0, 0), height=1, width=12, raw_scale=None, raw_middle=None):
    raw_height = group["raw_bounds"][3] - group["raw_bounds"][1]
    scale = min(height, width / group["width"]) if raw_scale is None else raw_scale * raw_height
    result = deepcopy(group["glyphs"])
    roles = glyph_roles(group)
    for glyph, role in zip(result, roles):
        glyph["center"] = [glyph["center"][axis] * scale + center[axis] for axis in range(2)]
        if raw_middle is not None:
            middle = (group["raw_bounds"][3] + group["raw_bounds"][1]) * 0.5
            glyph["center"][1] += (raw_middle - middle) * raw_scale
        glyph["size"] = [value * scale for value in glyph["size"]]
        glyph["opacity"] = 1.0
        glyph["role"] = role
        glyph["kind"] = group["kind"]
    return result


def chain_layouts(groups, names, center, height, width, max_height=None):
    """One TeX scale and baseline for a complete chapter, including fractions."""
    selected = [groups[name] for name in names]
    if not all(group["kind"] == "latex" for group in selected):
        return {name: layout(groups[name], center, height, width) for name in names}
    bounds = [group["raw_bounds"] for group in selected]
    heights = [box[3] - box[1] for box in bounds]
    padded = []
    for group, box, raw_height in zip(selected, bounds, heights):
        raw_middle = (box[1] + box[3]) * 0.5
        for glyph in group["glyphs"]:
            x = glyph["center"][0] * raw_height
            y = raw_middle - glyph["center"][1] * raw_height
            half_width, half_height = (value * raw_height / 2 for value in glyph["size"])
            padded.append((x - half_width, y - half_height, x + half_width, y + half_height))
    bottom = min(box[1] for box in padded)
    top = max(box[3] for box in padded)
    max_height = height * 1.65 if max_height is None else max_height
    scale = min(height / statistics.median(heights),
                (max_height - 0.12) / (top - bottom),
                (width - 0.12) / (2 * max(max(abs(box[0]), abs(box[2])) for box in padded)))
    middle = (bottom + top) * 0.5
    return {name: layout(groups[name], center, height, width, scale, middle) for name in names}


TRANSITION_MODES = ("shape_morph", "matching_transport")


def role_family(glyph):
    role = glyph.get("role", "body")
    if role.endswith("_rule") or glyph["id"] == "tex_rule":
        return role
    if role in ("superscript", "subscript"):
        return "script"
    return "body"


def shape_compatible(a, b):
    """Allow real outline changes without stretching rules into full characters."""
    family = role_family(a)
    if family != role_family(b):
        return False
    if family.endswith("_rule"):
        return a.get("role") == b.get("role")
    aw, ah = a["size"]
    bw, bh = b["size"]
    aspect_a, aspect_b = aw / ah, bw / bh
    aspect_ratio = max(aspect_a / aspect_b, aspect_b / aspect_a)
    height_ratio = max(ah / bh, bh / ah)
    area_ratio = max(aw * ah / (bw * bh), bw * bh / (aw * ah))
    # Long bars and tall fences keep their family even when they are not the
    # explicit tex_rule tile. Parentheses must not turn into square Chinese ink.
    slender_a = min(aspect_a, 1 / aspect_a) < .24
    slender_b = min(aspect_b, 1 / aspect_b) < .24
    if slender_a or slender_b:
        return (slender_a and slender_b and (aspect_a < 1) == (aspect_b < 1)
                and aspect_ratio <= 1.8 and height_ratio <= 2.5)
    return aspect_ratio <= 3.0 and height_ratio <= 3.0 and area_ratio <= 6.0


def pair_kind(a, b):
    if a["opacity"] == 0:
        return "birth"
    if b["opacity"] == 0:
        return "death"
    if a["id"] != b["id"] and vector(a["tile"]) != vector(b["tile"]):
        return "shape_morph"
    if all(vector(a[key]) == vector(b[key]) for key in ("center", "size", "tile")):
        return "stationary"
    return "transport"


def pair_glyphs(source, target, mode="shape_morph"):
    """Choose authored outline changes or identity transport, then local births.

    Shape mode deliberately pairs different compatible ink, including ordinary
    TeX glyphs and Chinese text. Transport mode preserves symbol identity. Neither
    moving the same tile nor appearing from zero opacity counts as a shape morph.
    """
    if mode not in TRANSITION_MODES:
        raise ValueError("Unknown typography transition mode: " + mode)
    source, target = deepcopy(source), deepcopy(target)
    original_source, original_target = list(source), list(target)
    pairs = []
    if mode == "shape_morph" and source and target:
        def span(glyphs):
            left = min(g["center"][0] - g["size"][0] / 2 for g in glyphs)
            right = max(g["center"][0] + g["size"][0] / 2 for g in glyphs)
            return (left + right) / 2, max(right - left, .001)

        source_middle, source_width = span(source)
        target_middle, target_width = span(target)
        candidates = []
        for i, a in enumerate(source):
            for j, b in enumerate(target):
                if (a["id"] == b["id"] or vector(a["tile"]) == vector(b["tile"])
                        or not shape_compatible(a, b)):
                    continue
                ax, ay = a["center"]
                bx, by = b["center"]
                relative = abs((ax - source_middle) / source_width
                               - (bx - target_middle) / target_width)
                travel_limit = max(1.2, 2.5 * max(a["size"][0], b["size"][0]),
                                   .18 * (source_width + target_width))
                if relative > .46 or abs(ax - bx) > travel_limit:
                    continue
                scale = max(.3, (a["size"][1] + b["size"][1]) / 2)
                distance = ((ax - bx) ** 2 + (ay - by) ** 2) / scale ** 2
                size_change = sum(abs(math.log(a["size"][k] / b["size"][k])) for k in (0, 1))
                role_change = .3 if a.get("role") != b.get("role") else 0
                candidates.append((distance + relative * 4 + size_change * .6 + role_change, i, j))
        used_source, used_target = set(), set()
        for _cost, i, j in sorted(candidates):
            if i not in used_source and j not in used_target:
                pairs.append((source[i], target[j]))
                used_source.add(i)
                used_target.add(j)
        source = [g for i, g in enumerate(source) if i not in used_source]
        target = [g for j, g in enumerate(target) if j not in used_target]
    identities = sorted(set((glyph["id"], glyph.get("role", "body")) for glyph in source))
    for identity in identities:
        left = sorted((glyph for glyph in source if (glyph["id"], glyph.get("role", "body")) == identity),
                      key=lambda glyph: (glyph["center"][0], glyph["center"][1]))
        right = sorted((glyph for glyph in target if (glyph["id"], glyph.get("role", "body")) == identity),
                       key=lambda glyph: (glyph["center"][0], glyph["center"][1]))
        for a, b in zip(left, right):
            pairs.append((a, b))
            source.remove(a)
            target.remove(b)
    for a in source:
        b = deepcopy(a)
        if original_target:
            closest = min(original_target, key=lambda glyph: sum(
                (glyph["center"][axis] - a["center"][axis]) ** 2 for axis in range(2)))
            b["center"] = list(closest["center"])
        b["opacity"] = 0.0
        pairs.append((a, b))
    for b in target:
        a = deepcopy(b)
        if original_source:
            closest = min(original_source, key=lambda glyph: sum(
                (glyph["center"][axis] - b["center"][axis]) ** 2 for axis in range(2)))
            a["center"] = list(closest["center"])
        a["opacity"] = 0.0
        pairs.append((a, b))
    return pairs


def render_pairs(pairs, amount="u", opacity="visibility", arc_strength=0.32, color="WHITE", morph=None):
    if morph is None:
        raise ValueError("Glyph rendering requires the atlas used for contour correspondence")
    return render_vector_pairs(morph, pairs, amount, opacity, arc_strength, color)


def transition_window(begin, stop, duration=0.6):
    """A short readable motion followed by a real hold, not a chapter-long morph."""
    start = begin + min(0.8, max(0.0, (stop - begin - duration) * 0.4))
    return round(start, 3), round(start + duration, 3)


def review_bounds(glyphs, margin=0.06):
    return [min(g["center"][0] - g["size"][0] / 2 for g in glyphs) - margin,
            min(g["center"][1] - g["size"][1] / 2 for g in glyphs) - margin,
            max(g["center"][0] + g["size"][0] / 2 for g in glyphs) + margin,
            max(g["center"][1] + g["size"][1] / 2 for g in glyphs) + margin]


def event_record(chapter, begin, stop, source, target, pairs, window, arc, bounds, mode):
    counts = {kind: 0 for kind in ("shape_morph", "transport", "stationary", "birth", "death")}
    for a, b in pairs:
        counts[pair_kind(a, b)] += 1
    return {"chapter": chapter, "start": begin, "end": stop, "transition_mode": mode,
            "transition_start": window[0], "transition_end": window[1],
            "source": source, "target": target, "tracks": len(pairs),
            **{kind + "_tracks": count for kind, count in counts.items()},
            "arc_strength": arc, "review_bounds": bounds,
            "source_hold": {"start": begin, "end": window[0], "duration": window[0] - begin},
            "preserved_symbols": sum(a["id"] == b["id"] and a["opacity"] > 0 and b["opacity"] > 0
                                     for a, b in pairs)}


def finish_holds(events, until):
    for index, event in enumerate(events):
        hold_until = events[index + 1]["transition_start"] if index + 1 < len(events) else until
        event["hold_until"] = hold_until
        event["target_hold"] = {"start": event["transition_end"], "end": hold_until,
                                "duration": round(hold_until - event["transition_end"], 3)}
        event["hold"] = {"before": round(event["source_hold"]["duration"], 3),
                         "after": event["target_hold"]["duration"]}


def make_type(groups, morph):
    """Five formula chapters surround large geometry; titles never clear it."""
    code = ["void typography(inout vec3 c,vec2 p,float t,float aa) {"]
    events = []

    def chain(name, start, end, keys, center=(0, -3.57), height=.62,
              width=12.2, color="WHITE", arc=.055, max_height=1.02):
        code.append("if(t>=%.3f && t<%.3f) { float visibility=gate(t,%.3f,%.3f);" %
                    (start, end, start, end))
        layouts = chain_layouts(groups, [key for _time, key in keys],
                                center, height, width, max_height)
        chapter_events = []
        for index, (begin, group_name) in enumerate(keys):
            stop, next_name = keys[index + 1] if index + 1 < len(keys) else (end, group_name)
            left, right = layouts[group_name], layouts[next_name]
            mode = "matching_transport" if group_name == next_name else "shape_morph"
            pairs = pair_glyphs(left, right, mode)
            window = transition_window(begin, stop, duration=.6)
            code.append("if(t>=%.3f && t<%.3f) { float u=smoothstep(%.3f,%.3f,t);" %
                        (begin, stop, window[0], window[1]))
            code.append(render_pairs(pairs, arc_strength=arc, color=color, morph=morph))
            code.append("}")
            if group_name != next_name:
                chapter_events.append(event_record(name, begin, stop, group_name, next_name,
                                                    pairs, window, arc, review_bounds(right), mode))
        finish_holds(chapter_events, end - .7)
        events.extend(chapter_events)
        code.append("}")

    def label(key, begin, end, center, height, width=12, color="WHITE"):
        glyphs = layout(groups[key], center, height, width)
        code.append("if(t>=%.3f && t<%.3f) { float visibility=gate(t,%.3f,%.3f);" %
                    (begin, end, begin, end))
        code.append(render_pairs([(g, g) for g in glyphs], "0.0", color=color,
                                 arc_strength=0, morph=morph))
        code.append("}")

    def chapter_title(key, begin, end):
        height, width, left = .46, 6.8, -6.55
        scale = min(height, width / groups[key]["width"])
        center = (left + groups[key]["width"] * scale / 2, 3.57)
        label(key, begin, end, center, height, width, "mix(WHITE,JADE,0.12)")

    def grow(key, begin, full, stop, center, height, width, fade_end=True):
        target = layout(groups[key], center, height, width)
        source = deepcopy(target)
        for glyph in source:
            glyph["opacity"] = 0.0
        # Birth contours expand at each glyph's own anchor: no flying fragments.
        pairs = pair_glyphs(source, target, "matching_transport")
        visibility = "smoothstep(%.3f,%.3f,t)" % (begin, begin + .65)
        if fade_end:
            visibility += "*(1.0-smoothstep(12.8,13.7,t))"
        code.append("if(t>=%.3f && t<%.3f) { float visibility=%s; float u=smoothstep(%.3f,%.3f,t);" %
                    (begin, stop, visibility, begin, full))
        code.append(render_pairs(pairs, color="WHITE", arc_strength=0, morph=morph))
        code.append("}")

    # Deliberately offset Song lines leave the lower material line visible.
    grow("c_open_line", .35, 2.2, 14.0, (-1.65, 1.12), 1.55, 9.8)
    grow("c_open_infinity", 3.4, 5.4, 14.0, (1.05, -.82), 1.55, 11.2)
    label("film_english", 6.1, 13.4, (0, -3.35), .25, 10.6, "JADE")

    chapter_title("c_petal", 14.0, 34.0)
    chain("geometry", 14, 34, [(14, "petal0"), (17.2, "petal0"), (22, "petal1"),
                              (26.8, "petal2"), (31.6, "petal3")])
    chapter_title("c_koch", 34.0, 54.0)
    chain("koch", 34, 54, [(34, "koch0"), (37.2, "koch0"), (42, "koch1"),
                          (46.8, "koch2"), (51.6, "koch3")])
    chapter_title("c_wave", 54.0, 74.0)
    chain("harmonics", 54, 74, [(54, "wave0"), (57.2, "wave0"), (62, "wave1"),
                               (66.8, "wave2"), (71.6, "wave3")], height=.60)
    chapter_title("c_sheet", 74.0, 96.0)
    chain("surface", 74, 96, [(74, "sheet0"), (78.2, "sheet0"), (83.6, "sheet1"),
                             (89, "sheet2"), (94.4, "sheet3")],
          height=.59, width=12.6, max_height=.98)
    chapter_title("c_star", 96.0, 112.0)
    chain("fractal", 96, 112, [(96, "star0"), (98.6, "star0"), (104.1, "star1"),
                              (109.3, "star2")], height=.61, max_height=1.02,
          color="mix(WHITE,GOLD,0.12)")

    # The seed is already fully grown at the handoff; title morph has no reset.
    grow("c_close_seed", 112.15, 112.9, 113.0, (0, .55), 1.40, 12, fade_end=False)
    a = layout(groups["c_close_seed"], (0, .55), 1.40, 12)
    b = layout(groups["c_film_title"], (0, .55), 1.40, 12)
    pairs = pair_glyphs(a, b, "shape_morph")
    code.append("if(t>=113.0) { float visibility=1.0; float u=smoothstep(113.8,114.4,t);")
    code.append(render_pairs(pairs, color="WHITE", arc_strength=.07, morph=morph))
    code.append("}")
    label("film_english", 115.0, 122.0, (0, -2.82), .25, 11.0, "JADE")
    code.append("}")
    closing = event_record("closing", 113, 120, "c_close_seed", "c_film_title",
                           pairs, (113.8, 114.4), .07, review_bounds(b), "shape_morph")
    finish_holds([closing], 120.0)
    events.append(closing)
    return "\n".join(code), events


def build(assets=None):
    assets = Path(assets) if assets else ROOT / "tools/showcase_v2"
    metadata = json.loads((assets / "type_data.json").read_text(encoding="utf-8"))
    source_atlas = assets / "type_atlas.png"
    if assets.resolve() == (ROOT / "tools/showcase_v2").resolve():
        source_atlas = ROOT / "resource_pack/textures/manim/client_showcase.png"
    if hashlib.sha256(source_atlas.read_bytes()).hexdigest() != metadata["sha256"]:
        raise ValueError("V2 SDF atlas checksum mismatch")
    # Repack from a cleared data region on every build. This also supports
    # rebuilding directly from the already packed production atlas.
    with Image.open(source_atlas) as image:
        morph = VectorMorphAtlas(image.convert("RGBA"))
    type_code, events = make_type(metadata["groups"], morph)
    metadata["vector_morph"] = morph.report()
    folder = ROOT / "tools/showcase_v2"
    shader=(folder / "film.fragment").read_text(encoding="utf-8")
    shader=shader.replace("// __GEOMETRY__",(folder / "geometry.glsl").read_text(encoding="utf-8"))
    shader=shader.replace("// __TYPE_FUNCTIONS__",shader_source()+"\n"+type_code)
    resource = ROOT / "resource_pack"
    output = resource / "shaders/glsl/client_showcase.fragment"
    output.write_bytes(shader.encode("utf-8"))
    atlas = resource / "textures/manim/client_showcase.png"
    morph.image.save(atlas, optimize=True)
    metadata["sha256"] = hashlib.sha256(atlas.read_bytes()).hexdigest()
    (folder / "type_data.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    config = ROOT / "behavior_pack/manim_ui/generated_scenes.py"
    scenes = [scene for scene in read_scenes(config) if scene["name"] != "client_showcase"]
    scenes.append({"name":"client_showcase","duration":120.0,"title":"万象，始于一线",
                   "canvas_compatible":False,"material":"pmanim_client_showcase",
                   "post_name":"pmanim_client_showcase","texture":"textures/manim/client_showcase"})
    config.write_text("# -*- coding: utf-8 -*-\n# Generated by the scene and showcase builders.\nSCENES = "+
                      pprint.pformat(scenes,width=100,sort_dicts=True)+"\n",encoding="utf-8",newline="\n")
    material_path = resource / "materials/postprocess.material"
    materials = json.loads(material_path.read_text(encoding="utf-8"))
    materials["pmanim_client_showcase"] = {
        "vertexShader":"shaders/uv_fullscreen.vertex","fragmentShader":"shaders/client_showcase.fragment",
        "vertexFields":[{"field":"Position"},{"field":"UV0"}],
        "samplerStates":[{"samplerIndex":i,"textureWrap":"Clamp","textureFilter":"Point"} for i in range(3)],
        "states":["DisableDepthTest"],"msaaSupport":"Both"}
    material_path.write_text(json.dumps(materials,indent=2)+"\n",encoding="utf-8",newline="\n")
    report={"duration":120,"title":"万象，始于一线","edition":"V8 / From a Line to Infinity",
            "shader_sha256":hashlib.sha256(output.read_bytes()).hexdigest(),
            "texture_sha256":metadata["sha256"],"shader_bytes":output.stat().st_size,
            "atlas_bytes":atlas.stat().st_size,"glyph_transitions":events,
            "vector_morph":morph.report(),
            "font_provenance":metadata["provenance"],
            "typography_transition_modes": {
                mode: sum(event["transition_mode"] == mode for event in events)
                for mode in TRANSITION_MODES},
            "typography_track_totals": {
                kind: sum(event[kind + "_tracks"] for event in events)
                for kind in ("shape_morph", "transport", "stationary", "birth", "death")},
            "geometry_transitions":"0–14: two offset Song title lines and a growing material line; 14–34: drawn circle to translucent six-petal sheet to projected (2,3) torus knot; 34–54: four actual Koch substitutions, local camera push and reunion; 54–74: complex rotation unrolls into sine and odd-harmonic synthesis; 74–96: a curve opens into a folded translucent surface and crown; 96–112: seven-piece assembly and four-level ratio-1/3 hexaflake; 112–120: single cream line and large Song title",
            "art_direction":{"primary":"warm cream","secondary":"jade","accents":["coral","gold"],
                             "climax_only":"restrained violet","primary_stroke_world_units":[0.026,0.034],
                             "auxiliary_stroke_world_units":0.01,"formula_morph_seconds":0.6},
            "background_continuity":"No rectangular text reading masks; background lines remain continuous outside glyph ink coverage",
            "rendering":"paired closed contours and nonzero winding during shape changes; exact SDF endpoints; selected identity transport; parametric geometry interpolation",
            "game_validation":"Not run for this revision; prior review does not validate these resource hashes"}
    (folder / "film.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({k:v for k,v in report.items() if k!="glyph_transitions"},ensure_ascii=False,indent=2))
    return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets",type=Path)
    args=parser.parse_args()
    build(args.assets)
