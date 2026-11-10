"""Deterministic 2D animations evaluated offline into the compiler IR."""
from dataclasses import dataclass

from .geometry import Shape, partial_polyline, resample


def smooth(t):
    return t * t * (3.0 - 2.0 * t)


@dataclass(frozen=True)
class Animation:
    target: str
    evaluate: object
    easing: object = smooth
    initial: object = None
    restore_opacity: bool = False


def Shift(target, x, y, *, easing=smooth):
    return Animation(target, lambda shape, a: shape.shift(x * a, y * a), easing)


def Rotate(target, radians, *, about=(0, 0), easing=smooth):
    return Animation(target, lambda shape, a: shape.rotate(radians * a, about), easing)


def Scale(target, factor, *, about=(0, 0), easing=smooth):
    return Animation(target, lambda shape, a: shape.scale(1 + (factor - 1) * a, about), easing)


def FadeIn(target, *, easing=smooth):
    return Animation(target, lambda shape, a: shape.opacity(a), easing,
                     initial=lambda shape: shape.opacity(0), restore_opacity=True)


def FadeOut(target, *, easing=smooth):
    return Animation(target, lambda shape, a: shape.opacity(1 - a), easing)


def Create(target, *, easing=smooth):
    return Animation(target, partial_polyline, easing, initial=lambda shape: partial_polyline(shape, 0))


def MoveAlong(target, function, *, easing=lambda t: t):
    """Translate relative to function(0); function is a host-only 2D path."""
    start = function(0.0)
    def evaluate(shape, alpha):
        position = function(alpha)
        return shape.shift(position[0] - start[0], position[1] - start[1])
    return Animation(target, evaluate, easing)


def Transform(target, destination, *, easing=smooth):
    """Approximate polygon morph with equal-distance perimeter samples.

    Both ends keep at least their existing vertex count. Scene.export promotes
    earlier, sparser frames to the same topology. Text uses the real Manim
    exporter instead of this polygon approximation.
    """
    def evaluate(source, alpha):
        if len(source.contours) != len(destination.contours):
            raise ValueError("Basic 2D Transform requires matching contour counts")
        contours = []
        for first, last in zip(source.contours, destination.contours):
            count = max(len(first), len(last))
            if len(first) < count:
                first = resample(first, count)
            if len(last) < count:
                last = resample(last, count)
            contours.append(tuple((a[0] + (b[0] - a[0]) * alpha,
                                   a[1] + (b[1] - a[1]) * alpha) for a, b in zip(first, last)))
        def mix(a, b):
            return tuple(x + (y - x) * alpha for x, y in zip(a, b))
        return Shape(tuple(contours), mix(source.fill, destination.fill),
                     mix(source.stroke, destination.stroke),
                     source.stroke_width + (destination.stroke_width - source.stroke_width) * alpha)
    return Animation(target, evaluate, easing)
