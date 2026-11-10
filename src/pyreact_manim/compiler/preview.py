"""CPU diagnostic preview, explicitly not a substitute for Manim/MC validation."""

import bisect

import numpy as np
from PIL import Image

from .codec import decode_unit
from .validation import validate_scene


def decode_frame(manifest, image, index):
    """Read one complete frame from the emitted data atlas for quantization checks."""
    if not 0 <= index < manifest["frame_count"]:
        raise IndexError("Frame index out of bounds")
    texture = manifest["texture"]
    pixel_data = list(image.convert("RGBA").getdata())
    offset = index * texture["frame_stride"]
    lower = manifest["coordinate_bounds"]["min"]
    span = [hi - lo for lo, hi in zip(lower, manifest["coordinate_bounds"]["max"])]

    def scalar(at):
        return decode_unit(pixel_data[offset + at])

    def point(at):
        return [lower[axis] + span[axis] * scalar(2 * at + axis) for axis in (0, 1)]

    paths = []
    for path_index, path in enumerate(manifest["paths"]):
        if "curves" in path:
            geometry = {"base": point(path["base_point"]),
                        "fill_border_width": path.get("fill_border_width", 0),
                        "fill_orientation": path.get("fill_orientation", 1),
                        "anti_alias_width": path.get("anti_alias_width", 1.5), "curves": [
                {"points": [point(i) for i in range(curve["start"], curve["start"] + curve["count"])],
                 "skip_marker": scalar(curve["active_offset"]) == 0.0} for curve in path["curves"]]}
        else:
            geometry = {"contours": [[point(i) for i in range(contour["start"], contour["start"] + contour["count"])]
                                     for contour in path["contours"]]}
        style = texture["style_offset"] + 9 * path_index
        paths.append({"id": path["id"], **geometry,
                      "fill": [scalar(style + i) for i in range(4)],
                      "stroke": [scalar(style + 4 + i) for i in range(4)],
                      "stroke_width": scalar(style + 8) * manifest["stroke_width_scale"]})
    return {"time": manifest["frame_times"][index], "paths": paths}


def sample_frame(scene, timestamp):
    """Interpolate frozen exported samples; this does not run upstream Manim."""
    frames = scene["frames"]
    times = [frame["time"] for frame in frames]
    timestamp = min(max(float(timestamp), times[0]), times[-1])
    index = min(max(0, bisect.bisect_right(times, timestamp) - 1), len(frames) - 2)
    source, target = frames[index], frames[index + 1]
    ratio = (timestamp - times[index]) / (times[index + 1] - times[index])

    def mix(a, b):
        return (np.asarray(a) * (1 - ratio) + np.asarray(b) * ratio).tolist()

    paths = []
    for a, b in zip(source["paths"], target["paths"]):
        if "curves" in a:
            geometry = {"base": mix(a["base"], b["base"]),
                        "fill_border_width": a.get("fill_border_width", 0),
                        "fill_orientation": a.get("fill_orientation", 1),
                        "anti_alias_width": a.get("anti_alias_width", 1.5), "curves": [
                {"points": mix(ca["points"], cb["points"]),
                 "skip_marker": ((not ca["skip_marker"]) * (1 - ratio) +
                                 (not cb["skip_marker"]) * ratio) <= 0}
                for ca, cb in zip(a["curves"], b["curves"])]}
        else:
            geometry = {"contours": [mix(ca, cb) for ca, cb in zip(a["contours"], b["contours"])]}
        paths.append({"id": a["id"], **geometry,
                      "fill": mix(a["fill"], b["fill"]), "stroke": mix(a["stroke"], b["stroke"]),
                      "stroke_width": a["stroke_width"] * (1 - ratio) + b["stroke_width"] * ratio})
    return {"time": timestamp, "paths": paths}


def _coverage(distance, edge0, edge1):
    fraction = np.clip((distance - edge0) / (edge1 - edge0), 0, 1)
    return 1 - fraction * fraction * (3 - 2 * fraction)


def _draw_path(colors, xx, yy, path, aa):
    winding = np.zeros(xx.shape, dtype=np.int32)
    nearest = np.full(xx.shape, 1e20)
    nearest_side = np.ones(xx.shape)
    for contour in path["contours"]:
        a = contour[-1]
        for b in contour:
            dx, dy = b[0] - a[0], b[1] - a[1]
            length_squared = dx * dx + dy * dy
            if length_squared > 1e-20:
                t = np.clip(((xx - a[0]) * dx + (yy - a[1]) * dy) / length_squared, 0, 1)
                distance = np.hypot(xx - a[0] - t * dx, yy - a[1] - t * dy)
                side = dx * (yy - a[1]) - dy * (xx - a[0])
                nearest_side = np.where(distance < nearest, np.where(side >= 0, 1, -1), nearest_side)
                nearest = np.minimum(nearest, distance)
                winding += ((a[1] <= yy) & (b[1] > yy) & (side > 0)).astype(np.int32)
                winding -= ((a[1] > yy) & (b[1] <= yy) & (side < 0)).astype(np.int32)
            a = b
    edge_coverage = _coverage(nearest, -aa, aa)
    fill_coverage = np.clip(np.abs(winding - nearest_side * edge_coverage), 0, 1)
    alpha = (fill_coverage * path["fill"][3])[..., None]
    colors[:] = colors * (1 - alpha) + np.asarray(path["fill"][:3]) * alpha
    half_stroke = path["stroke_width"] * 0.5
    if half_stroke > 0 and path["stroke"][3] > 0:
        alpha = (_coverage(nearest, half_stroke - aa, half_stroke + aa) * path["stroke"][3])[..., None]
        colors[:] = colors * (1 - alpha) + np.asarray(path["stroke"][:3]) * alpha


def _draw_curve_fans(colors, xx, yy, path, pixel_size):
    coverage = np.zeros(xx.shape)
    border_width = path.get("fill_border_width", 0)
    half_aa = path.get("anti_alias_width", 1.5) * pixel_size * 0.5
    native_alpha = 0.95 * path["fill"][3]
    for ox, oy in ((-0.25, -0.25), (0.25, -0.25), (-0.25, 0.25), (0.25, 0.25)):
        px, py = xx + ox * pixel_size, yy + oy * pixel_size
        winding = np.zeros(xx.shape, dtype=np.int32)
        distance = np.full(xx.shape, 1e20)
        for curve in path["curves"]:
            if curve["skip_marker"]:
                continue
            a = path["base"]
            for b in curve["points"] + [path["base"]]:
                side = (a[0] - px) * (b[1] - py) - (a[1] - py) * (b[0] - px)
                winding += ((a[1] <= py) & (b[1] > py) & (side > 0)).astype(np.int32)
                winding -= ((a[1] > py) & (b[1] <= py) & (side < 0)).astype(np.int32)
                a = b
            if border_width > 0:
                for a, b in zip(curve["points"], curve["points"][1:]):
                    dx, dy = b[0] - a[0], b[1] - a[1]
                    squared = max(dx * dx + dy * dy, 1e-20)
                    ratio = np.clip(((px - a[0]) * dx + (py - a[1]) * dy) / squared, 0, 1)
                    distance = np.minimum(distance, np.hypot(px - a[0] - ratio * dx, py - a[1] - ratio * dy))
        exponent = np.log(1 - native_alpha) * winding * path.get("fill_orientation", 1)
        samples = 1 - np.exp(np.clip(exponent, -80, 80))
        if border_width > 0:
            border = _coverage(distance, border_width * 0.5 - half_aa, border_width * 0.5 + half_aa)
            samples = np.where(distance < border_width * 0.5 + half_aa,
                               np.maximum(samples, border * native_alpha), samples)
        coverage += samples * 0.25
    negative = coverage < 0
    coverage[negative] = -coverage[negative] / (1 - coverage[negative])
    alpha = (coverage * 1.06)[..., None]
    colors[:] = colors * (1 - alpha) + np.asarray(path["fill"][:3]) * alpha


def render_preview(raw, timestamp, width=640, height=360):
    """Return an RGB diagnostic image in the same authored canvas coordinates."""
    scene = validate_scene(raw)
    if width < 1 or height < 1 or max(width, height) > 4096:
        raise ValueError("Preview dimensions must be in 1..4096")
    visible_height = max(scene["height"], scene["width"] / (width / height))
    xx, yy = np.meshgrid(((np.arange(width) + 0.5) / width - 0.5) * visible_height * width / height,
                         (0.5 - (np.arange(height) + 0.5) / height) * visible_height)
    pixels = np.broadcast_to(np.asarray(scene["background"]), (height, width, 3)).copy()
    frame = sample_frame(scene, timestamp)
    for path in frame["paths"]:
        if "curves" in path:
            _draw_curve_fans(pixels, xx, yy, path, visible_height / height)
        else:
            _draw_path(pixels, xx, yy, path, visible_height / height * 0.75)
    return Image.fromarray(np.uint8(np.clip(pixels, 0, 1) * 255 + 0.5))
