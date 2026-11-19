# -*- coding: utf-8 -*-
"""Static-only dimension recovery; native acceptance still needs pixel readback."""
import math
import traceback
import mod.client.extraClientApi as api
from stencil_large.integrated_runtime import ProbeSystem as IntegratedProbe, PROCESSES, LINKS
from stencil_large.runtime import CLOCK, _checksum


EVENTS = (('DimensionChangeClientEvent', 'on_dimension_start'),
          ('DimensionChangeFinishClientEvent', 'on_dimension_finish'))
MAX_TRANSITIONS = 8
RECOVERY_TIMEOUT = 20.


def _vector(value):
    return (isinstance(value, (list, tuple)) and len(value) == 3 and
            all(isinstance(item, (int, float)) and not isinstance(item, bool) and
                not math.isnan(item) and not math.isinf(item) for item in value))


class ProbeSystem(IntegratedProbe):
    def __init__(self, namespace, name):
        self.dimension_recovery = {'phase': 'idle', 'serial': 0, 'ready_serial': None,
            'pair': None, 'start_frame': None, 'finish_frame': None, 'error': None,
            'duplicate_starts': 0, 'ignored_finishes': 0, 'api_receipts': [],
            'history': [], 'strategy': 'reattach_retained_geometry',
            'pixel_verified': False, 'runtime_file_writes': False}
        self._dimension_saved = None
        self._dimension_internal = False
        self._dimension_events_registered = False
        IntegratedProbe.__init__(self, namespace, name)
        for event, handler in EVENTS:
            self.ListenForEvent(api.GetEngineNamespace(), api.GetEngineSystemName(),
                                event, self, getattr(self, handler))
        self._dimension_events_registered = True

    def _idle(self):
        if (not self._dimension_internal and
                self.dimension_recovery['phase'] not in ('idle', 'ready')):
            raise RuntimeError('Dimension recovery is pending or faulted')
        IntegratedProbe._idle(self)

    def _local_pair(self, args):
        if not isinstance(args, dict) or args.get('playerId') != api.GetLocalPlayerId():
            return None
        pair = (args.get('fromDimensionId'), args.get('toDimensionId'))
        if any(not isinstance(item, int) or isinstance(item, bool) or item < 0 for item in pair):
            return None
        return pair if pair[0] != pair[1] else None

    def _receipt(self, operation, accepted, **extra):
        row = {'operation': operation, 'accepted': accepted, 'frame': self.render_event}
        row.update(extra)
        self.dimension_recovery['api_receipts'].append(row)
        if accepted is not True:
            raise RuntimeError('Dimension recovery SDK rejected '+operation)

    def _fail_dimension(self, message):
        recovery = self.dimension_recovery
        recovery['phase'], recovery['error'], recovery['ready_serial'] = 'failed', message, None
        self.pipeline_ready = False
        self.error = message

    def on_dimension_start(self, args):
        pair = self._local_pair(args)
        if pair is None:
            return
        recovery = self.dimension_recovery
        if (tuple(recovery['pair'] or ()) == pair and
                (recovery['phase'] not in ('idle', 'ready') or self.game.GetCurrentDimension() == pair[1])):
            recovery['duplicate_starts'] += 1
            return
        if recovery['phase'] not in ('idle', 'ready'):
            self._fail_dimension('A different dimension transition superseded pending recovery')
            return
        recovery['serial'] += 1
        recovery.update(phase='waiting_finish', ready_serial=None, pair=list(pair),
                        start_frame=self.render_event, finish_frame=None, error=None,
                        api_receipts=[], pixel_verified=False)
        # Invalidate the cached post links before any later snapshot can claim readiness.
        linked = self.pipeline_ready
        self.pipeline_ready, self.pipeline_links = False, []
        if (recovery['serial'] > MAX_TRANSITIONS or self.state != 'resident' or
                self.payload is None or self.upload is not None or self.measurement is not None or
                self.build_busy or self.error is not None or not linked):
            self._fail_dimension('Dimension recovery requires idle linked static resident bytes within transition budget')
            return
        for controller in (self.known_fixture, self.ui_clip, self.outline,
                           getattr(self, 'ordinary_frameani', None)):
            if controller is not None and any(controller.snapshot().get(key) for key in ('visible', 'enabled')):
                self._fail_dimension('Disable optional scene fixtures before static dimension recovery')
                return
        specs = []
        for actor in self.actors:
            specs.append(dict((key, actor[key]) for key in
                              ('kind', 'index', 'count', 'stride', 'offset', 'pages')))
        self._dimension_saved = {'payload': self.payload, 'identity': dict(self.identity),
            'serial': recovery['serial'], 'pair': list(pair),
            'generation': self.generation, 'pages': list(self.pages), 'specs': specs,
            'mode': self.mode, 'consumer_mode': self.consumer_mode,
            'shape_enabled': self.shape_enabled, 'restore_enabled': self.restore_enabled,
            'pipeline_enabled': self.pipeline_enabled, 'camera': self.camera.GetPosition(),
            'effects': list(self.effects), 'native_attempts': len(self.attempts),
            'deadline': CLOCK()+RECOVERY_TIMEOUT}

    def _same_transition(self, expected_phase):
        saved, recovery = self._dimension_saved, self.dimension_recovery
        if (recovery['phase'] != expected_phase or recovery['serial'] != saved['serial'] or
                recovery['pair'] != saved['pair']):
            raise RuntimeError('Deferred dimension recovery was superseded before publication')

    def on_dimension_finish(self, args):
        pair = self._local_pair(args)
        recovery = self.dimension_recovery
        if (pair is None or recovery['phase'] != 'waiting_finish' or
                pair != tuple(recovery['pair'] or ()) or self.game.GetCurrentDimension() != pair[1]):
            recovery['ignored_finishes'] += 1
            return
        recovery.update(phase='wait_camera_request', finish_frame=self.render_event)

    def _request_camera(self):
        saved = self._dimension_saved
        self.game = self.factory.CreateGame(self.level)
        self.camera = self.factory.CreateCamera(self.level)
        self.post = self.factory.CreatePostProcess(self.level)
        if not _vector(saved['camera']):
            raise RuntimeError('Static recovery camera pose was unavailable')
        self.camera.DepartCamera()
        self._receipt('SetCameraPos', self.camera.SetCameraPos(tuple(saved['camera'])))
        self._receipt('SetCameraRotation', self.camera.SetCameraRotation((8., 180., 0.)))
        self._same_transition('wait_camera_request')
        self.dimension_recovery.update(phase='wait_camera', stage_frame=self.render_event)

    def _recreate(self):
        saved = self._dimension_saved
        position, forward = self.camera.GetPosition(), self.camera.GetForward()
        if not _vector(position) or not _vector(forward) or sum(v*v for v in forward) == 0.:
            raise RuntimeError('Static recovery camera did not settle')
        if any(abs(position[i]-saved['camera'][i]) > .01 for i in range(3)):
            raise RuntimeError('Static recovery camera differs from its requested pose')
        self.anchor = tuple(position[i]+forward[i]*3. for i in range(3))
        # Client-only actors are automatically removed by dimension changes (ModSDK).
        # SFX have a separate lifecycle; record each explicit destruction response.
        for effect in saved['effects']:
            result = self.DestroyEntity(effect)
            self.dimension_recovery['api_receipts'].append({
                'operation': 'DestroyEntity(old_effect)', 'accepted': result,
                'effect': effect, 'frame': self.render_event, 'already_absent_possible': True})
        self.actors, self.writer_actors, self.active_pages = [], [], []
        self.effects, self.controls, self.clear_actor = [], [], None
        self.payload_visible, self.clear_visible = False, False
        for spec in saved['specs']:
            actor = self._new_actor(spec['kind'], spec['index'])
            for key in ('count', 'stride', 'offset'):
                actor[key] = spec[key]
            actor['ready'] = self._actor_uniforms(actor)
            if spec['kind'] == 'clear':
                self.clear_actor = actor
            else:
                self.writer_actors.append(actor)
            for name in spec['pages']:
                self._receipt('AddActorBlockGeometry', actor['render'].AddActorBlockGeometry(
                    name, (0., 0., 0.), (0., 0., 0.)), geometry=name, entity=actor['entity'])
                actor['pages'].append(name)
                self._receipt('SetActorBlockGeometryVisible(hidden)',
                              actor['render'].SetActorBlockGeometryVisible(name, False), geometry=name)
                if spec['kind'] != 'clear':
                    self.active_pages.append({'name': name, 'actor': actor})
        self._effects_ready()
        order = list(self.post.GetPostProcessOrder() or [])
        present = [name for name in order if name in PROCESSES]
        if present and present != list(PROCESSES):
            raise RuntimeError('Partially stale or reordered native post processes require an explicit new project')
        if not present:
            self.pipeline_registered = []
            self.pipeline_installed, self.pipeline_enabled = False, False
            IntegratedProbe.install_pipeline(self)
        else:
            self.pipeline_registered, self.pipeline_installed = list(PROCESSES), True
            self.pipeline_install_frame = self.render_event
            self._pipeline_controls(0, False, False)
            for name in PROCESSES:
                self._receipt('SetEnableByName(prime)', self.post.SetEnableByName(name, True), process=name)
        self.pipeline_ready, self.pipeline_links = False, []
        self._same_transition('wait_camera')
        self.dimension_recovery.update(phase='wait_links', stage_frame=self.render_event)

    def _publish(self):
        saved = self._dimension_saved
        if not self._ready():
            for actor in self.actors:
                actor['ready'] = self._actor_uniforms(actor)
            if not self._ready():
                return
        self.pipeline_link_attempts += 1
        for link in LINKS:
            self._receipt('PostPassResultToOtherPass', self.post.PostPassResultToOtherPass(*link),
                          link=list(link))
            self.pipeline_links.append(link)
        order = [name for name in (self.post.GetPostProcessOrder() or []) if name in PROCESSES]
        if order != list(PROCESSES):
            raise RuntimeError('Native process order changed while relinking dimension recovery')
        self.pipeline_ready = True
        self.configure(saved['mode'])
        self.inspect(saved['consumer_mode'], saved['shape_enabled'],
                     saved['pipeline_enabled'], saved['restore_enabled'])
        if (self.payload is not saved['payload'] or self.identity != saved['identity'] or
                self.generation != saved['generation'] or self.pages != saved['pages'] or
                len(self.attempts) != saved['native_attempts'] or
                _checksum(bytearray(self.payload)) != saved['identity']['adler32']):
            raise RuntimeError('Static payload or native page identity changed during recovery')
        self._same_transition('wait_links')
        if self.game.GetCurrentDimension() != saved['pair'][1]:
            raise RuntimeError('Native dimension changed during recovery publication')
        recovery = self.dimension_recovery
        recovery.update(phase='ready', ready_serial=recovery['serial'], completed_frame=self.render_event)
        recovery['history'].append({'serial': recovery['serial'], 'pair': list(recovery['pair']),
            'ready_frame': self.render_event, 'identity': dict(self.identity),
            'geometry_names': list(self.pages), 'pixel_verified': False})

    def on_frame(self, args):
        phase = self.dimension_recovery['phase']
        if phase in ('idle', 'ready'):
            IntegratedProbe.on_frame(self, args)
            return
        self.render_event += 1
        if phase == 'failed':
            return
        self._dimension_internal = True
        try:
            if CLOCK() > self._dimension_saved['deadline']:
                raise RuntimeError('Static dimension recovery timed out')
            if phase == 'waiting_finish':
                return
            if self.game.GetCurrentDimension() != self.dimension_recovery['pair'][1]:
                raise RuntimeError('Dimension changed again during recovery')
            if phase == 'wait_camera_request' and self.render_event > self.dimension_recovery['finish_frame']:
                self._request_camera()
            elif phase == 'wait_camera' and self.render_event > self.dimension_recovery['stage_frame']+1:
                self._recreate()
            elif phase == 'wait_links' and self.render_event > self.dimension_recovery['stage_frame']:
                self._publish()
        except (RuntimeError, ValueError, TypeError, KeyError) as error:
            traceback.print_exc()
            self._fail_dimension(str(error))
        finally:
            self._dimension_internal = False

    def snapshot(self):
        result = IntegratedProbe.snapshot(self)
        recovery = dict(self.dimension_recovery)
        recovery['api_receipts'] = [dict(row) for row in recovery['api_receipts']]
        recovery['history'] = [dict(row) for row in recovery['history']]
        result['dimension_recovery'] = recovery
        if recovery['phase'] not in ('idle', 'ready'):
            result['ready'] = False
        return result

    def Destroy(self):
        if self._dimension_events_registered:
            for event, handler in EVENTS:
                self.UnListenForEvent(api.GetEngineNamespace(), api.GetEngineSystemName(),
                                      event, self, getattr(self, handler))
            self._dimension_events_registered = False
        IntegratedProbe.Destroy(self)
