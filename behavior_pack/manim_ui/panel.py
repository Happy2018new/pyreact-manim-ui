# -*- coding: utf-8 -*-
"""Pyreact controls overlay the shader canvas without rendering the glyphs."""
from functools import partial
from .pyreact import (
    Component, Panel, Label, Button, Slider, Style, Color,
    AlignItems, FlexDirection, FlexWrap, JustifyContent, Position, use_effect, use_state,
)


def action_button(text, callback, scale):
    return Button(
        style=Style(width=70 * scale, height=24 * scale, marginHorizontal=3 * scale), onClick=callback,
        children=Label(content=text, color=Color(1, 1, 1), fontSize=10 * scale, shadow=False),
    )


def seek_ratio(player, duration, value):
    player.seek(float(value) * duration)


def change_scene(player, step):
    player.select_scene(player.scene_index + step)


def button_row(children, scale):
    return Panel(style=Style(width="100%", maxWidth=320,
                             flexDirection=FlexDirection.row, flexWrap=FlexWrap.wrap,
                             justifyContent=JustifyContent.center, rowGap=4 * scale, marginBottom=4 * scale),
                 children=children)


@Component
def PlayerPanel(player):
    state, set_state = use_state(player.snapshot())

    def connect():
        unsubscribe = player.subscribe(set_state)
        player.show()
        set_state(player.snapshot())
        def disconnect():
            unsubscribe()
            player.hide()
        return disconnect

    use_effect(connect, [])
    duration = state["duration"]
    scale = state["ui_scale"]
    title = state["title"] or "文字变换实验室"
    return Panel(
        style=Style(width="100%", height="100%"),
        children=[
            Panel(
                style=Style(position=Position.absolute, left=18, top=14 * scale, right=18),
                children=[
                    Label(content="MANIM / " + title, color=Color(0.5, 0.85, 1), fontSize=15 * scale, shadow=False),
                    Label(content="拖动进度检查中间态 · Esc 关闭 · F8 重开",
                          color=Color(0.7, 0.72, 0.77), fontSize=10 * scale, shadow=False),
                    Button(style=Style(position=Position.absolute, right=0, top=0,
                                       width=92 * scale, height=26 * scale),
                           onClick=player.open_showcase,
                           children=Label(content="作品演示", color=Color(0.55, 0.9, 1),
                                          fontSize=12 * scale, shadow=False)),
                ],
            ),
            Panel(
                style=Style(position=Position.absolute, left=20, right=20, bottom=14 * scale,
                            alignItems=AlignItems.center),
                children=[
                    Label(content=state["error"] or "%.2f / %.2f s" % (state["position"], duration),
                          color=Color(0.8, 0.85, 0.92), fontSize=10 * scale, shadow=False),
                    Slider(style=Style(width="100%", maxWidth=320, height=18 * scale,
                                       marginTop=5 * scale, marginBottom=8 * scale),
                           value=state["position"] / duration, steps=1,
                           onChange=partial(seek_ratio, player, duration)),
                    button_row([
                        action_button("上一例", partial(change_scene, player, -1), scale),
                        action_button("暂停" if state["playing"] else "播放", player.toggle_play, scale),
                        action_button("下一例", partial(change_scene, player, 1), scale),
                    ], scale),
                    button_row([
                        action_button("起点", partial(player.seek, 0.0), scale),
                        action_button("中间态", partial(player.seek, duration / 2), scale),
                        action_button("终点", partial(player.seek, duration), scale),
                        action_button("独立画布", player.open_canvas_panel, scale),
                    ], scale),
                ],
            ),
        ],
    )
