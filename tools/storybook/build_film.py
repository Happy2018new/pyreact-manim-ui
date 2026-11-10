"""Rebuild the independent fairy-tale film, its Song atlas and story manifest.

Host Python only. Uses the already pinned Noto Serif SC source and the existing
SDF text compiler; it never imports the game runtime or overwrites math assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools/showcase_v2"))
sys.path.insert(0, str(ROOT / "tools/reference"))
from build_type import Atlas, normalize_group, text_items
from setup_cjk import build_subset

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
    ("lost", 3.4, 13.5, 0.245, -3.18),
    ("gift", 18.5, 30.8, 0.245, -3.18),
    ("voyage", 36.8, 49.8, 0.245, -3.18),
    ("storm", 57.0, 70.5, 0.245, -3.18),
    ("tree", 81.3, 93.1, 0.245, -3.18),
    ("return", 99.0, 108.7, 0.245, -3.18),
    ("title", 110.2, 120.5, 0.82, 0.50),
    ("motto", 113.5, 120.5, 0.255, -0.80),
]
CHAPTERS = [
    (0, 16, "失星的村落", "风在屋檐、丝带云和少女发间流动；最后一颗星落下。"),
    (16, 34, "掌心的种子", "同一位红斗篷少女伸手，接住风送来的金色种子。"),
    (34, 54, "没有地图的天空", "纸船载着少女和种子，穿过有前中后景的云海，船的轮廓化成云。"),
    (54, 76, "风也会迷路", "逆风弯曲森林、斗篷与发丝；少女护住种子的光。"),
    (76, 96, "星光生根", "种子连续拉长成树干，分枝依生长次序展开，光叶长出。"),
    (96, 110, "回家的方向", "光叶的同一轮廓展开为鸟翼，鸟群飞回星空。"),
    (110, 120, "风借来的一颗星", "村落重见星海，宋体片名和结语停留。"),
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def vec(values):
    return "vec%d(%s)" % (len(values), ",".join("%.6f" % value for value in values))


def typography(groups):
    lines = ["void typography(inout vec3 c,vec2 p,float t,float aa) {"]
    for name, start, end, height, y in CUES:
        group = groups[name]
        scale = min(height, 13.7 / group["width"])
        lines += ["if(t>%.3f && t<%.3f) {" % (start, end),
                  "float opacity=cue(t,%.3f,%.3f);" % (start, end)]
        if name == "title":
            lines += ["float unfold=smoothstep(110.2,112.8,t);"]
        for index, glyph in enumerate(group["glyphs"]):
            center = [glyph["center"][0] * scale, glyph["center"][1] * scale + y]
            size = [axis * scale for axis in glyph["size"]]
            if name == "title":
                position = "(%s+vec2(0.0,(1.0-unfold)*%.6f))" % (vec(center), (index % 3 - 1) * .08)
                opacity = "opacity*smoothstep(110.2+%.4f,111.8+%.4f,t)" % (index * .055, index * .055)
                hue = "vec3(1.0,0.86,0.56)"
            else:
                position, opacity, hue = vec(center), "opacity", "vec3(0.92,0.91,0.84)"
            lines.append("letter(c,p,%s,%s,%s,%s,%s,aa);" %
                         (position, vec(size), vec(glyph["tile"]), hue, opacity))
        lines.append("}")
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
    atlas_path = output / "story_atlas.png"
    atlas.image.save(atlas_path, optimize=True)
    source = HERE / "film.fragment"
    shader = source.read_text(encoding="utf-8").replace("// __STORY_TYPOGRAPHY__", typography(groups))
    shader_path = output / "story_showcase.fragment"
    shader_path.write_text(shader, encoding="utf-8", newline="\n")
    production_shader = ROOT / "resource_pack/shaders/glsl/story_showcase.fragment"
    production_atlas = ROOT / "resource_pack/textures/manim/story_showcase.png"
    production_shader.parent.mkdir(parents=True, exist_ok=True)
    production_atlas.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(shader_path, production_shader)
    shutil.copyfile(atlas_path, production_atlas)
    manifest = {
        "schema": 1, "id": "story_showcase", "title": TEXT["title"],
        "duration": 120.0, "fps": 60, "resolution": [1920, 1080],
        "style": "原创剪纸童话、电影宽幅、风驱动轮廓、连续种子叙事、宋体字幕",
        "shader": "shaders/glsl/story_showcase.fragment",
        "texture": "textures/manim/story_showcase", "texture_slot": "TEXTURE_2",
        "uniforms": {"EXTRA_VECTOR1": ["time_seconds", "physical_canvas_aspect", "physical_canvas_height", "opacity"],
                     "EXTRA_VECTOR2": ["flip_y", "canvas_top_fraction", "canvas_height_fraction", "reserved"]},
        "atlas": {"size": [4096, 4096], "tile": 192, "padding": 24, "sdf_range": 24,
                  "sample": "R; manual bilinear; positive inside; PNG top-left tiles; glyph UV Y flipped",
                  "glyphs": len(atlas.entries), "sha256": digest(atlas_path)},
        "font": dict(font_report, source_sha256=FONT_SHA256, license="SIL OFL 1.1"),
        "chapters": [{"start": a, "end": b, "title": title, "action": action} for a, b, title, action in CHAPTERS],
        "subtitles": [{"id": name, "start": a, "end": min(b, 120), "text": TEXT[name]} for name, a, b, _, _ in CUES],
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
