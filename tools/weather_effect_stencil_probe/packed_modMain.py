# -*- coding: utf-8 -*-
from mod.common.mod import Mod
import mod.client.extraClientApi as api


@Mod.Binding(name='pmanim_stencil_packed',version='0.1.0')
class PackedStencilMod(object):
    @Mod.InitClient()
    def init_client(self):
        api.RegisterSystem('pmanim_stencil_packed','probe','stencil_packed.runtime.ProbeSystem')

    @Mod.DestroyClient()
    def destroy_client(self):
        pass
