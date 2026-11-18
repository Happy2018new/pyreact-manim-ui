# -*- coding: utf-8 -*-
from mod.common.mod import Mod
import mod.client.extraClientApi as api


@Mod.Binding(name='pmanim_weather_effect_order',version='0.1.0')
class WeatherEffectOrderMod(object):
    @Mod.InitClient()
    def init_client(self):
        api.RegisterSystem('pmanim_weather_effect_order','probe','weather_effect_order_probe.runtime.ProbeSystem')

    @Mod.DestroyClient()
    def destroy_client(self):
        pass
