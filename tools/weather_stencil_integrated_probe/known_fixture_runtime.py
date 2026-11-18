# -*- coding: utf-8 -*-
"""Controlled native draw before the stencil carrier's layer-13 RGB blend."""


class KnownFixture(object):
    def __init__(self, probe):
        self.probe = probe
        self.effect = None
        self.control = None
        self.visible = False
        self.varying_alpha = None
        self.roi = None

    def _create(self):
        position = self.probe.camera.GetPosition()
        direction = self.probe.camera.GetForward()
        if position is None or direction is None:
            raise RuntimeError('Prepare the stationary probe camera before the RGBA fixture')
        anchor = tuple(position[i] + direction[i]*4. for i in range(3))
        self.effect = self.probe.CreateEngineSfxFromEditor(
            'effects/stencil_integrated_known_fixture.json', anchor, (0., 0., 0.), (4., 4., 4.))
        if self.effect is None:
            raise RuntimeError('Native layer-12 RGBA fixture was rejected')
        self.control = self.probe.factory.CreateFrameAniControl(self.effect)
        if not (self.control.SetFaceCamera(True) and self.control.SetLoop(True)
                and self.control.SetLayer(12) and self.control.Stop()):
            raise RuntimeError('Native layer-12 RGBA fixture controls were rejected')

    def configure(self, enabled, varying_alpha=True):
        if not enabled:
            if self.visible and not self.control.Stop():
                raise RuntimeError('Native layer-12 fixture stop was rejected')
            self.visible = False
            return self.snapshot()

        viewport = self.probe.viewport
        roi = self.probe.roi
        if (min(viewport) < 1 or max(viewport) > 4095 or min(roi) < 0
                or max(roi) > 4095 or min(roi[2:]) < 1):
            raise ValueError('Native layer-12 fixture requires a valid viewport and source ROI')
        if self.control is None:
            self._create()
        pairs = (viewport, roi[:2], roi[2:])
        packed = tuple((first*4096+second)/16777216. for first, second in pairs)
        mix = packed + (.75 if varying_alpha else .25,)
        if not self.control.SetMixColor(mix) or (not self.visible and not self.control.Play()):
            raise RuntimeError('Native layer-12 fixture mode was rejected')
        self.visible = True
        self.varying_alpha = bool(varying_alpha)
        self.roi = list(roi)
        return self.snapshot()

    def snapshot(self):
        return {'layer': 12, 'entity': self.effect, 'visible': self.visible,
                'varying_alpha': self.varying_alpha, 'roi': self.roi}

    def destroy(self):
        if self.control is not None:
            self.control.Stop()
        if self.effect is not None:
            self.probe.DestroyEntity(self.effect)
        self.effect = self.control = None
        self.visible = False
