"""Generate a small fixed-topology polygon renderer for Minecraft GLSL ES."""


def _float(value):
    result = format(float(value), ".10g")
    if "." not in result and "e" not in result:
        result += ".0"
    return result


def _vec(values):
    return "vec%d(%s)" % (len(values), ", ".join(map(_float, values)))


def _frame_branch(times, start, end, indent="    "):
    if start == end:
        return indent + "return vec3(%s, %s, clamp((t - %s) / %s, 0.0, 1.0));" % (
            _float(start), _float(start + 1), _float(times[start]),
            _float(times[start + 1] - times[start]))
    middle = (start + end) // 2
    return (indent + "if (t < %s) {\n" % _float(times[middle + 1]) +
            _frame_branch(times, start, middle, indent + "    ") + "\n" + indent + "} else {\n" +
            _frame_branch(times, middle + 1, end, indent + "    ") + "\n" + indent + "}")


def _path_code(index, path, layout):
    bounds = path["bounds"]
    style = layout["style_offset"] + index * 9
    lines = ["    // Path %d; conservative bounds cover every reference keyframe." % index,
             "    {", "        float styleOffset = %s;" % _float(style),
             "        float width = sampleScalar(styleOffset + 8.0, frames) * STROKE_SCALE;",
             "        float margin = width * 0.5 + aa * 2.0;",
             "        if (all(greaterThanEqual(p, %s - vec2(margin))) &&" % _vec(bounds["min"]),
             "            all(lessThanEqual(p, %s + vec2(margin)))) {" % _vec(bounds["max"]),
             "            float winding = 0.0;",
             "            float distanceToPath = 1.0e20;",
             "            float nearestSide = 1.0;"]
    for contour in path["contours"]:
        start, count = contour["start"], contour["count"]
        lines += ["            {", "                vec2 a = samplePoint(%s, frames);" % _float(start + count - 1),
                  "                for (int i = 0; i < %d; ++i) {" % count,
                  "                    vec2 b = samplePoint(%s + float(i), frames);" % _float(start),
                  "                    edge(p, a, b, winding, distanceToPath, nearestSide);",
                  "                    a = b;", "                }", "            }"]
    lines += ["            // Antialias the winding transition, not every internal contour edge.",
              "            float edgeCoverage = 1.0 - smoothstep(-aa, aa, distanceToPath);",
              "            float fillCoverage = clamp(abs(winding - nearestSide * edgeCoverage), 0.0, 1.0);",
              "            vec4 fill = sampleColor(styleOffset, frames);",
              "            color = mix(color, fill.rgb, fill.a * fillCoverage);",
              "            if (width > 0.0) {",
              "                float strokeCoverage = 1.0 - smoothstep(width * 0.5 - aa, width * 0.5 + aa, distanceToPath);",
              "                vec4 stroke = sampleColor(styleOffset + 4.0, frames);",
              "                color = mix(color, stroke.rgb, stroke.a * strokeCoverage);",
              "            }", "        }", "    }"]
    return "\n".join(lines)


FAN_HELPERS = """
// Four true subpixel winding tests avoid antialiasing artificial fan edges.
void fanEdge(vec4 px, vec4 py, vec2 a, vec2 b, inout vec4 winding) {
    // Canonical endpoint order makes shared reverse fan edges evaluate the
    // same operations, avoiding cancellation seams from floating contraction.
    float direction = 1.0;
    if (a.y > b.y) {
        vec2 temporary = a;
        a = b;
        b = temporary;
        direction = -1.0;
    }
    vec4 side = (b.x - a.x) * (py - vec4(a.y)) - (b.y - a.y) * (px - vec4(a.x));
    vec4 crossing = step(vec4(a.y), py) * (vec4(1.0) - step(vec4(b.y), py));
    winding += direction * crossing * sign(max(side, vec4(0.0)));
}

vec4 fanSegmentDistance(vec4 px, vec4 py, vec2 a, vec2 b) {
    vec2 direction = b - a;
    vec4 dx = px - vec4(a.x);
    vec4 dy = py - vec4(a.y);
    vec4 ratio = clamp((dx * direction.x + dy * direction.y) / max(dot(direction, direction), 1.0e-20), 0.0, 1.0);
    dx -= ratio * direction.x;
    dy -= ratio * direction.y;
    return sqrt(dx * dx + dy * dy);
}
"""


def _curve_activity(scene, path_index):
    """True/False for constant active/inactive slots, None for changing slots.

    Marker texture samples interpolate endpoint values in [0, 1]. Constant
    endpoints therefore stay constant at every time, including clamped ends.
    Do not infer activity from geometry: a degenerate active curve can still
    contribute to the native fill border.
    """
    paths = [frame["paths"][path_index] for frame in scene["frames"]]
    activity = []
    for index, curve in enumerate(paths[0]["curves"]):
        skipped = curve["skip_marker"]
        changing = any(path["curves"][index]["skip_marker"] != skipped for path in paths[1:])
        activity.append(None if changing else not skipped)
    return activity


def _fan_path_code(index, path, layout, activity):
    style = layout["style_offset"] + index * 9
    lines = ["    // Native fixed curve slots; shared-base fans accumulate as one glyph.",
             "    {",
             "        float pixelSize = visibleHeight / viewportHeight;",
             "        float borderHalfWidth = %s;" % _float(path.get("fill_border_width", 0) * 0.5),
             "        float borderHalfAA = pixelSize * %s;" % _float(path.get("anti_alias_width", 1.5) * 0.5),
             "        float margin = max(aa * 2.0, borderHalfWidth + borderHalfAA);",
             "        if (all(greaterThanEqual(p, %s - vec2(margin))) &&" % _vec(path["bounds"]["min"]),
             "            all(lessThanEqual(p, %s + vec2(margin)))) {" % _vec(path["bounds"]["max"]),
             "        vec4 px = vec4(p.x) + pixelSize * vec4(-0.25, 0.25, -0.25, 0.25);",
             "        vec4 py = vec4(p.y) + pixelSize * vec4(-0.25, -0.25, 0.25, 0.25);",
             "        vec4 winding = vec4(0.0);",
             "        vec4 distanceToCurve = vec4(1.0e20);",
             "        vec2 base = samplePoint(%s, frames);" % _float(path["base_point"])]
    for curve, active in zip(path["curves"], activity):
        if active is False:
            continue
        guard = ("        if (sampleScalar(%s, frames) > 0.0) {" % _float(curve["active_offset"])
                 if active is None else "        {")
        lines += [guard,
                  "            vec2 a = samplePoint(%s, frames);" % _float(curve["start"]),
                  "            fanEdge(px, py, base, a, winding);",
                  "            for (int i = 1; i < %d; ++i) {" % curve["count"],
                  "                vec2 b = samplePoint(%s + float(i), frames);" % _float(curve["start"]),
                  "                fanEdge(px, py, a, b, winding);",
                  "                distanceToCurve = min(distanceToCurve, fanSegmentDistance(px, py, a, b));",
                  "                a = b;",
                  "            }", "            fanEdge(px, py, a, base, winding);", "        }"]
    lines += ["        vec4 fill = sampleColor(%s, frames);" % _float(style),
              "        // Native signed alpha is accumulated in the 2x fill canvas before filtering.",
              "        // Bound the exponent, not winding: faint overlapping shapes must still accumulate.",
              "        vec4 signedExponent = log(1.0 - 0.95 * fill.a) * winding * %s;" % _float(path.get("fill_orientation", 1)),
              "        vec4 coverageSamples = vec4(1.0) - exp(clamp(signedExponent, -80.0, 80.0));",
              "        if (borderHalfWidth > 0.0) {",
              "            // Native fill-border uses real curves only, never the artificial fan edges.",
              "            vec4 borderCoverage = 1.0 - smoothstep(borderHalfWidth - borderHalfAA, borderHalfWidth + borderHalfAA, distanceToCurve);",
              "            // MAX applies only where border geometry exists: zero must not erase negative fill elsewhere.",
              "            vec4 borderPresent = vec4(1.0) - step(vec4(borderHalfWidth + borderHalfAA), distanceToCurve);",
              "            coverageSamples = mix(coverageSamples, max(coverageSamples, borderCoverage * (0.95 * fill.a)), borderPresent);",
              "        }",
              "        float coverage = dot(coverageSamples, vec4(0.25));",
              "        if (coverage < 0.0) coverage = -coverage / (1.0 - coverage);",
              "        color = mix(color, fill.rgb, coverage * 1.06);", "        }", "    }"]
    return "\n".join(lines)


def generate_shader(scene, layout):
    lower = layout["coordinate_bounds"]["min"]
    upper = layout["coordinate_bounds"]["max"]
    constants = {
        "texture_size": _vec([layout["width"], layout["height"]]),
        "stride": _float(layout["frame_stride"]),
        "minimum": _vec(lower), "span": _vec([b - a for a, b in zip(lower, upper)]),
        "width_scale": _float(layout["stroke_width_scale"]),
        "canvas_width": _float(scene["width"]), "canvas_height": _float(scene["height"]),
        "background": _vec(scene["background"]),
    }
    header = """// __multiversion__
// Generated by pyreact-manim-ui. Data textures require Point filtering and no sRGB decoding.
precision highp float;
#include "fragmentVersionCentroidUV.h"
uniform sampler2D TEXTURE_0;
uniform sampler2D TEXTURE_2;
uniform vec4 EXTRA_VECTOR1; // time_seconds, viewport_aspect, pixel_height, opacity
uniform vec4 EXTRA_VECTOR2; // flip_y, canvas_top_ratio, canvas_height_ratio (<=0 means full), reserved
const vec2 ATLAS_SIZE = %(texture_size)s;
const float FRAME_STRIDE = %(stride)s;
const vec2 POSITION_MIN = %(minimum)s;
const vec2 POSITION_SPAN = %(span)s;
const float STROKE_SCALE = %(width_scale)s;

float readScalar(float index) {
    vec2 tc = (vec2(mod(index, ATLAS_SIZE.x), floor(index / ATLAS_SIZE.x)) + vec2(0.5)) / ATLAS_SIZE;
    vec2 bytes = floor(texture2D(TEXTURE_2, tc).rg * 255.0 + vec2(0.5));
    return dot(bytes, vec2(256.0, 1.0)) / 65535.0;
}

float sampleScalar(float index, vec3 frames) {
    return mix(readScalar(frames.x * FRAME_STRIDE + index),
               readScalar(frames.y * FRAME_STRIDE + index), frames.z);
}

vec2 samplePoint(float index, vec3 frames) {
    vec2 normalized = vec2(sampleScalar(index * 2.0, frames), sampleScalar(index * 2.0 + 1.0, frames));
    return POSITION_MIN + normalized * POSITION_SPAN;
}

vec4 sampleColor(float index, vec3 frames) {
    return vec4(sampleScalar(index, frames), sampleScalar(index + 1.0, frames),
                sampleScalar(index + 2.0, frames), sampleScalar(index + 3.0, frames));
}

void edge(vec2 p, vec2 a, vec2 b, inout float winding, inout float nearest, inout float nearestSide) {
    vec2 ab = b - a;
    float lengthSquared = dot(ab, ab);
    if (lengthSquared <= 1.0e-20) return;
    float t = clamp(dot(p - a, ab) / lengthSquared, 0.0, 1.0);
    float distanceToEdge = length(p - a - t * ab);
    float side = ab.x * (p.y - a.y) - ab.y * (p.x - a.x);
    if (distanceToEdge < nearest) {
        nearest = distanceToEdge;
        nearestSide = side >= 0.0 ? 1.0 : -1.0;
    }
    if (a.y <= p.y && b.y > p.y && side > 0.0) winding += 1.0;
    if (a.y > p.y && b.y <= p.y && side < 0.0) winding -= 1.0;
}

vec3 selectFrames(float t) {
""" % constants
    if scene["schema_version"] == 2:
        header = header.replace("vec3 selectFrames(float t) {", FAN_HELPERS + "\nvec3 selectFrames(float t) {")
    frame_code = _frame_branch([frame["time"] for frame in scene["frames"]], 0, len(scene["frames"]) - 2)
    main = """
}

void main() {
    vec2 screenUV = uv;
    if (EXTRA_VECTOR2.x > 0.5) screenUV.y = 1.0 - screenUV.y;
    float canvasHeight = EXTRA_VECTOR2.z > 0.0 ? EXTRA_VECTOR2.z : 1.0;
    float canvasTop = EXTRA_VECTOR2.z > 0.0 ? EXTRA_VECTOR2.y : 0.0;
    screenUV.y = (screenUV.y - canvasTop) / canvasHeight;
    float aspect = max(EXTRA_VECTOR1.y, 0.001);
    float viewportHeight = max(EXTRA_VECTOR1.z, 1.0);
    // Contain the authored canvas without stretching glyphs.
    float visibleHeight = max(%(canvas_height)s, %(canvas_width)s / aspect);
    vec2 p = (screenUV - vec2(0.5)) * vec2(visibleHeight * aspect, -visibleHeight);
    float aa = visibleHeight / viewportHeight * 0.75;
    vec3 frames = selectFrames(EXTRA_VECTOR1.x);
    vec3 color = %(background)s;
    if (screenUV.y >= 0.0 && screenUV.y <= 1.0) {
""" % constants
    if scene["schema_version"] == 2:
        paths = "\n".join(_fan_path_code(i, path, layout, _curve_activity(scene, i))
                          for i, path in enumerate(layout["paths"]))
    else:
        paths = "\n".join(_path_code(i, path, layout) for i, path in enumerate(layout["paths"]))
    footer = """
    }
    vec4 original = texture2D(TEXTURE_0, uv);
    gl_FragColor = mix(original, vec4(color, 1.0), clamp(EXTRA_VECTOR1.w, 0.0, 1.0));
}
"""
    return header + frame_code + main + paths + footer
