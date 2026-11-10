"""Topology-preserving sampling of ManimGL's quadratic Bezier contours."""

import math
from fractions import Fraction


def quadratic_point(curve, t):
    """Evaluate one quadratic; do not change its upstream point ordering."""
    a, h, b = curve
    u = 1.0 - t
    return [u * u * a[k] + 2.0 * u * t * h[k] + t * t * b[k]
            for k in range(2)]


def chord_error_bound(curve, subdivisions):
    """Maximum Euclidean deviation from equal-parameter polygonal segments.

    For B(t) = A + V*t + Q*t*t, B minus its chord on an interval of
    length h is Q*(t-a)*(t-b). Its norm is at most |Q|*h*h/4.
    This bounds corresponding points, and therefore also Hausdorff distance.
    """
    if isinstance(subdivisions, bool) or not isinstance(subdivisions, int) or subdivisions < 1:
        raise ValueError("subdivisions must be a positive integer")
    q = [curve[0][k] - 2.0 * curve[1][k] + curve[2][k] for k in range(2)]
    return math.hypot(*q) / (4.0 * subdivisions * subdivisions)


def choose_subdivisions(curve, tolerance):
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be finite and positive")
    return max(1, math.ceil(math.sqrt(chord_error_bound(curve, 1) / tolerance)))


def contour_curves(points):
    if len(points) < 3 or len(points) % 2 != 1:
        raise ValueError("ManimGL quadratic contour needs 2*n+1 control points")
    return [points[i:i + 3] for i in range(0, len(points) - 2, 2)]


def sample_contour(points, subdivisions):
    """Keep winding and coincident/degenerate vertices; closure is implicit."""
    curves = contour_curves(points)
    if len(curves) != len(subdivisions):
        raise ValueError("Each aligned quadratic needs its own fixed subdivision count")
    result = []
    for curve, count in zip(curves, subdivisions):
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("subdivisions must be positive integers")
        result.extend(quadratic_point(curve, i / count) for i in range(count))
    return result


def sample_curve(curve, subdivisions):
    """Sample one independent curve slot, retaining both anchors."""
    if isinstance(subdivisions, bool) or not isinstance(subdivisions, int) or subdivisions < 1:
        raise ValueError("subdivisions must be a positive integer")
    return [quadratic_point(curve, i / subdivisions) for i in range(subdivisions + 1)]


def marker_behavior(start_curve, end_curve):
    """Classify exact zeros of the real-valued affine anchor-minus-handle.

    Float inputs are converted to exact binary rational values. This identifies
    geometric event candidates, not native float32 multiply/add equality bands;
    every event must still be checked against the real upstream execution.
    """
    dimensions = len(start_curve[0])
    if any(len(point) != dimensions for curve in (start_curve, end_curve) for point in curve):
        raise ValueError("Control-point dimensions must agree")
    before = [Fraction(start_curve[0][k]) - Fraction(start_curve[1][k]) for k in range(dimensions)]
    after = [Fraction(end_curve[0][k]) - Fraction(end_curve[1][k]) for k in range(dimensions)]
    zero_before = not any(before)
    zero_after = not any(after)
    if zero_before and zero_after:
        return {"kind": "always_skip", "rate_fraction": None}
    if zero_before:
        return {"kind": "start_only", "rate_fraction": 0.0}
    if zero_after:
        return {"kind": "end_only", "rate_fraction": 1.0}
    delta = [b - a for a, b in zip(before, after)]
    if any(a and not d for a, d in zip(before, delta)):
        return {"kind": "never_skip", "rate_fraction": None}
    candidates = [-a / d for a, d in zip(before, delta) if d]
    if candidates and 0 < candidates[0] < 1 and all(t == candidates[0] for t in candidates):
        return {"kind": "interior_event", "rate_fraction": float(candidates[0])}
    return {"kind": "never_skip", "rate_fraction": None}


def signed_area(contour):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1]
                     for a, b in zip(contour, contour[1:] + contour[:1]))
