# -*- coding: utf-8 -*-
"""Three resident passes: encoded scene copy, RGB restoration and late consumer."""
import math
from stencil_large.runtime import ProbeSystem as BulkProbe, CLOCK, NATIVE_POST, _integer
from stencil_large.integrated_config import WITH_UI, WITH_OUTLINE
from stencil_large.known_fixture import KnownFixture

if WITH_UI:
    from stencil_large.ui_clip_fixture import UiClipFixture
if WITH_OUTLINE:
    from stencil_large.outline_fixture import OutlineFixture


PROCESSES = ('stencil_integrated_copy', 'stencil_integrated_restore', 'stencil_integrated_consumer')
LINKS = ((PROCESSES[0], 0, PROCESSES[1], 0, 3),
         (PROCESSES[0], 0, PROCESSES[2], 0, 3),
         (PROCESSES[1], 0, PROCESSES[2], 0, 4))


class ProbeSystem(BulkProbe):
    def __init__(self, namespace, name):
        self.pipeline_registered = []
        self.pipeline_installed, self.pipeline_ready = False, False
        self.pipeline_enabled, self.pipeline_install_frame = False, None
        self.pipeline_links, self.pipeline_link_attempts = [], 0
        self.consumer_mode, self.shape_enabled, self.restore_enabled = 0, False, False
        self.known_fixture, self.ui_clip, self.outline = None, None, None
        BulkProbe.__init__(self, namespace, name)
        self.known_fixture = KnownFixture(self)
        if WITH_UI:
            self.ui_clip = UiClipFixture(self)
        if WITH_OUTLINE:
            self.outline = OutlineFixture(self)

    def install_pipeline(self):
        self._idle()
        if (self.pipeline_registered or self.oracle_installed
                or any(self.post.CheckEnabledByName(name) for name in NATIVE_POST)):
            raise RuntimeError('Need a new integrated pipeline and isolated native post effects')
        for index, name in enumerate(PROCESSES):
            process = {'name': name, 'enable': True, 'paras': [
                {'name': 'control', 'value': [720., 1080., 0., 65536.], 'range': [0., 2097152.]},
                {'name': 'roi', 'value': [8., 128., 512., 512.], 'range': [0., 2097152.]},
                {'name': 'output', 'value': [0., 128., 720., 0.], 'range': [0., 2097152.]}],
                'pass_array': [{'render_target': {'width': 1., 'height': 1.},
                                'material': name, 'depth_enable': False}]}
            if not self.post.AddPostProcess(process, index):
                raise RuntimeError('Integrated process registration rejected: '+name)
            self.pipeline_registered.append(name)
        self._pipeline_controls(0, False, False)
        for name in PROCESSES:
            if not self.post.SetEnableByName(name, True):
                raise RuntimeError('Integrated attachment priming rejected: '+name)
        self.pipeline_enabled = True
        self.pipeline_installed, self.pipeline_install_frame = True, self.render_event
        return self.snapshot()

    def finish_pipeline(self):
        self._idle()
        if not self.pipeline_installed or self.render_event <= self.pipeline_install_frame:
            raise RuntimeError('Register all processes, then wait for a later render turn before linking')
        if self.pipeline_ready:
            return self.snapshot()
        self.pipeline_link_attempts += 1
        for link in LINKS:
            if link not in self.pipeline_links:
                if not self.post.PostPassResultToOtherPass(*link):
                    raise RuntimeError('Integrated texture connection rejected: %s' % (link,))
                self.pipeline_links.append(link)
        order = list(self.post.GetPostProcessOrder() or [])
        if any(name not in order for name in PROCESSES):
            raise RuntimeError('Registered integrated processes are missing from native order')
        if [name for name in order if name in PROCESSES] != list(PROCESSES):
            raise RuntimeError('Native integrated process order differs from copy, restore, consumer')
        self.pipeline_ready = True
        return self.inspect(0)

    def install_oracle(self):
        return self.install_pipeline()

    def _pipeline_controls(self, mode, shape, restore):
        output = [0., 128., float(self.viewport[0]), float(shape)]
        roi = [float(value) for value in self.roi]
        for name, selector in zip(PROCESSES, (0, int(restore), mode)):
            control = [float(self.viewport[0]), float(self.viewport[1]), float(selector), float(self.byte_count)]
            for parameter, value in (('control', control), ('roi', roi), ('output', output)):
                if not self.post.SetParameter(name, parameter, value):
                    raise RuntimeError('Integrated process parameter rejected: '+name+'/'+parameter)

    def inspect(self, mode=0, shape_enabled=None, enabled=True, restore_enabled=None):
        self._idle()
        if not self.pipeline_ready or not _integer(mode, 0, 7):
            raise ValueError('Need linked integrated pipeline and consumer mode0..7')
        shape = mode == 4 if shape_enabled is None else bool(shape_enabled)
        restore = self.mode == 'all' if restore_enabled is None else bool(restore_enabled)
        self._pipeline_controls(mode, shape, restore)
        for name in PROCESSES:
            if not self.post.SetEnableByName(name, bool(enabled)):
                raise RuntimeError('Integrated process enable rejected: '+name)
        self.consumer_mode, self.shape_enabled, self.restore_enabled = mode, shape, restore
        self.pipeline_enabled = bool(enabled)
        return self.snapshot()

    def configure(self, mode='all'):
        BulkProbe.configure(self, mode)
        if self.pipeline_ready:
            self.restore_enabled = mode == 'all'
            self._pipeline_controls(self.consumer_mode, self.shape_enabled, self.restore_enabled)
        return self.snapshot()

    def configure_known_fixture(self, enabled, varying_alpha=True):
        self._idle()
        self.known_fixture.configure(bool(enabled), bool(varying_alpha))
        return self.snapshot()

    def open_ui(self):
        self._idle()
        if self.ui_clip is None:
            raise RuntimeError('UI clipping fixture was not included in this build')
        self.ui_clip.open()
        return self.snapshot()

    def configure_ui(self, enabled):
        self._idle()
        if self.ui_clip is None:
            raise RuntimeError('UI clipping fixture was not included in this build')
        self.ui_clip.configure(bool(enabled))
        return self.snapshot()

    def prepare_outline(self, roi=None, viewport=None, position=None, distance=4.):
        self._idle()
        if self.outline is None:
            raise RuntimeError('Native outline fixture was not included in this build')
        self.outline.create(roi=roi, viewport=viewport, position=position, distance=distance)
        return self.snapshot()

    def configure_outline(self, enabled):
        self._idle()
        if self.outline is None:
            raise RuntimeError('Native outline fixture was not included in this build')
        self.outline.set_enabled(bool(enabled))
        return self.snapshot()

    def start_measurement(self, mode, seconds=25., warm=2.):
        self._idle()
        seconds, warm = float(seconds), float(warm)
        profiles = {'baseline': ('off', 0), 'fixture': ('fixture', 0),
                    'restore': ('all', 0), 'visible': ('all', 4), 'dependent': ('all', 2)}
        if (mode not in profiles or self.state != 'resident' or not self.pipeline_ready
                or not self._ready() or any(math.isnan(value) or math.isinf(value) for value in (seconds, warm))
                or not 2. <= seconds <= 60. or not 0. <= warm <= 10.):
            raise ValueError('Need resident integrated probe, supported profile and finite duration')
        geometry_mode, consumer_mode = profiles[mode]
        self.configure(geometry_mode)
        if not self._ready():
            raise RuntimeError('Actor uniforms lost readiness during integrated measurement configuration')
        self.inspect(consumer_mode, consumer_mode == 4, True)
        now = CLOCK()
        self.measurement_serial += 1
        self.last_measurement = None
        self.measurement = {'serial': self.measurement_serial, 'mode': mode,
            'generation': self.generation, 'identity': dict(self.identity),
            'start': now, 'warm_until': now+warm, 'until': now+warm+seconds,
            'requested_seconds': seconds, 'warm_seconds': warm, 'previous': None,
            'frames': 0, 'interval_ms': [], 'fps_observations': [], 'sample_frame': 0,
            'native_attempt_count': len(self.attempts), 'resident_pages': list(self.pages),
            'consumer_mode': consumer_mode, 'restore_enabled': self.restore_enabled,
            'shape_enabled': self.shape_enabled, 'post_pass_count': 3,
            'shader_workload': 'copy, conditional source RGB restore, consumer '+mode,
            'pipeline_links': [list(link) for link in self.pipeline_links],
            'known_fixture': self.known_fixture.snapshot(),
            'ui_clip': self.ui_clip.snapshot() if self.ui_clip is not None else None,
            'outline': self.outline.snapshot() if self.outline is not None else None,
            'uploads_during_sampling': 0, 'actor_allocations_during_sampling': 0,
            'actor_destroys_during_sampling': 0}
        return self.snapshot()

    def snapshot(self):
        result = BulkProbe.snapshot(self)
        result.update(schema='weather_stencil_integrated_v1', post_pass_count=3,
            pipeline_registered=list(self.pipeline_registered), pipeline_installed=self.pipeline_installed,
            pipeline_ready=self.pipeline_ready, pipeline_install_frame=self.pipeline_install_frame,
            pipeline_enabled=self.pipeline_enabled, pipeline_link_attempts=self.pipeline_link_attempts,
            pipeline_links=[list(link) for link in self.pipeline_links],
            consumer_mode=self.consumer_mode, shape_enabled=self.shape_enabled,
            restore_enabled=self.restore_enabled, diagnostic_output_y=128,
            shape_bounds=[408, 704, 296, 304],
            known_fixture=self.known_fixture.snapshot() if self.known_fixture is not None else None,
            ui_clip=self.ui_clip.snapshot() if self.ui_clip is not None else None,
            outline=self.outline.snapshot() if self.outline is not None else None,
            same_frame_alpha_preservation_verified=False, native_ui_compatibility_verified=False,
            native_outline_compatibility_verified=False)
        return result

    def Destroy(self):
        for name in self.pipeline_registered:
            self.post.SetEnableByName(name, False)
        for controller in (self.known_fixture, self.ui_clip, self.outline):
            if controller is not None:
                controller.destroy()
        BulkProbe.Destroy(self)
