"""Build the showcase's Song-type masks and genuine outline-point transport.

The two short words use real font outlines, sampled at equal arc length and
matched by minimum squared travel. This is a point-cloud morph, not a claim of
Manim Transform's path topology. No font files are shipped to the game.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from scipy.optimize import linear_sum_assignment


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools/reference"))
SIZE = 2048
POINT_COUNT = 256
SOURCE_Y = 2040
TARGET_Y = 2041
FONT_HASH = "050080d9255a86808f2945bffac582b31ef32bc36411ce29563b4961670c66f9"
LABELS = [
    ("title", "让想法，成为可见", "song", (32, 32, 1984, 256), 0),
    ("opening_en", "FROM A POINT. TO POSSIBILITY.", "latin", (32, 320, 1984, 128), 8),
    ("brand", "PYREACT / MANIM", "latin", (32, 480, 1984, 128), 16),
    ("source_word", "想法", "song", (32, 640, 944, 384), 0),
    ("target_word", "可见", "song", (1056, 640, 944, 384), 0),
    ("chapter_light", "光", "song", (32, 1056, 448, 256), 0),
    ("chapter_shape", "形", "song", (544, 1056, 448, 256), 0),
    ("chapter_rhythm", "律", "song", (1056, 1056, 448, 256), 0),
    ("chapter_universe", "万象", "song", (1568, 1056, 448, 256), 0),
    ("footer", "MATHEMATICS IN MOTION", "latin", (32, 1680, 1984, 128), 14),
    ("signature", "EVERY IDEA BEGINS WITH A POINT", "latin", (32, 1856, 1984, 112), 7),
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_mask(text, font_path, tracking=0):
    font = ImageFont.truetype(str(font_path), 320)
    measured = font.getbbox(text)
    width = int(font.getlength(text) + max(0, len(text) - 1) * tracking + 64)
    image = Image.new("L", (width, measured[3] - measured[1] + 64))
    draw = ImageDraw.Draw(image)
    if tracking:
        x = 32
        for character in text:
            draw.text((x, 32 - measured[1]), character, font=font, fill=255)
            x += font.getlength(character) + tracking
    else:
        draw.text((32, 32 - measured[1]), text, font=font, fill=255)
    bounds = image.getbbox()
    if not bounds:
        raise ValueError("Empty rendered label: " + text)
    return image.crop(bounds)


def place_mask(atlas, mask, box):
    x, y, width, height = box
    scale = min((width - 16) / mask.width, (height - 16) / mask.height)
    size = (max(1, round(mask.width * scale)), max(1, round(mask.height * scale)))
    mask = mask.resize(size, Image.Resampling.LANCZOS)
    x += (width - mask.width) // 2
    y += (height - mask.height) // 2
    white = Image.merge("RGBA", (mask, mask, mask, Image.new("L", mask.size, 255)))
    atlas.paste(white, (x, y))
    # Rect has a four-pixel clear margin, suitable for clamp/masked bilinear use.
    rect = [x - 4, y - 4, mask.width + 8, mask.height + 8]
    return {"rect": rect, "ink_rect": [x, y, mask.width, mask.height],
            "aspect": mask.width / mask.height,
            "uv": [value / SIZE for value in rect]}


class OutlinePen(BasePen):
    """Dense deterministic quadratic/cubic sampling before arc-length sampling."""

    def __init__(self, glyph_set):
        super().__init__(glyph_set)
        self.contours = []
        self.current = []

    def _moveTo(self, point):
        self.current = [np.asarray(point, dtype=float)]

    def _lineTo(self, point):
        self.current.append(np.asarray(point, dtype=float))

    def _qCurveToOne(self, control, end):
        start = self.current[-1]
        control, end = np.asarray(control), np.asarray(end)
        for alpha in np.linspace(0, 1, 25)[1:]:
            self.current.append((1 - alpha) ** 2 * start + 2 * alpha * (1 - alpha) * control + alpha ** 2 * end)

    def _curveToOne(self, first, second, end):
        start = self.current[-1]
        first, second, end = np.asarray(first), np.asarray(second), np.asarray(end)
        for alpha in np.linspace(0, 1, 33)[1:]:
            self.current.append((1 - alpha) ** 3 * start + 3 * alpha * (1 - alpha) ** 2 * first
                                + 3 * alpha ** 2 * (1 - alpha) * second + alpha ** 3 * end)

    def _closePath(self):
        if len(self.current) > 1:
            if np.linalg.norm(self.current[0] - self.current[-1]) > 1e-9:
                self.current.append(self.current[0])
            self.contours.append(np.asarray(self.current))
        self.current = []

    def _endPath(self):
        self._closePath()


def outline_points(text, path, count=POINT_COUNT):
    contours = []
    with TTFont(path) as font:
        glyph_set, cmap = font.getGlyphSet(), font.getBestCmap()
        position = 0.0
        for character in text:
            name = cmap[ord(character)]
            pen = OutlinePen(glyph_set)
            glyph_set[name].draw(pen)
            contours.extend(part + (position, 0) for part in pen.contours)
            position += glyph_set[name].width
    all_points = np.concatenate(contours)
    low, high = all_points.min(axis=0), all_points.max(axis=0)
    scale = min(3.6 / (high[0] - low[0]), 1.6 / (high[1] - low[1]))
    contours = [(part - (high + low) / 2) * scale for part in contours]
    lengths = np.array([np.linalg.norm(np.diff(part, axis=0), axis=1).sum() for part in contours])
    allocation = np.maximum(2, np.floor(count * lengths / lengths.sum()).astype(int))
    while allocation.sum() > count:
        choices = np.where(allocation > 2)[0]
        allocation[choices[np.argmax(allocation[choices] / lengths[choices])]] -= 1
    while allocation.sum() < count:
        allocation[np.argmax(lengths / allocation)] += 1
    result = []
    for contour, slots in zip(contours, allocation):
        cumulative = np.r_[0, np.cumsum(np.linalg.norm(np.diff(contour, axis=0), axis=1))]
        sample = np.linspace(0, cumulative[-1], slots, endpoint=False)
        result.extend(np.column_stack([np.interp(sample, cumulative, contour[:, axis]) for axis in (0, 1)]))
    return np.asarray(result), {"bounds": [*((low - (high + low) / 2) * scale),
                                          *((high - (high + low) / 2) * scale)],
                                "contours": len(contours), "count": count}


def encode_points(points):
    if points.shape != (POINT_COUNT, 2) or not np.isfinite(points).all() or (np.abs(points) > 2).any():
        raise ValueError("Invalid point cloud")
    quantized = np.rint((points + 2.0) / 4.0 * 65535).astype(np.uint16)
    rgba = np.column_stack([quantized[:, 0] >> 8, quantized[:, 0] & 255,
                            quantized[:, 1] >> 8, quantized[:, 1] & 255]).astype(np.uint8)
    decoded = np.column_stack([rgba[:, 0].astype(float) * 256 + rgba[:, 1],
                               rgba[:, 2].astype(float) * 256 + rgba[:, 3]]) / 65535 * 4 - 2
    if np.abs(decoded - points).max() > 2 / 65535 + 1e-10:
        raise AssertionError("Point encoding exceeds half a quantization step")
    return rgba


def latex_mask(output):
    from pyreact_manim.reference.exporter import _reference_environment, _upstream_import_arguments
    from pyreact_manim.reference.mobject_source import native_tex_environment
    _reference_environment()
    with _upstream_import_arguments():
        from manimlib import Tex
        from manimlib.config import manim_config
    manim_config.directories.cache = str(output / "tex-cache")
    with native_tex_environment():
        formula = Tex(r"e^{i\theta}=\cos\theta+i\sin\theta", template="basic")
    svg = formula.get_svg_string()
    (output / "euler.svg").write_text(svg, encoding="utf-8")
    import cairosvg
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=1968)
    image = Image.open(io.BytesIO(png)).convert("RGBA").getchannel("A")
    return image.crop(image.getbbox())


def build(output):
    from setup_cjk import build_subset
    output.mkdir(parents=True, exist_ok=True)
    source = ROOT / ".runtime/cjk-font-source/serif/NotoSerifSC-VF.ttf"
    if not source.is_file() or sha256(source) != FONT_HASH:
        raise ValueError("Pinned Noto Serif SC source missing; run tools/reference/setup_cjk.py first")
    song = output / "ShowcaseSong.ttf"
    build_subset(source, song, "".join(label[1] for label in LABELS), "serif")
    fonts = {"song": song, "latin": ROOT / "tools/reference/fonts/DejaVuSerif.ttf"}
    atlas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 255))
    labels = {}
    for name, text, family, box, tracking in LABELS:
        labels[name] = dict(text=text, **place_mask(atlas, text_mask(text, fonts[family], tracking), box))
    labels["formula"] = dict(text=r"e^{i\theta}=\cos\theta+i\sin\theta",
                             **place_mask(atlas, latex_mask(output), (32, 1376, 1984, 256)))
    source_points, source_info = outline_points("想法", song)
    target_points, target_info = outline_points("可见", song)
    cost = ((source_points[:, None, :] - target_points[None, :, :]) ** 2).sum(axis=2)
    rows, columns = linear_sum_assignment(cost)
    if not np.array_equal(rows, np.arange(POINT_COUNT)):
        raise AssertionError("Point assignment is incomplete")
    target_points = target_points[columns]
    for y, points in ((SOURCE_Y, source_points), (TARGET_Y, target_points)):
        atlas.paste(Image.fromarray(encode_points(points)[None, :, :]), (0, y))
    atlas_path = output / "showcase_atlas.png"
    atlas.save(atlas_path, optimize=True)
    report = {
        "schema": 1, "size": [SIZE, SIZE], "atlas": atlas_path.name,
        "sha256": sha256(atlas_path), "sampler": "Point; manually bilinear text only",
        "texture_coordinates": "top-left pixel origin, x right, y down; use texel centers",
        "mask_channel": "R", "labels": labels,
        "morph": {"kind": "equal-arc-length font-outline point-cloud transport",
                  "source": "想法", "target": "可见", "source_row": SOURCE_Y, "target_row": TARGET_Y,
                  "count": POINT_COUNT, "first_column": 0, "encoding": "RG=x uint16 big-endian, BA=y uint16 big-endian",
                  "decode": "(high*255*256+low*255)/65535*4-2", "geometry_y": "up",
                  "source_geometry": source_info, "target_geometry": target_info,
                  "assignment": "scipy.optimize.linear_sum_assignment, minimum squared displacement",
                  "max_quantization_error": 2 / 65535,
                  "source_points": source_points.tolist(), "target_points": target_points.tolist()},
        "fonts": {"song": {"family": "Noto Serif SC / derived Pyreact Manim Song", "weight": 400,
                           "source_sha256": FONT_HASH, "subset_sha256": sha256(song), "license": "OFL-1.1"},
                  "latin": {"family": "DejaVu Serif", "sha256": sha256(fonts["latin"]),
                            "license": "tools/reference/fonts/LICENSE_DEJAVU"}},
        "formula_renderer": "ManimGL 1.7.2 Tex + installed LaTeX / dvisvgm, CairoSVG alpha rasterization",
    }
    (output / "typography.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    preview = Image.new("RGB", (1440, 400), (6, 14, 23))
    draw = ImageDraw.Draw(preview)
    for index, alpha in enumerate((0, 0.5, 1)):
        for x, y in source_points * (1 - alpha) + target_points * alpha:
            px, py = 240 + index * 480 + x * 110, 200 - y * 110
            draw.ellipse((px - 1.9, py - 1.9, px + 1.9, py + 1.9), fill=(76, 230, 221))
    preview.save(output / "morph-preview.png")
    print(json.dumps({"atlas": str(atlas_path), "bytes": atlas_path.stat().st_size,
                      "labels": {name: item["rect"] for name, item in labels.items()},
                      "morph_rows": [SOURCE_Y, TARGET_Y]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/showcase-assets")
    arguments = parser.parse_args()
    build(arguments.output.resolve())
