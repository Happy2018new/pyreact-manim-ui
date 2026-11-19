# -*- coding: utf-8 -*-
"""Loader entry only; the owner explicitly registers and creates the canary."""
from mod.common.mod import Mod


@Mod.Binding(name='pmanim_pack_order_fixture', version='1.0.1')
class PackOrderFixtureEntry(object):
    @Mod.InitClient()
    def client_init(self):
        # Keep the client-only ScreenNode import inside the client lifecycle.
        from pmanim_pack_order_fixture.runtime import PackOrderCanary
        self.canary_class = PackOrderCanary

    @Mod.DestroyClient()
    def client_destroy(self):
        self.canary_class = None
