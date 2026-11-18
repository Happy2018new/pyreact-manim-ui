# -*- coding: utf-8 -*-
from mod.common.mod import Mod
import mod.client.extraClientApi as api


@Mod.Binding(name='pmanim_stencil_integrated', version='0.1.0')
class IntegratedStencilMod(object):
    @Mod.InitClient()
    def init_client(self):
        api.RegisterSystem('pmanim_stencil_integrated', 'probe', 'stencil_large.integrated_runtime.ProbeSystem')
