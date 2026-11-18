# -*- coding: utf-8 -*-
from mod.common.mod import Mod
import mod.client.extraClientApi as api


@Mod.Binding(name='pmanim_stencil_large', version='0.1.0')
class LargeStencilMod(object):
    @Mod.InitClient()
    def init_client(self):
        api.RegisterSystem('pmanim_stencil_large', 'probe', 'stencil_large.runtime.ProbeSystem')
