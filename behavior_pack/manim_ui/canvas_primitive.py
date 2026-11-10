# -*- coding: utf-8 -*-
"""Pyreact ManimCanvas primitive; no changes to Pyreact's Python core."""
from functools import partial
from .canvas import CanvasRenderer
from .pyreact.primitives import Primitive


def _style_visible(fiber):
    return fiber.primitive_state.get("_visible", True)


def _layout_geometry(host, fiber):
    """Use committed dimensions even when native visibility suppresses GetSize."""
    applied = fiber.primitive_state.get("_layout_applied")
    path = getattr(fiber, "native_path", None)
    if applied is None or path is None:
        return None
    parent_path = path.rsplit("/", 1)[0]
    parent = host.GetBaseUIControl(parent_path)
    if parent is None:
        return None
    origin = parent.GetGlobalPosition()
    return ((origin[0] + applied[2], origin[1] + applied[3]),
            (applied[0], applied[1]))


class ManimCanvasPrimitive(Primitive):
    """Mount one canvas player in a normal Pyreact layout.

    Props: player from create_canvas_player(), scene name, autoPlay (False),
    and optional onReady(player). Style owns size/position/opacity/zIndex.
    Unmount stops the player and releases the slot; caller may remount it.
    Explicit player.dispose() permanently ends that player's lifetime.
    """
    template_path = "/root/manim_canvas_tmpl"

    def props_affect_layout(self, prev_props, next_props, style):
        # Scene, callback and play-state changes do not change geometry.
        # In particular, parent state notifications must not re-query screen
        # metrics just because they create a new onReady closure.
        return prev_props.get("player") is not next_props.get("player")

    def apply_props(self, host, fiber, control, prev_props, next_props):
        player = next_props.get("player")
        if not isinstance(getattr(player, "renderer", None), CanvasRenderer):
            raise TypeError("ManimCanvas.player must come from create_canvas_player")
        if player.disposed:
            raise RuntimeError("A disposed canvas player cannot be mounted")
        state = fiber.primitive_state.get("_manim_canvas")
        if state is not None and state["player"] is not player:
            self.unmount(host, fiber)
            state = None
        if state is None:
            player.renderer.attach(control, visibility=partial(_style_visible, fiber),
                                   geometry=partial(_layout_geometry, host, fiber))
            slot = {"fiber": fiber, "active": True,
                    "callback": partial(self._frame, fiber)}
            state = {"player": player, "slot": slot, "loaded": None, "ready": False,
                     "auto_play": None}
            fiber.primitive_state["_manim_canvas"] = state
            host.pyreact_register_animation_frame(slot)
        state["scene"] = next_props.get("scene")
        state["slot"]["active"] = True
        state["requested_play"] = bool(next_props.get("autoPlay", False))
        state["on_ready"] = next_props.get("onReady")
        if state["on_ready"] is not None and not callable(state["on_ready"]):
            raise TypeError("ManimCanvas.onReady must be callable")
        return False

    def apply_layout(self, host, node):
        state = node.fiber.primitive_state.get("_manim_canvas")
        if state is None:
            return
        opacity = node.fiber.primitive_state.get("_native_color_alpha", node.inherited_opacity)
        # ScreenSizeChanged may precede the native physical viewport update.
        # Read both geometry and screen metrics on the following render frame,
        # after the framework has committed this layout. This is one scheduled
        # measurement per layout, never an unconditional per-frame SDK query.
        state["layout_opacity"] = opacity
        state["layout_pending"] = True

    def _frame(self, fiber, _now):
        state = fiber.primitive_state.get("_manim_canvas")
        if state is None:
            return
        player = state["player"]
        if player.disposed:
            return
        player.renderer.sync_visibility()
        if state.get("layout_pending"):
            state["layout_pending"] = False
            updated = player.renderer.update_layout(
                state["layout_opacity"], refresh_screen=True)
            state["layout_ready"] = player.renderer.ready
            if not updated and state["layout_ready"]:
                player.fail_render("Canvas layout shader parameter update failed")
                return
        if not state.get("layout_ready"):
            return
        scene = state["scene"]
        if scene is None:
            names = player.scene_names()
            scene = names[0] if names else None
        request = (scene, state["requested_play"])
        if state.get("failed_request") == request:
            if not player.visible or player.error:
                return
            # A business load/play successfully recovered this mounted player.
            # Consume the original props without loading/pausing it again.
            state["loaded"] = scene
            state["auto_play"] = state["requested_play"]
            state["failed_request"] = None
        elif state.get("failed_request") is not None:
            state["failed_request"] = None
        if state["loaded"] != scene:
            if scene is None or not player.load(scene):
                state["failed_request"] = request
                return
            state["loaded"] = scene
            state["auto_play"] = None
        if state["auto_play"] != state["requested_play"]:
            success = player.play() if state["requested_play"] else player.pause()
            if not success:
                state["failed_request"] = request
                return
            state["auto_play"] = state["requested_play"]
        if not state["ready"]:
            state["ready"] = True
            callback = state["on_ready"]
            if callback is not None:
                callback(player)
        player.frame()

    def unmount(self, host, fiber):
        state = fiber.primitive_state.pop("_manim_canvas", None)
        if state is None:
            return
        state["slot"]["active"] = False
        host.pyreact_unregister_animation_frame(state["slot"])
        player = state["player"]
        if not player.disposed:
            player.stop()
        player.renderer.detach()


ManimCanvas = ManimCanvasPrimitive()
