# -*- coding: utf-8 -*-
from mod.common.mod import Mod
import mod.client.extraClientApi as api


@Mod.Binding(name='pmanim_weather_effect_stencil',version='0.1.0')
class WeatherStencilMod(object):
    @Mod.InitClient()
    def init_client(self):
        api.RegisterSystem('pmanim_weather_effect_stencil','probe','weather_effect_stencil_probe.runtime.ProbeSystem')

    @Mod.DestroyClient()
    def destroy_client(self):
        pass
