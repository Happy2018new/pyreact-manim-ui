# -*- coding: utf-8 -*-
"""Host-byte upload, bounded native pages, late stencil reads and frame samples."""
import math
import time
import mod.client.extraClientApi as api
from stencil_large.codec import INTEGER_TYPES, encode_values


ClientSystem = api.GetClientSystemCls()
CLOCK = time.clock if hasattr(time, 'clock') else time.perf_counter
MAX_BYTES = 524288
PAGE_BYTES = 65536
MAX_CHUNK_BYTES = 4096
MAX_NATIVE_ATTEMPTS = 40
MAX_NATIVE_RECORDS = 2097152
PROCESS = 'stencil_large_oracle'
NATIVE_POST = ('bloom', 'lensflare', 'depthoffield', 'gaussianblur',
               'coloradjustment', 'vignette', 'lensstain', 'oldtv', 'scanmap')


def _integer(value, low, high):
    return (not isinstance(value, bool) and isinstance(value, INTEGER_TYPES)
            and low <= value <= high)


def _stride(count):
    stride = 2
    while stride * stride < count:
        stride *= 2
    return stride


def _checksum(values):
    """Independent Adler-32 of received bytes; this is not a game-computed SHA."""
    a, b = 1, 0
    for value in values:
        a = (a + value) % 65521
        b = (b + a) % 65521
    return ((b << 16) | a) & 0xffffffff


def _statistics(values, intervals=False):
    ordered = sorted(values)
    result = {'count': len(ordered)}
    if ordered:
        result.update(mean=sum(ordered) / float(len(ordered)), min=ordered[0],
                      max=ordered[-1], p95=ordered[int((len(ordered)-1)*.95)],
                      p99=ordered[int((len(ordered)-1)*.99)])
    if intervals:
        result.update(over_25_ms=sum(value > 25. for value in ordered),
                      over_33_3_ms=sum(value > 33.3 for value in ordered),
                      over_50_ms=sum(value > 50. for value in ordered))
    return result


class ProbeSystem(ClientSystem):
    def __init__(self, namespace, name):
        ClientSystem.__init__(self, namespace, name)
        self.factory = api.GetEngineCompFactory()
        self.level = api.GetLevelId()
        self.game = self.factory.CreateGame(self.level)
        self.block = self.factory.CreateBlock(self.level)
        self.geometry = self.factory.CreateBlockGeometry(self.level)
        self.post = self.factory.CreatePostProcess(self.level)
        self.camera = self.factory.CreateCamera(self.level)
        self.origin, self.anchor = None, None
        self.actors, self.effects, self.controls = [], [], []
        self.clear_actor, self.clear_page = None, None
        self.writer_actors, self.active_pages, self.pages = [], [], []
        self.attempts, self.native_records = [], 0
        self.error, self.build_busy = None, False
        self.state, self.mode = 'empty', 'off'
        self.payload_visible, self.clear_visible = False, False
        self.viewport, self.roi = [720, 1080], [8, 128, 256, 1]
        self.byte_count, self.generation = 0, 0
        self.received, self.chunk_count, self.upload = 0, 0, None
        self.payload, self.identity = None, None
        self.plan, self.plan_cursor = [], 0
        self.oracle_installed, self.oracle_enabled = False, False
        self.oracle_mode, self.oracle_slot = 0, 0
        self.render_event, self.measurement_serial = 0, 0
        self.measurement, self.last_measurement = None, None
        self.native_hud_hidden, self.event_registered = False, True
        self.ListenForEvent(api.GetEngineNamespace(), api.GetEngineSystemName(),
                            'GameRenderTickEvent', self, self.on_frame)

    def _idle(self):
        if self.measurement is not None or self.build_busy or self.error is not None:
            raise RuntimeError('Probe is measuring, building or faulted')

    def prepare(self):
        self._idle()
        if self.origin is not None:
            return self.snapshot()
        position = self.camera.GetPosition()
        if position is None:
            raise RuntimeError('World camera is not ready')
        self.origin = (int(position[0]), int(position[1])-1, int(position[2]))
        self.camera.DepartCamera()
        if not (self.camera.SetCameraPos((self.origin[0], self.origin[1]+1., self.origin[2]))
                and self.camera.SetCameraRotation((8., 180., 0.))):
            raise RuntimeError('Fixed camera rejected')
        position, forward = self.camera.GetPosition(), self.camera.GetForward()
        self.anchor = tuple(position[i]+forward[i]*3. for i in range(3))
        api.HideHudGUI(True)
        self.native_hud_hidden = True
        self.clear_actor = self._new_actor('clear', 0)
        return self.snapshot()

    def _new_actor(self, kind, index):
        entity = self.CreateClientEntityByTypeStr('pmanim_geometry_atlas:anchor', self.anchor, (0., 0.))
        if entity is None:
            raise RuntimeError('Client-only geometry anchor rejected')
        actor = {'entity': entity, 'render': self.factory.CreateActorRender(entity),
                 'kind': kind, 'index': index, 'count': 1, 'stride': 2,
                 'offset': 0, 'ready': False, 'deadline': CLOCK()+10., 'pages': []}
        self.actors.append(actor)
        self.factory.CreateModel(entity).SetEntityShadowShow(False)
        actor['ready'] = self._actor_uniforms(actor)
        return actor

    def _actor_uniforms(self, actor):
        x, y, width, height = self.roi
        if actor['kind'] == 'clear':
            layout = (2., 1., float(width), float(height))
            enabled = self.clear_visible
        else:
            layout = (float(actor['stride']), float(actor['count']), float(width//4), 0.)
            enabled = self.payload_visible and actor['index']*PAGE_BYTES < self.byte_count
        groups = (layout, (float(x), float(y), float(self.viewport[0]), float(self.viewport[1])),
                  (1., .5, .5, 0.), (float(enabled), 0., 0., float(actor['offset'])))
        return all(actor['render'].SetEntityExtraUniforms(i+1, group)
                   for i, group in enumerate(groups))

    def _ready(self):
        count = (self.byte_count+PAGE_BYTES-1)//PAGE_BYTES
        relevant = ([self.clear_actor] if self.clear_actor is not None else []) + self.writer_actors[:count]
        return bool(relevant) and all(actor['ready'] for actor in relevant)

    def load_begin(self, byte_count, actual_host_sha, viewport, roi):
        self._idle()
        if self.origin is None or self.state in ('receiving', 'building'):
            raise RuntimeError('Prepare the idle probe before a new upload')
        if not _integer(byte_count, 1, MAX_BYTES):
            raise ValueError('Payload byte count must be in [1,524288]')
        if (not isinstance(actual_host_sha, str) or len(actual_host_sha) != 64
                or any(char not in '0123456789abcdefABCDEF' for char in actual_host_sha)):
            raise ValueError('Expected actual host SHA-256 hex identity')
        if (not isinstance(viewport, (list, tuple)) or len(viewport) != 2
                or any(not _integer(value, 1, 4095) for value in viewport)):
            raise ValueError('Viewport must contain two 12-bit positive dimensions')
        if (not isinstance(roi, (list, tuple)) or len(roi) != 4
                or any(not _integer(value, 0, 4095) for value in roi)):
            raise ValueError('ROI must contain four 12-bit integer coordinates')
        x, y, width, height = roi
        if (width < 4 or width % 4 or height < 1 or x+width > viewport[0]
                or y+height > viewport[1] or width*height != byte_count*4):
            raise ValueError('ROI must hold exactly four horizontal pixels per byte')
        self.configure('off')
        self.viewport, self.roi = list(viewport), list(roi)
        self.byte_count, self.generation = byte_count, self.generation+1
        self.received, self.chunk_count = 0, 0
        self.upload, self.payload = bytearray(byte_count), None
        self.identity = {'host_sha256': actual_host_sha.lower(), 'game_sha256_computed': False,
                         'byte_count': byte_count, 'adler32': None}
        self.plan, self.plan_cursor, self.active_pages = [], 0, []
        self.state = 'receiving'
        return self.snapshot()

    def load_chunk(self, offset, byte_list):
        self._idle()
        if self.state != 'receiving' or not _integer(offset, 0, self.byte_count):
            raise RuntimeError('No matching byte upload is receiving')
        if (offset != self.received or not isinstance(byte_list, (list, tuple))
                or not 1 <= len(byte_list) <= MAX_CHUNK_BYTES
                or offset+len(byte_list) > self.byte_count
                or any(not _integer(value, 0, 255) for value in byte_list)):
            raise ValueError('Chunks must be sequential, nonempty and at most4096integer bytes')
        self.upload[offset:offset+len(byte_list)] = bytearray(byte_list)
        self.received += len(byte_list)
        self.chunk_count += 1
        return {'generation': self.generation, 'received_bytes': self.received,
                'expected_bytes': self.byte_count, 'chunk_count': self.chunk_count}

    def load_finish(self):
        self._idle()
        if self.state != 'receiving' or self.received != self.byte_count:
            raise RuntimeError('Complete the host byte upload before freezing it')
        self.identity['adler32'] = _checksum(self.upload)
        self.payload, self.upload = bytes(self.upload), None
        count = (self.byte_count+PAGE_BYTES-1)//PAGE_BYTES
        while len(self.writer_actors) < count:
            self.writer_actors.append(self._new_actor('writer', len(self.writer_actors)))
        for index, actor in enumerate(self.writer_actors):
            actor['offset'] = index*PAGE_BYTES
            actor['count'] = max(0, min(PAGE_BYTES, self.byte_count-actor['offset']))
            actor['stride'] = _stride(actor['count'])
        for actor in self.actors:
            actor['deadline'], actor['ready'] = CLOCK()+10., self._actor_uniforms(actor)
        self._effects_ready()
        if self.clear_page is None:
            self.plan.append({'kind': 'clear', 'actor': self.clear_actor, 'offset': 0, 'count': 1})
        for actor in self.writer_actors[:count]:
            for kind in ('bit64', 'bit128'):
                self.plan.append({'kind': kind, 'actor': actor,
                                  'offset': actor['offset'], 'count': actor['count']})
        self.state = 'frozen'
        return self.snapshot()

    def _effects_ready(self):
        if not self.effects:
            position, forward = self.camera.GetPosition(), self.camera.GetForward()
            anchor = tuple(position[i]+forward[i]*4. for i in range(3))
            for index, kind in enumerate(('base', 'bit64', 'bit128')):
                effect = self.CreateEngineSfxFromEditor('effects/stencil_large_'+kind+'.json',
                                                       anchor, (0., 0., 0.), (4., 4., 4.))
                if effect is None:
                    raise RuntimeError('Late stencil effect creation rejected')
                control = self.factory.CreateFrameAniControl(effect)
                self.effects.append(effect)
                self.controls.append(control)
                if not (control.SetFaceCamera(True) and control.SetLoop(True)
                        and control.SetLayer(13+index) and control.Stop()):
                    raise RuntimeError('Late stencil effect controls rejected')
        packed = ((self.viewport[0]*4096+self.viewport[1])/16777216.,
                  (self.roi[0]*4096+self.roi[1])/16777216.,
                  (self.roi[2]*4096+self.roi[3])/16777216.)
        for index, control in enumerate(self.controls):
            if not control.SetMixColor(packed+((index+1)/4.,)):
                raise RuntimeError('Dynamic late effect metadata rejected')

    def _build_fail(self, message):
        self.error, self.build_busy, self.state = message, False, 'faulted'
        raise RuntimeError(message)

    def build_next_page(self):
        """One Combine at most. The host must preflight available commit first."""
        self._idle()
        if self.state not in ('frozen', 'building') or not self._ready():
            raise RuntimeError('Frozen payload and ready actor uniforms are required')
        if self.plan_cursor >= len(self.plan):
            raise RuntimeError('No native page remains to build')
        item = self.plan[self.plan_cursor]
        if (len(self.attempts) >= MAX_NATIVE_ATTEMPTS
                or self.native_records+item['count'] > MAX_NATIVE_RECORDS):
            raise RuntimeError('Bounded native geometry budget exhausted')
        # Consume the name and plan item before any native mutation. A failed or
        # timed-out call is never silently retried, and cached memory is not freed.
        name = 'pmanim_stencil_large_g%d_%s_%d' % (self.generation, item['kind'], len(self.attempts))
        attempt = {'name': name, 'generation': self.generation, 'kind': item['kind'],
                   'offset': item['offset'], 'byte_records': item['count'], 'status': 'attempting'}
        self.attempts.append(attempt)
        self.native_records += item['count']
        self.plan_cursor += 1
        self.build_busy, self.state = True, 'building'
        start = CLOCK()
        values = [0] if item['kind'] == 'clear' else self.payload[item['offset']:item['offset']+item['count']]
        encoded = encode_values(values, 'compact8')
        data, common = encoded['data'], {}
        for (identifier, aux), indices in data['common'].items():
            common[('pmanim_stencil_large:'+item['kind']+'_'+identifier.rsplit('_', 1)[-1], aux)] = indices
        data['common'] = common
        encoded_at = CLOCK()
        palette = self.block.GetBlankBlockPalette()
        if palette is None or not palette.DeserializeBlockPalette(data):
            self._build_fail('Native stencil palette rejected; attempt consumed')
        deserialized_at = CLOCK()
        result = self.geometry.CombineBlockPaletteToGeometry(palette, name, 1)
        combined_at = CLOCK()
        if not result:
            self._build_fail('Native stencil Combine rejected; attempt consumed')
        attempt['status'], attempt['result'] = 'combined', result
        render = item['actor']['render']
        if not render.AddActorBlockGeometry(result, (0., 0., 0.), (0., 0., 0.)):
            self._build_fail('Native stencil attachment rejected; attempt consumed')
        item['actor']['pages'].append(result)
        if not render.SetActorBlockGeometryVisible(result, False):
            self._build_fail('Native stencil initial hide rejected; attempt consumed')
        if item['kind'] == 'clear':
            self.clear_page = result
        else:
            self.active_pages.append({'name': result, 'actor': item['actor']})
        attempt.update(status='attached_hidden', encode_ms=(encoded_at-start)*1000.,
                       deserialize_ms=(deserialized_at-encoded_at)*1000.,
                       combine_ms=(combined_at-deserialized_at)*1000.,
                       attach_ms=(CLOCK()-combined_at)*1000., total_ms=(CLOCK()-start)*1000.)
        self.pages.append(result)
        self.build_busy = False
        if self.plan_cursor == len(self.plan):
            self.state = 'resident'
        return self.snapshot()

    def configure(self, mode='all'):
        self._idle()
        if mode not in ('off', 'fixture', 'all'):
            raise ValueError('Expected off, fixture or all')
        if mode != 'off' and (self.state != 'resident' or not self._ready()):
            raise RuntimeError('All native pages must be resident and ready')
        self.mode = mode
        self.payload_visible, self.clear_visible = mode == 'all', mode != 'off'
        if self.clear_page is not None:
            if not self.clear_actor['render'].SetActorBlockGeometryVisible(self.clear_page, self.clear_visible):
                raise RuntimeError('Clear visibility rejected')
        for page in self.active_pages:
            if not page['actor']['render'].SetActorBlockGeometryVisible(page['name'], self.payload_visible):
                raise RuntimeError('Writer visibility rejected')
        for actor in self.actors:
            actor['ready'] = self._actor_uniforms(actor)
        for control in self.controls:
            if not (control.Play() if mode == 'all' else control.Stop()):
                raise RuntimeError('Late stencil play/stop rejected')
        return self.snapshot()

    def hide_payload(self):
        self._idle()
        self.payload_visible = False
        for page in self.active_pages:
            if not page['actor']['render'].SetActorBlockGeometryVisible(page['name'], False):
                raise RuntimeError('Negative writer hide rejected')
        for actor in self.writer_actors:
            actor['ready'] = self._actor_uniforms(actor)
        return self.snapshot()

    def install_oracle(self):
        self._idle()
        if self.oracle_installed or any(self.post.CheckEnabledByName(name) for name in NATIVE_POST):
            raise RuntimeError('Oracle must be new and native post effects isolated')
        process = {'name': PROCESS, 'enable': False, 'paras': [
            {'name': 'control', 'value': [720., 1080., 0., 64.], 'range': [0., 2097152.]},
            {'name': 'roi', 'value': [8., 128., 256., 1.], 'range': [0., 2097152.]},
            {'name': 'output', 'value': [0., 64., 720., 0.], 'range': [0., 2097152.]}],
            'pass_array': [{'render_target': {'width': 1., 'height': 1.},
                            'material': 'stencil_large_'+name, 'depth_enable': False}
                           for name in ('copy', 'oracle')]}
        if not self.post.AddPostProcess(process, 0):
            raise RuntimeError('Large stencil oracle registration rejected')
        self.oracle_installed = True
        return self.snapshot()

    def inspect(self, mode=0, slot=0, enabled=True):
        self._idle()
        if (not self.oracle_installed or not _integer(mode, 0, 4)
                or not _integer(slot, 0, 1)):
            raise ValueError('Invalid large stencil oracle controls')
        vectors = (('control', [float(self.viewport[0]), float(self.viewport[1]), float(mode), float(self.byte_count)]),
                   ('roi', [float(value) for value in self.roi]),
                   ('output', [0., 64., float(self.viewport[0]), float(slot)]))
        for name, value in vectors:
            if not self.post.SetParameter(PROCESS, name, value):
                raise RuntimeError('Large stencil oracle parameters rejected')
        if not self.post.SetEnableByName(PROCESS, bool(enabled)):
            raise RuntimeError('Large stencil oracle enable rejected')
        self.oracle_mode, self.oracle_slot, self.oracle_enabled = mode, slot, bool(enabled)
        return self.snapshot()

    def start_measurement(self, mode, seconds=25., warm=2.):
        self._idle()
        seconds, warm = float(seconds), float(warm)
        if (mode not in ('baseline', 'dependent', 'restore') or self.state != 'resident'
                or not self.oracle_installed or not self._ready()
                or any(math.isnan(value) or math.isinf(value) for value in (seconds, warm))
                or not 2. <= seconds <= 60. or not 0. <= warm <= 10.):
            raise ValueError('Need resident probe, baseline/dependent/restore,2..60seconds and0..10warm')
        self.configure('off' if mode == 'baseline' else 'all')
        if not self._ready():
            raise RuntimeError('Actor uniforms lost readiness during measurement configuration')
        oracle_mode = {'baseline': 0, 'dependent': 2, 'restore': 4}[mode]
        workload = {'baseline': 'two post passes; copy and passthrough',
                    'dependent': 'two post passes; copy and dependent byte query',
                    'restore': 'two post passes; copy and source ROI RGB restoration'}[mode]
        self.inspect(oracle_mode, self.oracle_slot, True)
        now = CLOCK()
        self.measurement_serial += 1
        self.last_measurement = None
        self.measurement = {'serial': self.measurement_serial, 'mode': mode,
            'generation': self.generation, 'identity': dict(self.identity),
            'start': now, 'warm_until': now+warm, 'until': now+warm+seconds,
            'requested_seconds': seconds, 'warm_seconds': warm, 'previous': None,
            'frames': 0, 'interval_ms': [], 'fps_observations': [], 'sample_frame': 0,
            'native_attempt_count': len(self.attempts), 'resident_pages': list(self.pages),
            'oracle_mode': self.oracle_mode, 'oracle_slot': self.oracle_slot,
            'post_pass_count': 2, 'shader_workload': workload,
            'uploads_during_sampling': 0, 'actor_allocations_during_sampling': 0,
            'actor_destroys_during_sampling': 0}
        return self.snapshot()

    def on_frame(self, args):
        self.render_event += 1
        now = CLOCK()
        if self.measurement is None:
            for actor in self.actors:
                if not actor['ready'] and self.error is None:
                    actor['ready'] = self._actor_uniforms(actor)
                    if not actor['ready'] and now > actor['deadline']:
                        self.error = 'Actor uniforms did not become ready before timeout'
        sample = self.measurement
        if sample is None:
            return
        sample['frames'] += 1
        if now < sample['warm_until']:
            return
        if sample['previous'] is not None:
            sample['interval_ms'].append((now-sample['previous'])*1000.)
        sample['previous'] = now
        sample['sample_frame'] += 1
        if sample['sample_frame'] % 15 == 0:
            sample['fps_observations'].append([now-sample['start'], self.game.GetFps()])
        if now >= sample['until'] or sample['sample_frame'] >= 20000:
            self._finish_measurement(now)

    def _finish_measurement(self, now):
        sample = self.measurement
        sample.update(elapsed_seconds=now-sample['start'], render_event_end=self.render_event,
                      frame_interval_statistics=_statistics(sample['interval_ms'], True),
                      fps_statistics=_statistics([value[1] for value in sample['fps_observations']]),
                      sample_limit_reached=sample['sample_frame'] >= 20000,
                      gpu_completion_fence=False, fps_cap_is_performance_proof=False)
        self.last_measurement, self.measurement = sample, None

    def measurement_result(self):
        return {'running': self.measurement is not None, 'result': self.last_measurement,
                'progress': self._measurement_progress()}

    def _measurement_progress(self):
        sample = self.measurement
        if sample is None:
            return None
        return {'serial': sample['serial'], 'mode': sample['mode'], 'frames': sample['frames'],
                'elapsed_seconds': CLOCK()-sample['start'], 'interval_count': len(sample['interval_ms']),
                'fps_observation_count': len(sample['fps_observations'])}

    def snapshot(self):
        next_item = self.plan[self.plan_cursor] if self.plan_cursor < len(self.plan) else None
        return {'schema': 'weather_stencil_large_v1', 'state': self.state,
            'ready': self._ready(), 'error': self.error, 'generation': self.generation,
            'viewport': list(self.viewport), 'source_roi': list(self.roi),
            'logical_bytes': self.byte_count, 'source_pixels': self.byte_count*4,
            'geometry_records_per_payload_byte_per_bitplane': 1,
            'geometry_records_per_payload_byte_total': 2,
            'material_requests_destination_alpha_preservation': True,
            'identity': dict(self.identity) if self.identity is not None else None,
            'received_bytes': self.received, 'chunk_count': self.chunk_count,
            'page_bytes': PAGE_BYTES, 'native_attempt_count': len(self.attempts),
            'native_records_reserved': self.native_records, 'native_attempts': [dict(item) for item in self.attempts],
            'native_page_names': list(self.pages), 'active_pages': [page['name'] for page in self.active_pages],
            'clear_page': self.clear_page, 'build_busy': self.build_busy,
            'planned_pages': len(self.plan), 'completed_plan_items': self.plan_cursor,
            'next_native_page': {key: next_item[key] for key in ('kind', 'offset', 'count')} if next_item else None,
            'actor_count': len(self.actors), 'effects': list(self.effects), 'mode': self.mode,
            'payload_visible': self.payload_visible, 'clear_visible': self.clear_visible,
            'oracle_installed': self.oracle_installed, 'oracle_mode': self.oracle_mode,
            'oracle_slot': self.oracle_slot, 'oracle_enabled': self.oracle_enabled,
            'actual_post_order': list(self.post.GetPostProcessOrder() or []),
            'native_post_flags': [(name, self.post.CheckEnabledByName(name)) for name in NATIVE_POST],
            'render_event': self.render_event, 'measurement': self._measurement_progress(),
            'last_measurement_serial': self.last_measurement['serial'] if self.last_measurement else None,
            'runtime_file_writes': False, 'actual_host_bytes': True, 'continuous_update': False,
            'native_cache_reclamation_verified': False, 'stencil_bits_reserved': False,
            'performance_claimed': False, 'host_memory_preflight_required': True}

    def Destroy(self):
        if self.event_registered:
            self.UnListenForEvent(api.GetEngineNamespace(), api.GetEngineSystemName(),
                                  'GameRenderTickEvent', self, self.on_frame)
            self.event_registered = False
        for control in self.controls:
            control.Stop()
        for effect in self.effects:
            self.DestroyEntity(effect)
        if self.oracle_installed:
            self.post.SetEnableByName(PROCESS, False)
        for actor in self.actors:
            for name in actor['pages']:
                actor['render'].SetActorBlockGeometryVisible(name, False)
            self.DestroyEntity(actor['entity'])
        if self.origin is not None:
            self.camera.ResetCameraPos()
            self.camera.UnDepartCamera()
        if self.native_hud_hidden:
            api.HideHudGUI(False)
