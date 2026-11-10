"""Compile actual LaTeX glyph layout and Chinese/Latin text to a reusable SDF atlas.

Every glyph retains its individual position and natural aspect. Independent SDF
tiles let the film move matching symbols and interpolate different glyph shapes;
they are not point clouds or pre-rendered movie frames.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import cairosvg
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import distance_transform_edt
from svgelements import Path as SVGPath

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools/reference"))
ATLAS_SIZE = 4096
TILE_SIZE = 192
PADDING = 24
INK_SIZE = TILE_SIZE - 2 * PADDING
SDF_RANGE = 24.0
NS = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}"
FORMULAS = {
    "algebra0": r"(a+b)^2",
    "algebra1": r"a^2+2ab+b^2",
    "quadratic0": r"ax^2+bx+c=0",
    "quadratic1": r"x={-b\pm\sqrt{b^2-4ac}\over2a}",
    "exp0": r"e^{i\theta}",
    "exp1": r"\cos\theta+i\sin\theta",
    "exp2": r"e^{i\pi}+1=0",
    "calculus0": r"f(x)=x^3",
    "calculus1": r"f'(x)=3x^2",
    "calculus2": r"\int_0^1 3x^2\,dx=1",
    "fourier0": r"f(t)=\sin t",
    "fourier1": r"\sin t+{1\over3}\sin3t",
    "fourier2": r"\sin t+{1\over3}\sin3t+{1\over5}\sin5t",
    "fourier3": r"\sin t+{1\over3}\sin3t+{1\over5}\sin5t+{1\over7}\sin7t",
    "matrix0": r"\begin{pmatrix}1&0\\0&1\end{pmatrix}",
    "matrix1": r"\begin{pmatrix}\cos\theta&-\sin\theta\\\sin\theta&\cos\theta\end{pmatrix}",
}
TEXTS = {
    "c_thought": "思想", "c_shape": "形状", "c_formula": "公式", "c_universe": "万象",
    "c_title": "让想法，成为可见", "morph": "MORPH", "math": "MATH", "magic": "MAGIC",
    "brand": "PYREACT / MANIM", "opening": "FROM A POINT TO INFINITY",
    "title_en": "METAMORPHOSIS", "geometry_label": "GEOMETRY", "algebra_label": "ALGEBRA",
    "complex_label": "COMPLEX PLANE", "calculus_label": "CALCULUS",
    "harmonics_label": "HARMONICS", "finale_label": "INFINITE POSSIBILITIES",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sdf_tile(mask):
    """Signed pixel distance, positive inside, including subpixel edge coverage."""
    alpha = np.asarray(mask.convert("L"), dtype=float) / 255.0
    inside = alpha >= 0.5
    distance = distance_transform_edt(inside) - distance_transform_edt(~inside)
    distance += np.where(inside, -0.5, 0.5)
    fractional = (alpha > 0.0) & (alpha < 1.0)
    distance[fractional] = alpha[fractional] - 0.5
    encoded = np.rint(np.clip(0.5 + distance / (SDF_RANGE * 2), 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(encoded)


class Atlas:
    def __init__(self):
        self.image = Image.new("RGBA", (ATLAS_SIZE, ATLAS_SIZE), (0, 0, 0, 255))
        self.entries = {}

    def add(self, identity, mask, description):
        if identity in self.entries:
            return self.entries[identity]
        index = len(self.entries)
        columns = ATLAS_SIZE // TILE_SIZE
        x, y = (index % columns) * TILE_SIZE, (index // columns) * TILE_SIZE
        if y + TILE_SIZE > ATLAS_SIZE:
            raise ValueError("SDF atlas capacity exceeded")
        # Independent normalization axes preserve thin TeX rules. World size
        # below restores each glyph's original aspect without changing layout.
        mask = mask.resize((INK_SIZE, INK_SIZE), Image.Resampling.LANCZOS)
        padded = Image.new("L", (TILE_SIZE, TILE_SIZE))
        padded.paste(mask, (PADDING, PADDING))
        sdf = sdf_tile(padded)
        self.image.paste(Image.merge("RGBA", (sdf, sdf, sdf, Image.new("L", sdf.size, 255))), (x, y))
        entry = {"id": identity, "tile": [x, y, TILE_SIZE, TILE_SIZE], "description": description}
        self.entries[identity] = entry
        return entry


def svg_path_mask(path, bounds):
    x0, y0, x1, y1 = bounds
    root = ET.Element("svg", {"xmlns": "http://www.w3.org/2000/svg",
                              "viewBox": "%s %s %s %s" % (x0, y0, x1 - x0, y1 - y0),
                              "preserveAspectRatio": "none"})
    ET.SubElement(root, "path", {"d": path, "fill": "white"})
    png = cairosvg.svg2png(bytestring=ET.tostring(root), output_width=INK_SIZE * 4,
                          output_height=INK_SIZE * 4)
    return Image.open(io.BytesIO(png)).getchannel("A")


def svg_items(svg, atlas):
    document = ET.fromstring(svg)
    definitions = {element.attrib["id"]: element for element in document.iter()
                   if "id" in element.attrib}
    output = []

    def visit(element):
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "defs":
            return
        # Current pinned dvisvgm output uses direct x/y placement. Reject rather
        # than silently flatten a new transform convention incorrectly.
        if element.attrib.get("transform"):
            raise ValueError("Unexpected dvisvgm transform: " + element.attrib["transform"])
        if tag == "use":
            reference = element.attrib.get(XLINK + "href", element.attrib.get("href", ""))
            target = definitions[reference.lstrip("#")]
            if target.tag.rsplit("}", 1)[-1] != "path":
                raise ValueError("Unexpected SVG use target")
            path = target.attrib["d"]
            bounds = SVGPath(path).bbox()
            if bounds is None:
                return
            identity = "tex_" + digest(path.encode())[:20]
            entry = atlas.add(identity, svg_path_mask(path, bounds), reference)
            dx, dy = float(element.attrib.get("x", 0)), float(element.attrib.get("y", 0))
            output.append({"id": identity, "tile": entry["tile"],
                           "bounds": [bounds[0] + dx, bounds[1] + dy, bounds[2] + dx, bounds[3] + dy]})
            return
        if tag == "rect":
            x, y = float(element.attrib.get("x", 0)), float(element.attrib.get("y", 0))
            width, height = float(element.attrib["width"]), float(element.attrib["height"])
            entry = atlas.add("tex_rule", Image.new("L", (INK_SIZE, INK_SIZE), 255), "LaTeX fraction/radical rule")
            output.append({"id": entry["id"], "tile": entry["tile"], "bounds": [x, y, x + width, y + height]})
            return
        if tag == "path":
            raise ValueError("Unexpected direct path outside defs")
        for child in element:
            visit(child)

    visit(document)
    return output


def normalize_group(items, source, kind):
    if not items:
        raise ValueError("Empty glyph group")
    low_x = min(item["bounds"][0] for item in items)
    low_y = min(item["bounds"][1] for item in items)
    high_x = max(item["bounds"][2] for item in items)
    high_y = max(item["bounds"][3] for item in items)
    height = high_y - low_y
    center_x, center_y = (low_x + high_x) / 2, (low_y + high_y) / 2
    glyphs = []
    for item in items:
        x0, y0, x1, y1 = item["bounds"]
        glyphs.append({"id": item["id"], "tile": item["tile"],
                       "center": [((x0 + x1) / 2 - center_x) / height,
                                  -((y0 + y1) / 2 - center_y) / height],
                       "size": [(x1 - x0) / height * TILE_SIZE / INK_SIZE,
                                (y1 - y0) / height * TILE_SIZE / INK_SIZE],
                       "ink_size": [(x1 - x0) / height, (y1 - y0) / height]})
    return {"kind": kind, "source": source, "width": (high_x - low_x) / height, "height": 1.0,
            "raw_bounds": [low_x, low_y, high_x, high_y], "glyphs": glyphs}


def text_items(text, path, atlas):
    font = ImageFont.truetype(str(path), 320)
    position = 0.0
    items = []
    font_hash = digest(Path(path).read_bytes())[:12]
    for character in text:
        x0, y0, x1, y1 = font.getbbox(character)
        if x1 > x0 and y1 > y0 and not character.isspace():
            mask = Image.new("L", (x1 - x0, y1 - y0))
            ImageDraw.Draw(mask).text((-x0, -y0), character, font=font, fill=255)
            identity = "font_" + font_hash + "_%04x" % ord(character)
            entry = atlas.add(identity, mask, character)
            items.append({"id": identity, "tile": entry["tile"],
                          "bounds": [position + x0, y0, position + x1, y1]})
        position += font.getlength(character)
    return items


def make_contact_sheet(groups, atlas, output):
    width, row_height = 1600, 170
    image = Image.new("RGB", (width, row_height * len(groups)), (6, 12, 22))
    label_font = ImageFont.truetype(str(ROOT / "tools/reference/fonts/DejaVuSerif.ttf"), 18)
    draw = ImageDraw.Draw(image)
    for index, (name, group) in enumerate(groups.items()):
        scale = min(108, 1320 / group["width"])
        baseline = index * row_height + row_height / 2
        draw.text((12, baseline - 10), name, font=label_font, fill=(120, 160, 190))
        for glyph in group["glyphs"]:
            x, y, w, h = glyph["tile"]
            sdf = np.asarray(atlas.crop((x, y, x + w, y + h)).getchannel("R"), dtype=float)
            alpha = np.clip((sdf / 255 - 0.5) * 48 + 0.5, 0, 1)
            mask = Image.fromarray(np.rint(alpha * 255).astype(np.uint8))
            size = tuple(max(1, round(axis * scale)) for axis in glyph["size"])
            mask = mask.resize(size, Image.Resampling.LANCZOS)
            px = round(920 + glyph["center"][0] * scale - size[0] / 2)
            py = round(baseline - glyph["center"][1] * scale - size[1] / 2)
            image.paste((220, 238, 242), (px, py), mask)
    image.save(output / "type-contact.png")


def build(output):
    from pyreact_manim.reference.exporter import _reference_environment, _upstream_import_arguments
    from pyreact_manim.reference.mobject_source import native_tex_environment
    from setup_cjk import build_subset
    output.mkdir(parents=True, exist_ok=True)
    svg_directory = output / "svg"
    svg_directory.mkdir(exist_ok=True)
    _reference_environment()
    with _upstream_import_arguments():
        from manimlib import Tex
        from manimlib.config import manim_config
    manim_config.directories.cache = str(output / "tex-cache")
    atlas, groups = Atlas(), {}
    for name, formula in FORMULAS.items():
        with native_tex_environment():
            svg = Tex(formula, template="basic").get_svg_string()
        (svg_directory / (name + ".svg")).write_text(svg, encoding="utf-8")
        groups[name] = normalize_group(svg_items(svg, atlas), formula, "latex")
        print("formula", name, len(groups[name]["glyphs"]), flush=True)
    song = output / "ShowcaseV2Song.ttf"
    source_font = ROOT / ".runtime/cjk-font-source/serif/NotoSerifSC-VF.ttf"
    if digest(source_font.read_bytes()) != "050080d9255a86808f2945bffac582b31ef32bc36411ce29563b4961670c66f9":
        raise ValueError("Pinned Noto Serif SC source mismatch")
    build_subset(source_font, song, "".join(TEXTS.values()), "serif")
    for name, text in TEXTS.items():
        font = song if any(ord(character) > 127 for character in text) else ROOT / "tools/reference/fonts/DejaVuSerif.ttf"
        groups[name] = normalize_group(text_items(text, font, atlas), text, "text")
    groups["final"] = deepcopy(groups["exp2"])
    atlas_path = output / "type_atlas.png"
    atlas.image.save(atlas_path, optimize=True)
    report = {"schema": 1, "atlas": atlas_path.name, "atlas_size": [ATLAS_SIZE, ATLAS_SIZE],
              "tile_size": TILE_SIZE, "padding": PADDING, "ink_size": INK_SIZE,
              "sdf": {"channel": "R", "threshold": 0.5, "range_pixels": SDF_RANGE,
                      "decode": "(sample.r - 0.5) * 48.0; positive inside",
                      "axes": "Each tile normalizes ink X/Y independently; glyph size restores natural aspect.",
                      "sampler": "Point plus manual bilinear, clamp per tile; do not sample adjacent tiles"},
              "coordinates": "Groups centered at origin; Y up. Atlas rectangles use PNG top-left origin; flip glyph UV Y.",
              "groups": groups, "shapes": atlas.entries,
              "sha256": digest(atlas_path.read_bytes()), "unique_shapes": len(atlas.entries),
              "provenance": {"formulas": "ManimGL 1.7.2 Tex / native LaTeX + dvisvgm; per-use layout preserved",
                             "song": "Noto Serif SC OFL-1.1 derived 400-weight subset", "latin": "DejaVu Serif"}}
    (output / "type_data.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    make_contact_sheet(groups, atlas.image, output)
    print(json.dumps({"atlas": str(atlas_path), "unique_shapes": len(atlas.entries),
                      "groups": {name: len(group["glyphs"]) for name, group in groups.items()},
                      "bytes": atlas_path.stat().st_size}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/showcase-v2")
    args = parser.parse_args()
    build(args.output.resolve())
