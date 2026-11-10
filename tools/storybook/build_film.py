"""Build Wind's Reply, a geometric fairy tale with Song contour typography.

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

FONT_SHA256 = "050080d9255a86808f2945bffac582b31ef32bc36411ce29563b4961670c66f9"
TEXT = {
    "opening_a": "如果星光散落",
    "opening_b": "风会替它记住归途",
    "birth": "一束风，托起一颗星",
    "meteor": "它把远方，照成一条路",
    "shatter": "光碎了，名字还在",
    "drift": "每一片，都有归处",
    "rhythm": "风听见了它们的回声",
    "soul": "散落的光，重新相认",
    "return": "于是，夜空有了回信",
    "title": "风的回信",
    "motto": "风会记住，每一束光",
}
OPENING_LINES = [
    {"id": "opening_a", "start": 1.0, "reveal_end": 4.4, "hold_until": 12.0,
     "center": [-2.0, 1.5], "height": .65, "width": 8.6},
    {"id": "opening_b", "start": 5.3, "reveal_end": 8.7, "hold_until": 16.0,
     "center": [1.8, -1.0], "height": .65, "width": 9.8},
]
STAR_ANCHOR = (-1.2, .45)
OPENING_COLLAPSE = (12.0, 16.0)
TRANSFORM_SECONDS = 1.15
CUES = [
    ("birth", 16.0, 32.0, .36, -3.05),
    ("meteor", 32.0, 43.0, .36, -3.05),
    ("shatter", 43.0, 54.0, .36, -3.05),
    ("drift", 54.0, 64.0, .36, -3.05),
    ("rhythm", 64.0, 78.0, .36, -3.05),
    ("soul", 78.0, 96.0, .36, -3.05),
    ("return", 96.0, 110.0, .36, -3.05),
    ("title", 110.0, 120.5, .96, .55),
    ("motto", 113.4, 120.5, .34, -.72),
]
CHAPTERS = [
    (0, 16, "如果星光散落", "左上与右下两行大宋体先后淡入并展开轮廓，青金风带托住文字；第一句收拢为星核。"),
    (16, 32, "一束风与一颗星", "有宽窄变化的风带托起清晰的大星核，双层几何瓣片构成可辨认的完整形。"),
    (32, 44, "光碎了，名字还在", "明亮流星拖着长尾划过；43秒撞击，完整星核拆为24片有面积的几何碎片。"),
    (44, 64, "每一片都有归处", "同一批碎片分层散开，在横跨画面的风带中旋转漂流，保留各自轮廓与身份。"),
    (64, 78, "风听见回声", "风从乱流中找到旋转节拍，大片碎片进入不同半径的回旋轨道。"),
    (78, 96, "散落的光重新相认", "24片几何碎片逐片沿弧归位，94秒完成双层十二瓣光冠，并迎来明亮绽放。"),
    (96, 110, "夜空有了回信", "大光冠舒展为开阔光翼，中央星核与左右长线保持完整的几何构图。"),
    (110, 120, "风的回信", "末句轮廓变成大标题，结语轮廓随之展开；安定的光翼与风带陪伴片名停留。"),
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def layout(group, height, y, x=0.0, width=12.6):
    scale = min(height, width / group["width"])
    glyphs = deepcopy(group["glyphs"])
    for glyph in glyphs:
        glyph["center"] = [glyph["center"][0] * scale + x, glyph["center"][1] * scale + y]
        glyph["size"] = [value * scale for value in glyph["size"]]
        glyph["opacity"] = 1.0
    return glyphs


def nearest(glyphs, center):
    return min(glyphs, key=lambda glyph: sum(
        (glyph["center"][axis] - center[axis]) ** 2 for axis in range(2)))


def collapsed(glyph, center):
    result = deepcopy(glyph)
    result["center"], result["opacity"] = list(center), 0.0
    return result


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
        anchor = nearest(target, first["center"])
        second = collapsed(first, anchor["center"])
        pairs.append((first, second))
    for bi in unmatched_b[count:]:
        second = target[bi]
        anchor = nearest(source, second["center"])
        first = collapsed(second, anchor["center"])
        pairs.append((first, second))
    return pairs


def typography(groups, morph):
    lines = ["void typography(inout vec3 c,vec2 p,float t,float aa) {"]
    layouts = {name: layout(groups[name], height, y) for name, _, _, height, y in CUES}
    for cue in OPENING_LINES:
        name, start, end = cue["id"], cue["start"], cue["hold_until"]
        x, y = cue["center"]
        target = layouts[name] = layout(groups[name], cue["height"], y, x, cue["width"])
        lines.append("if(t>=%.3f && t<%.3f) {" % (start, end))
        # The opening alone combines a gentle alpha entrance with real contour
        # growth. Later captions have constant opacity throughout their morphs.
        opacity = "smoothstep(%.4f,%.4f,t)" % (start, start + 2.0)
        duration = cue["reveal_end"] - start
        stagger_span = min(1.5, duration * .42)
        for index, glyph in enumerate(target):
            origin = collapsed(glyph, (glyph["center"][0], y - .24))
            begin = start + stagger_span * index / max(1, len(target) - 1)
            amount = "smoothstep(%.4f,%.4f,t)" % (begin, begin + duration - stagger_span)
            lines.append(render_vector_pairs(morph, [(origin, glyph)], amount=amount,
                         opacity=opacity, arc_strength=0, color="PAPER"))
        lines.append("}")

    begin, end = OPENING_COLLAPSE
    lines.append("if(t>=%.3f && t<%.3f) { float u=smoothstep(%.3f,%.3f,t);" % (
        begin, end, begin, end))
    pairs = [(glyph, collapsed(glyph, STAR_ANCHOR)) for glyph in layouts["opening_a"]]
    lines.append(render_vector_pairs(morph, pairs, amount="u", opacity="1.0", arc_strength=.08,
                                    color="mix(PAPER,GOLD,u)"))
    lines.append("}")

    previous = "opening_b"
    for name, start, end, _height, _y in CUES:
        target = layouts[name]
        lines.append("if(t>=%.3f && t<%.3f) {" % (start, end))
        lines.append("float u=smoothstep(%.4f,%.4f,t);" % (start, start + TRANSFORM_SECONDS))
        if name == "motto":
            # Retain the completed title. New contours unfold from its nearby
            # glyph anchors; drawing a second complete title would overprint it.
            pairs = [(collapsed(glyph, nearest(layouts["title"], glyph["center"])["center"]), glyph)
                     for glyph in target]
            lines.append(render_vector_pairs(morph, pairs, amount="u", opacity="1.0",
                         arc_strength=0, color="PAPER"))
        else:
            source = layouts[previous]
            lines.append(render_vector_pairs(morph, correspondence(source, target), amount="u",
                         opacity="1.0", arc_strength=.25 if name == "title" else .065,
                         color="mix(PAPER,GOLD,u)" if name == "title" else "PAPER"))
        lines.append("}")
        previous = name
    lines.append("}")
    return "\n".join(lines)


def subtitle_manifest():
    subtitles = []
    for cue in OPENING_LINES:
        name = cue["id"]
        item = {"id": name, "text": TEXT[name], "start": cue["start"],
                "end": OPENING_COLLAPSE[1] if name == "opening_a" else cue["hold_until"],
                "center": cue["center"], "height": cue["height"], "max_width": cue["width"],
                "reveal_end": cue["reveal_end"], "hold_until": cue["hold_until"],
                "transition": "staggered closed-contour growth from baseline points with opening-only alpha fade",
                "fade_in": {"start": cue["start"], "end": cue["start"] + 2.0}}
        if name == "opening_a":
            item["collapse"] = {"start": OPENING_COLLAPSE[0], "end": OPENING_COLLAPSE[1],
                                "anchor": list(STAR_ANCHOR), "opacity": 1.0,
                                "transition": "closed contours contract to the star core; no alpha fade"}
        subtitles.append(item)
    previous = "opening_b"
    for name, start, end, height, y in CUES:
        subtitles.append({"id": name, "text": TEXT[name], "start": start, "end": min(end, 120),
                          "center": [0, y], "height": height, "max_width": 12.6,
                          "source": "title_anchor_points" if name == "motto" else previous,
                          "transform_seconds": TRANSFORM_SECONDS,
                          "transition_end": start + TRANSFORM_SECONDS,
                          "hold_until_next_transform": True, "opacity": 1.0,
                          "transition": "closed-contour point correspondence; no sentence alpha fade"})
        previous = name
    return subtitles


def build(output):
    output = Path(output)
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
    replacements = {"// __STORY_VECTOR_MORPH__": vector_shader_source(composite="over"),
                    "// __STORY_TYPOGRAPHY__": typography_source}
    for marker, content in replacements.items():
        if shader.count(marker) != 1:
            raise ValueError("Expected one story shader insertion point: " + marker)
        shader = shader.replace(marker, content)
    if "// __STORY_" in shader:
        raise ValueError("Unresolved story shader insertion point")
    shader_path = output / "story_showcase.fragment"
    shader_path.write_text(shader, encoding="utf-8", newline="\n")
    production_shader = ROOT / "resource_pack/shaders/glsl/story_showcase.fragment"
    production_atlas = ROOT / "resource_pack/textures/manim/story_showcase.png"
    production_shader.parent.mkdir(parents=True, exist_ok=True)
    production_atlas.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(shader_path, production_shader)
    shutil.copyfile(atlas_path, production_atlas)
    manifest = {
        "schema": 4, "id": "story_showcase", "title": TEXT["title"],
        "duration": 120.0, "fps": 60, "resolution": [1920, 1080],
        "style": "纯二维几何线条童话、明亮奶白主线、青绿风带、温金与少量珊瑚强调、局部半透明几何面、宋体轮廓短诗",
        "shader": "shaders/glsl/story_showcase.fragment",
        "texture": "textures/manim/story_showcase", "texture_slot": "TEXTURE_2",
        "uniforms": {"EXTRA_VECTOR1": ["time_seconds", "physical_canvas_aspect", "physical_canvas_height", "opacity"],
                     "EXTRA_VECTOR2": ["flip_y", "canvas_top_fraction", "canvas_height_fraction", "reserved"]},
        "atlas": {"size": [4096, 4096], "tile": 192, "padding": 24, "sdf_range": 24,
                  "sample": "R; manual bilinear; positive inside; PNG top-left tiles; glyph UV Y flipped",
                  "glyphs": len(atlas.entries), "sha256": digest(atlas_path)},
        "font": dict(font_report, source_sha256=FONT_SHA256, license="SIL OFL 1.1"),
        "vector_morph": morph.report(),
        "geometry": {"source": "tools/storybook/film.fragment", "source_sha256": digest(source),
                     "provenance": "original geometric star, shaped wind ribbons and 24 persistent filled contour fragments",
                     "opening_star_anchor": list(STAR_ANCHOR),
                     "main_star_anchor": [0, .45],
                     "persistent_fragments": 24, "reassembled_shape": "double-layer twelve-petal light crown",
                     "main_subject_height_fraction": [.45, .65],
                     "bounded_geometry": {"fragment_vertices": 4, "wind_ribbons": 3,
                                          "segments_per_ribbon": 36, "return_trails": 8,
                                          "segments_per_return_trail": 12,
                                          "meteor_strands": 3, "segments_per_meteor_strand": 20,
                                          "background_dots": 32},
                     "meteor_impact_seconds": 43.0, "reassembly_seconds": [78.0, 94.0],
                     "closing_title_seconds": 110.0, "caption_band_center_y": -3.05,
                     "transition": "the same filled geometric fragments break from the whole star, travel continuously and return along arcs"},
        "chapters": [{"start": a, "end": b, "title": title, "action": action} for a, b, title, action in CHAPTERS],
        "subtitles": subtitle_manifest(),
        "groups": groups,
        "source_sha256": digest(source), "builder_source_sha256": digest(Path(__file__)),
        "shader_sha256": digest(shader_path),
        "build": ".venv-reference/Scripts/python.exe -B -X utf8 tools/storybook/build_film.py",
        "verification": "resources generated; no test, render review, or game acceptance performed for this revision",
    }
    (output / "story.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"story": str(output / "story.json"), "shader": str(production_shader),
                      "atlas": str(production_atlas), "glyphs": len(atlas.entries),
                      "duration": 120, "fps": 60}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "generated")
    build(parser.parse_args().output.resolve())
