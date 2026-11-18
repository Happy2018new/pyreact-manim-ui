# -*- coding: utf-8 -*-
"""In-memory geometry RGB input and isolated forward scene codec controls."""
import math
import time
from geometry_atlas_probe.base_runtime import ProbeSystem as BaseProbe
from geometry_atlas_probe.codec import encode_values
from geometry_atlas_probe.scene_codec import payload_oracle, payload_to_symbols
from geometry_atlas_probe.scene_config import PROCESSES
from geometry_atlas_probe.scene_layout import plan_payload


class ProbeSystem(BaseProbe):
    def __init__(self, namespace, system_name):
        BaseProbe.__init__(self, namespace, system_name)
        self.rgb_bits = 2
        self.logical_bytes = 0
        self.allocated_bytes = 0
        self.payload_plan = None
        self.payload_salt = 29
        self.codec_roi = [8, 32, 32, 32]
        self.base_alpha = 255
        self.codec_mode = 'unconfigured'
        self.saved_post_states = []
        self.codec_processes = [item['name'] for item in PROCESSES]
        self.codec_connections = []
        self.static_measurement_window = None
        self.native_visibility = {}
        self.background_name = None
        self.background_entity = None
        self.background_render = None
        self.background_visible = False
        self.code_domain = False

    def _writer_controls(self, candidate=None):
        accepted = BaseProbe._writer_controls(self, candidate)
        if not accepted:
            return False
        accepted = self.render.SetEntityExtraUniforms(4, (float(self.writer_visible), 0.,
                                                         float(self.rgb_bits), 0.))
        return accepted and self._background_controls()

    def _background_controls(self):
        if self.background_render is None:
            return True
        groups = ((float(self.stride), 8., float(self.slot_count), float(self.layout[1])),
                  tuple(float(value) for value in self.layout[2:]+self.dimensions[:2]),
                  (1080.,)+tuple(float(value) for value in self.center),
                  (float(self.background_visible), 0., 0., 1.))
        return all(self.background_render.SetEntityExtraUniforms(index+1, values)
                   for index, values in enumerate(groups))

    def _params(self, name, mode=0, start=0, count=1, roi=None):
        roi = self.codec_roi if roi is None else roi
        second = self.logical_bytes if name == 'scene_codec_consumer' else self.base_alpha
        fields = (('codec', [self.rgb_bits, second, mode, start]),
                  ('roi', roi), ('physical', [720, 1080, 1, count]))
        for key, value in fields:
            if not self.post.SetParameter(name, key, [float(item) for item in value]):
                raise RuntimeError('Scene codec parameter rejected: '+name+'/'+key)

    def load_payload(self, byte_count=3072, bits=2, salt=29, code_domain=False, background_first=False):
        self._require_idle_controls()
        if not self.ready:
            raise ValueError('Open the actor before loading a payload')
        plan = plan_payload(byte_count, bits)
        if code_domain:
            pixels = 256*(1 << (3*bits))
            if byte_count != pixels*3*bits//8:
                raise ValueError('Code-domain sweep needs exactly 256 times all RGB symbols')
            plan.update(columns=256, rows=pixels//256, pixels=pixels, roi=[8, 192, 256, pixels//256])
        if not self.can_upload(plan['pixels']):
            raise RuntimeError('Named geometry budget exhausted; restart this owned probe')
        previous_names = list(self.dataset_names)
        self.begin_dataset()
        for previous in previous_names:
            self.native_visibility[previous] = False
        if self.background_name is not None:
            self.set_background_visible(False)
        self.code_domain = bool(code_domain)
        self.rgb_bits, self.logical_bytes, self.payload_salt = bits, int(byte_count), int(salt)
        self.payload_plan, self.allocated_bytes = plan, plan['allocated_bytes']
        started = time.clock()
        if code_domain:
            symbols = bytearray(index//256 for index in range(plan['pixels']))
        else:
            payload = bytearray(payload_oracle(index, self.payload_salt) if index < self.logical_bytes else 0
                                for index in range(self.allocated_bytes))
            symbols = payload_to_symbols(payload, bits)
        if code_domain and background_first:
            self._attach_background(plan['pixels'])
        result, stride = self._combine_symbols(symbols, 'scene_codec_epoch%d_attempt' % self.epoch)
        self.names.append(result)
        self.name_records[result] = len(symbols)
        self.named_records += len(symbols)
        self.dataset_names.add(result)
        if not self.render.AddActorBlockGeometry(result, (0., 0., 0.), (0., 0., 0.)):
            raise RuntimeError('Scene codec geometry attachment rejected')
        self.attached_names.add(result)
        if not self.render.SetActorBlockGeometryVisible(result, True):
            raise RuntimeError('Scene codec native attachment visibility rejected')
        self.native_visibility[result] = True
        self.geometry_name, self.slot_count, self.stride = result, len(symbols), stride
        self.geometry_build_serial += 1
        self.generation += 1
        self.layout = [len(symbols), plan['columns'], plan['roi'][0], plan['roi'][1]]
        self.dimensions = [1, 720, 1080, 0]
        self.codec_roi = list(plan['roi'])
        if code_domain and not background_first:
            self._attach_background(plan['pixels'])
        if not self._writer_controls():
            raise RuntimeError('Scene codec actor parameters rejected')
        self.timings = {'build_attach_ms': (time.clock()-started)*1000.}
        self.codec_mode = 'native_code_domain' if code_domain else 'geometry_rgb'
        if self.pipeline_ready:
            self.configure_codec()
        return self.snapshot()

    def _combine_symbols(self, symbols, prefix):
        encoded = encode_values(symbols, 'compact8')
        data = encoded['data']
        data['common'] = {(identifier.replace('pmanim_geometry_packet:', 'pmanim_geometry_atlas:'), aux): indices
                          for (identifier, aux), indices in data['common'].items()}
        palette = self.block.GetBlankBlockPalette()
        if palette is None or not palette.DeserializeBlockPalette(data):
            raise RuntimeError('Scene codec palette rejected')
        self.native_attempt_serial += 1
        name = prefix+str(self.native_attempt_serial)
        result = self.geometry.CombineBlockPaletteToGeometry(palette, name, 1)
        if not result:
            raise RuntimeError('Scene codec geometry combine rejected')
        return result, encoded['stride']

    def _attach_background(self, pixels):
        if self.background_entity is None:
            camera = self.factory.CreateCamera(self.level)
            position, forward = camera.GetPosition(), camera.GetForward()
            anchor = tuple(position[index]+forward[index]*6. for index in range(3))
            self.background_entity = self.CreateClientEntityByTypeStr('pmanim_geometry_atlas:anchor',anchor,(0.,0.))
            if self.background_entity is None:
                raise RuntimeError('Native background anchor rejected')
            self.background_render = self.factory.CreateActorRender(self.background_entity)
            self.factory.CreateModel(self.background_entity).SetEntityShadowShow(False)
        encoded = encode_values(bytearray(index%256 for index in range(pixels)), 'compact8')
        data = encoded['data']
        data['common'] = {(identifier.replace('pmanim_geometry_packet:', 'pmanim_geometry_atlas:'), aux): indices
                          for (identifier, aux), indices in data['common'].items()}
        palette = self.block.GetBlankBlockPalette()
        if palette is None or not palette.DeserializeBlockPalette(data):
            raise RuntimeError('Native background palette rejected')
        self.native_attempt_serial += 1
        name = 'scene_background_attempt%d' % self.native_attempt_serial
        result = self.geometry.CombineBlockPaletteToGeometry(palette, name, 1)
        if not result or not self.background_render.AddActorBlockGeometry(result, (0.,0.,0.), (0.,0.,0.)):
            raise RuntimeError('Native background build/attachment rejected')
        self.background_name, self.background_visible = result, True
        self.native_visibility[result] = True
        self.names.append(result)
        self.name_records[result] = pixels
        self.named_records += pixels

    def set_background_visible(self, visible):
        self.background_visible = bool(visible)
        if self.background_name is not None:
            if not self.background_render.SetActorBlockGeometryVisible(self.background_name, bool(visible)):
                raise RuntimeError('Native background visibility rejected')
            self.native_visibility[self.background_name] = bool(visible)
        if self.ready and not self._writer_controls():
            raise RuntimeError('Native background actor controls rejected')
        return self.snapshot()

    def install_pipeline(self):
        if self.pipeline_installed:
            raise RuntimeError('Scene codec pipeline already installed')
        self.saved_post_states = [(name, self.post.CheckEnabledByName(name))
                                  for name in (self.post.GetPostProcessOrder() or [])]
        for name, enabled in self.saved_post_states:
            if enabled and not self.post.SetEnableByName(name, False):
                raise RuntimeError('Baseline post disable rejected: '+name)
        for index, process in enumerate(PROCESSES):
            if not self.post.AddPostProcess(process, index):
                raise RuntimeError('Scene codec process rejected: '+process['name'])
        self.pipeline = PROCESSES[-1]
        self.pipeline_installed = True
        return self.snapshot()

    def finish_pipeline(self):
        if not self.pipeline_installed:
            raise RuntimeError('Install in a preceding render turn')
        links = [('scene_codec_fixture', 'scene_codec_encode', 3),
                 ('scene_codec_encode', 'scene_codec_decode', 3),
                 ('scene_codec_encode', 'scene_codec_consumer', 3),
                 ('scene_codec_encode', 'scene_codec_inspect', 3),
                 ('scene_codec_decode', 'scene_codec_inspect', 4),
                 ('scene_codec_raw', 'scene_codec_inspect', 5)]
        for source, destination, slot in links:
            accepted = self.post.PostPassResultToOtherPass(source, 0, destination, 0, slot)
            self.codec_connections.append([source, destination, slot, bool(accepted)])
            if not accepted:
                raise RuntimeError('Scene codec private texture link rejected')
        self.pipeline_ready = self.connection = True
        return self.configure_codec()

    def configure_codec(self):
        for name in self.codec_processes:
            if name != 'scene_codec_raw':
                self._params(name)
        for name in self.codec_processes:
            enabled = name not in ('scene_codec_consumer', 'scene_codec_fixture', 'scene_codec_diagnostic')
            if not self.post.SetEnableByName(name, enabled):
                raise RuntimeError('Scene codec enable rejected: '+name)
        return self.inspect(0, 0, min(4096, self.codec_roi[2]*self.codec_roi[3]))

    def fixture(self, mode=1, bits=2, blocks=128, salt=29):
        if mode not in (0, 1, 2, 3) or bits not in (1, 2) or not 1 <= blocks <= 512:
            raise ValueError('Invalid independent codec fixture')
        self.rgb_bits, self.payload_salt = bits, salt
        self.codec_roi = [8, 32, 32, int(blocks)]
        self.logical_bytes = int(blocks)*12*bits
        self.allocated_bytes = self.logical_bytes
        self.payload_plan = None
        self.set_writer_visible(False)
        self.configure_codec()
        self._params('scene_codec_fixture', mode, salt)
        self._params('scene_codec_encode', 1)
        if not self.post.SetEnableByName('scene_codec_fixture', True):
            raise RuntimeError('Independent codec fixture enable rejected')
        self.codec_mode = 'independent_fixture_%d' % mode
        return self.inspect(2, 0, min(4096, int(blocks)*32))

    def set_base_alpha(self, value):
        self._require_idle_controls()
        if int(value) != value or not 0 <= value <= 255:
            raise ValueError('Alpha baseline must be an integer byte')
        self.base_alpha = int(value)
        return self.configure_codec()

    def set_native_writer_visible(self, visible):
        self._require_idle_controls()
        for name in self.attached_names:
            enabled = bool(visible) and name == self.geometry_name
            if not self.render.SetActorBlockGeometryVisible(name, enabled):
                raise RuntimeError('Native writer visibility rejected: '+name)
            self.native_visibility[name] = enabled
        self.set_writer_visible(visible)
        return self.snapshot()

    def diagnostic(self, mode=0, full_scene=True):
        self._require_idle_controls()
        if mode not in (0, 1, 2):
            raise ValueError('Use alpha diagnostic mode 0, 1 or 2')
        roi = [0, 0, 720, 1080] if full_scene else self.codec_roi
        self._params('scene_codec_diagnostic', mode, 0, 1, roi)
        for name in ('scene_codec_consumer', 'scene_codec_inspect'):
            if not self.post.SetEnableByName(name, False):
                raise RuntimeError('Diagnostic output selection rejected')
        if not self.post.SetEnableByName('scene_codec_diagnostic', True):
            raise RuntimeError('Alpha diagnostic enable rejected')
        self.query_value = [0, roi[2]*roi[3], mode, int(bool(full_scene))]
        return self.snapshot()

    def inspect(self, mode=0, start=0, count=4096, full_scene=False):
        self._require_idle_controls()
        maximum = 673920 if mode >= 10 else 4096
        if not 0 <= mode <= 23 or start < 0 or not 1 <= count <= maximum:
            raise ValueError('Invalid diagnostic query')
        if mode == 23 and (self.logical_bytes != 65536 or self.payload_salt != 29 or self.code_domain):
            raise ValueError('Same-frame RGB/alpha diagnostic requires 64 KiB salt-29 payload')
        roi = [0, 0, 720, 1080] if full_scene else self.codec_roi
        if start+count > roi[2]*roi[3]:
            raise ValueError('Diagnostic query exceeds its ROI')
        self._params('scene_codec_inspect', mode, start, count, roi)
        for name, enabled in (('scene_codec_consumer', False), ('scene_codec_diagnostic', False),
                              ('scene_codec_inspect', True)):
            if not self.post.SetEnableByName(name, enabled):
                raise RuntimeError('Inspect output selection rejected')
        self.query_value = [start, count, mode, int(bool(full_scene))]
        return self.snapshot()

    def query(self, start, count, mode=0, *unused, **ignored):
        self._require_idle_controls()
        maximum = 673920 if mode >= 3 else 4096
        if (mode not in (0, 1, 2, 3, 4, 5) or start < 0 or not 1 <= count <= maximum or
                start+count > self.logical_bytes):
            raise ValueError('Invalid payload query')
        self._params('scene_codec_consumer', mode, start, count)
        for name, enabled in (('scene_codec_inspect', False), ('scene_codec_diagnostic', False),
                              ('scene_codec_consumer', True)):
            if not self.post.SetEnableByName(name, enabled):
                raise RuntimeError('Consumer output selection rejected')
        self.query_value = [start, count, mode, 0]
        return self.snapshot()

    def snapshot(self):
        result = BaseProbe.snapshot(self)
        result.update(schema='scene_codec_probe_v1', rgb_bits=getattr(self, 'rgb_bits', 2),
                      logical_payload_bytes=getattr(self, 'logical_bytes', 0),
                      allocated_payload_bytes=getattr(self, 'allocated_bytes', 0),
                      payload_plan=getattr(self, 'payload_plan', None),
                      payload_salt=getattr(self, 'payload_salt', 29),
                      codec_roi=list(getattr(self, 'codec_roi', [8, 32, 32, 32])),
                      base_alpha=getattr(self, 'base_alpha', 255),
                      codec_mode=getattr(self, 'codec_mode', 'unconfigured'),
                      native_background_name=getattr(self, 'background_name', None),
                      native_background_visible=getattr(self, 'background_visible', False),
                      code_domain_sweep=getattr(self, 'code_domain', False),
                      baseline_sampling='separate writer-off/on captures; live raw producer',
                      codec_connections=list(getattr(self, 'codec_connections', [])),
                      codec_enabled_processes=([name for name in getattr(self, 'codec_processes', [])
                                                if self.post.CheckEnabledByName(name)]
                                               if getattr(self, 'pipeline_installed', False) else []),
                      prior_post_states=list(getattr(self, 'saved_post_states', [])),
                      static_measurement_window=getattr(self, 'static_measurement_window', None),
                      native_attachment_visibility=dict(getattr(self, 'native_visibility', {})),
                      native_visibility_receipt='successful SetActorBlockGeometryVisible calls; no getter or GPU fence',
                      game_runtime_file_writes=False)
        return result

    def start_static_measurement(self, sample_seconds=25., warmup_seconds=2.):
        sample, warmup = float(sample_seconds), float(warmup_seconds)
        if (math.isnan(sample) or math.isinf(sample) or math.isnan(warmup) or math.isinf(warmup) or
                not 20. <= sample <= 25. or not 2. <= warmup <= 4. or sample+warmup > 30.):
            raise ValueError('Use 20..25 sample seconds and 2..4 warmup seconds, total <=30')
        BaseProbe.start_measurement(self, sample+warmup)
        self.measurement['warm_until'] = self.measurement['start']+warmup
        self.static_measurement_window = {'warmup_seconds': warmup, 'sample_seconds': sample,
                                          'total_seconds': sample+warmup}
        return self.snapshot()

    def start_updates(self, *unused, **ignored):
        raise RuntimeError('This experiment permits static payloads only')

    def close(self):
        if getattr(self, 'background_entity', None) is not None:
            self.DestroyClientEntity(self.background_entity)
            self.background_entity = self.background_render = None
        for name in getattr(self, 'codec_processes', []):
            if self.pipeline_installed:
                self.post.SetEnableByName(name, False)
        for name, enabled in getattr(self, 'saved_post_states', []):
            if enabled:
                self.post.SetEnableByName(name, True)
        BaseProbe.close(self)
