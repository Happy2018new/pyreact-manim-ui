"""Build the abstract wind-and-starlight film, Song typography and manifest.

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
    "opening_a": "风，记得每一颗星的名字",
    "opening_b": "也记得，它们回家的方向",
    "birth": "风轻轻一旋，一颗星醒了",
    "meteor": "它奔向远方，拖着长长的梦",
    "shatter": "一瞬，梦碎成了漫天微光",
    "drift": "风把散落的名字，藏进旋涡",
    "soul": "微光循风相认，灵魂一片片归来",
    "return": "终于，所有微光都认出了自己",
    "title": "风借来的一颗星",
    "motto": "风起时，灵魂记得归途",
}
OPENING_LINES = [
    {"id": "opening_a", "start": 1.0, "reveal_end": 4.6, "hold_until": 12.0,
     "center": [-2.0, 1.6], "height": .50, "width": 9.0},
    {"id": "opening_b", "start": 5.8, "reveal_end": 9.4, "hold_until": 18.0,
     "center": [2.0, -1.2], "height": .50, "width": 9.0},
]
STAR_ANCHOR = (-.4, .2)
OPENING_COLLAPSE = (12.0, 16.0)
TRANSFORM_SECONDS = 1.15
CUES = [
    ("birth", 18.0, 34.0, .34, -2.72),
    ("meteor", 34.0, 43.0, .34, -2.72),
    ("shatter", 43.0, 54.0, .34, -2.72),
    ("drift", 54.0, 76.0, .34, -2.72),
    ("soul", 76.0, 96.0, .34, -2.72),
    ("return", 96.0, 110.2, .34, -2.72),
    ("title", 110.2, 120.5, .78, .50),
    ("motto", 113.5, 120.5, .275, -.72),
]
CHAPTERS = [
    (0, 18, "风记得名字", "两行错位宋体先后缓慢展开，金青风线托住文字；第一句收拢为星核。"),
    (18, 34, "星核初醒", "风线绕成轨道，同一束光在旋转的闭合曲线中醒来。"),
    (34, 54, "梦碎成微光", "流星拖曳长弧；43秒撞击后，同一批星光轮廓散成碎片。"),
    (54, 76, "名字在风里", "碎片沿风线和旋涡漂流，保持各自轮廓与连续运动。"),
    (76, 96, "灵魂归来", "散落的轮廓沿弧线逐片重组，风与星光重新形成同一个核心。"),
    (96, 110, "认出自己", "重组后的星核舒展为明亮星光，细线轨道逐渐安定。"),
    (110, 120, "风借来的一颗星", "末句轮廓展开成片名，结语从片名附近的光点生长，风线与星光陪伴停留。"),
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
        "schema": 3, "id": "story_showcase", "title": TEXT["title"],
        "duration": 120.0, "fps": 60, "resolution": [1920, 1080],
        "style": "纯抽象数学线条童话、深靛星空、金青发光风线、固定身份星光碎片、宋体轮廓短诗",
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
                     "provenance": "original parametric wind lines, orbital curves and persistent closed starlight contours",
                     "opening_star_anchor": list(STAR_ANCHOR), "main_star_anchor": [0, .2],
                     "meteor_impact_seconds": 43.0, "reassembly_seconds": [76.0, 96.0],
                     "caption_band_center_y": -2.72,
                     "transition": "continuous positions and corresponding closed contours across chapters"},
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
