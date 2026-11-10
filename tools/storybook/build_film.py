"""Rebuild the independent fairy-tale film, its Song atlas and story manifest.

Host Python only. Uses the already pinned Noto Serif SC source and the existing
SDF text compiler; it never imports the game runtime or overwrites math assets.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools/showcase_v2"))
sys.path.insert(0, str(ROOT / "tools/reference"))
sys.path.insert(0, str(ROOT / "tools"))
from build_type import Atlas, normalize_group, text_items
from setup_cjk import build_subset
from presentation.vector_morph import VectorMorphAtlas, render_pairs as render_vector_pairs, shader_source as vector_shader_source
from storybook.build_art import shader_source as art_shader_source

FONT_SHA256 = "050080d9255a86808f2945bffac582b31ef32bc36411ce29563b4961670c66f9"
TEXT = {
    "lost": "很久以前，星星忘了回家的路。",
    "gift": "直到风，把一颗种子交给了她。",
    "voyage": "她折一叶纸船，驶向没有地图的天空。",
    "storm": "风也会迷路。勇敢的人，会替它点灯。",
    "tree": "于是，一颗小小的星，长成了一整片夜空。",
    "return": "那些曾被吹散的，都有了回家的方向。",
    "title": "风借来的一颗星",
    "motto": "每一次风起，都是星星回家的路",
}
CUES = [
    ("lost", 3.4, 18.5, 0.285, -3.18),
    ("gift", 18.5, 36.8, 0.285, -3.18),
    ("voyage", 36.8, 57.0, 0.285, -3.18),
    ("storm", 57.0, 81.3, 0.285, -3.18),
    ("tree", 81.3, 99.0, 0.285, -3.18),
    ("return", 99.0, 110.2, 0.285, -3.18),
    ("title", 110.2, 120.5, 0.78, 0.50),
    ("motto", 113.5, 120.5, 0.275, -0.65),
]
CHAPTERS = [
    (0, 16, "失星的村落", "弧顶村屋依坡地分层，风线绕过月牙与屋檐；最后一颗星落下。"),
    (16, 34, "掌心的种子", "六头身侧脸少女用弯曲的双臂接住种子，斗篷、发丝与风线连续流动。"),
    (34, 54, "没有地图的天空", "同一组风曲线重构为弧形帆船和云卷，青绿云海分层展开。"),
    (54, 76, "风也会迷路", "船与波浪的对应控制点抬升成弯曲枝干，少女护住种子的光。"),
    (76, 96, "星光生根", "森林曲线收束为不对称光树，种子落地拉长成树干，侧枝与光叶生长。"),
    (96, 110, "回家的方向", "叶、燕、星使用同一组64点闭合轮廓连续变换；树枝重构为鸟翼。"),
    (110, 120, "风借来的一颗星", "鸟翼继续重构成星图，前句宋体字幕重构为片名，结语从片名字形派生展开。"),
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def vec(values):
    return "vec%d(%s)" % (len(values), ",".join("%.6f" % value for value in values))


def layout(group, height, y):
    scale = min(height, 13.7 / group["width"])
    glyphs = deepcopy(group["glyphs"])
    for glyph in glyphs:
        glyph["center"] = [glyph["center"][0] * scale, glyph["center"][1] * scale + y]
        glyph["size"] = [value * scale for value in glyph["size"]]
        glyph["opacity"] = 1.0
    return glyphs


def correspondence(source, target):
    """Keep recurring characters, then pair remaining characters in reading order."""
    unmatched_a, unmatched_b = list(range(len(source))), list(range(len(target)))
    pairs = []
    for ai in list(unmatched_a):
        candidates = [bi for bi in unmatched_b if source[ai]["id"] == target[bi]["id"]]
        if candidates:
            bi = min(candidates, key=lambda index: abs(ai / len(source) - index / len(target)))
            pairs.append((source[ai], target[bi]))
            unmatched_a.remove(ai)
            unmatched_b.remove(bi)
    count = min(len(unmatched_a), len(unmatched_b))
    pairs.extend((source[a], target[b]) for a, b in zip(unmatched_a[:count], unmatched_b[:count]))
    for ai in unmatched_a[count:]:
        first = source[ai]
        anchor = min(target, key=lambda glyph: abs(glyph["center"][0] - first["center"][0]))
        second = deepcopy(first)
        second["center"], second["opacity"] = list(anchor["center"]), 0.0
        pairs.append((first, second))
    for bi in unmatched_b[count:]:
        second = target[bi]
        anchor = min(source, key=lambda glyph: abs(glyph["center"][0] - second["center"][0]))
        first = deepcopy(second)
        first["center"], first["opacity"] = list(anchor["center"]), 0.0
        pairs.append((first, second))
    return pairs


def typography(groups, morph):
    lines = ["void typography(inout vec3 c,vec2 p,float t,float aa) {"]
    layouts = {name: layout(groups[name], height, y) for name, _, _, height, y in CUES}
    previous = None
    for name, start, end, _height, _y in CUES:
        target = layouts[name]
        lines.append("if(t>=%.3f && t<%.3f) {" % (start, end))
        if previous is None:
            # Each first-line contour grows from its baseline; no opacity fade.
            for index, glyph in enumerate(target):
                origin = deepcopy(glyph)
                origin["opacity"] = 0.0
                origin["center"][1] -= .035
                begin = start + index * .042
                amount = "smoothstep(%.4f,%.4f,t)" % (begin, begin + .72)
                lines.append(render_vector_pairs(morph, [(origin, glyph)], amount=amount,
                             opacity="1.0", arc_strength=0, color="PAPER"))
        else:
            source = layouts["title"] if name == "motto" else layouts[previous]
            lines.append("float u=smoothstep(%.4f,%.4f,t);" % (start, start + 1.15))
            lines.append(render_vector_pairs(morph, correspondence(source, target), amount="u",
                         opacity="1.0", arc_strength=.25 if name == "title" else .065,
                         color="mix(PAPER,GOLD,u)" if name == "title" else
                               "mix(GOLD,PAPER,u)" if name == "motto" else "PAPER"))
        lines.append("}")
        previous = name
    lines.append("}")
    return "\n".join(lines)


def build(output):
    output.mkdir(parents=True, exist_ok=True)
    font_source = ROOT / ".runtime/cjk-font-source/serif/NotoSerifSC-VF.ttf"
    if digest(font_source) != FONT_SHA256:
        raise ValueError("Pinned Noto Serif SC source mismatch")
    font_path = output / "StorybookSong.ttf"
    font_report = build_subset(font_source, font_path, "".join(TEXT.values()), "serif")
    shutil.copyfile(font_source.with_name("OFL.txt"), output / "LICENSE_NOTO_SERIF_SC.txt")
    atlas = Atlas()
    groups = {name: normalize_group(text_items(text, font_path, atlas), text, "text")
              for name, text in TEXT.items()}
    morph = VectorMorphAtlas(atlas.image)
    typography_source = typography(groups, morph)
    atlas_path = output / "story_atlas.png"
    morph.image.save(atlas_path, optimize=True)
    source = HERE / "film.fragment"
    shader = source.read_text(encoding="utf-8")
    shader = shader.replace("// __STORY_ART__", art_shader_source())
    shader = shader.replace("// __STORY_VECTOR_MORPH__", vector_shader_source(composite="over"))
    shader = shader.replace("// __STORY_TYPOGRAPHY__", typography_source)
    shader_path = output / "story_showcase.fragment"
    shader_path.write_text(shader, encoding="utf-8", newline="\n")
    production_shader = ROOT / "resource_pack/shaders/glsl/story_showcase.fragment"
    production_atlas = ROOT / "resource_pack/textures/manim/story_showcase.png"
    production_shader.parent.mkdir(parents=True, exist_ok=True)
    production_atlas.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(shader_path, production_shader)
    shutil.copyfile(atlas_path, production_atlas)
    manifest = {
        "schema": 2, "id": "story_showcase", "title": TEXT["title"],
        "duration": 120.0, "fps": 60, "resolution": [1920, 1080],
        "style": "原创曲线插画、深靛与青绿层景、珊瑚斗篷、金色细线、宋体真实轮廓字幕变换",
        "shader": "shaders/glsl/story_showcase.fragment",
        "texture": "textures/manim/story_showcase", "texture_slot": "TEXTURE_2",
        "uniforms": {"EXTRA_VECTOR1": ["time_seconds", "physical_canvas_aspect", "physical_canvas_height", "opacity"],
                     "EXTRA_VECTOR2": ["flip_y", "canvas_top_fraction", "canvas_height_fraction", "reserved"]},
        "atlas": {"size": [4096, 4096], "tile": 192, "padding": 24, "sdf_range": 24,
                  "sample": "R; manual bilinear; positive inside; PNG top-left tiles; glyph UV Y flipped",
                  "glyphs": len(atlas.entries), "sha256": digest(atlas_path)},
        "font": dict(font_report, source_sha256=FONT_SHA256, license="SIL OFL 1.1"),
        "vector_morph": morph.report(),
        "illustration": {"source": "tools/storybook/build_art.py", "source_sha256": digest(HERE / "build_art.py"),
                         "provenance": "original hand-authored cubic Bezier paths; no external image assets",
                         "figure": "six-head curved profile; bent hands; flowing hair, cloak and skirt",
                         "persistent_curve_tracks": 18, "leaf_bird_star_contour_points": 64,
                         "transition": "corresponding Bezier controls and resampled closed contours; no full-scene crossfade"},
        "chapters": [{"start": a, "end": b, "title": title, "action": action} for a, b, title, action in CHAPTERS],
        "subtitles": [{"id": name, "start": a, "end": min(b, 120), "text": TEXT[name],
                       "transform_seconds": 1.15, "hold_until_next_transform": True,
                       "transition": "closed-contour point correspondence; no sentence alpha fade"}
                      for name, a, b, _, _ in CUES],
        "groups": groups,
        "source_sha256": digest(source), "shader_sha256": digest(shader_path),
        "build": ".venv-reference/Scripts/python.exe -B -X utf8 tools/storybook/build_film.py",
        "verification": "built; no game acceptance requested",
    }
    (output / "story.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"story": str(output / "story.json"), "shader": str(production_shader),
                      "atlas": str(production_atlas), "glyphs": len(atlas.entries),
                      "duration": 120, "fps": 60}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "generated")
    build(parser.parse_args().output.resolve())
