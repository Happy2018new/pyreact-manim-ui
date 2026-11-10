# -*- coding: utf-8 -*-
"""Minimal overlay for the client presentation; no debug chrome or progress."""
from .pyreact import (
    Component, Panel, Image, Label, Button, Style, Color, ButtonState,
    FlexDirection, Position, TextAlignment, use_effect, use_state,
)
from .presentation_audio import PRESENTATION_SCENES, PRESENTATION_TITLES


def _quiet_background(state):
    alpha = 0.36 if state == ButtonState.hover else 0.18 if state == ButtonState.pressed else 0.0
    return Image(color=Color(0.04, 0.08, 0.13, alpha),
                 style=Style(width="100%", height="100%"))


def _quiet_button(text, callback, width=38):
    return Button(style=Style(width=width, height=18, marginLeft=4),
                  onClick=callback, buttonBuilder=_quiet_background,
                  children=Label(content=text, fontSize=9, shadow=False,
                                 textAlign=TextAlignment.center,
                                 color=Color(0.65, 0.73, 0.83, 0.8)))


@Component
def ShowcasePanel(player):
    state, set_state = use_state(player.snapshot())

    def connect():
        # Native Esc and explicit pop share the same unmount path. The result
        # callback is an idempotent fallback for mount/transition failures.
        unsubscribe = player.subscribe(set_state)
        def disconnect():
            unsubscribe()
            player._showcase_closed()
        return disconnect
    use_effect(connect, [])
    other_scene = (PRESENTATION_SCENES[1] if state["showcase_scene"] == PRESENTATION_SCENES[0]
                   else PRESENTATION_SCENES[0])
    audio_error = state["audio_error"]
    return Panel(style=Style(width="100%", height="100%"), children=[
        Panel(style=Style(position=Position.absolute, right=8, bottom=5,
                          height=18, flexDirection=FlexDirection.row), children=[
            _quiet_button("切换：" + PRESENTATION_TITLES[other_scene], player.switch_showcase, 94),
            _quiet_button("暂停" if state["playing"] else "继续", player.toggle_play),
            _quiet_button("重播", player.replay_showcase),
            _quiet_button("返回", player.close_showcase),
        ]),
        Label(content=audio_error, fontSize=9, shadow=False, color=Color(1, 0.65, 0.5),
              style=Style(position=Position.absolute, left=8, bottom=8)) if audio_error else None,
    ])
