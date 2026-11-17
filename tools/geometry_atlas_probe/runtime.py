# -*- coding: utf-8 -*-
"""Isolated public-API geometry writer and forward postprocess gather probe."""
import time
import math
import mod.client.extraClientApi as api
from geometry_atlas_probe.codec import encode_values
from geometry_atlas_probe.pipeline_config import PROCESS

ClientSystem=api.GetClientSystemCls()
MASK=0xffffffff
MAX_BYTES=65536
MAX_RECORDS=2097152
MAX_NAMES=256


def byte_at(seed,generation,index):
    value=(seed ^ ((generation*0x9e3779b9)&MASK) ^ ((index*0x85ebca6b)&MASK))&MASK
    value^=value>>16
    value=(value*0x7feb352d)&MASK
    value^=value>>15
    value=(value*0x846ca68b)&MASK
    value^=value>>16
    return value&255


class ProbeSystem(ClientSystem):
    def __init__(self,namespace,system_name):
        ClientSystem.__init__(self,namespace,system_name)
        self.factory=api.GetEngineCompFactory()
        self.level=api.GetLevelId()
        self.game=self.factory.CreateGame(self.level)
        self.block=self.factory.CreateBlock(self.level)
        self.geometry=self.factory.CreateBlockGeometry(self.level)
        self.post=self.factory.CreatePostProcess(self.level)
        self.entity=None
        self.render=None
        self.ready=False
        self.ready_until=0.
        self.error=None
        self.native_hud_hidden=False
        self.seed=0
        self.generation=0
        self.slot_count=0
        self.geometry_name=''
        self.geometry_build_serial=0
        self.native_attempt_serial=0
        self.epoch=0
        self.named_records=0
        self.names=[]
        self.upload_history=[]
        self.writer_visible=True
        self.stride=2
        self.y_offset=8.
        self.center=[.5,.5,.5]
        self.layout=[0,16,8,64]
        self.dimensions=[4,720,1080,0]
        self.query_value=[0,1,0,0]
        self.orientation=[1,0,0,0]
        self.direct_source=False
        self.packed_mode=4
        self.pipeline_installed=False
        self.pipeline_ready=False
        self.connection=False
        self.pipeline=None
        self.timings={}
        self.measurement=None
        self.last_measurement=None
        self.ListenForEvent(api.GetEngineNamespace(),api.GetEngineSystemName(),
                            'GameRenderTickEvent',self,self.on_frame)

    def open(self):
        api.HideHudGUI(True)
        self.native_hud_hidden=True
        if self.entity is None:
            camera=self.factory.CreateCamera(self.level)
            position,forward=camera.GetPosition(),camera.GetForward()
            if position is None or forward is None:
                raise RuntimeError('World camera is not ready')
            anchor=tuple(position[index]+forward[index]*3. for index in range(3))
            self.entity=self.CreateClientEntityByTypeStr('pmanim_geometry_atlas:anchor',anchor,(0.,0.))
            if self.entity is None:
                raise RuntimeError('Client-only anchor creation failed')
            self.render=self.factory.CreateActorRender(self.entity)
            self.factory.CreateModel(self.entity).SetEntityShadowShow(False)
            self.ready_until=time.clock()+10.
            self.error=None
            self.ready=self._writer_controls()
        return self.snapshot()

    def _writer_controls(self):
        groups=((float(self.stride),self.y_offset,float(self.slot_count),float(self.layout[1])),
                tuple(float(value) for value in self.layout[2:]+self.dimensions[:2]),
                (float(self.dimensions[2]),)+tuple(float(value) for value in self.center),
                (float(self.writer_visible),0.,0.,0.))
        return all(self.render.SetEntityExtraUniforms(index+1,group)
                   for index,group in enumerate(groups))

    def on_frame(self,args):
        if self.entity is not None and not self.ready and self.error is None:
            self.ready=self._writer_controls()
            if not self.ready and time.clock()>self.ready_until:
                self.error='Actor uniforms did not become ready before timeout'
        sample=self.measurement
        if sample is None:
            return
        now=time.clock()
        if now>=sample['warm_until'] and sample['previous'] is not None:
            sample['interval_ms'].append((now-sample['previous'])*1000.)
        sample['previous']=now
        sample['frames']+=1
        if now>=sample['warm_until'] and sample['frames']%15==0:
            sample['fps'].append(self.game.GetFps())
        if now>=sample['until']:
            result={'elapsed':now-sample['start'],'frames':sample['frames'],
                'generation':self.generation,'geometry_name':self.geometry_name,
                'geometry_build_serial':self.geometry_build_serial,
                'query':list(self.query_value),'gpu_completion_fence':False}
            for key in ('fps','interval_ms'):
                values=sorted(sample[key])
                result[key]={'count':len(values)}
                if values:
                    result[key].update(mean=sum(values)/len(values),min=values[0],max=values[-1],
                        p95=values[int((len(values)-1)*.95)])
            self.last_measurement=result
            self.measurement=None

    def start_measurement(self,seconds=8.):
        seconds=float(seconds)
        if (not self.pipeline_ready or self.measurement is not None or
                math.isnan(seconds) or math.isinf(seconds) or not 2.<=seconds<=30.):
            raise ValueError('An idle ready pipeline and 2..30 finite seconds are required')
        now=time.clock()
        self.last_measurement=None
        self.measurement={'start':now,'until':now+seconds,'warm_until':now+1.,
            'previous':None,'frames':0,'fps':[],'interval_ms':[]}
        return self.snapshot()

    def begin_dataset(self,encoding='compact8'):
        if encoding!='compact8':
            raise ValueError('This isolated scatter fixture uses compact8 only')
        if self.geometry_name and not self.render.SetActorBlockGeometryVisible(self.geometry_name,False):
            raise RuntimeError('Previous geometry hide failed')
        self.epoch+=1
        self.geometry_name=''
        self.seed,self.generation,self.slot_count=0,0,0
        self.layout[0]=0
        self.upload_history=[]
        return self.snapshot()

    def load(self,byte_count,seed=54321,generation=1):
        if not self.ready:
            raise RuntimeError('Open the probe and wait for actor readiness')
        byte_count=int(byte_count)
        if not 2<=byte_count<=MAX_BYTES:
            raise ValueError('Atlas probe payload must be in [2,65536]')
        if len(self.names)>=MAX_NAMES or self.named_records+byte_count>MAX_RECORDS:
            raise RuntimeError('Named geometry budget exhausted; restart this owned probe')
        seed,generation=int(seed)&MASK,int(generation)&MASK
        started=time.clock()
        values=bytearray(byte_at(seed,generation,index) for index in range(byte_count))
        generated=time.clock()
        encoded=encode_values(values,'compact8')
        data=encoded['data']
        data['common']={(identifier.replace('pmanim_geometry_packet:','pmanim_geometry_atlas:'),aux):indices
                        for (identifier,aux),indices in data['common'].items()}
        packed=time.clock()
        palette=self.block.GetBlankBlockPalette()
        if palette is None or not palette.DeserializeBlockPalette(data):
            raise RuntimeError('DeserializeBlockPalette rejected')
        deserialized=time.clock()
        # Consume the name before native creation. A later bind/hide failure
        # must never make a retry overwrite or reattach that candidate.
        self.native_attempt_serial+=1
        name='pmanim_geometry_atlas_epoch%d_version%d'%(self.epoch,self.native_attempt_serial)
        result=self.geometry.CombineBlockPaletteToGeometry(palette,name,1)
        combined=time.clock()
        if not result:
            raise RuntimeError('CombineBlockPaletteToGeometry rejected')
        self.names.append(result)
        self.named_records+=byte_count
        if not self.render.AddActorBlockGeometry(result,(0.,0.,0.),(0.,0.,0.)):
            raise RuntimeError('World geometry attachment failed')
        if self.geometry_name and not self.render.SetActorBlockGeometryVisible(self.geometry_name,False):
            self.render.SetActorBlockGeometryVisible(result,False)
            raise RuntimeError('Previous world geometry could not be hidden')
        self.seed,self.generation,self.slot_count=seed,generation,byte_count
        self.geometry_name=result
        self.stride,self.y_offset=encoded['stride'],encoded['y_offset']
        # Native world attachments expose palette coordinates minus .5 on
        # every axis. PaperDoll's volume/2 centering is a different path.
        self.center=[.5,.5,.5]
        columns,cell=(16,4) if byte_count<=256 else ((64,4) if byte_count<=12288 else (256,2))
        self.layout=[byte_count,columns,8,64]
        self.dimensions=[cell,720,1080,0]
        if not self._writer_controls():
            self.ready=False
            self.error='Actor control upload failed after native geometry creation'
            raise RuntimeError(self.error)
        self.geometry_build_serial+=1
        bound=time.clock()
        self.timings={'generation_ms':(generated-started)*1000.,'palette_ms':(packed-generated)*1000.,
            'deserialize_ms':(deserialized-packed)*1000.,'combine_ms':(combined-deserialized)*1000.,
            'attach_ms':(bound-combined)*1000.,'total_ms':(bound-started)*1000.}
        self.upload_history.append({'seed':seed,'generation':generation,'name':result,
            'serial':self.geometry_build_serial,'slot_count':byte_count,'encoding':'compact8',
            'timings':dict(self.timings)})
        if self.pipeline_ready:
            self.query(0,min(byte_count,4096),0,0,0,True,0,False)
        return self.snapshot()

    def install_pipeline(self):
        if self.pipeline_installed:
            raise RuntimeError('Pipeline is already installed; use finish_pipeline')
        self.pipeline=PROCESS
        if not self.post.AddPostProcess(self.pipeline):
            raise RuntimeError('AddPostProcess rejected geometry gather pipeline')
        self.pipeline_installed=True
        return self.snapshot()

    def finish_pipeline(self):
        if not self.pipeline_installed:
            raise RuntimeError('Install pipeline in a preceding render turn')
        name=self.pipeline['name']
        if name not in (self.post.GetPostProcessOrder() or []):
            raise RuntimeError('Pipeline registration has not settled')
        if not self.post.SetEnableByName(name,True):
            raise RuntimeError('Pipeline enable rejected')
        self.connection=bool(self.post.PostPassResultToOtherPass(name,0,name,2,3))
        if not self.connection:
            raise RuntimeError('Nonadjacent copy-to-gather texture connection rejected')
        self.pipeline_ready=True
        return self.query(0,min(self.slot_count,4096),0,0,0,True,0,False)

    def query(self,start,count,mode=0,salt=0,salt2=0,flip_y=True,channel_mode=0,direct_source=False):
        start,count,mode,salt,salt2,channel_mode=map(int,(start,count,mode,salt,salt2,channel_mode))
        if (not self.pipeline_ready or start<0 or not 1<=count<=4096 or
                start+count>self.slot_count or mode not in (0,1,2,3) or
                not 0<=salt<=65535 or not 0<=salt2<=65535 or channel_mode not in (0,1)):
            raise ValueError('Invalid frozen atlas query')
        packed=mode+4*int(bool(flip_y))+8*channel_mode+16*int(bool(direct_source))
        self.dimensions[3]=salt2
        controls=(('query',(start,count,packed,salt)),('layout',self.layout),('dimensions',self.dimensions))
        for key,value in controls:
            if not self.post.SetParameter(self.pipeline['name'],key,[float(item) for item in value]):
                self.pipeline_ready=False
                raise RuntimeError('Gather control rejected: '+key)
        self.query_value=[start,count,mode,salt]
        self.orientation=[int(bool(flip_y)),channel_mode,0,0]
        self.packed_mode=packed
        self.direct_source=bool(direct_source)
        return self.snapshot()

    def set_writer_visible(self,visible):
        self.writer_visible=bool(visible)
        if not self.ready or not self._writer_controls():
            raise RuntimeError('Writer visibility controls rejected')
        return self.snapshot()

    def set_center(self,x,y,z):
        self.center=[float(x),float(y),float(z)]
        if not self.ready or not self._writer_controls():
            raise RuntimeError('World geometry centering controls rejected')
        return self.snapshot()

    def set_pipeline_enabled(self,enabled):
        if not self.pipeline_installed or not self.post.SetEnableByName(self.pipeline['name'],bool(enabled)):
            raise RuntimeError('Pipeline enable/disable rejected')
        return self.snapshot()

    def snapshot(self):
        return {'schema':'geometry_atlas_probe_v1','ready':self.ready,'error':self.error,
            'encoding':'compact8','seed':self.seed,'generation':self.generation,'slot_count':self.slot_count,
            'geometry_name':self.geometry_name,'geometry_build_serial':self.geometry_build_serial,
            'native_attempt_serial':self.native_attempt_serial,
            'epoch':self.epoch,'entity':self.entity,'upload_history':list(self.upload_history),
            'screen_size':[720,1080],'logical_screen_size':list(self.game.GetScreenSize()),
            'display_rect_norm':[0,64./1080.,1,1000./1080.],
            'layout':list(self.layout),'dimensions':list(self.dimensions),'query':list(self.query_value),
            'orientation':list(self.orientation),'packed_mode':self.packed_mode,
            'direct_source':self.direct_source,'pipeline_installed':self.pipeline_installed,
            'pipeline_ready':self.pipeline_ready,'connection':self.connection,
            'writer_visible':self.writer_visible,'center':list(self.center),
            'native_hud_hidden':self.native_hud_hidden,
            'timings':dict(self.timings),'fps':self.game.GetFps(),
            'measurement_running':self.measurement is not None,'last_measurement':self.last_measurement,
            'resource_budget':{'names':len(self.names),'named_records':self.named_records,
                'max_names':MAX_NAMES,'max_named_records':MAX_RECORDS,'native_reclamation_verified':False},
            'gpu_verified':False,'gpu_to_python_readback':False}

    def close(self):
        disable_failed=False
        try:
            if self.pipeline_installed:
                disable_failed=not self.post.SetEnableByName(self.pipeline['name'],False)
        finally:
            try:
                if self.entity is not None:
                    self.DestroyClientEntity(self.entity)
                    self.entity,self.render=None,None
            finally:
                self.ready=False
                self.pipeline_ready=False
                if self.native_hud_hidden:
                    api.HideHudGUI(False)
                    self.native_hud_hidden=False
        if disable_failed:
            raise RuntimeError('Owned geometry pipeline disable rejected')

    def Destroy(self):
        try:
            self.close()
        finally:
            self.UnListenForEvent(api.GetEngineNamespace(),api.GetEngineSystemName(),
                                  'GameRenderTickEvent',self,self.on_frame)
