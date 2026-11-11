# -*- coding: utf-8 -*-
"""Compact image playground with a persistent, independent original preview."""
from functools import partial
import math
from . import ShaderImage
from .demo import ImageDemo
from ..pyreact import (
    Component, Panel, Image, Label, Button, Slider, ScrollView, Style, Color,
    FlexDirection, AlignItems, Position, TextAlignment,
    use_effect, use_memo, use_state,
)


_FIT_TITLES = {"contain": "完整", "cover": "铺满", "fill": "拉满"}
_EFFECT_TITLES = {"none": "无", "wave": "波纹", "swirl": "旋涡"}
_ACCENT = Color(0.45, 0.85, 1.0)
_GOLD = Color(1.0, 0.77, 0.45)


def _label(text, size=10, color=None, **layout):
    layout.setdefault("minWidth", 0)
    layout.setdefault("zIndex", 2)
    return Label(content=text, fontSize=size, color=color or Color(0.85, 0.9, 0.96),
                 shadow=True, style=Style(**layout))


def _backdrop():
    return Image(color=Color(0.025, 0.04, 0.065, 0.88),
                 style=Style(position=Position.absolute, left=0, right=0,
                             top=0, bottom=0, zIndex=0))


def _button(text, action, active=False):
    return Button(style=Style(flex=1, minWidth=0, height=21, marginHorizontal=2, zIndex=2),
                  onClick=action, children=Label(
                      content=text, fontSize=9, shadow=True,
                      color=_ACCENT if active else Color(0.93, 0.96, 1.0),
                      textAlign=TextAlignment.center))


def _row(children, height=24):
    return Panel(style=Style(width="100%", minWidth=0, height=height, flexShrink=0,
                             zIndex=2, flexDirection=FlexDirection.row,
                             alignItems=AlignItems.center), children=children)


def _slider(demo, title, name, value, caption):
    return _row([
        _label(title, size=9, width=42, height=12),
        Slider(value=max(0.0, min(1.0, value)), steps=1,
               onChange=partial(demo.set_parameter, name),
               style=Style(flex=1, minWidth=0, height=17, marginHorizontal=5, zIndex=2)),
        _label(caption, size=9, width=33, height=12),
    ], 22)


def _image_view(controller, on_ready):
    return Panel(style=Style(width="100%", height="100%", minWidth=0, minHeight=0), children=[
        Image(src="textures/manim/images_checker", color=Color(1, 1, 1),
              style=Style(position=Position.absolute, left=0, right=0, top=0, bottom=0, zIndex=1)),
        ShaderImage(controller=controller, onReady=on_ready,
                    style=Style(width="100%", height="100%", zIndex=2)),
    ])


def _main_card(demo, state, preview):
    config = state["config"]
    if state["error"]:
        status = "图片暂时无法显示，请返回后重试"
    elif not state["ready"]["primary"]:
        status = "正在载入图片…"
    else:
        status = "方格表示透明区域 · " + _EFFECT_TITLES[config["effect"]]
    return Panel(style=Style(flex=1.2, minWidth=0, height="100%", padding=9,
                             marginRight=4), children=[
        _backdrop(),
        _label(state["title"], size=13, color=_ACCENT, width="100%", height=19),
        _label("实时预览", size=9, width="100%", height=14),
        Panel(style=Style(width="100%", flex=1, minHeight=20, marginVertical=6),
              children=preview),
        _label(status, size=9, color=Color(1, 0.65, 0.5) if state["error"] else None,
               width="100%", height=15),
        _row([_button("上一张", partial(demo.select_image, -1)),
              _label("%d / %d" % (state["index"] + 1, state["total"]),
                     width=36, height=12),
              _button("下一张", partial(demo.select_image, 1))], 26),
    ])


def _comparison(state, original):
    size = state["size"]
    return _row([
        Panel(style=Style(width=90, height=54, flexShrink=0, marginRight=8), children=original),
        Panel(style=Style(flex=1, minWidth=0), children=[
            _label("原图对照", size=10, color=_GOLD, width="100%", height=17),
            _label("%d × %d" % (size[0], size[1]), size=9, width="100%", height=14),
            _label("保留原始比例", size=9, width="100%", height=14),
        ]),
    ], 64)


def _controls(demo, state):
    config = state["config"]
    crop_on = config["crop"] != (0.0, 0.0, 1.0, 1.0)
    return [
        _row([_button("适配：" + _FIT_TITLES[config["fit"]], demo.cycle_fit),
              _button("效果：" + _EFFECT_TITLES[config["effect"]], demo.cycle_effect,
                      active=config["effect"] != "none")]),
        _slider(demo, "旋转", "rotation", (config["rotation"] / math.pi + 1.0) / 2.0,
                "%.0f°" % math.degrees(config["rotation"])),
        _slider(demo, "横向拉伸", "scale_x", (config["scale"][0] - 0.25) / 1.75,
                "%.0f%%" % (config["scale"][0] * 100)),
        _slider(demo, "纵向拉伸", "scale_y", (config["scale"][1] - 0.25) / 1.75,
                "%.0f%%" % (config["scale"][1] * 100)),
        _slider(demo, "不透明度", "opacity", config["opacity"],
                "%.0f%%" % (config["opacity"] * 100)),
        _slider(demo, "效果强度", "strength", (config["strength"] + 1.0) / 2.0,
                "%+.0f%%" % (config["strength"] * 100)),
        _row([_button("水平镜像", demo.toggle_flip_x, active=config["flip_x"]),
              _button("垂直镜像", demo.toggle_flip_y, active=config["flip_y"]),
              _button("完整图片" if crop_on else "裁切中心", demo.toggle_crop, active=crop_on)]),
        _row([_button("暂停动画" if state["primary"]["playing"] else "播放波纹",
                      demo.toggle_animation, active=state["primary"]["playing"]),
              _button("恢复原图", demo.reset)]),
    ]


def _settings_card(demo, state, original):
    return Panel(style=Style(flex=1, minWidth=0, height="100%", padding=8, marginLeft=4), children=[
        _backdrop(),
        _label("调整图片", size=11, color=_ACCENT, width="100%", height=17),
        _comparison(state, original),
        ScrollView(showScrollbar=True, style=Style(width="100%", flex=1, minWidth=0, zIndex=2),
                   children=Panel(style=Style(width="100%", height=197), children=_controls(demo, state) + [
                       _label("拖动滑条，即时预览", size=9, width="100%", height=15),
                   ])),
    ])


@Component
def ImagePanel(demo, onBack):
    state, set_state = use_state(demo.snapshot())

    def connect():
        unsubscribe = demo.subscribe(set_state)
        set_state(demo.snapshot())
        def disconnect():
            unsubscribe()
            demo.dispose()
        return disconnect
    use_effect(connect, [])

    # Both native image subtrees stay identical while sliders update captions.
    # Animation updates controller uniforms without re-rendering this page.
    def make_preview():
        return _image_view(demo.primary, demo.on_ready)
    def make_original():
        return _image_view(demo.original, demo.on_ready)
    preview = use_memo(make_preview, [demo])
    original = use_memo(make_original, [demo])

    return Panel(style=Style(width="100%", height="100%", padding=10), children=[
        Panel(style=Style(width="100%", height=30, flexShrink=0,
                          flexDirection=FlexDirection.row, alignItems=AlignItems.center), children=[
            _label("MANIM / 图片工坊", size=13, color=Color(0.6, 0.9, 1.0), flex=1),
            _label("Esc 返回", size=9, width=52),
            Button(style=Style(width=54, height=22), onClick=onBack,
                   children=Label(content="返回", fontSize=10, color=Color(1, 1, 1))),
        ]),
        Panel(style=Style(width="100%", flex=1, minHeight=0,
                          flexDirection=FlexDirection.row), children=[
            _main_card(demo, state, preview), _settings_card(demo, state, original),
        ]),
    ])
