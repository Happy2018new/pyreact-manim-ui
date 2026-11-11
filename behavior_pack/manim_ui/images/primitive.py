# -*- coding: utf-8 -*-
"""Pyreact ShaderImage primitive using the established native canvas template."""
from functools import partial
from ..canvas_primitive import _layout_geometry, _style_visible
from ..pyreact.primitives import Primitive
from .model import ImageController


class ShaderImagePrimitive(Primitive):
    """ShaderImage(controller=..., style=..., onReady=None).

    Style owns the native rectangle, visibility, opacity and stacking. Image
    transforms and normalized crop belong to controller.configure().
    """
    template_path = "/root/manim_canvas_tmpl"

    def props_affect_layout(self, prev_props, next_props, style):
        return prev_props.get("controller") is not next_props.get("controller")

    def apply_props(self, host, fiber, control, prev_props, next_props):
        controller = next_props.get("controller")
        callback = next_props.get("onReady")
        if not isinstance(controller, ImageController):
            raise TypeError("ShaderImage.controller must come from create_image_controller")
        if controller.disposed:
            raise RuntimeError("A disposed image controller cannot be mounted")
        if callback is not None and not callable(callback):
            raise TypeError("ShaderImage.onReady must be callable")
        state = fiber.primitive_state.get("_shader_image")
        if state is not None and state["controller"] is not controller:
            self.unmount(host, fiber)
            state = None
        if state is None:
            controller.mount(control, partial(_style_visible, fiber),
                             partial(_layout_geometry, host, fiber))
            slot = {"fiber": fiber, "active": True, "callback": partial(self._frame, fiber)}
            state = {"controller": controller, "slot": slot, "ready": False}
            fiber.primitive_state["_shader_image"] = state
            host.pyreact_register_animation_frame(slot)
            controller._mount_cleanup = partial(self._release, host, fiber, state)
        state["on_ready"] = callback
        return False

    def apply_layout(self, host, node):
        state = node.fiber.primitive_state.get("_shader_image")
        if state is None:
            return
        state["layout_opacity"] = node.fiber.primitive_state.get(
            "_native_color_alpha", node.inherited_opacity)
        # The next frame sees committed geometry and the new physical viewport.
        state["layout_pending"] = True

    def _frame(self, fiber, _now):
        state = fiber.primitive_state.get("_shader_image")
        if state is None:
            return
        controller = state["controller"]
        if controller.disposed:
            return
        if state.get("layout_pending"):
            state["layout_pending"] = False
            controller.update_layout(state["layout_opacity"])
        if not state["ready"] and controller.visible and not controller.error:
            state["ready"] = True
            if state["on_ready"] is not None:
                state["on_ready"](controller)
        controller.frame()

    def _release(self, host, fiber, state):
        if fiber.primitive_state.get("_shader_image") is state:
            fiber.primitive_state.pop("_shader_image")
        state["slot"]["active"] = False
        host.pyreact_unregister_animation_frame(state["slot"])

    def unmount(self, host, fiber):
        state = fiber.primitive_state.get("_shader_image")
        if state is not None:
            state["controller"].unmount()


ShaderImage = ShaderImagePrimitive()
