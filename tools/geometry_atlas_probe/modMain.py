# -*- coding: utf-8 -*-
from mod.common.mod import Mod
import mod.client.extraClientApi as api


@Mod.Binding(name='pmanim_geometry_atlas_probe',version='0.1.0')
class GeometryAtlasMod(object):
    @Mod.InitClient()
    def init_client(self):
        api.RegisterSystem('pmanim_geometry_atlas_probe','probe','geometry_atlas_probe.runtime.ProbeSystem')

    @Mod.DestroyClient()
    def destroy_client(self):
        pass
