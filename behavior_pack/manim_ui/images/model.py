# -*- coding: utf-8 -*-
"""Validated image parameters and client-owned controller, without SDK imports."""
import math
import traceback
from ..timeline import finite_number


DEFAULT_CONFIG = {
    "src": "aurora", "fit": "contain", "scale": (1.0, 1.0),
    "rotation": 0.0, "flip_x": False, "flip_y": False,
    "crop": (0.0, 0.0, 1.0, 1.0), "opacity": 1.0,
    "effect": "none", "strength": 0.15,
}
EFFECT_MODES = {"none": 0.0, "wave": 1.0, "swirl": 2.0}


def bounded(value, name, lower, upper):
    value = finite_number(value, name)
    if value < lower or value > upper:
        raise ValueError(name + " is outside its supported range")
    return value


def _components(value, name, length):
    if not isinstance(value, (tuple, list)) or len(value) != length:
        raise ValueError(name + " must contain %d components" % length)
    return tuple(finite_number(item, name) for item in value)


def validate_config(previous, changes, images):
    """Build a complete candidate before any accepted state or GPU is changed."""
    if any(name not in DEFAULT_CONFIG for name in changes):
        raise ValueError("Unknown ShaderImage parameter")
    candidate = dict(previous)
    candidate.update(changes)
    if candidate["src"] not in tuple(images):
        raise ValueError("Unknown registered image: " + str(candidate["src"]))
    if candidate["fit"] not in ("fill", "contain", "cover"):
        raise ValueError("fit must be fill, contain or cover")
    scale = _components(candidate["scale"], "scale", 2)
    if min(scale) < 0.0001 or max(scale) > 10000.0:
        raise ValueError("scale components must be in [0.0001, 10000]; use flip_x/flip_y")
    candidate["scale"] = scale
    candidate["rotation"] = finite_number(candidate["rotation"], "rotation")
    for name in ("flip_x", "flip_y"):
        if not isinstance(candidate[name], bool):
            raise ValueError(name + " must be a boolean")
    crop = _components(candidate["crop"], "crop", 4)
    if (min(crop) < 0.0 or crop[2] < 0.000001 or crop[3] < 0.000001 or
            crop[0] + crop[2] > 1.0 or crop[1] + crop[3] > 1.0):
        raise ValueError("crop must be inside normalized image UV with width/height >= 0.000001")
    candidate["crop"] = crop
    candidate["opacity"] = bounded(candidate["opacity"], "opacity", 0.0, 1.0)
    if candidate["effect"] not in tuple(EFFECT_MODES):
        raise ValueError("effect must be none, wave or swirl")
    candidate["strength"] = bounded(candidate["strength"], "strength", -1.0, 1.0)
    return candidate


def image_uniforms(config, image, canvas_aspect):
    """Return signed display dimensions and the cropped atlas UV rectangle.

    Display dimensions use canvas-height units. Fit happens before independent
    scale, flips and rotation; the shader clips the result to the canvas.
    """
    crop = config["crop"]
    source_aspect = float(image["size"][0]) * crop[2] / (image["size"][1] * crop[3])
    width, height = canvas_aspect, 1.0
    fit = config["fit"]
    if fit != "fill":
        wider = source_aspect > canvas_aspect
        if (fit == "contain" and wider) or (fit == "cover" and not wider):
            height = canvas_aspect / source_aspect
        else:
            width = source_aspect
    width *= config["scale"][0] * (-1.0 if config["flip_x"] else 1.0)
    height *= config["scale"][1] * (-1.0 if config["flip_y"] else 1.0)
    atlas = image["uv"]
    uv = (atlas[0] + atlas[2] * crop[0], atlas[1] + atlas[3] * crop[1],
          atlas[2] * crop[2], atlas[3] * crop[3])
    rotation = math.fmod(config["rotation"], 2.0 * math.pi)
    return (width, height, rotation, config["strength"]), uv


class ImageController(object):
    """One image's config, wave clock and lifetime; all calls use client thread.

    Configuration is valid before mount. Unmount pauses and releases the slot;
    dispose permanently ends the controller. A failed native operation hides
    the image until explicit configure/play/seek/reset/retry or a new mount.
    """
    def __init__(self, images, renderer, clock, **config):
        self.images = images
        self.renderer = renderer
        self._clock = clock
        self._config = validate_config(DEFAULT_CONFIG, config, images)
        self._initial_config = dict(self._config)
        self.time = 0.0
        self.playing = False
        self.visible = False
        self.error = ""
        self.disposed = False
        self._anchor_time = 0.0
        self._anchor_position = 0.0
        self._subscribers = []
        self._mount_cleanup = None

    def _animated(self):
        return self._config["effect"] == "wave" and self._config["strength"] != 0.0

    def _sample(self, now):
        if self.playing and self._animated():
            self.time = self._anchor_position + max(0.0, now - self._anchor_time)

    def _anchor(self, now):
        self._anchor_position = self.time
        self._anchor_time = now

    def mount(self, control, visibility=None, geometry=None):
        if self.disposed:
            raise RuntimeError("A disposed image controller cannot be mounted")
        self.renderer.attach(control, visibility, geometry)
        self.error = ""
        self._anchor(self._clock())
        self.notify()
        return True

    def update_layout(self, opacity=1.0):
        if self.disposed:
            return False
        if not self.renderer.update_layout(opacity):
            self.visible = False
            if self.renderer.last_error:
                return self._fail(self.renderer.last_error)
            return False
        # A resize may refresh geometry after failure, but never retries the GPU.
        return self._render()

    def _render(self, retry=False):
        if retry:
            self.error = ""
        if self.error:
            return False
        if not self.renderer.ready:
            return True
        if not self.renderer.draw(self._config, self.time):
            return self._fail(self.renderer.last_error or
                              "ShaderImage render or shader parameter update failed")
        self.visible = True
        return True

    def _fail(self, message):
        self.playing = False
        self.visible = False
        self.error = message
        self.renderer.hide()
        print("[manim-ui] " + message)
        self.notify()
        return False

    def configure(self, **changes):
        if self.disposed:
            return False
        candidate = validate_config(self._config, changes, self.images)
        now = self._clock()
        self._sample(now)
        self._config = candidate
        self._anchor(now)
        success = self._render(retry=True)
        self.notify()
        return success

    def play(self):
        if self.disposed:
            return False
        now = self._clock()
        self._sample(now)
        if not self._render(retry=True):
            return False
        self.playing = True
        self._anchor(now)
        self.notify()
        return True

    def pause(self):
        if self.disposed:
            return False
        self._sample(self._clock())
        self.playing = False
        success = self._render()
        self.notify()
        return success

    def toggle_play(self):
        return self.pause() if self.playing else self.play()

    def seek(self, seconds):
        if self.disposed:
            return False
        seconds = finite_number(seconds, "time")
        if seconds < 0.0:
            raise ValueError("time must be nonnegative")
        self.time = seconds
        self.playing = False
        self._anchor(self._clock())
        success = self._render(retry=True)
        self.notify()
        return success

    def reset(self):
        if self.disposed:
            return False
        self._config = dict(self._initial_config)
        self.time = 0.0
        self.playing = False
        self._anchor(self._clock())
        success = self._render(retry=True)
        self.notify()
        return success

    def retry(self):
        if self.disposed:
            return False
        success = self._render(retry=True)
        self.notify()
        return success

    def frame(self):
        if self.disposed:
            return
        if not self.renderer.sync_visibility():
            self._fail(self.renderer.last_error)
            return
        if self.error or not self.renderer.ready or not self.playing or not self._animated():
            return
        self._sample(self._clock())
        self._render()
        # The UI observes discrete edits, not a new layout tree each wave frame.

    def snapshot(self):
        return {"config": dict(self._config), "time": self.time,
                "playing": self.playing, "ready": self.renderer.ready,
                "mounted": self.renderer.control is not None,
                "visible": self.visible, "error": self.error, "disposed": self.disposed}

    def subscribe(self, callback):
        if not callable(callback):
            raise TypeError("subscriber must be callable")
        entry = [callback]
        if not self.disposed:
            self._subscribers.append(entry)
        def unsubscribe():
            for index, item in enumerate(self._subscribers):
                if item is entry:
                    del self._subscribers[index]
                    break
        return unsubscribe

    def notify(self):
        if self.disposed:
            return
        for entry in tuple(self._subscribers):
            if self.disposed:
                break
            try:
                entry[0](self.snapshot())
            except Exception:
                # Infrastructure boundary: one observer cannot block cleanup.
                traceback.print_exc()

    def unmount(self):
        self._sample(self._clock())
        self.playing = False
        self.visible = False
        cleanup = self._mount_cleanup
        self._mount_cleanup = None
        if cleanup is not None:
            cleanup()
        self.renderer.detach()
        self.notify()

    def dispose(self):
        if self.disposed:
            return False
        # Teardown observers cannot recursively dispose or remount this owner.
        self.disposed = True
        self.unmount()
        self._subscribers = []
        return True
