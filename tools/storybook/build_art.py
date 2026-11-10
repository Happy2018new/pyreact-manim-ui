"""Original curved illustration contours, compiled to bounded GLSL polygons.

The small path library is artwork, not a downloaded illustration. Cubics are
sampled off-line; only interpolation and coverage remain in the fragment shader.
"""
from __future__ import annotations

import numpy as np
from svgelements import Path as SVGPath


PATHS = {
    "cape": "M -.13 2.29 C -.40 2.17 -.43 1.91 -.55 1.65 C -.70 1.24 -1.00 .98 -1.12 .74 C -.83 .77 -.66 .60 -.45 .70 C -.20 .81 -.12 1.10 .05 1.39 C .20 1.73 .14 2.04 .06 2.25 C .00 2.30 -.06 2.32 -.13 2.29 Z",
    "capeShade": "M -.16 2.21 C -.38 1.86 -.31 1.39 -.64 .98 C -.76 .83 -.91 .79 -1.10 .75 C -.82 .76 -.65 .61 -.45 .71 C -.22 .86 -.07 1.16 .03 1.43 C -.13 1.44 -.22 1.72 -.16 2.21 Z",
    "capeFold": "M -.24 2.09 C -.38 1.52 -.52 1.18 -.83 .85 C -.65 .98 -.46 1.01 -.35 1.26 C -.22 1.58 -.22 1.85 -.24 2.09 Z",
    "backBoot": "M -.18 .50 C -.16 .35 -.16 .15 -.21 .10 C -.24 .08 -.31 .09 -.35 .05 C -.38 -.01 -.27 -.04 -.17 -.01 C -.08 .02 -.04 .10 -.06 .24 L -.04 .51 Z",
    "frontBoot": "M .13 .52 C .15 .34 .13 .17 .15 .10 C .20 .08 .29 .06 .31 .02 C .30 -.03 .17 -.04 .09 -.01 C .02 .06 .02 .21 .02 .42 Z",
    "dress": "M -.12 2.23 C .01 2.29 .15 2.23 .17 2.08 C .15 1.91 .08 1.73 .11 1.55 C .17 1.11 .38 .79 .39 .57 C .21 .45 -.02 .46 -.26 .51 C -.41 .53 -.52 .55 -.58 .65 C -.39 .95 -.31 1.27 -.23 1.59 C -.18 1.82 -.26 2.10 -.12 2.23 Z",
    "dressLight": "M .02 1.67 C -.03 1.36 .05 .86 .13 .50 C .22 .48 .30 .52 .38 .57 C .37 .81 .17 1.15 .11 1.56 Z",
    "neck": "M -.08 2.44 C -.07 2.33 -.12 2.26 -.15 2.23 C -.05 2.15 .04 2.15 .10 2.22 C .06 2.28 .04 2.35 .08 2.43 Z",
    "face": "M -.16 2.78 C -.13 2.93 .07 2.97 .18 2.84 C .22 2.79 .22 2.73 .23 2.68 C .25 2.63 .29 2.61 .29 2.58 C .29 2.56 .24 2.56 .23 2.54 C .23 2.49 .20 2.44 .14 2.42 C .07 2.39 -.02 2.42 -.08 2.47 C -.16 2.54 -.19 2.68 -.16 2.78 Z",
    "hair": "M .20 2.77 C .20 2.91 .10 3.00 -.05 2.99 C -.22 2.99 -.32 2.85 -.33 2.68 C -.35 2.53 -.46 2.49 -.59 2.44 C -.75 2.36 -.77 2.22 -.99 2.25 C -.91 2.12 -.70 2.12 -.54 2.23 C -.39 2.33 -.34 2.32 -.27 2.46 C -.30 2.25 -.45 2.18 -.55 2.09 C -.35 2.08 -.20 2.23 -.16 2.40 C -.11 2.51 -.13 2.67 -.06 2.78 C .03 2.84 .08 2.80 .20 2.77 Z",
    "hairLight": "M -.13 2.91 C -.29 2.78 -.21 2.61 -.36 2.43 C -.47 2.31 -.60 2.28 -.72 2.25 C -.52 2.27 -.31 2.32 -.23 2.51 C -.15 2.68 -.24 2.77 -.13 2.91 Z",
    "sleeve": "M .10 2.19 C .24 2.15 .25 1.98 .31 1.88 C .35 1.82 .43 1.89 .49 1.93 L .55 1.83 C .44 1.72 .32 1.68 .25 1.74 C .13 1.83 .07 2.00 .04 2.11 Z",
    "hand": "M .48 1.94 C .56 1.99 .60 2.04 .64 2.06 C .68 2.08 .72 2.07 .74 2.09 C .77 2.11 .79 2.10 .78 2.07 C .74 2.02 .69 2.02 .65 1.99 C .71 2.00 .76 2.03 .80 2.03 C .83 2.01 .80 1.99 .77 1.98 C .70 1.94 .62 1.94 .56 1.90 L .52 1.85 Z",
    "farSleeve": "M -.04 2.15 C -.06 1.97 -.01 1.80 .13 1.76 C .29 1.77 .38 1.86 .47 1.89 L .50 1.81 C .39 1.70 .25 1.65 .12 1.65 C -.08 1.68 -.20 1.93 -.15 2.10 Z",
    "roof": "M -.68 .78 C -.46 .88 -.43 1.30 -.09 1.45 C .14 1.33 .39 .98 .69 .82 C .48 .82 .34 .76 .12 .78 C -.17 .83 -.41 .74 -.68 .78 Z",
    "roofTall": "M -.52 .90 C -.34 1.05 -.35 1.39 -.03 1.72 C .18 1.41 .21 1.09 .56 .91 C .36 .93 .25 .88 .04 .90 C -.17 .93 -.30 .86 -.52 .90 Z",
    "house": "M -.49 .00 L -.48 .80 C -.19 .76 .10 .84 .48 .78 L .44 .03 C .16 -.01 -.14 .04 -.49 .00 Z",
    "houseSide": "M .11 .02 L .12 .80 C .25 .79 .36 .81 .48 .78 L .44 .03 Z",
    "hill": "M -10 -5 L -10 -2.55 C -7 -1.87 -5.8 -1.65 -3.5 -2.24 C -1.4 -2.80 .8 -2.30 2.6 -1.95 C 4.9 -1.45 6.2 -1.97 10 -2.35 L 10 -5 Z",
    "boat": "M -1.57 .17 C -.93 .09 -.46 -.02 -.07 -.03 C .40 -.05 .97 .13 1.56 .35 C 1.22 .05 .83 -.29 .20 -.50 C -.51 -.40 -1.15 -.08 -1.57 .17 Z",
    "sail": "M -.13 .16 C -.15 .69 -.12 1.24 -.05 1.88 C -.50 1.46 -.98 .91 -1.15 .36 C -.80 .23 -.49 .21 -.13 .16 Z",
    "sailShade": "M -.13 .16 C -.43 .28 -.74 .39 -1.15 .36 C -.98 .91 -.50 1.46 -.05 1.88 C -.60 1.03 -.37 .50 -.13 .16 Z",
    "trunk": "M -.17 -2.45 C -.03 -1.84 -.06 -1.11 .02 -.51 C .09 .00 .06 .61 .35 1.25 C .19 .58 .19 .05 .17 -.50 C .12 -1.12 .21 -1.91 .31 -2.44 C .15 -2.36 .05 -2.38 -.17 -2.45 Z",
    "leaf": "M -.32 0 C -.12 .19 .12 .19 .34 .00 C .13 -.12 -.10 -.14 -.32 0 Z",
    "bird": "M -.04 .01 C -.16 .12 -.32 .39 -.54 .37 C -.42 .24 -.30 .07 -.14 -.02 C -.23 -.04 -.25 -.10 -.29 -.14 C -.17 -.12 -.08 -.08 -.01 -.08 C .06 -.12 .11 -.14 .17 -.13 C .12 -.08 .07 -.04 .05 -.02 C .21 .01 .41 .22 .55 .37 C .31 .37 .18 .14 .03 .04 C .08 .08 .13 .09 .13 .05 C .13 .01 .07 -.01 .04 .00 C .02 .01 -.01 .02 -.04 .01 Z",
    "star": "M 0 .10 C .015 .025 .025 .015 .10 0 C .025 -.015 .015 -.025 0 -.10 C -.015 -.025 -.025 -.015 -.10 0 C -.025 .015 -.015 .025 0 .10 Z",
}


def points(path, count=None):
    result = []
    for segment in SVGPath(path):
        if segment.__class__.__name__ in ("Move", "Close"):
            continue
        samples = 2 if segment.__class__.__name__ == "Line" else 10
        for alpha in np.linspace(0, 1, samples, endpoint=False):
            point = segment.point(float(alpha))
            result.append((point.x, point.y))
    result = np.asarray(result, dtype=float)
    if count is None:
        return result
    closed = np.concatenate([result, result[:1]])
    lengths = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))])
    targets = np.linspace(0, lengths[-1], count, endpoint=False)
    return np.column_stack([np.interp(targets, lengths, closed[:, axis]) for axis in range(2)])


def vector(point):
    return "vec2(%.5f,%.5f)" % tuple(point)


def static_path(name, path):
    pts = points(path)
    low, high = pts.min(axis=0), pts.max(axis=0)
    center, extent = (low + high) / 2, (high - low) / 2 + .018
    result = ["float art_%s(vec2 p) {" % name,
              "vec2 bound=abs(p-%s)-%s;" % (vector(center), vector(extent)),
              "if(max(bound.x,bound.y)>0.) return max(bound.x,bound.y)+.018;",
              "float d=100.; float winding=1.; vec2 a=%s; vec2 b;" % vector(pts[-1])]
    for point in pts:
        result.append("b=%s; contourEdge(p,a,b,d,winding); a=b;" % vector(point))
    result += ["return sqrt(d)*winding;", "}"]
    return "\n".join(result)


def transform_path():
    leaf, bird, star = [points(PATHS[key], 64) for key in ("leaf", "bird", "star")]

    def aligned(source, target):
        def area(contour):
            following = np.roll(contour, -1, axis=0)
            return np.sum(contour[:, 0] * following[:, 1] - contour[:, 1] * following[:, 0])
        if area(source) * area(target) < 0:
            target = target[::-1]
        costs = [np.sum((source - np.roll(target, offset, axis=0)) ** 2) for offset in range(len(target))]
        return np.roll(target, int(np.argmin(costs)), axis=0)

    bird = aligned(leaf, bird)
    star = aligned(bird, star)
    result = ["float art_leafBirdStar(vec2 p,float wing,float morph,float constellation) {",
              "if(max(abs(p.x),abs(p.y))>.62) return max(abs(p.x),abs(p.y))-.60;",
              "float d=100.; float winding=1.; vec2 a; vec2 b;",
              "a=mix(mix(%s,%s*vec2(1.,wing),morph),%s,constellation);" %
              (vector(leaf[-1]), vector(bird[-1]), vector(star[-1]))]
    for first, second, third in zip(leaf, bird, star):
        result.append("b=mix(mix(%s,%s*vec2(1.,wing),morph),%s,constellation); contourEdge(p,a,b,d,winding); a=b;" %
                      (vector(first), vector(second), vector(third)))
    result += ["return sqrt(d)*winding;", "}"]
    return "\n".join(result)


def shader_source():
    return "\n\n".join([static_path(name, path) for name, path in PATHS.items()
                          if name not in ("leaf", "bird", "star")] + [transform_path()])
