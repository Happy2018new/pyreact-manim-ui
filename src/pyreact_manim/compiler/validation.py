"""Validate the small, explicit scene format accepted by the first renderer."""

import math
import re
import struct


MAX_VERTICES = 1024
MAX_PATHS = 32
MAX_FRAMES = 256


class SceneError(ValueError):
    """A scene cannot be represented by this compiler without losing semantics."""


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SceneError(label + " must be a finite number")
    if not math.isfinite(value):
        raise SceneError(label + " must be finite")
    return float(value)


def _vector(value, size, label, unit=False):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise SceneError("%s must have %d components" % (label, size))
    result = [_number(part, label) for part in value]
    if unit and any(part < 0 or part > 1 for part in result):
        raise SceneError(label + " components must be between zero and one")
    return result


def _path(raw, label):
    if not isinstance(raw, dict):
        raise SceneError(label + " must be an object")
    path_id = raw.get("id")
    if not isinstance(path_id, str) or not path_id or len(path_id) > 200:
        raise SceneError(label + ".id must be a nonempty short string")
    if raw.get("closed", True) is not True:
        raise SceneError("Open contours are not supported by this compiler")
    raw_contours = raw.get("contours")
    if not isinstance(raw_contours, list) or not raw_contours:
        raise SceneError(label + ".contours must be a nonempty list")
    contours = []
    for contour in raw_contours:
        if not isinstance(contour, list) or len(contour) < 3:
            raise SceneError(label + " requires at least three points per closed contour")
        contours.append([_vector(p, 2, label + ".point") for p in contour])
    width = _number(raw.get("stroke_width", 0), label + ".stroke_width")
    if width < 0:
        raise SceneError("stroke_width must be nonnegative")
    if width > 1e6 or any(abs(value) > 1e6 for contour in contours for point in contour for value in point):
        raise SceneError("Coordinates and stroke widths must fit the prototype's +/-1e6 range")
    return {
        "id": path_id,
        "contours": contours,
        "fill": _vector(raw.get("fill", [1, 1, 1, 1]), 4, label + ".fill", True),
        "stroke": _vector(raw.get("stroke", [0, 0, 0, 0]), 4, label + ".stroke", True),
        "stroke_width": width,
    }


def _curve_path(raw, label):
    if not isinstance(raw, dict):
        raise SceneError(label + " must be an object")
    path_id = raw.get("id")
    if not isinstance(path_id, str) or not path_id or len(path_id) > 200:
        raise SceneError(label + ".id must be a nonempty short string")
    base = _vector(raw.get("base"), 2, label + ".base")
    curves = raw.get("curves")
    if not isinstance(curves, list) or not curves:
        raise SceneError(label + ".curves must be a nonempty list")
    normalized = []
    for curve in curves:
        if not isinstance(curve, dict) or type(curve.get("skip_marker")) is not bool:
            raise SceneError("Every curve requires an explicit boolean skip_marker")
        points = curve.get("points")
        if not isinstance(points, list) or len(points) < 2:
            raise SceneError("Curve sampling chains need at least two points")
        normalized.append({"points": [_vector(p, 2, label + ".curve.point") for p in points],
                           "skip_marker": curve["skip_marker"]})
    width = _number(raw.get("stroke_width", 0), label + ".stroke_width")
    if width != 0:
        raise SceneError("Schema 2 currently supports filled curve fans only; stroke_width must be zero")
    border = _number(raw.get("fill_border_width", 0), label + ".fill_border_width")
    antialias = _number(raw.get("anti_alias_width", 1.5), label + ".anti_alias_width")
    if not 0 <= border <= 1e6 or not 0 < antialias <= 64:
        raise SceneError("Fill border width must be in [0, 1e6]; anti_alias_width must be in (0, 64]")
    coordinates = base + [value for curve in normalized for point in curve["points"] for value in point]
    if any(abs(value) > 1e6 for value in coordinates):
        raise SceneError("Coordinates must fit the prototype's +/-1e6 range")
    return {"id": path_id, "base": base, "curves": normalized,
            "fill": _vector(raw.get("fill", [1, 1, 1, 1]), 4, label + ".fill", True),
            "stroke": _vector(raw.get("stroke", [0, 0, 0, 0]), 4, label + ".stroke", True),
            "stroke_width": 0.0, "fill_border_width": border, "anti_alias_width": antialias}


def validate_scene(raw):
    """Return a normalized copy; reject unsupported topology instead of hiding it."""
    if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw["schema_version"] not in (1, 2):
        raise SceneError("scene.schema_version must be 1 or 2")
    version = raw["schema_version"]
    name = raw.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", name):
        raise SceneError("scene.name must match [a-z][a-z0-9_]{0,47}")
    duration = _number(raw.get("duration"), "duration")
    width = _number(raw.get("width"), "width")
    height = _number(raw.get("height"), "height")
    if duration <= 0 or width <= 0 or height <= 0:
        raise SceneError("duration, width and height must be positive")
    if duration > 86400 or max(width, height) > 1e6:
        raise SceneError("Duration is limited to one day; canvas dimensions to 1e6")
    frames = raw.get("frames")
    if not isinstance(frames, list) or not 2 <= len(frames) <= MAX_FRAMES:
        raise SceneError("The compiler requires 2..%d frames" % MAX_FRAMES)
    normalized = []
    topology = None
    border_styles = None
    previous_time = -1.0
    previous_float32 = -1.0
    for index, frame in enumerate(frames):
        if not isinstance(frame, dict):
            raise SceneError("Each frame must be an object")
        timestamp = _number(frame.get("time"), "frame.time")
        if timestamp <= previous_time or timestamp < 0 or timestamp > duration:
            raise SceneError("Frame times must increase strictly within [0, duration]")
        float32_time = struct.unpack("f", struct.pack("f", timestamp))[0]
        if version == 2 and float32_time <= previous_float32:
            raise SceneError("Schema 2 event times must remain distinct in float32")
        paths = frame.get("paths")
        if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_PATHS:
            raise SceneError("Each frame requires 1..%d paths" % MAX_PATHS)
        normalize_path = _path if version == 1 else _curve_path
        paths = [normalize_path(p, "frame[%d].path[%d]" % (index, j)) for j, p in enumerate(paths)]
        ids = [p["id"] for p in paths]
        if len(set(ids)) != len(ids):
            raise SceneError("Path IDs must be unique in each frame")
        current = [(p["id"], tuple(map(len, p["contours"]))) for p in paths] if version == 1 else [
            (p["id"], tuple(len(curve["points"]) for curve in p["curves"])) for p in paths]
        if topology is not None and current != topology:
            raise SceneError("Path order and contour topology must remain fixed across frames")
        if version == 2:
            current_borders = [(p["fill_border_width"], p["anti_alias_width"]) for p in paths]
            if border_styles is not None and current_borders != border_styles:
                raise SceneError("Schema 2 fill border and anti-alias widths must remain fixed across frames")
            border_styles = current_borders
        point_count = sum(sum(sizes) for _, sizes in current) + (len(paths) if version == 2 else 0)
        if point_count > MAX_VERTICES:
            raise SceneError("Scene exceeds the %d vertex prototype limit" % MAX_VERTICES)
        topology = current
        normalized.append({"time": timestamp, "paths": paths})
        previous_time = timestamp
        previous_float32 = float32_time
    if normalized[0]["time"] != 0 or normalized[-1]["time"] != duration:
        raise SceneError("First/last frame times must be zero/duration")
    return {
        "schema_version": version, "name": name, "duration": duration,
        "width": width, "height": height,
        "background": _vector(raw.get("background", [0, 0, 0]), 3, "background", True),
        "frames": normalized,
    }
