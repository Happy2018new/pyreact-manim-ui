"""Small host-side 2D vector primitives; these are not a Manim API shim."""
from dataclasses import dataclass, replace
import math

WHITE = (1.0, 1.0, 1.0, 1.0)
BLUE = (0.35, 0.72, 1.0, 1.0)
YELLOW = (1.0, 0.83, 0.25, 1.0)
GREEN = (0.35, 0.9, 0.65, 1.0)
TRANSPARENT = (0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Shape:
    contours: tuple
    fill: tuple = WHITE
    stroke: tuple = TRANSPARENT
    stroke_width: float = 0.0
    # A polyline uses a filled ribbon, avoiding unsupported open contours.
    centerline: tuple = ()
    line_width: float = 0.0

    def mapped(self, function):
        return replace(self,
            contours=tuple(tuple(function(p) for p in contour) for contour in self.contours),
            centerline=tuple(function(p) for p in self.centerline))

    def shift(self, x, y):
        return self.mapped(lambda p: (p[0] + x, p[1] + y))

    def scale(self, factor, about=(0.0, 0.0)):
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError("Scale factor must be finite and positive")
        return replace(self.mapped(lambda p: (
            about[0] + (p[0] - about[0]) * factor,
            about[1] + (p[1] - about[1]) * factor)),
            stroke_width=self.stroke_width * factor, line_width=self.line_width * factor)

    def rotate(self, radians, about=(0.0, 0.0)):
        c, s = math.cos(radians), math.sin(radians)
        return self.mapped(lambda p: (
            about[0] + c * (p[0] - about[0]) - s * (p[1] - about[1]),
            about[1] + s * (p[0] - about[0]) + c * (p[1] - about[1])))

    def opacity(self, alpha):
        if not 0 <= alpha <= 1:
            raise ValueError("Opacity must be within [0, 1]")
        return replace(self, fill=self.fill[:3] + (self.fill[3] * alpha,),
                       stroke=self.stroke[:3] + (self.stroke[3] * alpha,))

    def path(self, name):
        return {"id": name, "contours": [[list(p) for p in c] for c in self.contours],
                "closed": True, "fill": list(self.fill), "stroke": list(self.stroke),
                "stroke_width": self.stroke_width}


def Polygon(points, *, fill=TRANSPARENT, stroke=BLUE, stroke_width=0.04):
    points = tuple(tuple(map(float, p)) for p in points)
    if len(points) < 3:
        raise ValueError("Polygon needs at least three vertices")
    return Shape((points,), tuple(fill), tuple(stroke), float(stroke_width))


def Circle(radius=1.0, *, samples=64, **style):
    if radius <= 0 or samples < 8:
        raise ValueError("Circle needs positive radius and at least eight samples")
    return Polygon([(radius * math.cos(i * math.tau / samples),
                     radius * math.sin(i * math.tau / samples)) for i in range(samples)], **style)


def Rectangle(width=2.0, height=2.0, **style):
    if width <= 0 or height <= 0:
        raise ValueError("Rectangle dimensions must be positive")
    return Polygon([(width / 2, -height / 2), (width / 2, height / 2),
                    (-width / 2, height / 2), (-width / 2, -height / 2)], **style)


def Dot(point=(0, 0), radius=0.09, color=YELLOW):
    return Circle(radius, samples=20, fill=color, stroke=TRANSPARENT).shift(*point)


def _lengths(points):
    lengths = [0.0]
    for a, b in zip(points, points[1:]):
        lengths.append(lengths[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    return lengths


def _at_distance(points, lengths, distance):
    for i, end in enumerate(lengths[1:]):
        start = lengths[i]
        if end >= distance and end > start:
            t = (distance - start) / (end - start)
            a, b = points[i], points[i + 1]
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    return points[-1]


def resample(contour, count):
    points = tuple(contour) + (contour[0],)
    lengths = _lengths(points)
    if lengths[-1] == 0:
        return (points[0],) * count
    return tuple(_at_distance(points, lengths, lengths[-1] * i / count) for i in range(count))


def Polyline(points, *, width=0.045, color=BLUE):
    points = tuple(tuple(map(float, p)) for p in points)
    if len(points) < 2 or width <= 0:
        raise ValueError("Polyline needs two points and positive width")
    if any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in points):
        raise ValueError("Polyline coordinates must be finite 2D points")
    if any(a == b for a, b in zip(points, points[1:])):
        raise ValueError("Polyline cannot contain consecutive duplicate points")
    # A bounded miter keeps acute joins from generating unbounded geometry.
    normals = []
    for a, b in zip(points, points[1:]):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        normals.append((-(b[1] - a[1]) / length, (b[0] - a[0]) / length))
    offsets = []
    for i in range(len(points)):
        a, b = normals[max(i - 1, 0)], normals[min(i, len(normals) - 1)]
        denominator = max(0.25, 1.0 + a[0] * b[0] + a[1] * b[1])
        offsets.append(((a[0] + b[0]) / denominator * width / 2,
                        (a[1] + b[1]) / denominator * width / 2))
    left = [(p[0] + n[0], p[1] + n[1]) for p, n in zip(points, offsets)]
    right = [(p[0] - n[0], p[1] - n[1]) for p, n in zip(points, offsets)]
    return Shape((tuple(left + right[::-1]),), tuple(color), centerline=points, line_width=width)


def Line(start=(-1, 0), end=(1, 0), *, width=0.045, color=WHITE):
    return Polyline([start, end], width=width, color=color)


def Arrow(start=(0, 0), end=(1, 0), *, width=0.05, tip=0.2, color=WHITE):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 0 or not 0 < tip < length or width <= 0:
        raise ValueError("Arrow needs a positive length, width, and shorter tip")
    x, y = dx / length, dy / length
    points = [(0, -width / 2), (length - tip, -width / 2), (length - tip, -tip / 2),
              (length, 0), (length - tip, tip / 2), (length - tip, width / 2), (0, width / 2)]
    return Polygon([(start[0] + a * x - b * y, start[1] + a * y + b * x) for a, b in points],
                   fill=color, stroke=TRANSPARENT)


def Axes(x_range=(-5, 5), y_range=(-2, 2), *, color=(0.45, 0.5, 0.6, 1)):
    return {"x": Arrow((x_range[0], 0), (x_range[1], 0), width=0.025, color=color),
            "y": Arrow((0, y_range[0]), (0, y_range[1]), width=0.025, color=color)}


def Plot(function, x_range=(-4, 4), *, samples=80, width=0.05, color=BLUE):
    if samples < 2 or x_range[1] <= x_range[0]:
        raise ValueError("Plot needs increasing x range and at least two samples")
    return Polyline([(x, function(x)) for x in
                     [x_range[0] + (x_range[1] - x_range[0]) * i / (samples - 1)
                      for i in range(samples)]], width=width, color=color)


def partial_polyline(shape, alpha):
    """Reveal a fixed-size ribbon; unrevealed vertices collapse to its endpoint."""
    if not shape.centerline:
        raise ValueError("Create currently requires a Line, Plot or Polyline")
    points = shape.centerline
    lengths = _lengths(points)
    distance = lengths[-1] * alpha
    endpoint = _at_distance(points, lengths, distance)
    active = [p for p, length in zip(points, lengths) if length < distance]
    if not active:
        return replace(shape, contours=((points[0],) * (len(points) * 2),))
    if active[-1] != endpoint:
        active.append(endpoint)
    ribbon = Polyline(active, width=shape.line_width, color=shape.fill).contours[0]
    half = len(active)
    left, right = list(ribbon[:half]), list(reversed(ribbon[half:]))
    left += [left[-1]] * (len(points) - half)
    right += [right[-1]] * (len(points) - half)
    return replace(shape, contours=(tuple(left + right[::-1]),))
