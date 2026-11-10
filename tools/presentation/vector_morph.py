"""Offline contour correspondence shared by the two authored films.

Glyph SDFs remain the exact endpoints. Only transitions use corresponding
closed polygon contours, extracted at the same continuous SDF threshold.
The bottom half of the existing atlas stores pairs of RGBA16 xy coordinates;
the shader has one bounded loop, never generated per-vertex source code.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

ATLAS_SIZE = 4096
DATA_Y = 2048
MAX_POINTS = 256


def _area(points):
    return float(np.sum(points[:, 0] * np.roll(points[:, 1], -1)
                        - points[:, 1] * np.roll(points[:, 0], -1)) * .5)


def _contains(points, point):
    a, b = points, np.roll(points, -1, axis=0)
    crossing = (a[:, 1] > point[1]) != (b[:, 1] > point[1])
    a, b = a[crossing], b[crossing]
    return bool(np.count_nonzero(point[0] < a[:, 0] + (point[1] - a[:, 1])
                                 * (b[:, 0] - a[:, 0]) / (b[:, 1] - a[:, 1])) % 2)


def _length(points):
    return float(np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1).sum())


def _contours(image, tile):
    """Marching squares with interpolated crossings and explicit saddle choice."""
    x, y, width, height = (int(value) for value in tile)
    field = np.asarray(image.crop((x, y, x + width, y + height)).getchannel("R"),
                       dtype=np.float64) - 127.5
    signs = field >= 0
    cells = (signs[:-1, :-1].astype(np.uint8) + signs[:-1, 1:] * 2
             + signs[1:, 1:] * 4 + signs[1:, :-1] * 8)
    ys, xs = np.nonzero((cells != 0) & (cells != 15))
    positions, neighbors = {}, {}
    vertical_base = width * height
    for row, column in zip(ys.tolist(), xs.tolist()):
        values = (field[row, column], field[row, column + 1],
                  field[row + 1, column + 1], field[row + 1, column])
        corners = ((column, row), (column + 1, row),
                   (column + 1, row + 1), (column, row + 1))
        keys = (row * width + column, vertical_base + row * width + column + 1,
                (row + 1) * width + column, vertical_base + row * width + column)
        crossed = []
        for edge in range(4):
            following = (edge + 1) % 4
            if (values[edge] >= 0) == (values[following] >= 0):
                continue
            key = keys[edge]
            crossed.append(edge)
            if key not in positions:
                ratio = values[edge] / (values[edge] - values[following])
                start, stop = np.array(corners[edge]), np.array(corners[following])
                at = start + ratio * (stop - start)
                positions[key] = np.array(((at[0] + .5) / width - .5,
                                            .5 - (at[1] + .5) / height))
        if len(crossed) == 2:
            connections = [crossed]
        else:
            same = (values[0] >= 0) == (sum(values) >= 0)
            connections = ((0, 1), (2, 3)) if same else ((0, 3), (1, 2))
        for a, b in connections:
            a, b = keys[a], keys[b]
            neighbors.setdefault(a, []).append(b)
            neighbors.setdefault(b, []).append(a)
    remaining = set(neighbors)
    loops = []
    while remaining:
        start = min(remaining)
        current, previous, ordered = start, None, []
        while True:
            ordered.append(positions[current])
            remaining.discard(current)
            adjacent = neighbors[current]
            if len(adjacent) != 2:
                raise ValueError("Open glyph contour in atlas tile %r" % (tile,))
            following = adjacent[0] if adjacent[0] != previous else adjacent[1]
            previous, current = current, following
            if current == start:
                break
            if current not in remaining:
                raise ValueError("Non-manifold glyph contour in atlas tile %r" % (tile,))
        points = np.array(ordered)
        area = _area(points)
        if len(points) >= 3 and abs(area) > 1e-9:
            loops.append({"points": points, "area": abs(area), "center": points.mean(axis=0),
                          "length": _length(points)})
    loops.sort(key=lambda loop: (-loop["area"], *loop["center"]))
    for index, loop in enumerate(loops):
        containing = [other for other in range(index)
                      if _contains(loops[other]["points"], loop["points"][0])]
        loop["depth"] = len(containing)
        loop["parent"] = containing[-1] if containing else None
        loop["hole"] = bool(len(containing) % 2)
        # Non-zero winding requires opposite orientation for actual counters.
        if (_area(loop["points"]) > 0) == loop["hole"]:
            loop["points"] = loop["points"][::-1]
    if not loops:
        raise ValueError("Glyph tile has no nonzero contour: %r" % (tile,))
    return loops


def _pair_indices(left, right, source, target):
    if not left or not right:
        return [], list(left), list(right)
    costs = np.zeros((len(left), len(right)))
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            first, second = source[a], target[b]
            costs[i, j] = (float(np.sum((first["center"] - second["center"]) ** 2)) * 8
                           + .12 * abs(math.log(first["area"] / second["area"]))
                           + .06 * abs(math.log(first["length"] / second["length"])))
    rows, columns = linear_sum_assignment(costs)
    return ([(left[i], right[j]) for i, j in zip(rows.tolist(), columns.tolist())],
            [a for i, a in enumerate(left) if i not in rows],
            [b for j, b in enumerate(right) if j not in columns])


def _interior_point(points):
    """Find an actual interior anchor, including for concave glyph strokes."""
    center = points.mean(axis=0)
    if _contains(points, center):
        return center
    # Between consecutive vertex heights, scanline intersections are paired
    # interior intervals. Their midpoint cannot fall into a concave notch.
    heights = np.unique(points[:, 1])
    following = np.roll(points, -1, axis=0)
    best, width = None, -1.0
    for y in (heights[:-1] + heights[1:]) * .5:
        crossing = (points[:, 1] > y) != (following[:, 1] > y)
        a, b = points[crossing], following[crossing]
        xs = np.sort(a[:, 0] + (y - a[:, 1]) * (b[:, 0] - a[:, 0])
                     / (b[:, 1] - a[:, 1]))
        for left, right in zip(xs[::2], xs[1::2]):
            if right - left > width:
                best, width = np.array(((left + right) * .5, y)), right - left
    if best is None:
        raise ValueError("A nonzero glyph contour needs an interior anchor")
    return best


def _loop_pairs(source, target):
    outers_a = [i for i, loop in enumerate(source) if not loop["hole"]]
    outers_b = [i for i, loop in enumerate(target) if not loop["hole"]]
    matched, missing_b, missing_a = _pair_indices(outers_a, outers_b, source, target)
    result = []

    def append_pair(a, b, anchor_a=None, anchor_b=None):
        left = source[a]["points"] if a is not None else np.array([anchor_a])
        right = target[b]["points"] if b is not None else np.array([anchor_b])
        hole = source[a]["hole"] if a is not None else target[b]["hole"]
        result.append((left, right, hole))

    def holes(loops, parent):
        return [i for i, loop in enumerate(loops) if loop["hole"] and loop["parent"] == parent]

    for a, b in matched:
        append_pair(a, b)
        paired_holes, lost, born = _pair_indices(holes(source, a), holes(target, b), source, target)
        for first, second in paired_holes:
            append_pair(first, second)
        for first in lost:
            anchor = _interior_point(source[first]["points"])
            append_pair(first, None, anchor_b=anchor)
        for second in born:
            anchor = _interior_point(target[second]["points"])
            append_pair(None, second, anchor_a=anchor)
    for a in missing_b:
        anchor = _interior_point(source[a]["points"])
        append_pair(a, None, anchor_b=anchor)
        for first in holes(source, a):
            append_pair(first, None, anchor_b=anchor)
    for b in missing_a:
        anchor = _interior_point(target[b]["points"])
        append_pair(None, b, anchor_a=anchor)
        for second in holes(target, b):
            append_pair(None, second, anchor_a=anchor)
    return result


def _resample(points, count):
    if len(points) == 1:
        return np.repeat(points, count, axis=0)
    closed = np.vstack((points, points[:1]))
    lengths = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    accumulated = np.concatenate(([0.0], np.cumsum(lengths)))
    distances = np.arange(count) * accumulated[-1] / count
    # Keep pronounced stroke corners when possible instead of consistently
    # replacing their tips by chords. A short arc neighbourhood suppresses
    # the small zigzags from the raster extraction before measuring the turn.
    spacing = accumulated[-1] / count
    span = spacing * .45
    def at(values):
        values = values % accumulated[-1]
        return np.column_stack([np.interp(values, accumulated, closed[:, axis])
                                for axis in range(2)])
    before = points - at(accumulated[:-1] - span)
    after = at(accumulated[:-1] + span) - points
    turn = 1 - np.sum(before * after, axis=1) / np.maximum(
        np.linalg.norm(before, axis=1) * np.linalg.norm(after, axis=1), 1e-20)
    occupied = set()
    for vertex in np.argsort(-turn, kind="stable"):
        if turn[vertex] < .25 or len(occupied) >= max(1, count // 3):
            break
        index = int(math.floor(accumulated[vertex] / spacing + .5)) % count
        if index in occupied:
            continue
        distances[index] = accumulated[vertex]
        occupied.add(index)
    distances.sort()
    indices = np.minimum(np.searchsorted(accumulated, distances, side="right") - 1, len(points) - 1)
    fractions = (distances - accumulated[indices]) / np.maximum(lengths[indices], 1e-20)
    return closed[indices] + np.diff(closed, axis=0)[indices] * fractions[:, None]


def _crossings(points):
    """Count proper crossings; adjacent edges and touching tips are excluded."""
    a, b = np.triu_indices(len(points), 2)
    keep = (a != 0) | (b != len(points) - 1)
    a, b = a[keep], b[keep]
    stop = np.roll(points, -1, axis=0)
    first, second = stop[a] - points[a], stop[b] - points[b]
    delta = points[b] - points[a]
    def cross(x, y):
        return x[:, 0] * y[:, 1] - x[:, 1] * y[:, 0]
    side_a, side_b = cross(first, delta), cross(first, delta + second)
    side_c, side_d = cross(second, -delta), cross(second, first - delta)
    return int(np.count_nonzero((side_a * side_b < -1e-16)
                                & (side_c * side_d < -1e-16)))


def _align_samples(a, b):
    costs = np.array([np.sum((a - np.roll(b, offset, axis=0)) ** 2)
                      for offset in range(len(a))])
    candidates = np.argsort(costs, kind="stable")[:8]
    # Prefer a similarly short correspondence without intermediate folds.
    # This is a bounded local choice, not a promise of arbitrary topology.
    expected = 1 if _area(a) >= 0 else -1
    def score(offset):
        aligned = np.roll(b, int(offset), axis=0)
        mixed = [a * (1 - u) + aligned * u for u in (.25, .5, .75)]
        folds = sum(_crossings(points) for points in mixed)
        folds += len(a) * sum(_area(points) * expected < 0 for points in mixed)
        return folds, float(costs[offset])
    return np.roll(b, int(min(candidates.tolist(), key=score)), axis=0)


def _sample_pairs(pairs, maximum):
    # Each contour includes its closing vertex and an explicit break record.
    minimum = 4
    if len(pairs) * (minimum + 2) > maximum:
        raise ValueError("Glyph needs more contours than the %d-point budget permits" % maximum)
    weights = np.array([max(_length(a), _length(b), .025) for a, b, _hole in pairs])
    desired = max(64, int(math.ceil(weights.sum() * 52)), len(pairs) * (minimum + 2))
    available = min(maximum, desired) - len(pairs) * 2
    counts = np.full(len(pairs), minimum, dtype=int)
    allocation = weights / weights.sum() * (available - counts.sum())
    counts += np.floor(allocation).astype(int)
    remainder = available - int(counts.sum())
    counts[np.argsort(-(allocation - np.floor(allocation)), kind="stable")[:remainder]] += 1
    sampled = []
    for (left, right, hole), count in zip(pairs, counts.tolist()):
        a, b = _resample(left, count), _resample(right, count)
        if len(left) > 1 and len(right) > 1:
            b = _align_samples(a, b)
        sampled.append((np.vstack((a, a[:1])), np.vstack((b, b[:1])), hole))
    return sampled


class VectorMorphAtlas:
    """Pack deterministic per-shape tracks into an existing SDF atlas in place."""

    def __init__(self, image, max_points=MAX_POINTS):
        if image.size != (ATLAS_SIZE, ATLAS_SIZE) or image.mode != "RGBA":
            raise ValueError("Contour data needs the existing 4096 RGBA atlas")
        if not 16 <= max_points <= MAX_POINTS:
            raise ValueError("Contour point budget must be between 16 and 256")
        self.image = image
        self.max_points = max_points
        self.image.paste((0, 0, 0, 255), (0, DATA_Y, ATLAS_SIZE, ATLAS_SIZE))
        self._pixels = self.image.load()
        self._cursor = DATA_Y * ATLAS_SIZE
        self._contours, self._tracks = {}, {}

    def _shape(self, glyph):
        tile = tuple(int(value) for value in glyph["tile"])
        if tile[1] + tile[3] > DATA_Y:
            raise ValueError("SDF tile overlaps reserved contour storage: %r" % (tile,))
        if tile not in self._contours:
            self._contours[tile] = _contours(self.image, tile)
        return self._contours[tile]

    def add_pair(self, source, target):
        absent_a = source.get("opacity", 1) <= 0
        absent_b = target.get("opacity", 1) <= 0
        key = (tuple(source["tile"]), tuple(target["tile"]), absent_a, absent_b)
        if key in self._tracks:
            return self._tracks[key]
        left = [] if absent_a else self._shape(source)
        right = [] if absent_b else self._shape(target)
        if not left and not right:
            raise ValueError("A contour track must have at least one visible endpoint")
        loops = _sample_pairs(_loop_pairs(left, right), self.max_points)
        start = self._cursor
        records = sum(len(a) + 1 for a, _b, _hole in loops)
        if start + records * 2 > ATLAS_SIZE * ATLAS_SIZE:
            raise ValueError("Contour atlas capacity exceeded")
        for a, b, hole in loops:
            for first, second in zip(a, b):
                for point in (first, second):
                    values = np.rint(np.clip(point + .5, 0, 1) * 65535).astype(np.uint16)
                    x, y = (int(value) for value in values)
                    self._pixels[self._cursor % ATLAS_SIZE, self._cursor // ATLAS_SIZE] = (
                        x >> 8, x & 255, y >> 8, y & 255)
                    self._cursor += 1
            self._pixels[self._cursor % ATLAS_SIZE, self._cursor // ATLAS_SIZE] = (255, 255, 255, 255)
            self._cursor += 1
            # The break's target pixel identifies a hole of the preceding
            # outer component. The shader clips it to that component only.
            self._pixels[self._cursor % ATLAS_SIZE, self._cursor // ATLAS_SIZE] = (
                255 if hole else 0, 255 if hole else 0, 0, 0)
            self._cursor += 1
        track = {"offset": start, "count": records, "contours": len(loops),
                 "source_present": not absent_a, "target_present": not absent_b}
        self._tracks[key] = track
        return track

    def report(self):
        return {"schema": 2, "method": "paired closed contours; component-local nonzero winding",
                "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()
                    + Path(__file__).with_suffix(".glsl").read_bytes()).hexdigest(),
                "extraction": "marching squares at SDF byte threshold 127.5; bilinear crossings; cell-mean saddle choice",
                "coordinates": "local glyph coordinates in [-0.5,0.5], Y up; 16-bit unsigned xy",
                "packing": "two RGBA pixels per vertex; all-255 source marks break, target x=0 outer or x=65535 hole",
                "data_region": [0, DATA_Y, ATLAS_SIZE, ATLAS_SIZE - DATA_Y],
                "max_points_per_track": self.max_points, "unique_tracks": len(self._tracks),
                "packed_pixels": self._cursor - DATA_Y * ATLAS_SIZE,
                "peak_track_points": max((track["count"] for track in self._tracks.values()), default=0),
                "component_matching": "outer then parent-local holes; arc samples preserve sharp corners; cyclic phase favours fewer folds",
                "birth_death": "interior point anchors; an unmatched component and its holes contract together; no opacity ramp",
                "fill": "union of outer coverage clipped by its holes; no independent hole or degenerate-point AA",
                "endpoints": "original SDF; 2.5% endpoint interval reconciles polygon sampling and SDF AA",
                "limitations": "bounded polygon approximation, not native Manim curve topology or pixel-equivalent Transform"}


def _vec(values):
    return "vec%d(%s)" % (len(values), ",".join("%.6f" % value for value in values))


def _pair_bounds(a, b, arc):
    """Enclose the entire padded, rotated glyph for normalized progress."""
    # Bound the emitted constants rather than the higher-precision layouts.
    first = np.array([float("%.6f" % value) for value in a["center"]])
    second = np.array([float("%.6f" % value) for value in b["center"]])
    size = np.maximum([[float("%.6f" % value) for value in glyph["size"]]
                       for glyph in (a, b)], .00001).max(axis=0)
    arc = abs(float("%.6f" % arc))
    # |cos(theta)| <= 1 and |sin(theta)| <= |theta|, including the
    # maximum arc tilt. Linear size/center interpolation stays in these hulls.
    extent = size * .5 + size[::-1] * (arc * .08)
    extent += np.array((.21, 1.0)) * arc
    margin = .00001 * (1 + max(float(np.abs(first).max()),
                              float(np.abs(second).max()), float(size.max())))
    return np.minimum(first, second) - extent - margin, np.maximum(first, second) + extent + margin


def render_pairs(atlas, pairs, amount="u", opacity="visibility", arc_strength=.08, color="WHITE"):
    """Compile existing layout pairs; alpha-zero endpoints mean geometric growth."""
    lines = []
    bounds = []
    dynamic = False
    for index, (a, b) in enumerate(pairs):
        present_a, present_b = a.get("opacity", 1) > 0, b.get("opacity", 1) > 0
        if not present_a and not present_b:
            continue
        same = _vec(a["tile"]) == _vec(b["tile"]) and present_a and present_b
        arc = math.sin(index * 2.399 + .5) * arc_strength if present_a and present_b else 0.0
        u = amount
        if same and all(_vec(a[key]) == _vec(b[key]) for key in ("center", "size")):
            u, arc = "0.0", 0.0
        dynamic = dynamic or u != "0.0"
        bounds.append(_pair_bounds(a, b, arc))
        arguments = "%s,%s,%s,%s,%s,%s,%s,%.6f,%s,%s,aa" % (
            _vec(a["center"]), _vec(a["size"]), _vec(a["tile"]),
            _vec(b["center"]), _vec(b["size"]), _vec(b["tile"]), u, arc, color, opacity)
        if same:
            lines.append("vectorStaticGlyph(c,p,%s);" % arguments)
        else:
            track = atlas.add_pair(a, b)
            lines.append("vectorGlyph(c,p,%s,%s,%s);" % (
                arguments, _vec([track["offset"], track["count"]]),
                _vec([float(present_a), float(present_b)])))
    if not lines:
        return ""
    low = np.min([bound[0] for bound in bounds], axis=0)
    high = np.max([bound[1] for bound in bounds], axis=0)
    condition = "p.x>=%.6f && p.y>=%.6f && p.x<=%.6f && p.y<=%.6f" % (*low, *high)
    if dynamic:
        # Preserve extrapolation for callers that do not normalize progress.
        condition = "(%s) || (%s)<0.0 || (%s)>1.0" % (condition, amount, amount)
    # Time branches alone still run every glyph's transform for every screen
    # pixel. Reject the whole caption/formula before any per-glyph work; the
    # existing local bounds, contour reads, hole fill and AA remain untouched.
    return "if(%s) {\n%s\n}" % (condition, "\n".join(lines))


def shader_source(composite="add"):
    """Requires only TEXTURE_2 and the film's sdfSample(vec2, vec4)."""
    if composite not in ("add", "over"):
        raise ValueError("Unknown contour composite: " + composite)
    source = Path(__file__).with_suffix(".glsl").read_text(encoding="utf-8")
    return source.replace("// __VECTOR_COMPOSITE__", "c += hue * coverage;" if composite == "add"
                          else "c = mix(c, hue, coverage);")
