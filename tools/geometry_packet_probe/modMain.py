# -*- coding: utf-8 -*-
from mod.common.mod import Mod
import mod.client.extraClientApi as api


@Mod.Binding(name="pmanim_geometry_packet_probe", version="0.1.0")
class GeometryPacketMod(object):
    @Mod.InitClient()
    def init_client(self):
        api.RegisterSystem("pmanim_geometry_packet_probe", "probe",
                           "geometry_packet_probe.runtime.ProbeSystem")

    @Mod.DestroyClient()
    def destroy_client(self):
        pass
