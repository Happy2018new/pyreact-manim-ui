"""Portable RG16 scalar texture encoding; every PNG alpha byte is opaque."""

import math

from PIL import Image


def encode_unit(value):
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Encoded value must be finite and in [0, 1]")
    integer = int(math.floor(value * 65535 + 0.5))
    return integer >> 8, integer & 255, 0, 255


def decode_unit(pixel):
    return (pixel[0] * 256 + pixel[1]) / 65535.0


def _power_two(value):
    return 1 << max(0, (int(value) - 1).bit_length())


def path_points(path):
    if "curves" in path:
        yield path["base"]
        for curve in path["curves"]:
            yield from curve["points"]
    else:
        for contour in path["contours"]:
            yield from contour


def build_atlas(scene):
    """Return an RGBA image and its layout, with fixed records for every frame."""
    version = scene["schema_version"]
    all_points = [point for frame in scene["frames"] for path in frame["paths"] for point in path_points(path)]
    lower = [min(point[axis] for point in all_points) for axis in (0, 1)]
    upper = [max(point[axis] for point in all_points) for axis in (0, 1)]
    for axis in (0, 1):
        if upper[axis] == lower[axis]:
            upper[axis] += 1.0
    span = [hi - lo for lo, hi in zip(lower, upper)]
    if any(not math.isfinite(value) or value > 1e6 for value in span):
        raise ValueError("Scene coordinate span must be finite and at most 1e6")
    paths = []
    point_count = 0
    curve_count = 0
    for path_index, path in enumerate(scene["frames"][0]["paths"]):
        topology = {}
        if version == 2:
            topology["fill_border_width"] = path["fill_border_width"]
            topology["anti_alias_width"] = path["anti_alias_width"]
            topology["base_point"] = point_count
            point_count += 1
            topology["curves"] = []
            for curve in path["curves"]:
                topology["curves"].append({"start": point_count, "count": len(curve["points"]),
                                            "active_index": curve_count})
                point_count += len(curve["points"])
                curve_count += 1
        else:
            topology["contours"] = []
            for contour in path["contours"]:
                topology["contours"].append({"start": point_count, "count": len(contour)})
                point_count += len(contour)
        points = [point for frame in scene["frames"] for point in path_points(frame["paths"][path_index])]
        paths.append({"id": path["id"], **topology,
            "bounds": {"min": [min(p[a] for p in points) for a in (0, 1)],
                       "max": [max(p[a] for p in points) for a in (0, 1)]},
        })
    width_scale = max(1.0, max(path["stroke_width"] for frame in scene["frames"]
                               for path in frame["paths"]))
    style_offset = 2 * point_count
    marker_offset = style_offset + 9 * len(paths)
    frame_stride = marker_offset + curve_count
    for path in paths:
        for curve in path.get("curves", []):
            curve["active_offset"] = marker_offset + curve.pop("active_index")
    total = frame_stride * len(scene["frames"])
    texture_width = _power_two(math.ceil(math.sqrt(total)))
    texture_height = _power_two(math.ceil(total / texture_width))
    if max(texture_width, texture_height) > 2048:
        raise ValueError("Scene exceeds the 2048-pixel prototype atlas dimension")
    pixels = []
    for frame in scene["frames"]:
        for path in frame["paths"]:
            for point in path_points(path):
                for axis in (0, 1):
                    value = (point[axis] - lower[axis]) / span[axis]
                    pixels.append(encode_unit(min(1.0, max(0.0, value))))
        for path in frame["paths"]:
            pixels.extend(encode_unit(value) for value in path["fill"] + path["stroke"])
            pixels.append(encode_unit(path["stroke_width"] / width_scale))
        for path in frame["paths"]:
            for curve in path.get("curves", []):
                pixels.append(encode_unit(0.0 if curve["skip_marker"] else 1.0))
    pixels.extend([(0, 0, 0, 255)] * (texture_width * texture_height - len(pixels)))
    image = Image.new("RGBA", (texture_width, texture_height))
    image.putdata(pixels)
    return image, {
        "width": texture_width, "height": texture_height,
        "frame_stride": frame_stride, "point_offset": 0, "style_offset": style_offset,
        "marker_offset": marker_offset, "curve_count": curve_count,
        "coordinate_bounds": {"min": lower, "max": upper},
        "stroke_width_scale": width_scale, "vertex_count": point_count, "paths": paths,
        "coordinate_error_bound": [value / (2 * 65535) for value in span],
    }
