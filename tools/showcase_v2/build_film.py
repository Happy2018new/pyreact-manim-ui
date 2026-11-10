"""Compile the two-minute film's glyph correspondence and authored geometry."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import pprint
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from build_canvas import read_scenes


def vector(values):
    return "vec%d(%s)" % (len(values), ",".join("%.6f" % value for value in values))


def layout(group, center=(0, 0), height=1, width=12):
    scale = min(height, width / group["width"])
    result = deepcopy(group["glyphs"])
    for glyph in result:
        glyph["center"] = [glyph["center"][axis] * scale + center[axis] for axis in range(2)]
        glyph["size"] = [value * scale for value in glyph["size"]]
        glyph["opacity"] = 1.0
    return result


def pair_glyphs(source, target):
    """Keep matching symbols, then assign changed glyphs by smallest travel."""
    source, target = deepcopy(source), deepcopy(target)
    pairs = []
    for same_id in (True, False):
        while source and target:
            choices = [(sum((a["center"][k] - b["center"][k]) ** 2 for k in range(2)), i, j)
                       for i, a in enumerate(source) for j, b in enumerate(target)
                       if not same_id or a["id"] == b["id"]]
            if not choices:
                break
            _, i, j = min(choices)
            pairs.append((source.pop(i), target.pop(j)))
    for a in source:
        b = deepcopy(a)
        b["center"][1] -= 0.45
        b["size"] = [value * 0.04 for value in b["size"]]
        b["opacity"] = 0.0
        pairs.append((a, b))
    for b in target:
        a = deepcopy(b)
        a["center"][1] += 0.45
        a["size"] = [value * 0.04 for value in a["size"]]
        a["opacity"] = 0.0
        pairs.append((a, b))
    return pairs


def render_pairs(pairs, amount="u", opacity="visibility", arc_strength=0.32, color="WHITE"):
    lines = []
    for index, (a, b) in enumerate(pairs):
        arc = math.sin(index * 2.399 + 0.5) * arc_strength
        actual_amount = amount
        if all(a[key] == b[key] for key in ("center", "size", "tile", "opacity")):
            actual_amount = "0.0"
            arc = 0.0
        coverage = opacity
        if a["opacity"] != b["opacity"]:
            coverage = "(%s)*mix(%.1f,%.1f,%s)" % (opacity, a["opacity"], b["opacity"], amount)
        lines.append("glyph(c,p,%s,%s,%s,%s,%s,%s,%s,%.6f,%s,%s,aa);" % (
            vector(a["center"]), vector(a["size"]), vector(a["tile"]),
            vector(b["center"]), vector(b["size"]), vector(b["tile"]),
            actual_amount, arc, color, coverage))
    return "\n".join(lines)


def make_type(groups):
    code = ["void typography(inout vec3 c,vec2 p,float t,float aa) {"]
    events = []

    def chain(name, start, end, keys, center=(0, 0), height=1.5, width=12, color="WHITE", arc=0.35):
        code.append("if(t>=%.3f && t<%.3f) { float visibility=gate(t,%.3f,%.3f);" % (start, end, start, end))
        for index, (begin, group_name) in enumerate(keys):
            stop, next_name = keys[index + 1] if index + 1 < len(keys) else (end, group_name)
            left = layout(groups[group_name], center, height, width)
            right = layout(groups[next_name], center, height, width)
            pairs = pair_glyphs(left, right)
            code.append("if(t>=%.3f && t<%.3f) { float u=smoothstep(%.3f,%.3f,t);" % (
                begin, stop, begin + min(0.8, (stop - begin) * .25), stop - .3))
            code.append(render_pairs(pairs, arc_strength=arc, color=color))
            code.append("}")
            if group_name != next_name:
                events.append({"chapter": name, "start": begin, "end": stop,
                               "source": group_name, "target": next_name, "tracks": len(pairs),
                               "preserved_symbols": sum(a["id"] == b["id"] and a["opacity"]>0 and b["opacity"]>0 for a, b in pairs)})
        code.append("}")

    def label(key, begin, end, center, height, width=12, color="GOLD"):
        glyphs = layout(groups[key], center, height, width)
        code.append("if(t>=%.3f && t<%.3f) { float visibility=gate(t,%.3f,%.3f);" % (begin,end,begin,end))
        code.append(render_pairs([(g,g) for g in glyphs], "0.0", color=color, arc_strength=0))
        code.append("}")

    assembled = layout(groups["morph"], (0, 0.25), 1.42, 11.5)
    scattered = deepcopy(assembled)
    for index, glyph in enumerate(scattered):
        angle = index * 2.399
        glyph["center"] = [math.cos(angle) * 6.3, math.sin(angle) * 3.4]
        glyph["size"] = [v * 0.035 for v in glyph["size"]]
    code.append("if(t<2.4) { float u=smoothstep(0.2,2.3,t); float visibility=1.0;")
    code.append(render_pairs(list(zip(scattered,assembled)), color="WHITE", arc_strength=.6))
    code.append("}")
    chain("opening",2.4,12.0,[(2.4,"morph"),(5.3,"math"),(8.0,"magic"),(10.3,"c_thought")],
          center=(0,.25),height=1.42,width=11.5,color="mix(WHITE,CYAN,0.13)",arc=.7)
    label("title_en",0,12,(0,3.2),.22,color="CYAN")
    label("opening",0,12,(0,-2.5),.20,color="WHITE")
    label("geometry_label",12,28,(0,3.75),.22,color="GOLD")
    # Small matrices sit outside the main morph's silhouette, not over it.
    chain("matrix",12,28,[(12,"matrix0"),(18,"matrix1"),(24,"matrix0")],
          center=(5.65,-2.8),height=.95,width=3.0,color="CYAN",arc=.16)
    chain("algebra",28,48,[(28,"algebra0"),(32.4,"algebra1"),(37.0,"quadratic0"),
                           (42.3,"quadratic1"),(46.8,"quadratic1")],
          center=(0,.25),height=1.7,width=11.5,arc=.6)
    label("algebra_label",28,48,(0,3.45),.22)
    chain("complex",48,66,[(48,"exp0"),(53.4,"exp1"),(59,"exp2"),(63.7,"exp0")],
          center=(0,2.55),height=1.05,width=10.5,color="WHITE",arc=.3)
    label("complex_label",48,66,(0,3.75),.20,color="GOLD")
    chain("calculus",66,84,[(66,"calculus0"),(71.2,"calculus1"),(77,"calculus2")],
          center=(0,2.5),height=1.15,width=11,arc=.35)
    label("calculus_label",66,84,(0,3.75),.20)
    chain("harmonics",84,102,[(84,"fourier0"),(89,"fourier1"),(95,"fourier2"),(100,"fourier3")],
          center=(0,2.55),height=1.35,width=12.5,arc=.25)
    label("harmonics_label",84,102,(0,3.8),.20)
    chain("finale",102,114,[(102,"c_thought"),(104.2,"c_shape"),(106.4,"c_formula"),
                           (108.6,"c_universe"),(110.8,"final")],
          center=(0,.1),height=1.1,width=6.4,color="mix(WHITE,GOLD,0.15)",arc=.42)
    label("finale_label",102,114,(0,3.65),.20,color="CYAN")
    # The closing title itself is assembled by moving the final equation's glyphs.
    a=layout(groups["final"],(0,.1),1.1,6.4)
    b=layout(groups["c_title"],(0,.15),1.0,11.8)
    code.append("if(t>=114.0) { float u=smoothstep(114.0,116.1,t); float visibility=1.0;")
    code.append(render_pairs(pair_glyphs(a,b),color="mix(WHITE,GOLD,0.14)",arc_strength=.65))
    code.append("}")
    label("brand",115.0,121.0,(0,-2.15),.22,color="CYAN")
    label("title_en",115.0,121.0,(0,-1.05),.19,color="WHITE")
    code.append("}")
    events.append({"chapter":"closing","start":114,"end":116.1,"source":"final","target":"c_title"})
    return "\n".join(code),events


def build(assets=None):
    assets = Path(assets) if assets else ROOT / "tools/showcase_v2"
    metadata = json.loads((assets / "type_data.json").read_text(encoding="utf-8"))
    source_atlas = assets / "type_atlas.png"
    if assets.resolve() == (ROOT / "tools/showcase_v2").resolve():
        source_atlas = ROOT / "resource_pack/textures/manim/client_showcase.png"
    if hashlib.sha256(source_atlas.read_bytes()).hexdigest() != metadata["sha256"]:
        raise ValueError("V2 SDF atlas checksum mismatch")
    type_code, events = make_type(metadata["groups"])
    folder = ROOT / "tools/showcase_v2"
    shader=(folder / "film.fragment").read_text(encoding="utf-8")
    shader=shader.replace("// __GEOMETRY__",(folder / "geometry.glsl").read_text(encoding="utf-8"))
    shader=shader.replace("// __TYPE_FUNCTIONS__",type_code)
    resource = ROOT / "resource_pack"
    output = resource / "shaders/glsl/client_showcase.fragment"
    output.write_bytes(shader.encode("utf-8"))
    atlas = resource / "textures/manim/client_showcase.png"
    if source_atlas.resolve() != atlas.resolve():
        shutil.copyfile(source_atlas,atlas)
    (folder / "type_data.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    config = ROOT / "behavior_pack/manim_ui/generated_scenes.py"
    scenes = [scene for scene in read_scenes(config) if scene["name"] != "client_showcase"]
    scenes.append({"name":"client_showcase","duration":120.0,"title":"两分钟作品：万象变换",
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
    report={"duration":120,"shader_sha256":hashlib.sha256(output.read_bytes()).hexdigest(),
            "texture_sha256":metadata["sha256"],"shader_bytes":output.stat().st_size,
            "atlas_bytes":atlas.stat().st_size,"glyph_transitions":events,
            "geometry_transitions":"six opening shape transitions, ellipse, calculus, four harmonic levels, finale loop",
            "rendering":"per-glyph matched transport plus SDF interpolation; parametric geometry interpolation",
            "game_validation":"not run in this iteration, at user's request"}
    (folder / "film.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({k:v for k,v in report.items() if k!="glyph_transitions"},ensure_ascii=False,indent=2))
    return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets",type=Path)
    args=parser.parse_args()
    build(args.assets)
