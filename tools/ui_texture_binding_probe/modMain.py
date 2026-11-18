# -*- coding: utf-8 -*-
from mod.common.mod import Mod
import mod.client.extraClientApi as api


@Mod.Binding(name='pmanim_ui_texture_probe',version='0.1.0')
class TextureProbeMod(object):
    @Mod.InitClient()
    def init_client(self):
        api.RegisterSystem('pmanim_ui_texture_probe','probe','ui_texture_binding_probe.runtime.ProbeSystem')

    @Mod.DestroyClient()
    def destroy_client(self):
        pass
