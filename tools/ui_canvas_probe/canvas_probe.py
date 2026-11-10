# -*- coding: utf-8 -*-
"""Client-only, explicit SDK-driven UI canvas feasibility probe.

This module does not register events, timers or private native callbacks.
The owner creates it after UiInitFinished and captures background frames.
"""
import mod.client.extraClientApi as clientApi

ScreenNode = clientApi.GetScreenNodeCls()
NAMESPACE = "manim_canvas_probe"
UI_KEY = "canvas_probe"
SLOTS = ("left", "right")


class CanvasProbe(ScreenNode):
    def __init__(self, namespace, name, param):
        ScreenNode.__init__(self, namespace, name, param)
        self.actor = clientApi.GetEngineCompFactory().CreateActorRender(None)
        self.game = clientApi.GetEngineCompFactory().CreateGame(clientApi.GetLevelId())
        self.results = {}
        self.closed = False

    def Create(self):
        self.configure()

    def configure(self):
        for slot in SLOTS:
            base = self.GetBaseUIControl("/" + slot + "/canvas")
            doll = base.asNeteasePaperDoll() if base is not None else None
            if doll is None:
                self.results[slot] = "missing paperdoll"
                continue
            self.results[slot] = doll.RenderEntity({
                "entity_identifier": "pmanim_probe:" + slot,
                "scale": 1.0, "render_depth": -15,
                "init_rot_x": 0.0, "init_rot_y": 0.0, "init_rot_z": 0.0,
            })
        self.set_state("left", 0.15, 1.0, (0.2, 0.9, 1.0))
        self.set_state("right", 0.85, 0.5, (1.0, 0.3, 0.85))
        self.fit_images()
        self.sync_layout()
        return dict(self.results)

    def fit_images(self):
        for slot in SLOTS:
            for child in ("back", "grid_v", "grid_h", "occluder"):
                base = self.GetBaseUIControl("/" + slot + "/" + child)
                image = base.asImage() if base is not None else None
                if image is not None:
                    image.SetImageAdaptionType("originNineSlice", (0.0, 0.0, 0.0, 0.0))

    def sync_layout(self):
        if self.closed:
            return False
        screen = self.game.GetScreenSize()
        if screen[0] <= 0 or screen[1] <= 0:
            return False
        for slot in SLOTS:
            canvas = self.GetBaseUIControl("/" + slot + "/canvas")
            if canvas is None:
                continue
            position = canvas.GetGlobalPosition()
            size = canvas.GetSize()
            rectangle = (2.0 * position[0] / screen[0] - 1.0,
                         1.0 - 2.0 * position[1] / screen[1],
                         2.0 * size[0] / screen[0], 2.0 * size[1] / screen[1])
            for suffix in ("", "_glyph"):
                self.actor.SetEntityUIExtraUniforms("pmanim_probe:" + slot + suffix, 3, rectangle)
            self.results[slot + "_rectangle"] = (position, size, screen, rectangle)
        return True

    def set_state(self, slot, progress, opacity, color):
        if self.closed or slot not in SLOTS:
            return False
        identifier = "pmanim_probe:" + slot
        first = self.actor.SetEntityUIExtraUniforms(identifier, 1,
            (float(progress), float(opacity), 0.0, 0.0))
        second = self.actor.SetEntityUIExtraUniforms(identifier, 2,
            (float(color[0]), float(color[1]), float(color[2]), 1.0))
        self.results[slot + "_uniforms"] = (first, second)
        return bool(first and second)

    def resize(self, slot, size, canvas_size=None):
        if self.closed or slot not in SLOTS:
            return False
        window = self.GetBaseUIControl("/" + slot)
        canvas = self.GetBaseUIControl("/" + slot + "/canvas")
        if window is None or canvas is None:
            return False
        window.SetSize((float(size[0]), float(size[1])))
        if canvas_size is not None:
            canvas.SetSize((float(canvas_size[0]), float(canvas_size[1])))
        self.sync_layout()
        return True

    def show_glyph(self, slot, seconds, opacity=1.0, aspect=1.7142857,
                   pixel_height=308.0, flip_y=False):
        if self.closed or slot not in SLOTS:
            return False
        base = self.GetBaseUIControl("/" + slot + "/canvas")
        doll = base.asNeteasePaperDoll() if base is not None else None
        if doll is None:
            return False
        identifier = "pmanim_probe:" + slot + "_glyph"
        rendered = doll.RenderEntity({"entity_identifier": identifier, "scale": 1.0,
            "render_depth": -15, "init_rot_x": 0.0, "init_rot_y": 0.0, "init_rot_z": 0.0})
        first = self.actor.SetEntityUIExtraUniforms(identifier, 1,
            (float(seconds), float(aspect), float(pixel_height), float(opacity)))
        second = self.actor.SetEntityUIExtraUniforms(identifier, 2,
            (1.0 if flip_y else 0.0, 0.0, 1.0, 0.0))
        self.sync_layout()
        return (rendered, first, second)

    def set_image(self, path, raw_path=False):
        control = self.GetBaseUIControl("/raw" if raw_path else "/normal")
        image = control.asImage() if control is not None else None
        if image is None or self.closed:
            return False
        image.SetSprite(path)
        return True

    def Destroy(self):
        self.closed = True
        for slot in SLOTS:
            self.actor.SetEntityUIExtraUniforms("pmanim_probe:" + slot, 1, (0.0, 0.0, 0.0, 0.0))
            self.actor.SetEntityUIExtraUniforms("pmanim_probe:" + slot + "_glyph", 1, (0.0, 0.0, 0.0, 0.0))
        self.actor = None
        self.game = None


def open_probe():
    existing = clientApi.GetUI(NAMESPACE, UI_KEY)
    if existing is not None:
        return existing
    clientApi.RegisterUI(NAMESPACE, UI_KEY, "manim_ui.canvas_probe.CanvasProbe",
                         NAMESPACE + ".main")
    return clientApi.CreateUI(NAMESPACE, UI_KEY, {"isHud": 0})


def close_probe():
    existing = clientApi.GetUI(NAMESPACE, UI_KEY)
    if existing is not None:
        existing.SetRemove()
