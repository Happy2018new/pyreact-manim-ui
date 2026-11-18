# -*- coding: utf-8 -*-
"""Client-only transparent-geometry controls over the frozen static codec."""
import math
from geometry_atlas_probe.scene_runtime import ProbeSystem as SceneProbe
from geometry_atlas_probe.rain_config import SOURCE_BUNDLE_SHA256


class ProbeSystem(SceneProbe):
    def __init__(self, namespace, system_name):
        self.transparency_receipts = []
        self.transparent_requested = False
        self.transparent_amount_requested = None
        SceneProbe.__init__(self, namespace, system_name)

    def set_transparent(self, enabled, amount=1.0):
        self._require_idle_controls()
        amount = float(amount)
        if math.isnan(amount) or math.isinf(amount) or not 0. <= amount <= 1.:
            raise ValueError('Transparent amount must be finite and within0..1')
        if not self.geometry_name or self.logical_bytes != 65536:
            if not self.code_domain:
                raise RuntimeError('Need a loaded payload or the known-color domain')
        enabled = bool(enabled)
        receipt = {'geometry_name': self.geometry_name, 'entity': self.entity,
                   'enabled': enabled, 'amount': amount, 'amount_setter_called': enabled,
                   'render_event': self.render_event,
                   'EnableActorBlockGeometryTransparent': bool(
                       self.render.EnableActorBlockGeometryTransparent(self.geometry_name, enabled))}
        if enabled:
            receipt['SetActorBlockGeometryTransparency'] = bool(
                self.render.SetActorBlockGeometryTransparency(self.geometry_name, amount))
            self.transparent_amount_requested = amount
        self.transparency_receipts.append(receipt)
        self.transparent_requested = enabled
        if not receipt['EnableActorBlockGeometryTransparent'] or (enabled and not receipt['SetActorBlockGeometryTransparency']):
            raise RuntimeError('Transparent geometry setter rejected; do not replay automatically')
        return self.snapshot()

    def snapshot(self):
        result = SceneProbe.snapshot(self)
        result.update(source_bundle_sha256=SOURCE_BUNDLE_SHA256,
                      rain_camera_origin=list(getattr(self, 'rain_origin', [])),
                      transparent_requested=self.transparent_requested,
                      transparent_amount_requested=self.transparent_amount_requested,
                      transparency_receipts=list(self.transparency_receipts),
                      native_post_order=list(self.post.GetPostProcessOrder() or []))
        result['actual_post_states'] = [(name, bool(self.post.CheckEnabledByName(name)))
                                        for name in result['native_post_order']]
        result['native_reported_enabled'] = [name for name, enabled in result['actual_post_states']
                                             if enabled and not name.startswith('scene_codec_')]
        return result

    def rain_inspect(self, mode, count):
        self._require_idle_controls()
        if mode not in (11, 12, 20, 23, 24, 25) or not 1 <= count <= self.codec_roi[2]*self.codec_roi[3]:
            raise ValueError('Invalid rain diagnostic query')
        self._params('scene_codec_inspect', mode, 0, count)
        for name, enabled in (('scene_codec_consumer', False), ('scene_codec_diagnostic', False),
                              ('scene_codec_inspect', True)):
            if not self.post.SetEnableByName(name, enabled):
                raise RuntimeError('Rain inspect selection rejected')
        self.query_value = [0, count, mode, 0]
        return self.snapshot()

    def quiesce(self):
        self.set_native_writer_visible(False)
        if self.background_name is not None:
            self.set_background_visible(False)
        for name in self.codec_processes:
            # Disabling the last active custom process can reset the chain.
            # Read membership again before each setter, rather than mutating
            # a process removed by the preceding successful disable.
            if name in (self.post.GetPostProcessOrder() or []) and not self.post.SetEnableByName(name, False):
                raise RuntimeError('Custom pass quiesce rejected '+name)
        return self.snapshot()
