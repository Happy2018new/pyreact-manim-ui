# -*- coding: utf-8 -*-
"""Two independent native UI canvases with explicit resource ownership.

Only the client thread may instantiate or call this module. Geometry resources
are compiled ahead of time; runtime_shapes uses live uniform parameters.
"""
import mod.client.extraClientApi as clientApi
from .timeline import finite_number, get_playback_clock
from .playback import PlaybackController

_SLOT_OWNERS = [None, None]
RUNTIME_SCENE = "runtime_shapes"


def _bounded(value, name, lower, upper=None):
    value = finite_number(value, name)
    if value < lower or (upper is not None and value > upper):
        raise ValueError(name + " is outside its supported range")
    return value


class CanvasRenderer(object):
    """PlaybackController renderer attached to one native paperdoll control.

    A slot belongs to one mounted canvas, across all scene switches. A third
    simultaneous canvas fails explicitly; detach/unmount returns its slot.
    """

    def __init__(self, scenes, actor=None, game=None):
        self.scene_names = frozenset(scene["name"] for scene in scenes)
        if actor is None or game is None:
            factory = clientApi.GetEngineCompFactory()
            actor = actor if actor is not None else factory.CreateActorRender(None)
            game = game if game is not None else factory.CreateGame(clientApi.GetLevelId())
        self.actor = actor
        self.game = game
        self.control = None
        self.doll = None
        self.slot = None
        self._identifiers = {}
        self._installed = set()
        self._uniforms = {}
        self._current = None
        self._enabled = False
        self._screen = None
        self._rectangle = None
        self._aspect = 1.0
        self._pixel_height = 1.0
        self._opacity = 1.0
        self._position = 0.0
        self._shape = (0.0, 1.0, 0.04, 0.8)
        self._shape_color = (0.25, 0.8, 1.0, 0.0)
        self._visibility_source = None
        self._geometry_source = None
        self._style_visible = None
        self._native_visible = None

    @property
    def ready(self):
        return self.control is not None and self._rectangle is not None

    def attach(self, control, visibility=None, geometry=None):
        if self.control is control:
            return True
        if self.control is not None:
            raise RuntimeError("One canvas player cannot be mounted in two controls")
        doll = control.asNeteasePaperDoll() if control is not None else None
        if doll is None:
            raise TypeError("Canvas requires a native NeteasePaperDoll control")
        free_slot = next((index for index, owner in enumerate(_SLOT_OWNERS) if owner is None), None)
        if free_slot is None:
            raise RuntimeError("Only two simultaneous Manim canvases are supported")
        _SLOT_OWNERS[free_slot] = self
        self.slot = free_slot
        self.control = control
        self.doll = doll
        self._visibility_source = visibility
        self._geometry_source = geometry
        self._style_visible = None
        self._native_visible = None
        self._identifiers = dict((name, "pmanim:canvas_%d_%s" % (free_slot, name))
                                 for name in self.scene_names)
        self.sync_visibility()
        return True

    def sync_visibility(self):
        """Merge content visibility with current Style.visible without an FFI get."""
        if self.control is None:
            return
        style_visible = bool(self._visibility_source()) if self._visibility_source else True
        # An empty paperdoll must remain available to native layout. In the
        # real engine a hidden control reports a zero size; hiding before the
        # first entity is installed would prevent it becoming ready forever.
        visible = bool(style_visible and
                       (self._current is None or (self._enabled and self.ready)))
        # Pyreact may have written its style visibility directly since our last
        # frame. A changed style must reapply the merged result, even when the
        # content is still hidden and its previous result was also False.
        if visible != self._native_visible or style_visible != self._style_visible:
            self.control.SetVisible(visible)
            self._native_visible = visible
        self._style_visible = style_visible

    def update_layout(self, opacity=1.0, refresh_screen=True):
        """Refresh only on layout/resize, never query screen metrics per tick."""
        if self.control is None:
            return False
        self._opacity = _bounded(opacity, "opacity", 0.0, 1.0)
        if refresh_screen or self._screen is None:
            size = self.game.GetScreenSize()
            view = self.game.GetScreenViewInfo()
            if size[0] <= 0 or size[1] <= 0:
                self._rectangle = None
                self.sync_visibility()
                return False
            self._screen = (float(size[0]), float(size[1]), float(view[1]) / size[1])
        geometry = self._geometry_source() if self._geometry_source else None
        if geometry is None:
            position = self.control.GetGlobalPosition()
            size = self.control.GetSize()
        else:
            position, size = geometry
        if size[0] <= 0 or size[1] <= 0:
            self._rectangle = None
            self.sync_visibility()
            return False
        width, height, pixel_scale = self._screen
        self._rectangle = (2.0 * position[0] / width - 1.0,
                           1.0 - 2.0 * position[1] / height,
                           2.0 * size[0] / width, 2.0 * size[1] / height)
        self._aspect = float(size[0]) / size[1]
        self._pixel_height = max(1.0, size[1] * pixel_scale)
        if self._current is not None:
            return self._draw(self._current, self._position)
        return True

    def _upload(self, identifier, index, value):
        key = (identifier, index)
        if self._uniforms.get(key) == value:
            return True
        if not self.actor.SetEntityUIExtraUniforms(identifier, index, value):
            return False
        self._uniforms[key] = value
        return True

    def install_scene(self, scene):
        name = scene.get("name")
        if not self.ready or name not in self._identifiers:
            return False, False
        reused = name in self._installed
        identifier = self._identifiers[name]
        if not self._upload(identifier, 1, (0.0, self._aspect, self._pixel_height, 0.0)):
            return False, reused
        self._installed.add(name)
        return True, reused

    def set_scene_visible(self, scene, enabled):
        name = scene.get("name")
        if name not in self._installed or self.control is None:
            return not enabled
        if not enabled:
            if self._current == name:
                self._enabled = False
                self.sync_visibility()
                # Hiding must not depend on a previous failed rectangle or
                # shape upload. Always target the opacity uniform directly.
                return self._upload(self._identifiers[name], 1,
                    (self._position, self._aspect, self._pixel_height, 0.0))
            return True
        identifier = self._identifiers[name]
        if self._current != name:
            if not self.doll.RenderEntity({"entity_identifier": identifier,
                    "scale": 1.0, "render_depth": -15,
                    "init_rot_x": 0.0, "init_rot_y": 0.0, "init_rot_z": 0.0}):
                return False
            self._current = name
        self._enabled = True
        return True

    def _draw(self, name, position):
        if not self.ready:
            return False
        identifier = self._identifiers[name]
        opacity = self._opacity if self._enabled else 0.0
        first = (float(position), self._aspect, self._pixel_height, opacity)
        second = self._shape if name == RUNTIME_SCENE else (0.0, 0.0, 1.0, 0.0)
        values = [(3, self._rectangle), (2, second)]
        if name == RUNTIME_SCENE:
            values.append((4, self._shape_color))
        # Make new visibility the last upload. A failed prerequisite cannot
        # reveal a frame with default rectangle/shape parameters.
        values.append((1, first))
        for index, value in values:
            if not self._upload(identifier, index, value):
                return False
        self._position = float(position)
        self.sync_visibility()
        return True

    def render_scene(self, scene, position):
        name = scene.get("name")
        if name != self._current or name not in self._installed:
            return False
        return self._draw(name, position)

    def set_shape(self, **changes):
        """Set live morph/progress/stroke_width/scale/color/rotation parameters.

        Rotation is radians. Stroke width and scale use the shader's local
        canvas coordinates. This changes uniforms; it never bakes new frames.
        """
        allowed = ("morph", "progress", "stroke_width", "scale", "color", "rotation")
        if any(name not in allowed for name in changes):
            raise ValueError("Unknown runtime shape parameter")
        shape = list(self._shape)
        color = list(self._shape_color)
        for index, name in enumerate(allowed[:4]):
            if name in changes:
                upper = 1.0 if name in ("morph", "progress") else None
                shape[index] = _bounded(changes[name], name, 0.0, upper)
        if shape[3] <= 0.0:
            raise ValueError("scale must be greater than zero")
        if "color" in changes:
            value = changes["color"]
            if not isinstance(value, (tuple, list)) or len(value) != 3:
                raise ValueError("color must contain three RGB components")
            color[:3] = [_bounded(component, "color", 0.0, 1.0) for component in value]
        if "rotation" in changes:
            color[3] = finite_number(changes["rotation"], "rotation")
        self._shape = tuple(shape)
        self._shape_color = tuple(color)
        if self._current == RUNTIME_SCENE:
            return self._draw(RUNTIME_SCENE, self._position)
        return True

    def shape_snapshot(self):
        return {"morph": self._shape[0], "progress": self._shape[1],
                "stroke_width": self._shape[2], "scale": self._shape[3],
                "color": self._shape_color[:3], "rotation": self._shape_color[3]}

    def detach(self):
        if self.slot is None:
            return
        self.control.SetVisible(False)
        for name in self._installed:
            identifier = self._identifiers[name]
            self.actor.SetEntityUIExtraUniforms(identifier, 1, (0.0, 1.0, 1.0, 0.0))
        if _SLOT_OWNERS[self.slot] is self:
            _SLOT_OWNERS[self.slot] = None
        self.slot = None
        self.control = None
        self.doll = None
        self._current = None
        self._enabled = False
        self._rectangle = None
        self._screen = None
        self._identifiers.clear()
        self._installed.clear()
        self._uniforms.clear()
        self._visibility_source = None
        self._geometry_source = None
        self._style_visible = None
        self._native_visible = None

    def release_scenes(self):
        self.detach()


def create_canvas_player(scenes=None, clock=None):
    """Create an unmounted business player; ManimCanvas attaches its renderer."""
    if scenes is None:
        from .generated_canvas import CANVAS_SCENES
        scenes = CANVAS_SCENES
    scenes = tuple(scenes)
    if clock is None:
        clock = get_playback_clock(platform=clientApi.GetPlatform())
    return PlaybackController(scenes, CanvasRenderer(scenes), clock)
