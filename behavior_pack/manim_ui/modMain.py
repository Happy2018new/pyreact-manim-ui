# -*- coding: utf-8 -*-
from mod.common.mod import Mod
import mod.client.extraClientApi as clientApi


@Mod.Binding(name="pyreact_manim_ui", version="0.3.0")
class ManimMod(object):
    @Mod.InitClient()
    def client_init(self):
        clientApi.RegisterSystem("pyreact_manim_ui", "player", "manim_ui.client.ManimClient")

    @Mod.DestroyClient()
    def client_destroy(self):
        pass
