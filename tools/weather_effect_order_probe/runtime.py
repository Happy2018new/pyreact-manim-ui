# -*- coding: utf-8 -*-
"""Finite native frame-effect controls and same-texture RGB/alpha oracle."""
import mod.client.extraClientApi as api

ClientSystem=api.GetClientSystemCls()


class ProbeSystem(ClientSystem):
    def __init__(self,namespace,name):
        ClientSystem.__init__(self,namespace,name)
        self.factory=api.GetEngineCompFactory()
        self.level=api.GetLevelId()
        self.camera=self.factory.CreateCamera(self.level)
        self.post=self.factory.CreatePostProcess(self.level)
        self.effect=None
        self.control=None
        self.anchor=None
        self.origin=None
        self.visible=False
        self.seed=42
        self.layer=1
        self.installed=False
        self.post_enabled=False
        self.post_slot=0
        self.query_mode=0
        self.flip=True
        self.saved_post=[]
        self.calls=[]

    def prepare_camera(self):
        position=self.camera.GetPosition()
        self.origin=(int(position[0]),int(position[1])-1,int(position[2]))
        self.camera.DepartCamera()
        point=(self.origin[0],self.origin[1]+1.,self.origin[2])
        if not self.camera.SetCameraPos(point) or not self.camera.SetCameraRotation((8.,180.,0.)):
            raise RuntimeError('Fixed test camera rejected')
        return self.snapshot()

    def create(self):
        if self.effect is not None:
            raise RuntimeError('One frame effect already exists')
        position,forward=self.camera.GetPosition(),self.camera.GetForward()
        self.anchor=tuple(position[index]+forward[index]*4. for index in range(3))
        self.effect=self.CreateEngineSfxFromEditor('effects/order_frame.json',self.anchor,(0.,0.,0.),(4.,4.,4.))
        if self.effect is None:
            raise RuntimeError('Native frame effect creation failed')
        self.control=self.factory.CreateFrameAniControl(self.effect)
        for name,accepted in (('face_camera',self.control.SetFaceCamera(True)),('loop',self.control.SetLoop(True))):
            self.calls.append([name,bool(accepted)])
            if not accepted:
                raise RuntimeError('Frame control rejected: '+name)
        return self.configure(False,42,1)

    def configure(self,visible=True,seed=42,layer=1):
        if self.control is None or not 0<=int(seed)<=255 or layer not in (1,15):
            raise ValueError('Invalid finite frame configuration')
        for name,accepted in (('layer',self.control.SetLayer(layer)),
                ('mix_color',self.control.SetMixColor((seed/255.,.25,.75,1.))),
                ('play' if visible else 'stop',self.control.Play() if visible else self.control.Stop())):
            self.calls.append([name,bool(accepted)])
            if not accepted:
                raise RuntimeError('Frame control rejected: '+name)
        self.visible,self.seed,self.layer=bool(visible),int(seed),layer
        return self.snapshot()

    def install_post(self):
        if self.installed:
            raise RuntimeError('Post oracle already installed')
        self.saved_post=[(name,self.post.CheckEnabledByName(name)) for name in self.post.GetPostProcessOrder() or []]
        if any(enabled for name,enabled in self.saved_post):
            raise RuntimeError('Isolated native post enable-off config is not effective')
        process={'name':'weather_effect_oracle','enable':False,'paras':[
            {'name':'roi','value':[72.,162.,576.,216.],'range':[0.,1048576.]},
            {'name':'control','value':[720.,1080.,0.,1.],'range':[0.,1048576.]},
            {'name':'output','value':[0.,600.,720.,124416.],'range':[0.,1048576.]}],
            'pass_array':[{'render_target':{'width':1.,'height':1.},'material':'weather_effect_oracle','depth_enable':False}]}
        if not self.post.AddPostProcess(process,0):
            raise RuntimeError('Post oracle rejected')
        self.installed=True
        return self.snapshot()

    def inspect(self,enabled=True,slot=0,flip=True,mode=0):
        if not self.installed or slot not in (0,1) or mode not in (0,1,2):
            raise ValueError('Invalid effect post inspection')
        # Source and output map are fixed; mode0 emits adjacent RGB / alpha
        # samples from the SAME original texture fetch. mode1/2 are indexed32B.
        if not self.post.SetParameter('weather_effect_oracle','control',[720.,1080.,float(slot),float(bool(flip))]):
            raise RuntimeError('Post sampler control rejected')
        if not self.post.SetParameter('weather_effect_oracle','output',[float(mode),600.,720.,124416.]):
            raise RuntimeError('Post output control rejected')
        if not self.post.SetEnableByName('weather_effect_oracle',bool(enabled)):
            raise RuntimeError('Post oracle enable rejected')
        self.post_enabled=bool(enabled)
        self.post_slot,self.query_mode,self.flip=slot,mode,bool(flip)
        return self.snapshot()

    def remove(self):
        if self.effect is not None:
            self.control.Stop()
            if not self.DestroyEntity(self.effect):
                raise RuntimeError('Owned frame effect removal rejected')
        self.effect=self.control=None
        self.visible=False
        return self.snapshot()

    def snapshot(self):
        return {'schema':'weather_effect_order_v1','effect':self.effect,'anchor':self.anchor,
            'camera_origin':self.origin,'visible_requested':self.visible,'seed':self.seed,'layer_requested':self.layer,
            'installed':self.installed,'post_slot':self.post_slot,'query_mode':self.query_mode,'source_flip':self.flip,
            'post_enabled':self.post.CheckEnabledByName('weather_effect_oracle') if self.installed else False,
            'source_roi':[72,162,576,216],'output_roi':[0,600,720,346],
            'alpha_write_disabled':True,'controls':list(self.calls[-12:]),
            'saved_native_post_states':list(self.saved_post),
            'actual_post_order':list(self.post.GetPostProcessOrder() or []),
            'seed_transport':'documented FrameAniControl.SetMixColor to native EXTRA_VECTOR3.r',
            'runtime_file_writes':False,'continuous_update':False}

    def Destroy(self):
        if self.control is not None:
            self.control.Stop()
        if self.effect is not None:
            self.DestroyEntity(self.effect)
        self.effect=self.control=None
        if self.installed:
            self.post.SetEnableByName('weather_effect_oracle',False)
            for name,enabled in self.saved_post:
                if enabled:
                    self.post.SetEnableByName(name,True)
        self.camera.ResetCameraPos()
        self.camera.UnDepartCamera()
