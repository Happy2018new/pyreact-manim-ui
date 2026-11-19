# -*- coding: utf-8 -*-
"""Ordinary native FrameAni controls only; no events, material or shader changes."""
import math


ROUTES = ('sequence', 'point_sequence', 'point_sequence_add', 'sequence_add')
CENTERS = {'inside':(264.,352.), 'outside':(616.,352.)}


def _dot(a,b):
    return sum(a[i]*b[i] for i in range(3))


def _plane_point(camera, point, normal, distance, x, y):
    ray = camera.GetWorldRayFromScreenPoint(float(x),float(y))
    if not ray or 'origin' not in ray or 'direction' not in ray:
        raise RuntimeError('Native screen-to-world ray unavailable')
    origin, direction = ray['origin'], ray['direction']
    denominator = _dot(direction,normal)
    if denominator <= 0.:
        raise RuntimeError('Screen ray does not meet the camera-facing fixture plane')
    relative = tuple(origin[i]-point[i] for i in range(3))
    amount = (distance-_dot(relative,normal))/denominator
    return tuple(origin[i]+amount*direction[i] for i in range(3))


class FrameAniFixture(object):
    def __init__(self,probe):
        self.probe = probe
        self.effects, self.controls = {}, {}
        self.location, self.position, self.scale, self.expected_bounds = None, None, None, None
        self.world_corners, self.initial_camera = [], None
        self.route, self.visible, self.tint, self.layer = None, False, [1.,1.,1.,1.], 1

    def _idle(self):
        if getattr(self.probe,'measurement',None) is not None:
            raise RuntimeError('Configure ordinary FrameAni outside timing samples')

    def create(self,location='inside',distance=4.,span=96.,scale_multiplier=1.,layer=1):
        self._idle()
        if self.effects or location not in CENTERS or not 1. <= distance <= 16. or not 48. <= span <= 128.:
            raise ValueError('Need an empty fixture, fixed location, distance1..16 and span48..128')
        if not 0.0625 <= scale_multiplier <= 16. or layer not in (1,12):
            raise ValueError('Use an explicit preselected scale multiplier and layer1or12')
        camera = self.probe.camera
        point, normal = camera.GetPosition(), camera.GetForward()
        if point is None or normal is None:
            raise RuntimeError('Prepare a stationary native camera first')
        length = math.sqrt(_dot(normal,normal))
        normal = tuple(value/length for value in normal)
        x,y = CENTERS[location]
        self.world_corners = [_plane_point(camera,point,normal,distance,x+dx*span,y+dy*span)
                              for dx,dy in ((-.5,-.5),(.5,-.5),(.5,.5),(-.5,.5))]
        self.position = _plane_point(camera,point,normal,distance,x,y)
        horizontal = math.sqrt(sum((self.world_corners[1][i]-self.world_corners[0][i])**2 for i in range(3)))
        vertical = math.sqrt(sum((self.world_corners[3][i]-self.world_corners[0][i])**2 for i in range(3)))
        self.scale = (horizontal*scale_multiplier,vertical*scale_multiplier,1.)
        self.initial_camera = {'position':point,'forward':camera.GetForward()}
        self.expected_bounds, self.location, self.layer = [x-span/2,y-span/2,x+span/2,y+span/2],location,layer
        for route in ROUTES:
            effect = self.probe.CreateEngineSfxFromEditor('effects/native_frameani_'+route+'.json',
                self.position,(0.,0.,0.),self.scale)
            if effect is None:
                raise RuntimeError('Ordinary native FrameAni creation rejected: '+route)
            self.effects[route] = effect
            control = self.probe.factory.CreateFrameAniControl(effect)
            self.controls[route] = control
            if not (control.SetFaceCamera(True) and control.SetLoop(True) and control.SetLayer(layer)
                    and control.SetMixColor((1.,1.,1.,1.)) and control.Stop()):
                raise RuntimeError('Ordinary native FrameAni controls rejected: '+route)
        return self.snapshot()

    def set_route(self,route,enabled=True,tint=(1.,1.,1.,1.)):
        self._idle()
        if route not in self.controls or len(tint)!=4 or any(not 0.<=value<=1. for value in tint):
            raise ValueError('Choose a created route and four normalized tint values')
        for name,control in self.controls.items():
            if not control.Stop():
                raise RuntimeError('Ordinary native FrameAni isolation stop rejected')
        control = self.controls[route]
        if not control.SetMixColor(tuple(float(value) for value in tint)):
            raise RuntimeError('Ordinary native FrameAni tint rejected')
        if enabled and not control.Play():
            raise RuntimeError('Ordinary native FrameAni play rejected')
        self.route,self.visible,self.tint = route,bool(enabled),list(tint)
        return self.snapshot()

    def snapshot(self):
        camera = {'position':self.probe.camera.GetPosition(),'forward':self.probe.camera.GetForward()}
        projected = [self.probe.camera.WorldToScreenPoint(*point) for point in self.world_corners]
        x,y = CENTERS[self.location] if self.location is not None else (0.,0.)
        patches = [{'name':name,'rect':[int(x+dx),int(y+dy),6,6],'rgba':rgba}
            for name,dx,dy,rgba in (('red_opaque',-12,-12,[240,32,48,255]),
                ('green_alpha192',6,-12,[32,224,64,192]),('blue_alpha128',-12,6,[40,64,240,128]),
                ('transparent',6,6,[0,0,0,0]))] if self.location is not None else []
        return {'schema':'ordinary_native_frameani_fixture_v1','effects':dict(self.effects),
            'route':self.route,'visible':self.visible,'tint':list(self.tint),'layer':self.layer,
            'location':self.location,'position':self.position,'scale':self.scale,
            'expected_bounds':self.expected_bounds,'predeclared_patches':patches,
            'expected_plane_world_corners':list(self.world_corners),'projected_plane_corners':projected,
            'native_quad_extent_verified':False,'native_quad_unit_size_documented':False,
            'patches_establish_native_positive_before_carrier_comparison':True,
            'camera':camera,'initial_camera':self.initial_camera,'camera_matches_initial':camera==self.initial_camera,
            'materials_or_shaders_modified':False,'runtime_file_writes':False}

    def destroy(self):
        self._idle()
        for control in self.controls.values():
            control.Stop()
        for effect in self.effects.values():
            self.probe.DestroyEntity(effect)
        self.effects,self.controls = {},{}
        self.route,self.visible = None,False
