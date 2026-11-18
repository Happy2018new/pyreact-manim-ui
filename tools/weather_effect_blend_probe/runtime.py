# -*- coding: utf-8 -*-
"""43 six-bit symbols, native k2 blending and an early-copy late reader."""
from weather_effect_order_probe.runtime_base import ProbeSystem as BaseProbeSystem


class ProbeSystem(BaseProbeSystem):
    def __init__(self,namespace,name):
        BaseProbeSystem.__init__(self,namespace,name)
        self.effects=[]
        self.controls=[]
        self.payload=[0]*32
        self.payload_version=0
        self.packed_colors=[]
        self.symbols=[]
        self.restore_enabled=False
        self.copy_connected=False

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
        symbols=[]
        for index in range(43):
            bit=index*6
            offset,shift=bit//8,bit%8
            value=values[offset]>>shift
            if shift>2 and offset+1<32:
                value|=values[offset+1]<<(8-shift)
            symbols.append(value&63)
        padded=symbols+[0]*5
        colors=[]
        for page in range(4):
            color=[]
            for channel in range(3):
                offset=page*12+channel*4
                word=padded[offset]*262144+padded[offset+1]*4096+padded[offset+2]*64+padded[offset+3]
                color.append(word/16777216.)
            color.append((page+1)/8.)
            accepted=self.controls[page].SetMixColor(tuple(color))
            self.calls.append(['mix_color',page,bool(accepted)])
            if not accepted:
                raise RuntimeError('Public packed mix-color rejected')
            colors.append(color)
        self.payload=list(values)
        self.symbols=symbols
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

    def install_post(self):
        if self.installed:
            raise RuntimeError('Blend chain already installed')
        self.saved_post=[(name,self.post.CheckEnabledByName(name)) for name in self.post.GetPostProcessOrder() or []]
        if any(enabled for name,enabled in self.saved_post):
            raise RuntimeError('Isolated native post enable-off config is not effective')
        process={'name':'weather_effect_oracle','enable':False,'paras':[
            {'name':'roi','value':[72.,162.,576.,216.],'range':[0.,1048576.]},
            {'name':'control','value':[720.,1080.,3.,1.],'range':[0.,1048576.]},
            {'name':'output','value':[0.,500.,720.,124416.],'range':[0.,1048576.]}],
            'pass_array':[{'render_target':{'width':1.,'height':1.},'material':'blend_'+name,'depth_enable':False}
                for name in ('copy','restore','inspect')]}
        if not self.post.AddPostProcess(process,0):
            raise RuntimeError('Blend chain rejected')
        self.copy_connected=self.post.PostPassResultToOtherPass('weather_effect_oracle',0,'weather_effect_oracle',2,3)
        if not self.copy_connected:
            raise RuntimeError('Public early-copy to late-consumer slot3 connection rejected')
        self.installed=True
        return self.snapshot()

    def inspect(self,enabled=True,slot=3,flip=True,mode=0,restore=True):
        if not self.installed or slot not in (0,1,3) or mode not in (0,1,2,3):
            raise ValueError('Invalid finite blend inspection')
        changes=(('control',[720.,1080.,float(slot),float(bool(flip))]),
            ('output',[float(mode+8*bool(restore)),500.,720.,124416.]))
        for name,value in changes:
            if not self.post.SetParameter('weather_effect_oracle',name,value):
                raise RuntimeError('Blend post parameter rejected: '+name)
        if not self.post.SetEnableByName('weather_effect_oracle',bool(enabled)):
            raise RuntimeError('Blend post enable rejected')
        self.post_enabled,self.post_slot,self.query_mode,self.flip=bool(enabled),slot,mode,bool(flip)
        self.restore_enabled=bool(restore)
        return self.snapshot()

    def snapshot(self):
        result=BaseProbeSystem.snapshot(self)
        result.pop('seed')
        result.pop('seed_transport')
        result.update({'schema':'weather_effect_k2_blend32_v1','effects':list(self.effects),
            'payload':list(self.payload),'payload_version':self.payload_version,
            'symbols':list(self.symbols),'symbol_count':43,'final_padding_bits':2,
            'packed_colors':list(self.packed_colors),'effect_count':len(self.effects),
            'payload_transport':'four public SetMixColor, 4 six-bit symbols per uint24 RGB word, page alpha',
            'rgb_blend':['SourceAlpha','OneMinusSrcAlpha'],'source_alpha':192/255.,
            'restore_enabled':self.restore_enabled,'copy_connected':self.copy_connected,
            'post_chain':['raw_copy','restore_rgb_pass_alpha','late_TEXTURE_3_consumer'],
            'output_roi':[0,500,720,519],
            'gpu_payload_seed':False,'arbitrary_32_byte_upload':True})
        return result

    def Destroy(self):
        self.remove()
        BaseProbeSystem.Destroy(self)
