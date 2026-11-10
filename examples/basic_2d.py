"""Editable 2D scenes; all Python runs during the host build, never in MC."""
import math

from pyreact_manim.animation import Create, FadeIn, FadeOut, MoveAlong, Rotate, Scale, Shift, Transform
from pyreact_manim.geometry import Axes, BLUE, Circle, Dot, GREEN, Plot, Polygon, Rectangle, YELLOW
from pyreact_manim.scene import Scene


def geometry_scene():
    scene = Scene("basic_geometry")
    circle = Circle(fill=(0.1, 0.25, 0.4, 0.65), stroke=BLUE).shift(-2, 0)
    triangle = Polygon([(1.1, -0.8), (2.9, -0.8), (2, 0.9)],
                       fill=(0.35, 0.25, 0.06, 0.7), stroke=YELLOW)
    scene.add("shape", circle).add("triangle", triangle)
    scene.play(FadeIn("shape"), FadeIn("triangle"), duration=0.6)
    scene.play(Transform("shape", Rectangle(2.2, 2.2, fill=(0.1, 0.3, 0.2, 0.7),
                                           stroke=GREEN).shift(-2, 0)),
               Rotate("triangle", math.tau, about=(2, 0)), duration=2)
    scene.play(Shift("shape", 0, 0.65), Scale("triangle", 0.65, about=(2, 0)), duration=1)
    scene.play(Rotate("shape", math.pi / 4, about=(-2, 0.65)),
               Shift("triangle", -0.35, 0.5), duration=1)
    scene.wait(0.5).play(FadeOut("shape"), FadeOut("triangle"), duration=0.6)
    return scene


def graph_scene():
    scene = Scene("axes_sine")
    for name, shape in Axes().items():
        scene.add("axis_" + name, shape)
    curve = Plot(lambda x: math.sin(x), (-4.5, 4.5))
    scene.add("sine", curve)
    scene.add("point", Dot((-4.5, math.sin(-4.5))))
    scene.play(Create("sine"), duration=2)
    scene.play(FadeIn("point"), duration=0.3)
    scene.play(MoveAlong("point", lambda a: (-4.5 + 9 * a, math.sin(-4.5 + 9 * a))), duration=3)
    scene.wait(0.5)
    return scene


def build_scenes():
    return [geometry_scene(), graph_scene()]
