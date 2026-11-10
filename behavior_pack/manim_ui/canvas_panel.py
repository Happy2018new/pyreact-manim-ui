# -*- coding: utf-8 -*-
"""Two owned canvas players and their compact interactive demo page."""
from functools import partial
import math
from .canvas import create_canvas_player, RUNTIME_SCENE
from .canvas_primitive import ManimCanvas
from .timeline import finite_number
from .pyreact import (
    Component, Panel, Image, Label, Button, Slider, Style, Color,
    FlexDirection, JustifyContent, AlignItems, Position, TextAlignment,
    use_effect, use_state,
)


class CanvasDemo(object):
    """Page-owned players; these same actions are callable by SDK diagnostics."""
    def __init__(self, factory=create_canvas_player):
        self.left = factory()
        self.right = factory()
        self.names = tuple(name for name in self.left.scene_names() if name != RUNTIME_SCENE)
        if not self.names or RUNTIME_SCENE not in self.right.scene_names():
            self.dispose()
            raise ValueError("Canvas demo requires compiled scenes and runtime_shapes")
        self.initial_left_scene = self.names[0]
        self.ready = {"left": False, "right": False}
        self.right.renderer.set_shape(morph=0.25, progress=1.0, scale=0.72,
                                      color=(0.25, 0.8, 1.0), rotation=0.0)

    def on_ready(self, side, _player):
        self.ready[side] = True
        self.left.notify()

    def snapshot(self):
        return {"left": self.left.snapshot(), "right": self.right.snapshot(),
                "shape": self.right.renderer.shape_snapshot(), "ready": dict(self.ready),
                "disposed": self.left.disposed and self.right.disposed}

    def subscribe(self, callback):
        def receive(_state):
            callback(self.snapshot())
        cancel_left = self.left.subscribe(receive)
        cancel_right = self.right.subscribe(receive)
        def unsubscribe():
            cancel_left()
            cancel_right()
        return unsubscribe

    def load_left(self, name):
        if name not in self.names or not self.ready["left"]:
            return False
        return self.left.load(name)

    def select_left(self, step):
        current = self.left.snapshot()["scene"]
        index = self.names.index(current) if current in self.names else 0
        return self.load_left(self.names[(index + int(step)) % len(self.names)])

    def toggle_left(self):
        if not self.ready["left"]:
            return False
        if self.left.snapshot()["playing"]:
            return self.left.pause()
        return self.left.play()

    def seek_left(self, ratio):
        if not self.ready["left"]:
            return False
        return self.left.seek(finite_number(ratio, "progress") * self.left.snapshot()["duration"])

    def set_shape(self, **changes):
        if self.right.disposed:
            return False
        result = self.right.renderer.set_shape(**changes)
        self.right.notify()
        return result

    def set_parameter(self, name, value):
        if name not in ("morph", "progress", "rotation"):
            raise ValueError("Unsupported demo parameter")
        value = finite_number(value, name)
        if name == "rotation":
            value *= 2.0 * math.pi
        return self.set_shape(**{name: value})

    def set_color(self, color):
        return self.set_shape(color=color)

    def preset(self, name):
        presets = {"circle": {"morph": 0.0, "progress": 1.0, "rotation": 0.0},
                   "square": {"morph": 1.0, "progress": 1.0, "rotation": 0.0},
                   "partial": {"morph": 0.5, "progress": 0.55, "rotation": math.pi / 4}}
        if name not in presets:
            raise ValueError("Unknown shape preset")
        return self.set_shape(**presets[name])

    def dispose(self):
        self.left.dispose()
        self.right.dispose()


def _label(text, size=10, color=None, **layout):
    layout.setdefault("minWidth", 0)
    layout.setdefault("zIndex", 2)
    return Label(content=text, fontSize=size, color=color or Color(0.85, 0.9, 0.96),
                 shadow=True, style=Style(**layout))


def _button(text, action, color=None):
    return Button(style=Style(flex=1, minWidth=0, height=22, marginHorizontal=2, zIndex=2), onClick=action,
                  children=Label(content=text, fontSize=10, shadow=True,
                                 color=color or Color(1, 1, 1), textAlign=TextAlignment.center))


def _row(children, height=24):
    return Panel(style=Style(width="100%", minWidth=0, height=height, flexShrink=0, zIndex=2,
                             flexDirection=FlexDirection.row, alignItems=AlignItems.center),
                 children=children)


def _parameter_slider(demo, title, name, value, caption):
    return _row([
        _label(title, width=28, height=12),
        Slider(value=value, steps=1, onChange=partial(demo.set_parameter, name),
               style=Style(flex=1, minWidth=0, height=17, marginHorizontal=6, zIndex=2)),
        _label(caption, width=31, height=12),
    ], 22)


def _backdrop():
    # A translucent panel gives pale strokes contrast while keeping the world
    # visible through both the canvas's transparent pixels and its surroundings.
    return Image(color=Color(0.025, 0.04, 0.065, 0.72),
                 style=Style(position=Position.absolute, left=0, right=0, top=0, bottom=0, zIndex=0))


def _left_card(demo, state):
    current = state["left"]
    duration = current["duration"]
    return Panel(style=Style(flex=1, minWidth=0, height="100%", padding=8, marginRight=4), children=[
        _backdrop(),
        _label("文字与二维动画", size=12, color=Color(0.45, 0.85, 1), width="100%", height=17),
        _label(current["title"], size=9, width="100%", height=14),
        ManimCanvas(player=demo.left, scene=demo.initial_left_scene, autoPlay=False,
                    onReady=partial(demo.on_ready, "left"),
                    style=Style(width="100%", flex=1, minWidth=0, minHeight=30, marginVertical=4, zIndex=2)),
        _label(current["error"] or "%.2f / %.2f s" % (current["position"], duration), width="100%", height=14),
        Panel(style=Style(width="100%", height=24, paddingHorizontal=6, zIndex=2), children=
              Slider(value=current["position"] / duration, steps=1, onChange=demo.seek_left,
                     style=Style(width="100%", height=18, marginVertical=3))),
        _row([_button("上一例", partial(demo.select_left, -1)),
              _button("暂停" if current["playing"] else "播放", demo.toggle_left),
              _button("下一例", partial(demo.select_left, 1))]),
        _row([_button("起点", partial(demo.seek_left, 0)),
              _button("中间", partial(demo.seek_left, 0.5)),
              _button("终点", partial(demo.seek_left, 1))]),
    ])


def _right_card(demo, state):
    shape = state["shape"]
    return Panel(style=Style(flex=1, minWidth=0, height="100%", padding=8, marginLeft=4), children=[
        _backdrop(),
        _label("实时图形", size=12, color=Color(1, 0.75, 0.4), width="100%", height=17),
        _label("拖动滑条，即时改变形状", size=9, width="100%", height=14),
        ManimCanvas(player=demo.right, scene=RUNTIME_SCENE, autoPlay=False,
                    onReady=partial(demo.on_ready, "right"),
                    style=Style(width="100%", flex=1, minWidth=0, minHeight=30, marginVertical=4, zIndex=2)),
        _label(state["right"]["error"] or "透明背景 · 独立控制", size=9, width="100%", height=14),
        _parameter_slider(demo, "形状", "morph", shape["morph"], "%.0f%%" % (100 * shape["morph"])),
        _parameter_slider(demo, "描绘", "progress", shape["progress"], "%.0f%%" % (100 * shape["progress"])),
        _parameter_slider(demo, "旋转", "rotation", (shape["rotation"] / (2 * math.pi)) % 1.0,
                          "%.0f°" % math.degrees(shape["rotation"])),
        _row([_button("圆形", partial(demo.preset, "circle")),
              _button("方形", partial(demo.preset, "square")),
              _button("半绘", partial(demo.preset, "partial"))]),
        _row([_button("青色", partial(demo.set_color, (0.25, 0.8, 1.0)), Color(0.25, 0.8, 1.0)),
              _button("粉色", partial(demo.set_color, (1.0, 0.4, 0.75)), Color(1.0, 0.4, 0.75)),
              _button("金色", partial(demo.set_color, (1.0, 0.78, 0.2)), Color(1.0, 0.78, 0.2))]),
    ])


@Component
def CanvasPanel(demo, onBack):
    state, set_state = use_state(demo.snapshot())
    def connect():
        unsubscribe = demo.subscribe(set_state)
        set_state(demo.snapshot())
        def disconnect():
            unsubscribe()
            demo.dispose()
        return disconnect
    use_effect(connect, [])
    return Panel(style=Style(width="100%", height="100%", padding=12), children=[
        Panel(style=Style(width="100%", height=28, flexShrink=0,
                          flexDirection=FlexDirection.row, alignItems=AlignItems.center,
                          justifyContent=JustifyContent.space_between), children=[
            _label("MANIM / 独立画布", size=13, color=Color(0.6, 0.9, 1), flex=1),
            _label("Esc 返回", size=9, width=52),
            Button(style=Style(width=54, height=22), onClick=onBack,
                   children=Label(content="返回", fontSize=10, color=Color(1, 1, 1))),
        ]),
        Panel(style=Style(width="100%", flex=1, flexDirection=FlexDirection.row),
              children=[_left_card(demo, state), _right_card(demo, state)]),
    ])
