# -*- coding: utf-8 -*-
"""Isolated public-API geometry writer and forward postprocess gather probe."""
import time
import math
import mod.client.extraClientApi as api
from geometry_atlas_probe.codec import encode_values
from geometry_atlas_probe.pipeline_config import PROCESS
from geometry_atlas_probe.update_scheduler import UpdateScheduler, statistics

ClientSystem=api.GetClientSystemCls()
MASK=0xffffffff
MAX_BYTES=524288
MAX_RECORDS=2097152
MAX_NAMES=256
# Calibrated against native atlas captures, not a general model-origin rule.
ATLAS_CENTER=(1.,.5,.5)


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
        self.name_records={}
        self.attached_names=set()
        self.dataset_names=set()
        self.update_policy='fresh'
        self.publish_delay_ms=0.
        self.active_bank=-1
        self.pending_upload=None
        self.updates=None
        self.last_updates=None
        self.update_run_serial=0
        self.render_event=0
        self.upload_history=[]
        self.writer_visible=True
        self.stride=2
        self.y_offset=8.
        self.center=list(ATLAS_CENTER)
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

    def _writer_controls(self,candidate=None):
        source=candidate if candidate is not None else self
        if candidate is None:
            stride,y_offset,count,layout,dimensions,center=(self.stride,self.y_offset,self.slot_count,
                self.layout,self.dimensions,self.center)
            bank=self.active_bank
        else:
            stride,y_offset,count,layout,dimensions,center=(source['stride'],8.,source['slot_count'],
                source['layout'],source['dimensions'],ATLAS_CENTER)
            bank=source['bank']
        selector=0. if self.update_policy=='fresh' else float(bank+1 if bank>=0 else 3)
        groups=((float(stride),y_offset,float(count),float(layout[1])),
                tuple(float(value) for value in layout[2:]+dimensions[:2]),
                (float(dimensions[2]),)+tuple(float(value) for value in center),
                (float(self.writer_visible),selector,0.,0.))
        return all(self.render.SetEntityExtraUniforms(index+1,group)
                   for index,group in enumerate(groups))

    def on_frame(self,args):
        self.render_event+=1
        if self.entity is not None and not self.ready and self.error is None:
            self.ready=self._writer_controls()
            if not self.ready and time.clock()>self.ready_until:
                self.error='Actor uniforms did not become ready before timeout'
        if self.pending_upload is not None:
            try:
                self._publish_pending(time.clock())
            except (RuntimeError,ValueError,TypeError) as error:
                self.error='%s: %s'%(type(error).__name__,error)
                if self.updates is not None:
                    self.updates.error=self.error
                    self.updates.finish(time.clock())
        if self.updates is not None:
            self.updates.on_frame(time.clock())
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
                result[key]=statistics(sample[key],key=='interval_ms')
            self.last_measurement=result
            self.measurement=None

    def start_measurement(self,seconds=8.):
        seconds=float(seconds)
        if (not self.pipeline_ready or self.measurement is not None or self.updates is not None or
                self.pending_upload is not None or
                math.isnan(seconds) or math.isinf(seconds) or not 2.<=seconds<=30.):
            raise ValueError('An idle ready pipeline and 2..30 finite seconds are required')
        now=time.clock()
        self.last_measurement=None
        self.measurement={'start':now,'until':now+seconds,'warm_until':now+1.,
            'previous':None,'frames':0,'fps':[],'interval_ms':[]}
        return self.snapshot()

    def begin_dataset(self,encoding='compact8'):
        if self.updates is not None or self.measurement is not None or self.pending_upload is not None:
            raise RuntimeError('Finish active updates and pending publication before a new dataset')
        if encoding!='compact8':
            raise ValueError('This isolated scatter fixture uses compact8 only')
        for name in self.dataset_names:
            if not self.render.SetActorBlockGeometryVisible(name,False):
                raise RuntimeError('Previous geometry hide failed')
        self.epoch+=1
        self.geometry_name=''
        self.seed,self.generation,self.slot_count=0,0,0
        self.layout[0]=0
        self.upload_history=[]
        self.dataset_names=set()
        self.active_bank=-1
        if self.render is not None and not self._writer_controls():
            raise RuntimeError('Empty dataset writer controls rejected')
        return self.snapshot()

    def configure_updates(self,policy='fresh',publish_delay_ms=0):
        delay=float(publish_delay_ms)
        if (policy not in ('fresh','double') or math.isnan(delay) or math.isinf(delay) or
                not 0.<=delay<=5000.):
            raise ValueError('Use fresh/double and a finite publication delay in [0,5000] ms')
        if self.pending_upload is not None:
            raise RuntimeError('Pending upload must publish before update configuration changes')
        if (self.geometry_name or self.dataset_names or self.pending_upload is not None or
                self.updates is not None or self.measurement is not None):
            raise RuntimeError('Configure updates only in an empty idle dataset')
        self.update_policy,self.publish_delay_ms=policy,delay
        self.active_bank=-1
        if self.render is not None and not self._writer_controls():
            raise RuntimeError('Update policy writer controls rejected')
        return self.snapshot()

    def _next_name(self):
        bank=0 if self.active_bank<0 else 1-self.active_bank
        if self.update_policy=='double':
            return 'pmanim_geometry_atlas_epoch%d_bank%d'%(self.epoch,bank),bank
        return 'pmanim_geometry_atlas_epoch%d_version%d'%(self.epoch,self.native_attempt_serial+1),-1

    def can_upload(self,byte_count):
        name,_=self._next_name()
        previous=self.name_records.get(name,0)
        return (self.named_records-previous+byte_count<=MAX_RECORDS and
                (name in self.name_records or len(self.names)<MAX_NAMES))

    def load(self,byte_count,seed=54321,generation=1):
        self._require_idle_controls()
        self._submit_upload(byte_count,seed,generation)
        self._publish_pending(time.clock())
        return self.snapshot()

    def _submit_upload(self,byte_count,seed,generation):
        if not self.ready:
            raise RuntimeError('Open the probe and wait for actor readiness')
        if self.pending_upload is not None:
            raise RuntimeError('Pending upload must publish before another candidate can overwrite it')
        byte_count=int(byte_count)
        if not 2<=byte_count<=MAX_BYTES:
            raise ValueError('Atlas probe payload must be in [2,524288]')
        if not self.can_upload(byte_count):
            raise RuntimeError('Named geometry budget exhausted; restart this owned probe')
        seed,generation=int(seed)&MASK,int(generation)&MASK
        name,bank=self._next_name()
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
        result=self.geometry.CombineBlockPaletteToGeometry(palette,name,1)
        combined=time.clock()
        if not result:
            raise RuntimeError('CombineBlockPaletteToGeometry rejected')
        if result not in self.name_records:
            self.names.append(result)
        self.named_records+=byte_count-self.name_records.get(result,0)
        self.name_records[result]=byte_count
        self.dataset_names.add(result)
        if result not in self.attached_names:
            if not self.render.AddActorBlockGeometry(result,(0.,0.,0.),(0.,0.,0.)):
                raise RuntimeError('World geometry attachment failed')
            self.attached_names.add(result)
        if self.update_policy=='double':
            if not (self.render.EnableActorBlockGeometryTransparent(result,True) and
                    self.render.SetActorBlockGeometryTransparency(result,.25+.5*bank)):
                raise RuntimeError('Double-bank transparency tag rejected')
        elif self.publish_delay_ms>0.:
            if not self.render.SetActorBlockGeometryVisible(result,False):
                raise RuntimeError('Pending fresh writer hide failed')
        bound=time.clock()
        timings={'generation_ms':(generated-started)*1000.,'encode_ms':(packed-generated)*1000.,
            'palette_ms':(packed-generated)*1000.,
            'deserialize_ms':(deserialized-packed)*1000.,'combine_ms':(combined-deserialized)*1000.,
            'attach_ms':(bound-combined)*1000.,'total_ms':(bound-started)*1000.}
        columns,cell,top=(16,4,64) if byte_count<=256 else (
            (64,4,64) if byte_count<=12288 else ((256,2,64) if byte_count<=65536 else (512,1,32)))
        candidate={'seed':seed,'generation':generation,'name':result,'slot_count':byte_count,
            'encoding':'compact8','bank':bank,'stride':encoded['stride'],
            'layout':[byte_count,columns,8,top],'dimensions':[cell,720,1080,self.dimensions[3]],
            'started_at':started,'upload_finished_at':bound,
            'ready_at':bound+self.publish_delay_ms/1000.,'published_at':None,
            'upload_event':self.render_event,'publish_event':None,
            'attempt_serial':self.native_attempt_serial,'timings':timings,
            'previous_bank_publication':None}
        for previous in reversed(self.upload_history):
            if previous['name']==result:
                candidate['previous_bank_publication']=previous['published_at']
                break
        self.pending_upload=candidate
        return candidate

    def _publish_pending(self,now):
        candidate=self.pending_upload
        if candidate is None or now<candidate['ready_at']:
            return False
        if self.update_policy=='fresh':
            if self.geometry_name and not self.render.SetActorBlockGeometryVisible(self.geometry_name,False):
                self.render.SetActorBlockGeometryVisible(candidate['name'],False)
                self.pending_upload=None
                raise RuntimeError('Previous world geometry could not be hidden')
            if self.publish_delay_ms>0. and not self.render.SetActorBlockGeometryVisible(candidate['name'],True):
                self.pending_upload=None
                raise RuntimeError('Pending fresh writer publication failed')
        if not self._writer_controls(candidate):
            self.ready=False
            self.error='Actor control upload failed after native geometry creation'
            self.pending_upload=None
            raise RuntimeError(self.error)
        self.seed,self.generation,self.slot_count=(candidate['seed'],candidate['generation'],candidate['slot_count'])
        self.geometry_name=candidate['name']
        self.stride,self.y_offset=candidate['stride'],8.
        self.center=list(ATLAS_CENTER)
        self.layout,self.dimensions=list(candidate['layout']),list(candidate['dimensions'])
        self.active_bank=candidate['bank']
        self.geometry_build_serial+=1
        candidate['serial']=self.geometry_build_serial
        candidate['published_at']=time.clock()
        candidate['publish_event']=self.render_event
        candidate['publish_wait_ms']=(candidate['published_at']-candidate['upload_finished_at'])*1000.
        self.timings=dict(candidate['timings'])
        self.upload_history.append(self.upload_receipt(candidate))
        if len(self.upload_history)>257:
            del self.upload_history[:-257]
        self.pending_upload=None
        if self.updates is not None:
            self.updates.note_publish(candidate)
        elif self.pipeline_ready:
            self.query(0,min(self.slot_count,4096),0,0,0,True,0,False)
        return True

    def upload_receipt(self,candidate):
        return {key:value for key,value in candidate.items()
                if key not in ('layout','dimensions','stride')}

    def _dependent_query(self):
        return self._set_query(0,min(self.slot_count,4096),2,37,91,True,0,False)

    def start_updates(self,duration_seconds=8,interval_ms=16.6666667,max_updates=64):
        duration,interval=float(duration_seconds),float(interval_ms)
        if (not self.ready or not self.pipeline_ready or not self.geometry_name or
                self.updates is not None or self.measurement is not None or self.pending_upload is not None or
                math.isnan(duration) or math.isinf(duration) or not 2.<=duration<=30. or
                math.isnan(interval) or math.isinf(interval) or not 0.<=interval<=30000. or
                isinstance(max_updates,bool) or not isinstance(max_updates,int) or not 1<=max_updates<=4096):
            raise ValueError('Use an idle ready payload, 2..30 seconds, finite nonnegative interval and 1..4096 updates')
        self._dependent_query()
        self.update_run_serial+=1
        self.last_updates=None
        self.updates=UpdateScheduler(self,duration,interval,max_updates,time.clock())
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

    def _require_idle_controls(self):
        if self.updates is not None or self.measurement is not None:
            raise RuntimeError('Benchmark controls are frozen until measurement completes')

    def query(self,start,count,mode=0,salt=0,salt2=0,flip_y=True,channel_mode=0,direct_source=False):
        self._require_idle_controls()
        return self._set_query(start,count,mode,salt,salt2,flip_y,channel_mode,direct_source)

    def _set_query(self,start,count,mode=0,salt=0,salt2=0,flip_y=True,channel_mode=0,direct_source=False):
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
        self._require_idle_controls()
        self.writer_visible=bool(visible)
        if not self.ready or not self._writer_controls():
            raise RuntimeError('Writer visibility controls rejected')
        return self.snapshot()

    def set_center(self,x,y,z):
        self._require_idle_controls()
        self.center=[float(x),float(y),float(z)]
        if not self.ready or not self._writer_controls():
            raise RuntimeError('World geometry centering controls rejected')
        return self.snapshot()

    def set_pipeline_enabled(self,enabled):
        self._require_idle_controls()
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
            'update_policy':self.update_policy,'publish_delay_ms':self.publish_delay_ms,
            'active_bank':self.active_bank,
            'pending_upload':None if self.pending_upload is None else self.upload_receipt(self.pending_upload),
            'updates_running':self.updates is not None,'last_updates':self.last_updates,
            'update_run_serial':self.update_run_serial,
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
                    self.attached_names.clear()
            finally:
                self.ready=False
                self.pipeline_ready=False
                self.updates=None
                self.pending_upload=None
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
