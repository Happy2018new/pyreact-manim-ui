# -*- coding: utf-8 -*-
from mod.common.mod import Mod
import mod.client.extraClientApi as api


@Mod.Binding(name="pmanim_packet_probe", version="0.1.0")
class PacketMod(object):
    @Mod.InitClient()
    def init_client(self):
        api.RegisterSystem("pmanim_packet_probe", "probe", "packet_probe.runtime.ProbeSystem")

    @Mod.DestroyClient()
    def destroy_client(self):
        pass
