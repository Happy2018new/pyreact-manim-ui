# -*- coding: utf-8 -*-
"""Client-only native outline fixture. No events, motion or runtime file writes."""
import math


ENTITY = 'pmanim_integrated_outline:cube'
QUERY = 'query.mod.pmanim_integrated_outline_enabled'
MATERIAL_VALUES = ('entity_alphatest_netease', 'netease_entity_alphatest_outline_base',
                   'netease_entity_alphatest_outline')
CONTROLLERS = ('controller.render.pmanim_integrated_outline.base',
               'controller.render.pmanim_integrated_outline.outline')


class OutlineFixture(object):
    def __init__(self, probe):
        self.probe = probe
        self.entity, self.query, self.render = None, None, None
        self.registered, self.enabled = False, False
        self.position, self.roi, self.viewport = None, None, None
        self.initial_camera = None

    def _camera_state(self):
        return {'position': self.probe.camera.GetPosition(),
                'forward': self.probe.camera.GetForward()}

    def _position_at_roi_edge(self, distance):
        x, y, width, height = self.roi
        ray = self.probe.camera.GetWorldRayFromScreenPoint(x + width, y + height * .5)
        if not ray or not ray.get('origin') or not ray.get('direction'):
            raise RuntimeError('Native ROI-edge world ray unavailable')
        origin, direction = ray['origin'], ray['direction']
        length = math.sqrt(sum(value * value for value in direction))
        if length <= 0.:
            raise RuntimeError('Native ROI-edge ray has zero direction')
        center = [origin[i] + direction[i] * distance / length for i in range(3)]
        return (center[0], center[1] - .5, center[2])

    def create(self, roi=None, viewport=None, position=None, distance=4.0):
        """Place once at the right ROI edge; on/off only changes native query."""
        if self.entity is not None or self.registered:
            raise RuntimeError('Destroy the previous outline fixture before create')
        self.roi = list(roi if roi is not None else self.probe.roi)
        self.viewport = list(viewport if viewport is not None else self.probe.viewport)
        if len(self.roi) != 4 or len(self.viewport) != 2:
            raise ValueError('Outline fixture needs ROI x/y/width/height and viewport width/height')
        x, y, width, height = self.roi
        if (min(x, y) < 0 or min(width, height) <= 0 or x + width >= self.viewport[0]
                or y + height > self.viewport[1] or distance <= 1.0):
            raise ValueError('ROI right edge needs visible outside space and distance above one block')
        self.position = tuple(position) if position is not None else self._position_at_roi_edge(distance)
        if len(self.position) != 3:
            raise ValueError('Outline position needs three world coordinates')
        self.initial_camera = self._camera_state()
        registry = self.probe.factory.CreateQueryVariable(self.probe.level)
        self.registered = bool(registry.Register(QUERY, 0.0))
        if not self.registered:
            raise RuntimeError('Native outline query registration rejected')
        try:
            self.entity = self.probe.CreateClientEntityByTypeStr(ENTITY, self.position, (0., 0.))
            if self.entity is None:
                raise RuntimeError('Native outline client-only cube creation rejected')
            self.query = self.probe.factory.CreateQueryVariable(self.entity)
            self.render = self.probe.factory.CreateActorRender(self.entity)
            self.probe.factory.CreateModel(self.entity).SetEntityShadowShow(False)
            return self.set_enabled(False)
        except Exception:
            self.destroy()
            raise

    def set_enabled(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError('Outline enabled must be an explicit bool')
        if self.entity is None or not self.registered:
            raise RuntimeError('Create the native outline fixture before toggling')
        if not self.query.Set(QUERY, 1.0 if enabled else 0.0):
            raise RuntimeError('Native outline query update rejected')
        self.enabled = enabled
        if self.query.Get(QUERY) != (1.0 if enabled else 0.0):
            raise RuntimeError('Native outline query readback mismatch')
        return self.snapshot()

    def _project(self, foot):
        points = []
        for dx in (-.5, .5):
            for dy in (0., 1.):
                for dz in (-.5, .5):
                    point = self.probe.camera.WorldToScreenPoint(
                        foot[0] + dx, foot[1] + dy, foot[2] + dz)
                    if not point:
                        return [], None
                    points.append(point)
        if any('screenX' not in point or 'screenY' not in point for point in points):
            return points, None
        return points, [min(point['screenX'] for point in points),
                        min(point['screenY'] for point in points),
                        max(point['screenX'] for point in points),
                        max(point['screenY'] for point in points)]

    def snapshot(self):
        state = {'kind': 'integrated_native_outline_fixture_v1', 'entity': self.entity,
                 'registered': self.registered, 'requested_enabled': self.enabled,
                 'requested_position': self.position, 'roi': self.roi, 'viewport': self.viewport,
                 'native_stencil_ref': 117, 'native_stencil_mask': 117,
                 'shared_transport_bits': 64, 'runtime_file_writes': False,
                 'native_visible_positive_control_verified': False,
                 'native_data_compatibility_verified': False,
                 'query_readback_is_render_proof': False}
        if self.entity is None:
            return state
        foot = self.probe.factory.CreatePos(self.entity).GetFootPos()
        camera = self._camera_state()
        projected, bounds = self._project(foot) if foot is not None else ([], None)
        stable = foot is not None and all(abs(foot[i] - self.position[i]) <= .0001 for i in range(3))
        materials = self.render.GetActorRenderParams(self.entity, 'materials', True)
        controllers = self.render.GetActorRenderParams(self.entity, 'render_controllers', True)
        state.update({'native_query': self.query.Get(QUERY), 'native_position': foot,
                      'position_matches_requested': stable, 'camera': camera,
                      'initial_camera': self.initial_camera,
                      'camera_matches_initial': camera == self.initial_camera,
                      'projected_corners': projected, 'projected_bounds': bounds,
                      'projection_all_visible': len(projected) == 8 and all(
                          point.get('isInScreen') and point.get('depth', 0.) > 0.
                          for point in projected),
                      'registered_material_values': materials,
                      'registered_render_controllers': controllers,
                      'native_material_recipe_present': materials is not None and all(
                          value in materials for value in MATERIAL_VALUES),
                      'native_render_controllers_present': controllers is not None and all(
                          value in controllers for value in CONTROLLERS)})
        return state

    def destroy(self):
        """SDK destroy has no return value; unregister only our successful registration."""
        entity = self.entity
        try:
            if entity is not None:
                self.probe.DestroyClientEntity(entity)
        finally:
            self.entity, self.query, self.render = None, None, None
            self.enabled = False
            if self.registered:
                registry = self.probe.factory.CreateQueryVariable(self.probe.level)
                removed = registry.UnRegister(QUERY)
                self.registered = False
                if not removed:
                    raise RuntimeError('Native outline query unregister rejected')
        return {'destroy_requested_entity': entity, 'query_registered': self.registered,
                'destroy_sdk_has_return_value': False}
