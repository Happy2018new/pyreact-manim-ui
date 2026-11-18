# -*- coding: utf-8 -*-
"""Arbitrary32B via four public FrameAni SetMixColor controls; no file writes."""
from weather_effect_order_probe.runtime_base import ProbeSystem as BaseProbeSystem


class ProbeSystem(BaseProbeSystem):
    def __init__(self,namespace,name):
        BaseProbeSystem.__init__(self,namespace,name)
        self.effects=[]
        self.controls=[]
        self.payload=[0]*32
        self.payload_version=0
        self.packed_colors=[]

    def create(self):
        if self.effects:
            raise RuntimeError('Packed frame effects already exist')
        position,forward=self.camera.GetPosition(),self.camera.GetForward()
        self.anchor=tuple(position[index]+forward[index]*4. for index in range(3))
        for page in range(4):
            effect=self.CreateEngineSfxFromEditor('effects/order_frame.json',self.anchor,(0.,0.,0.),(4.,4.,4.))
            if effect is None:
                raise RuntimeError('Native packed frame effect creation failed')
            self.effects.append(effect)
            control=self.factory.CreateFrameAniControl(effect)
            self.controls.append(control)
            for name,accepted in (('face_camera',control.SetFaceCamera(True)),('loop',control.SetLoop(True))):
                self.calls.append([name,page,bool(accepted)])
                if not accepted:
                    raise RuntimeError('Packed frame control rejected: '+name)
        self.write([0]*32)
        return self.configure(False,15)

    def write(self,values):
        if len(self.controls)!=4 or not isinstance(values,(list,tuple)) or len(values)!=32:
            raise ValueError('Expected exactly 32 arbitrary integer bytes and four controls')
        for value in values:
            if not isinstance(value,(int,long)) or not 0<=value<=255:
                raise ValueError('Payload value is not a byte')
        padded=list(values)+[0]*4
        colors=[]
        for page in range(4):
            color=[]
            for channel in range(3):
                offset=page*9+channel*3
                word=padded[offset]*65536+padded[offset+1]*256+padded[offset+2]
                color.append(word/16777216.)
            color.append((page+1)/8.)
            accepted=self.controls[page].SetMixColor(tuple(color))
            self.calls.append(['mix_color',page,bool(accepted)])
            if not accepted:
                raise RuntimeError('Public packed mix-color rejected')
            colors.append(color)
        self.payload=list(values)
        self.packed_colors=colors
        self.payload_version+=1
        return self.snapshot()

    def configure(self,visible=True,layer=15):
        if len(self.controls)!=4 or layer not in (1,15):
            raise ValueError('Invalid finite packed frame configuration')
        for page,control in enumerate(self.controls):
            for name,accepted in (('layer',control.SetLayer(layer)),
                    ('play' if visible else 'stop',control.Play() if visible else control.Stop())):
                self.calls.append([name,page,bool(accepted)])
                if not accepted:
                    raise RuntimeError('Packed frame control rejected: '+name)
        self.visible,self.layer=bool(visible),layer
        return self.snapshot()

    def remove(self):
        for effect,control in zip(self.effects,self.controls):
            control.Stop()
            if not self.DestroyEntity(effect):
                raise RuntimeError('Owned packed frame effect removal rejected')
        self.effects=[]
        self.controls=[]
        self.visible=False
        return self.snapshot()

    def snapshot(self):
        result=BaseProbeSystem.snapshot(self)
        result.pop('seed')
        result.pop('seed_transport')
        result.update({'schema':'weather_effect_packed32_v1','effects':list(self.effects),
            'payload':list(self.payload),'payload_version':self.payload_version,
            'packed_colors':list(self.packed_colors),'effect_count':len(self.effects),
            'payload_transport':'four public FrameAniControl.SetMixColor, RGB uint24/2^24, alpha page/8',
            'gpu_payload_seed':False,'arbitrary_32_byte_upload':True})
        return result

    def Destroy(self):
        self.remove()
        BaseProbeSystem.Destroy(self)
