# -*- coding: utf-8 -*-
"""Page-owned image controls, also callable by SDK acceptance checks."""
import math
from . import create_image_controller, IMAGES
from ..timeline import finite_number


_IMAGE_ORDER = ("aurora", "sunrise", "prism")
_FITS = ("contain", "cover", "fill")
_EFFECTS = ("none", "wave", "swirl")
_FULL_CROP = (0.0, 0.0, 1.0, 1.0)
_DETAIL_CROP = (0.15, 0.15, 0.7, 0.7)
_DEFAULTS = {"fit": "contain", "scale": (1.0, 1.0), "rotation": 0.0,
             "flip_x": False, "flip_y": False, "crop": _FULL_CROP,
             "opacity": 1.0, "effect": "none", "strength": 0.75}


class ImageDemo(object):
    """Keep one editable image and one independently rendered original."""
    def __init__(self, factory=create_image_controller):
        self.names = tuple(name for name in _IMAGE_ORDER if name in IMAGES)
        self.names += tuple(sorted(name for name in IMAGES if name not in _IMAGE_ORDER))
        if not self.names:
            raise ValueError("Image demo requires at least one bundled image")
        self.disposed = False
        self._listeners = []
        self.primary = factory(src=self.names[0], **_DEFAULTS)
        self.original = factory(src=self.names[0])
        self._cancel_primary = self.primary.subscribe(self._receive)
        self._cancel_original = self.original.subscribe(self._receive)

    def snapshot(self):
        primary = self.primary.snapshot()
        original = self.original.snapshot()
        source = primary["config"]["src"]
        image = IMAGES[source]
        return {"primary": primary, "original": original,
                "config": primary["config"], "title": image["title"],
                "size": image["size"], "index": self.names.index(source),
                "total": len(self.names), "disposed": self.disposed,
                "error": primary["error"] or original["error"],
                "ready": {"primary": primary["ready"],
                          "original": original["ready"]}}

    def _receive(self, _state):
        if self.disposed or not self._listeners:
            return
        state = self.snapshot()
        for callback in tuple(self._listeners):
            callback(state)

    def subscribe(self, callback):
        if not self.disposed and callback not in self._listeners:
            self._listeners.append(callback)
        def unsubscribe():
            if callback in self._listeners:
                self._listeners.remove(callback)
        return unsubscribe

    def on_ready(self, _controller):
        self._receive(None)

    def apply(self, **changes):
        """Configure the editable image; source selection also updates comparison."""
        if self.disposed:
            return False
        if "src" in changes and changes["src"] not in self.names:
            raise ValueError("Unknown demo image")
        result = self.primary.configure(**changes)
        if "src" in changes:
            result = self.original.configure(src=changes["src"]) and result
        return result

    def select_image(self, step):
        state = self.snapshot()
        return self.apply(src=self.names[(state["index"] + int(step)) % len(self.names)])

    def cycle_fit(self):
        current = self.primary.snapshot()["config"]["fit"]
        return self.apply(fit=_FITS[(_FITS.index(current) + 1) % len(_FITS)])

    def cycle_effect(self):
        current = self.primary.snapshot()["config"]["effect"]
        effect = _EFFECTS[(_EFFECTS.index(current) + 1) % len(_EFFECTS)]
        if effect != "wave":
            self.primary.pause()
        return self.apply(effect=effect)

    def set_parameter(self, name, value):
        """Slider values are normalized; direct apply uses public image units."""
        ratio = max(0.0, min(1.0, finite_number(value, name)))
        if name == "rotation":
            return self.apply(rotation=(ratio * 2.0 - 1.0) * math.pi)
        if name in ("scale_x", "scale_y"):
            scale = list(self.primary.snapshot()["config"]["scale"])
            scale[0 if name == "scale_x" else 1] = 0.25 + ratio * 1.75
            return self.apply(scale=tuple(scale))
        if name == "opacity":
            return self.apply(opacity=ratio)
        if name == "strength":
            return self.apply(strength=ratio * 2.0 - 1.0)
        raise ValueError("Unknown image demo parameter")

    def toggle_flip_x(self):
        return self.apply(flip_x=not self.primary.snapshot()["config"]["flip_x"])

    def toggle_flip_y(self):
        return self.apply(flip_y=not self.primary.snapshot()["config"]["flip_y"])

    def toggle_crop(self):
        crop = self.primary.snapshot()["config"]["crop"]
        return self.apply(crop=_DETAIL_CROP if crop == _FULL_CROP else _FULL_CROP)

    def toggle_animation(self):
        if self.disposed:
            return False
        state = self.primary.snapshot()
        if state["playing"]:
            return self.primary.pause()
        config = state["config"]
        self.apply(effect="wave", strength=config["strength"] or _DEFAULTS["strength"])
        return self.primary.play()

    def seek(self, seconds):
        if self.disposed:
            return False
        return self.primary.seek(seconds)

    def reset(self):
        """Restore the selected image without changing its source."""
        if self.disposed:
            return False
        self.primary.pause()
        self.primary.seek(0.0)
        return self.apply(**_DEFAULTS)

    def dispose(self):
        if self.disposed:
            return
        self.disposed = True
        self._cancel_primary()
        self._cancel_original()
        self._listeners = []
        self.primary.dispose()
        self.original.dispose()
