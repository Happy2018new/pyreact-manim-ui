# -*- coding: utf-8 -*-
"""Client-only static particle replacement for the integrated late draws."""
from stencil_large.integrated_runtime import ProbeSystem as IntegratedProbe
from stencil_large.particle_candidate_config import VIEWPORT, ROI


ROLES = (('base', 13), ('bit64', 14), ('bit128', 15))


class ParticleDraw(object):
    def __init__(self, probe, role, layer):
        self.probe, self.role, self.layer = probe, role, layer
        self.entity, self.control, self.born_frame = None, None, None
        self.paused = False

    def show(self):
        if self.entity is not None:
            return True
        position, forward = self.probe.camera.GetPosition(), self.probe.camera.GetForward()
        if position is None or forward is None or len(position) != 3 or len(forward) != 3:
            raise RuntimeError('Prepare the stationary camera before particle creation')
        anchor = tuple(position[i] + forward[i]*4. for i in range(3))
        self.entity = self.probe.CreateEngineParticle(
            'effects/pmanim_particle_candidate/'+self.role+'.json', anchor)
        if self.entity is None:
            raise RuntimeError('Independent particle creation rejected: '+self.role)
        self.control = self.probe.factory.CreateParticleControl(self.entity)
        if not (self.control.SetLayer(self.layer) and self.control.SetGlobal(True)
                and self.control.SetFadeDistance(0.) and self.control.Play()):
            raise RuntimeError('Independent particle controls rejected: '+self.role)
        if self.control.GetParticleMaxNum() != 1:
            raise RuntimeError('Independent emitter must have capacity one: '+self.role)
        self.born_frame, self.paused = self.probe.render_event, False
        return True

    def pause(self):
        if self.entity is None:
            return False
        if self.paused:
            return True
        if self.probe.render_event <= self.born_frame:
            raise RuntimeError('Particle must cross a render turn before Pause; pixels still require validation')
        if not self.control.Pause():
            raise RuntimeError('Independent particle Pause rejected: '+self.role)
        self.paused = True
        return True

    def snapshot(self):
        return {'role': self.role, 'layer': self.layer, 'entity': self.entity,
                'visible_requested': self.entity is not None, 'paused': self.paused,
                'born_frame': self.born_frame,
                'capacity': self.control.GetParticleMaxNum() if self.control is not None else None,
                'emission_rate': self.control.GetParticleEmissionRate() if self.control is not None else None,
                'live_particle_count_verified': False}

    def destroy(self):
        if self.control is not None and not self.control.Stop():
            raise RuntimeError('Independent particle stop rejected: '+self.role)
        if self.entity is not None and not self.probe.DestroyEntity(self.entity):
            raise RuntimeError('Independent particle destruction rejected: '+self.role)
        self.entity, self.control, self.born_frame = None, None, None
        self.paused = False


class KnownFixture(object):
    """At most one layer-12 reference; two offline assets select alpha mode."""
    def __init__(self, probe):
        self.probe, self.draw = probe, None
        self.visible, self.varying_alpha, self.roi = False, None, None

    def configure(self, enabled, varying_alpha=True):
        varying_alpha = bool(varying_alpha)
        if not enabled:
            self.destroy()
            return self.snapshot()
        if self.draw is not None and self.varying_alpha != varying_alpha:
            self.destroy()
        if self.draw is None:
            self.draw = ParticleDraw(self.probe, 'reference' if varying_alpha else 'reference_opaque', 12)
        self.draw.show()
        self.visible, self.varying_alpha, self.roi = True, varying_alpha, list(ROI)
        return self.snapshot()

    def snapshot(self):
        return {'layer': 12, 'entity': self.draw.entity if self.draw is not None else None,
                'visible': self.visible, 'varying_alpha': self.varying_alpha, 'roi': self.roi,
                'independent_particle': self.draw.snapshot() if self.draw is not None else None}

    def destroy(self):
        if self.draw is not None:
            self.draw.destroy()
        self.draw, self.visible = None, False


class ProbeSystem(IntegratedProbe):
    def __init__(self, namespace, name):
        self.particle_draws = {}
        IntegratedProbe.__init__(self, namespace, name)
        self.known_fixture = KnownFixture(self)

    def load_begin(self, byte_count, actual_host_sha, viewport, roi):
        if list(viewport) != list(VIEWPORT) or list(roi) != list(ROI):
            raise ValueError('Particle candidate layout is compiled offline; rebuild for a different viewport or ROI')
        return IntegratedProbe.load_begin(self, byte_count, actual_host_sha, viewport, roi)

    def _effects_ready(self):
        # Deliberately do not call the frozen FrameAni factory or SetMixColor.
        if self.effects or self.controls:
            raise RuntimeError('Static particle candidate cannot own shared FrameAni draws')

    def configure(self, mode='all'):
        IntegratedProbe.configure(self, mode)
        for role, layer in ROLES:
            draw = self.particle_draws.get(role)
            if mode == 'all':
                if draw is None:
                    draw = ParticleDraw(self, role, layer)
                    self.particle_draws[role] = draw
                draw.show()
            elif draw is not None:
                draw.destroy()
        return self.snapshot()

    def pause_particles(self, include_reference=True):
        self._idle()
        for draw in self.particle_draws.values():
            if draw.entity is not None:
                draw.pause()
        fixture = self.known_fixture
        if include_reference and fixture.draw is not None:
            fixture.draw.pause()
        return self.snapshot()

    def snapshot(self):
        result = IntegratedProbe.snapshot(self)
        result['particle_candidate'] = {
            'schema': 'static_independent_particle_candidate_v1',
            'viewport': list(VIEWPORT), 'roi': list(ROI),
            'draws': {key: value.snapshot() for key, value in self.particle_draws.items()},
            'sfx_overlay_omitted': True, 'runtime_file_writes': False,
            'after_weather_order_verified': False, 'native_shadow_compatibility_verified': False}
        return result

    def Destroy(self):
        for draw in self.particle_draws.values():
            draw.destroy()
        IntegratedProbe.Destroy(self)
