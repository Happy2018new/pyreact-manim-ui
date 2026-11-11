# -*- coding: utf-8 -*-
"""Registered PNG shader images for client-side Pyreact UI."""
import mod.client.extraClientApi as clientApi
from ..timeline import get_playback_clock
from .generated import IMAGES, SLOT_COUNT
from .model import ImageController
from .renderer import ImageRenderer
from .primitive import ShaderImage


def create_image_controller(src="aurora", clock=None, **config):
    """Create an unmounted image; use ShaderImage to own its native control."""
    config["src"] = src
    if clock is None:
        clock = get_playback_clock(platform=clientApi.GetPlatform())
    return ImageController(IMAGES, ImageRenderer(IMAGES), clock, **config)
