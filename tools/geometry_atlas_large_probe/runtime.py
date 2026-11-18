# -*- coding: utf-8 -*-
"""In-memory, single-generation paged geometry. No runtime file output."""
import time
import mod.client.extraClientApi as api
from geometry_atlas_probe.codec import encode_values
from geometry_atlas_probe.pipeline_config import PROCESS
from geometry_atlas_probe.update_scheduler import statistics

ClientSystem = api.GetClientSystemCls()
MASK = 0xffffffff
PAGE_BYTES = 65536
MAX_BYTES = 2097152


def byte_at(seed, generation, index):
    value = (seed ^ ((generation * 0x9e3779b9) & MASK) ^ ((index * 0x85ebca6b) & MASK)) & MASK
    value ^= value >> 16
    value = (value * 0x7feb352d) & MASK
    value ^= value >> 15
    value = (value * 0x846ca68b) & MASK
    return (value ^ (value >> 16)) & 255


class ProbeSystem(ClientSystem):
    def __init__(self, namespace, system_name):
        ClientSystem.__init__(self, namespace, system_name)
        self.factory = api.GetEngineCompFactory()
        self.level = api.GetLevelId()
        self.game = self.factory.CreateGame(self.level)
        self.block = self.factory.CreateBlock(self.level)
        self.geometry = self.factory.CreateBlockGeometry(self.level)
        self.post = self.factory.CreatePostProcess(self.level)
        self.pages = []
        self.seed, self.generation, self.slot_count = 0, 0, 0
        self.writer_visible = True
        self.geometry_visible = True
        self.pipeline_installed = False
        self.pipeline_ready = False
        self.pipeline_enabled = False
        self.connection = False
        self.error = None
        self.render_event = 0
        self.query_value = [0, 0, 0, 0]
        self.dimensions = [1, 2560, 1440, 0]
        self.layout = [0, 2048, 8, 32]
        self.flip_y = True
        self.measurement = None
        self.last_measurement = None
        self.ListenForEvent(api.GetEngineNamespace(), api.GetEngineSystemName(),
            'GameRenderTickEvent', self, self.on_frame)

    def _page_controls(self, page):
        groups = ((256., 8., float(page['count']), 2048.), (8., 32., 1., 2560.),
            (1440., 1., .5, .5), (float(self.writer_visible and page['loaded']), 0., float(page['base']), 0.))
        return all(page['render'].SetEntityExtraUniforms(index + 1, group)
            for index, group in enumerate(groups))

    def on_frame(self, args):
        self.render_event += 1
        for page in self.pages:
            if not page['ready']:
                page['ready'] = self._page_controls(page)
        sample = self.measurement
        if sample is None:
            return
        now = time.clock()
        if now >= sample['warm_until'] and sample['previous'] is not None:
            sample['interval_ms'].append((now - sample['previous']) * 1000.)
        sample['previous'] = now
        if now >= sample['warm_until']:
            sample['frames'] += 1
        if now >= sample['warm_until'] and sample['frames'] % 15 == 0:
            sample['fps'].append(self.game.GetFps())
        if now >= sample['until']:
            self.last_measurement = {'elapsed': now - sample['start'], 'warmup_seconds': sample['warmup'],
                'sample_seconds': now - sample['warm_until'], 'frames': sample['frames'],
                'slot_count': self.slot_count, 'writer_visible': self.writer_visible,
                'query': list(self.query_value), 'generation': self.generation,
                'geometry_visible': self.geometry_visible, 'pipeline_enabled': self.pipeline_enabled,
                'fps': statistics(sample['fps']), 'interval_ms': statistics(sample['interval_ms'], True),
                'gpu_completion_fence': False}
            self.measurement = None

    def grow(self, byte_count, seed=54321, generation=1):
        byte_count = int(byte_count)
        if byte_count <= self.slot_count or byte_count > MAX_BYTES or byte_count % PAGE_BYTES:
            raise ValueError('Grow a single prefix in multiples of64KiB, at most2MiB')
        if self.measurement is not None or self.error is not None:
            raise RuntimeError('Cannot mutate while measuring or after a failed page')
        if self.pages and (seed != self.seed or generation != self.generation):
            raise ValueError('A resident prefix keeps its seed and generation')
        api.HideHudGUI(True)
        self.seed, self.generation = int(seed) & MASK, int(generation) & MASK
        camera = self.factory.CreateCamera(self.level)
        position, forward = camera.GetPosition(), camera.GetForward()
        if position is None or forward is None:
            raise RuntimeError('World camera is not ready')
        anchor = tuple(position[index] + forward[index] * 3. for index in range(3))
        for base in range(self.slot_count, byte_count, PAGE_BYTES):
            entity = self.CreateClientEntityByTypeStr('pmanim_geometry_atlas:anchor', anchor, (0., 0.))
            if entity is None:
                raise RuntimeError('Page anchor creation failed')
            page = {'base': base, 'count': PAGE_BYTES, 'entity': entity,
                'render': self.factory.CreateActorRender(entity), 'ready': False,
                'loaded': False, 'attempted': False, 'name': '', 'timings': {},
                'seed': self.seed, 'generation': self.generation, 'payload_fingerprint': None, 'upload_serial': 0}
            self.factory.CreateModel(entity).SetEntityShadowShow(False)
            self.pages.append(page)
            page['ready'] = self._page_controls(page)
        self.slot_count = byte_count
        self.layout[0] = byte_count
        return self.snapshot()

    def upload_page(self, page_index):
        page_index = int(page_index)
        if not 0 <= page_index < len(self.pages):
            raise ValueError('Page index out of range')
        page = self.pages[page_index]
        if not page['ready'] or page['attempted'] or self.error is not None or self.measurement is not None:
            raise RuntimeError('Page is not ready, already attempted, or controls are frozen')
        page['attempted'] = True
        started = time.clock()
        values = bytearray(byte_at(self.seed, self.generation, index)
            for index in range(page['base'], page['base'] + page['count']))
        generated = time.clock()
        page['payload_fingerprint'] = {'algorithm': 'sum_u8_mod2^32', 'value': sum(values) & MASK}
        fingerprinted = time.clock()
        encoded = encode_values(values, 'compact8')
        data = encoded['data']
        data['common'] = {(identifier.replace('pmanim_geometry_packet:', 'pmanim_geometry_atlas:'), aux): indices
            for (identifier, aux), indices in data['common'].items()}
        packed = time.clock()
        palette = self.block.GetBlankBlockPalette()
        if palette is None or not palette.DeserializeBlockPalette(data):
            self.error = 'DeserializeBlockPalette rejected page%d' % page_index
            raise RuntimeError(self.error)
        deserialized = time.clock()
        name = 'pmanim_large_generation%d_page%03d' % (self.generation, page_index)
        result = self.geometry.CombineBlockPaletteToGeometry(palette, name, 1)
        combined = time.clock()
        page['name'] = result or ''
        if not result:
            self.error = 'Combine rejected page%d' % page_index
            raise RuntimeError(self.error)
        if not page['render'].AddActorBlockGeometry(result, (0., 0., 0.), (0., 0., 0.)):
            self.error = 'Attach rejected page%d' % page_index
            raise RuntimeError(self.error)
        page['loaded'] = True
        page['upload_serial'] = page_index + 1
        if not self._page_controls(page):
            self.error = 'Loaded page uniforms rejected page%d' % page_index
            raise RuntimeError(self.error)
        bound = time.clock()
        page['timings'] = {'generation_ms': (generated-started)*1000., 'fingerprint_ms': (fingerprinted-generated)*1000.,
            'encode_ms': (packed-fingerprinted)*1000.,
            'deserialize_ms': (deserialized-packed)*1000., 'combine_ms': (combined-deserialized)*1000.,
            'attach_ms': (bound-combined)*1000., 'total_ms': (bound-started)*1000.}
        page['upload_event'] = self.render_event
        return self.snapshot()

    def install_pipeline(self):
        if self.pipeline_installed:
            raise RuntimeError('Pipeline already installed')
        if not self.post.AddPostProcess(PROCESS):
            raise RuntimeError('AddPostProcess rejected')
        self.pipeline_installed = True
        return self.snapshot()

    def finish_pipeline(self):
        name = PROCESS['name']
        if not self.pipeline_installed or name not in (self.post.GetPostProcessOrder() or []):
            raise RuntimeError('Pipeline registration is not ready')
        if not self.post.SetEnableByName(name, True):
            raise RuntimeError('Pipeline enable rejected')
        self.connection = bool(self.post.PostPassResultToOtherPass(name, 0, name, 2, 3))
        if not self.connection:
            raise RuntimeError('Explicit pass0 to pass2 TEXTURE_3 connection rejected')
        self.pipeline_ready = True
        self.pipeline_enabled = True
        return self.query(0)

    def query(self, mode=0, salt=37, salt2=91, flip_y=True):
        if not self.pipeline_ready or self.measurement is not None or mode not in (0, 1, 2, 3):
            raise ValueError('Need idle ready pipeline and query mode0..3')
        if not self.pages or not all(page['loaded'] for page in self.pages):
            raise RuntimeError('Every logical page must be resident before a query')
        if not 0 <= salt <= 65535 or not 0 <= salt2 <= 65535:
            raise ValueError('Salts out of range')
        self.query_value = [0, self.slot_count, int(mode), int(salt)]
        self.dimensions[3] = int(salt2)
        self.flip_y = bool(flip_y)
        controls = (('query', [0, self.slot_count, mode + 4*int(self.flip_y), salt]),
            ('layout', self.layout), ('dimensions', self.dimensions))
        for key, value in controls:
            if not self.post.SetParameter(PROCESS['name'], key, [float(item) for item in value]):
                self.pipeline_ready = False
                raise RuntimeError('Gather control rejected: ' + key)
        return self.snapshot()

    def set_writer_visible(self, visible):
        if self.measurement is not None:
            raise RuntimeError('Measurement freezes controls')
        self.writer_visible = bool(visible)
        for page in self.pages:
            if not self._page_controls(page):
                raise RuntimeError('Writer visibility uniform rejected')
        return self.snapshot()

    def set_pipeline_enabled(self, enabled):
        if self.measurement is not None or not self.pipeline_installed:
            raise RuntimeError('Need an idle installed pipeline')
        if not self.post.SetEnableByName(PROCESS['name'], bool(enabled)):
            raise RuntimeError('Pipeline enable rejected')
        self.pipeline_enabled = bool(enabled)
        return self.snapshot()

    def set_geometry_visible(self, visible):
        if self.measurement is not None:
            raise RuntimeError('Measurement freezes native attachment visibility')
        for page in self.pages:
            if page['loaded'] and not page['render'].SetActorBlockGeometryVisible(page['name'], bool(visible)):
                raise RuntimeError('Native geometry visibility rejected')
        self.geometry_visible = bool(visible)
        return self.snapshot()

    def start_measurement(self, seconds=25., warmup=2.):
        seconds, warmup = float(seconds), float(warmup)
        if (not self.pipeline_ready or self.measurement is not None or
                not 2. <= seconds <= 30. or not 2. <= warmup <= 10.):
            raise ValueError('Need idle ready pipeline and2..30seconds')
        now = time.clock()
        self.last_measurement = None
        self.measurement = {'start': now, 'until': now+warmup+seconds, 'warm_until': now+warmup, 'warmup': warmup,
            'previous': None, 'frames': 0, 'fps': [], 'interval_ms': []}
        return self.snapshot()

    def snapshot(self):
        pages = [{key: value for key, value in page.items() if key != 'render'} for page in self.pages]
        timing_keys = ('generation_ms', 'fingerprint_ms', 'encode_ms', 'deserialize_ms', 'combine_ms', 'attach_ms', 'total_ms')
        return {'schema': 'geometry_atlas_large_probe_v1', 'ready': bool(pages) and all(page['ready'] for page in pages),
            'error': self.error, 'seed': self.seed, 'generation': self.generation, 'slot_count': self.slot_count,
            'loaded_bytes': sum(page['count'] for page in pages if page['loaded']), 'pages': pages,
            'geometry_build_serial': sum(int(page['loaded']) for page in pages),
            'native_attempt_serial': sum(int(page['attempted']) for page in pages),
            'page_bytes': PAGE_BYTES, 'geometry_names': [page['name'] for page in pages if page['name']],
            'encoding': 'compact8', 'screen_size': [2560,1440], 'logical_screen_size': list(self.game.GetScreenSize()),
            'layout': list(self.layout), 'dimensions': list(self.dimensions), 'query': list(self.query_value),
            'flip_y': self.flip_y, 'writer_visible': self.writer_visible, 'pipeline_ready': self.pipeline_ready,
            'geometry_visible': self.geometry_visible, 'diagnostic_layout': [16,128,2048,1],
            'diagnostic_border_policy': 'declared_guard_rect_excluding_native_debug_UI',
            'border_guard_rect_native': [0,128,2560,1408],
            'pipeline_installed': self.pipeline_installed, 'connection': self.connection,
            'pipeline_enabled': self.pipeline_enabled,
            'render_event': self.render_event, 'runtime_payload_files': False, 'gpu_completion_fence': False,
            'cumulative_timings': {key: sum(page['timings'].get(key, 0.) for page in pages) for key in timing_keys},
            'measurement_running': self.measurement is not None, 'last_measurement': self.last_measurement}

    def Destroy(self):
        self.UnListenForEvent(api.GetEngineNamespace(), api.GetEngineSystemName(),
            'GameRenderTickEvent', self, self.on_frame)
