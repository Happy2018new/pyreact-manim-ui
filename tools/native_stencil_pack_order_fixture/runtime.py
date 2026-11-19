# -*- coding: utf-8 -*-
"""Passive ordinary JSON UI canary, explicitly created by the owned runner."""
import mod.client.extraClientApi as api


class PackOrderCanary(api.GetScreenNodeCls()):
    def __init__(self, namespace, name, params):
        api.GetScreenNodeCls().__init__(self, namespace, name, params)
        self.ready, self.receipt = False, {}

    def Create(self):
        self.ready = True

    def configure(self, visible, physical, position):
        if not self.ready:
            raise RuntimeError('Canary UI Create has not completed')
        game = api.GetEngineCompFactory().CreateGame(api.GetLevelId())
        logical = game.GetScreenSize()
        scale = (float(logical[0])/physical[0], float(logical[1])/physical[1])
        if min(scale) <= 0.:
            raise RuntimeError('Canary UI logical scale is invalid')
        root = self.GetBaseUIControl('/canary')
        root.SetPosition((position[0]*scale[0], position[1]*scale[1]))
        root.SetSize((64.*scale[0], 32.*scale[1]))
        for index in range(4):
            patch = self.GetBaseUIControl('/canary/patch%d' % index)
            patch.SetPosition((16.*index*scale[0], 0.))
            patch.SetSize((16.*scale[0], 32.*scale[1]))
        root.SetVisible(bool(visible), False)
        self.UpdateScreen(True)
        self.receipt = {'ready': self.ready, 'requested_visible': bool(visible),
            'actual_visible': root.GetVisible(), 'position': list(position), 'size': [64, 32],
            'physical': list(physical), 'logical': list(logical), 'scale': list(scale),
            'native_json_ui': True, 'clipping': False, 'custom_materials': False,
            'runtime_file_writes': False, 'input_sent': False}
        return self.snapshot()

    def snapshot(self):
        return dict(self.receipt)
