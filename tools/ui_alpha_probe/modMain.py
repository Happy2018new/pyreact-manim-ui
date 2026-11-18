# -*- coding: utf-8 -*-
from mod.common.mod import Mod
import mod.client.extraClientApi as api


@Mod.Binding(name='pmanim_ui_alpha_probe', version='0.1.0')
class AlphaMod(object):
    @Mod.InitClient()
    def init_client(self):
        api.RegisterSystem('pmanim_ui_alpha_probe','probe','ui_alpha_probe.runtime.ProbeSystem')

    @Mod.DestroyClient()
    def destroy_client(self):
        pass
