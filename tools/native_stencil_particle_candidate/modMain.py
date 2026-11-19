# -*- coding: utf-8 -*-
from mod.common.mod import Mod


@Mod.Binding(name='pmanim_stencil_integrated', version='0.1.0')
class ParticleCandidateMod(object):
    @Mod.InitClient()
    def init_client(self):
        import mod.client.extraClientApi as api
        api.RegisterSystem('pmanim_stencil_integrated', 'probe',
                           'stencil_large.particle_candidate_runtime.ProbeSystem')
