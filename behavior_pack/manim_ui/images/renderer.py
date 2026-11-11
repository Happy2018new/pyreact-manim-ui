# -*- coding: utf-8 -*-
"""Four independent atlas-backed native UI image renderers (client thread)."""
import traceback
import mod.client.extraClientApi as clientApi
from .generated import SLOT_COUNT
from .model import bounded, image_uniforms, EFFECT_MODES


_SLOT_OWNERS = [None] * SLOT_COUNT


class ImageRenderer(object):
    def __init__(self, images, actor=None, game=None):
        if actor is None or game is None:
            factory = clientApi.GetEngineCompFactory()
            actor = actor if actor is not None else factory.CreateActorRender(None)
            game = game if game is not None else factory.CreateGame(clientApi.GetLevelId())
        self.images = images
        self.actor = actor
        self.game = game
        self.control = None
        self.doll = None
        self.slot = None
        self.identifier = None
        self.last_error = ""
        self._uniforms = {}
        self._rectangle = None
        self._aspect = 1.0
        self._opacity = 1.0
        self._installed = False
        self._attempted = False
        self._enabled = False
        self._visibility_source = None
        self._geometry_source = None
        self._style_visible = None
        self._native_visible = None

    @property
    def ready(self):
        return self.control is not None and self._rectangle is not None

    def attach(self, control, visibility=None, geometry=None):
        if self.control is control and control is not None:
            return True
        if self.control is not None:
            raise RuntimeError("One ShaderImage controller cannot mount in two controls")
        doll = control.asNeteasePaperDoll() if control is not None else None
        if doll is None:
            raise TypeError("ShaderImage requires a native NeteasePaperDoll control")
        slot = next((index for index, owner in enumerate(_SLOT_OWNERS) if owner is None), None)
        if slot is None:
            raise RuntimeError("Only four simultaneous ShaderImage instances are supported")
        _SLOT_OWNERS[slot] = self
        self.slot = slot
        self.identifier = "pmanim:image_%d" % slot
        self.control = control
        self.doll = doll
        self._visibility_source = visibility
        self._geometry_source = geometry
        self.sync_visibility()
        return True

    def sync_visibility(self):
        if self.control is None:
            return True
        style_visible = bool(self._visibility_source()) if self._visibility_source else True
        # Keep an empty control measurable until its first installation attempt.
        visible = bool(style_visible and (not self._attempted or (self._enabled and self.ready)))
        if visible != self._native_visible or style_visible != self._style_visible:
            result = self._native_call(self.control.SetVisible, visible)
            # Even a stale native control must not be called again every frame.
            self._native_visible = visible
            self._style_visible = style_visible
            return result is not False
        self._style_visible = style_visible
        return True

    def _native_call(self, callback, *args):
        try:
            return callback(*args)
        except Exception as error:
            # Native controls may already be removed when Pyreact unmounts.
            # Keep the traceback and convert SDK failures into controller state.
            self.last_error = "ShaderImage native API failed: " + str(error)
            traceback.print_exc()
            return False

    def update_layout(self, opacity=1.0):
        opacity = bounded(opacity, "layout opacity", 0.0, 1.0)
        if self.control is None:
            return False
        self.last_error = ""
        self._opacity = opacity
        screen = self._native_call(self.game.GetScreenSize)
        if not screen:
            return False
        geometry = self._native_call(self._geometry_source) if self._geometry_source else None
        if geometry is False:
            return False
        if geometry is None:
            position = self._native_call(self.control.GetGlobalPosition)
            size = self._native_call(self.control.GetSize)
            if position is False or size is False:
                return False
        else:
            position, size = geometry
        if min(screen[:2]) <= 0 or min(size[:2]) <= 0:
            self._rectangle = None
            self.sync_visibility()
            return False
        width, height = float(screen[0]), float(screen[1])
        self._rectangle = (2.0 * position[0] / width - 1.0,
                           1.0 - 2.0 * position[1] / height,
                           2.0 * size[0] / width, 2.0 * size[1] / height)
        self._aspect = float(size[0]) / size[1]
        return True

    def _upload(self, index, value):
        if self._uniforms.get(index) == value:
            return True
        if not self._native_call(self.actor.SetEntityUIExtraUniforms, self.identifier, index, value):
            if not self.last_error:
                self.last_error = "ShaderImage uniform %d update failed" % index
            return False
        self._uniforms[index] = value
        return True

    def draw(self, config, position):
        if not self.ready:
            return False
        self.last_error = ""
        self._attempted = True
        mode = EFFECT_MODES[config["effect"]]
        # Wave is exactly one-second periodic. Preserve full controller time
        # while keeping the shader phase precise during long playback/seeks.
        position = float(position) % 1.0 if config["effect"] == "wave" else 0.0
        second, fourth = image_uniforms(config, self.images[config["src"]], self._aspect)
        if not self._installed:
            self._enabled = False
            if not self.sync_visibility():
                return False
            if not self._upload(1, (position, self._aspect, 0.0, mode)):
                return False
        for index, value in ((3, self._rectangle), (2, second), (4, fourth)):
            if not self._upload(index, value):
                return False
        if not self._installed:
            if not self._native_call(self.doll.RenderEntity, {"entity_identifier": self.identifier,
                    "scale": 1.0, "render_depth": -15,
                    "init_rot_x": 0.0, "init_rot_y": 0.0, "init_rot_z": 0.0}):
                if not self.last_error:
                    self.last_error = "ShaderImage RenderEntity failed"
                return False
            self._installed = True
        # Reveal only after all prerequisite values and the entity succeeded.
        first = (position, self._aspect, self._opacity * config["opacity"], mode)
        if not self._upload(1, first):
            return False
        self._enabled = True
        return self.sync_visibility()

    def hide(self):
        if self.control is None:
            return
        self._attempted = True
        self._enabled = False
        self.sync_visibility()
        first = self._uniforms.get(1, (0.0, self._aspect, 0.0, 0.0))
        # Physical visibility remains authoritative if the GPU API itself fails.
        self._upload(1, (first[0], first[1], 0.0, first[3]))

    def detach(self):
        if self.slot is None:
            return
        try:
            self.hide()
        finally:
            if _SLOT_OWNERS[self.slot] is self:
                _SLOT_OWNERS[self.slot] = None
            self.slot = None
            self.identifier = None
            self.control = None
            self.doll = None
            self._uniforms.clear()
            self._rectangle = None
            self._installed = False
            self._attempted = False
            self._enabled = False
            self._visibility_source = None
            self._geometry_source = None
            self._style_visible = None
            self._native_visible = None
