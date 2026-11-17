# -*- coding: utf-8 -*-
"""Game Python 2: bytes enter native geometry only; queries change one image."""
import math
import time
import traceback
import mod.client.extraClientApi as api

ScreenNode=api.GetScreenNodeCls()
ClientSystem=api.GetClientSystemCls()
NAMESPACE='pmanim_geometry_packet_probe'
IDENTIFIER='pmanim_geometry_packet:quad'
MASK=0xffffffff
MAX_BYTES=1048576


def byte_at(seed,generation,index):
    value=(seed ^ ((generation*0x9e3779b9)&MASK) ^ ((index*0x85ebca6b)&MASK))&MASK
    value^=value>>16
    value=(value*0x7feb352d)&MASK
    value^=value>>15
    value=(value*0x846ca68b)&MASK
    value^=value>>16
    return value&255


def stats(values):
    if not values:
        return {'count':0}
    ordered=sorted(values)
    return {'count':len(values),'mean':sum(values)/len(values),
            'p50':ordered[int((len(ordered)-1)*.5)],
            'p95':ordered[int((len(ordered)-1)*.95)],
            'min':ordered[0],'max':ordered[-1]}


class GeometryScreen(ScreenNode):
    def __init__(self,namespace,name,param):
        ScreenNode.__init__(self,namespace,name,param)
        self.ready=False
        self.image=None
        self.canvas=None

    def Create(self):
        carrier=self.GetBaseUIControl('/carrier')
        canvas=self.GetBaseUIControl('/canvas')
        if carrier is None or canvas is None:
            raise RuntimeError('Geometry UI controls missing')
        self.image=carrier.asImage()
        self.canvas=canvas.asNeteasePaperDoll()
        self.ready=True

    def draw(self,name):
        if not self.ready:
            raise RuntimeError('Wait for geometry screen Create')
        if not self.canvas.RenderBlockGeometryModel({
                'block_geometry_model_name':name,'scale':1.,
                'init_rot_x':0.,'init_rot_y':0.,'init_rot_z':0.}):
            raise RuntimeError('RenderBlockGeometryModel rejected')


class ProbeSystem(ClientSystem):
    def __init__(self,namespace,system_name):
        ClientSystem.__init__(self,namespace,system_name)
        self.factory=api.GetEngineCompFactory()
        self.level=api.GetLevelId()
        self.game=self.factory.CreateGame(self.level)
        self.screen=None
        self.registered=False
        self.seed=0
        self.generation=0
        self.slot_count=0
        self.geometry_name=''
        self.geometry_build_serial=0
        self.epoch=0
        self.stride=0
        self.query_value=[0,1,1]
        self.query_mode=0
        self.query_count=0
        self.y_offset=128.
        self.timings={}
        self.last_run=None
        self.run=None
        # Capture target is declared separately from the SDK's logical UI size.
        # The owner-bound host must resize and verify the actual WGC pixels.
        self.capture_size=[720,1080]
        self.ListenForEvent(api.GetEngineNamespace(),api.GetEngineSystemName(),
                            'GameRenderTickEvent',self,self.on_frame)

    def open(self):
        if self.screen is None:
            if not self.registered:
                if not api.RegisterUI(NAMESPACE,'probe','geometry_packet_probe.runtime.GeometryScreen',
                                      'pmanim_geometry_packet_probe.main'):
                    raise RuntimeError('RegisterUI rejected')
                self.registered=True
            self.screen=api.CreateUI(NAMESPACE,'probe',{'isHud':1})
            if self.screen is None:
                raise RuntimeError('CreateUI failed')
        return self.snapshot()

    def load(self,byte_count,seed=12345,generation=None):
        if self.screen is None or not self.screen.ready:
            raise RuntimeError('Open and wait for ready screen before load')
        byte_count=int(byte_count)
        if not 1<=byte_count<=MAX_BYTES:
            raise ValueError('Experimental byte_count must be in [1,1048576]')
        seed=int(seed)&MASK
        generation=(self.generation+1)&MASK if generation is None else int(generation)&MASK
        started=time.clock()
        values=bytearray(byte_at(seed,generation,index) for index in range(byte_count))
        generated=time.clock()
        stride=2
        while stride*stride<byte_count:
            stride*=2
        indices=[]
        plane=stride*stride
        for index,value in enumerate(values):
            indices.append(value*plane+(index//stride)*stride+index%stride)
        data={'volume':(stride,stride,256),'common':{(IDENTIFIER,0):indices},
              'extra':{},'actor':{},'states':{},'extraStates':{},
              'void':False,'eliminateAir':True}
        packed=time.clock()
        palette=self.factory.CreateBlock(self.level).GetBlankBlockPalette()
        if palette is None or not palette.DeserializeBlockPalette(data):
            raise RuntimeError('DeserializeBlockPalette rejected')
        deserialized=time.clock()
        # Independent datasets get fresh names. Repeated updates remain bounded
        # to two banks inside one epoch; that path still needs pixel validation.
        name='pmanim_geometry_packet_payload_epoch%d_bank%d'%(
            self.epoch,(self.geometry_build_serial+1)%2)
        result=self.factory.CreateBlockGeometry(self.level).CombineBlockPaletteToGeometry(palette,name,1)
        combined=time.clock()
        if not result:
            raise RuntimeError('CombineBlockPaletteToGeometry rejected')
        self.screen.draw(result)
        rendered=time.clock()
        self.seed,self.generation,self.slot_count=seed,generation,byte_count
        self.stride,self.geometry_name=stride,result
        self.geometry_build_serial+=1
        self.timings={'generation_ms':(generated-started)*1000.,
                      'palette_ms':(packed-generated)*1000.,
                      'deserialize_ms':(deserialized-packed)*1000.,
                      'combine_ms':(combined-deserialized)*1000.,
                      'render_ms':(rendered-combined)*1000.,
                      'total_ms':(rendered-started)*1000.}
        count=min(byte_count,4096)
        self.query(0,count,min(64,count))
        return self.snapshot()

    def begin_dataset(self):
        if self.run is not None:
            raise RuntimeError('Finish active benchmark before beginning a dataset')
        self.epoch+=1
        # Invalidate the old receipt before a new upload can fail. This method
        # does not claim to flush native resources or fix same-name update races.
        self.seed,self.generation,self.slot_count=0,0,0
        self.geometry_name=''
        self.stride=0
        self.timings={}
        return self.snapshot()

    def query(self,start=0,count=4096,columns=64,mode=0):
        self._write_query(start,count,columns,mode)
        return self.snapshot()

    def _write_query(self,start,count,columns,mode=0):
        start,count,columns,mode=int(start),int(count),int(columns),int(mode)
        if (not self.geometry_name or start<0 or not 1<=count<=4096 or
                start+count>self.slot_count or not 1<=columns<=64 or not 0<=mode<=3):
            raise ValueError('Invalid geometry query')
        started=time.clock()
        query=(count-1)+(columns-1)*4096+mode*262144
        layout=self.stride+int(round(self.y_offset*2))*2048
        self.screen.image.SetSpriteColor((start/16777216.,query/16777216.,layout/8388608.))
        self.query_value=[start,count,columns]
        self.query_mode=mode
        self.query_count+=1
        self.timings['query_ms']=(time.clock()-started)*1000.

    def configure_capture_size(self,width=720,height=1080):
        width,height=int(width),int(height)
        if width<1 or height<1:
            raise ValueError('Capture target dimensions must be positive')
        self.capture_size=[width,height]
        return self.snapshot()

    def calibrate(self,y_offset=128.):
        self.y_offset=float(y_offset)
        if not 0<=self.y_offset<=511 or self.y_offset*2!=int(self.y_offset*2):
            raise ValueError('Y offset must be a half-integer in [0,511]')
        return self.query(*(self.query_value+[self.query_mode]))

    def start(self,seconds=8.,dynamic=False,seed=None):
        seconds=float(seconds)
        if self.run is not None or not self.geometry_name or seconds<=1. or math.isnan(seconds) or math.isinf(seconds):
            raise ValueError('A loaded idle probe and finite duration >1 second are required')
        now=time.clock()
        self.last_run=None
        self.run={'start':now,'until':now+seconds,'warm_until':now+1.,'previous':None,
                  'dynamic':bool(dynamic),'baseline':False,
                  'seed':self.seed if seed is None else int(seed)&MASK,
                  'frames':0,'interval_ms':[],'fps':[],'generation_ms':[],'palette_ms':[],
                  'deserialize_ms':[],'combine_ms':[],'render_ms':[],'query_ms':[],
                  'initial_build_serial':self.geometry_build_serial,'initial_generation':self.generation}
        return self.snapshot()

    def start_baseline(self,seconds=12.):
        if self.run is not None:
            raise RuntimeError('Finish active benchmark before baseline')
        seconds=float(seconds)
        if seconds<=1. or math.isnan(seconds) or math.isinf(seconds):
            raise ValueError('Baseline requires a finite duration >1 second')
        if self.screen is not None:
            self.screen.SetRemove()
            self.screen=None
        now=time.clock()
        self.last_run=None
        self.run={'start':now,'until':now+seconds,'warm_until':now+1.,'previous':None,
                  'dynamic':False,'baseline':True,'seed':self.seed,'frames':0,
                  'interval_ms':[],'fps':[],'generation_ms':[],'palette_ms':[],
                  'deserialize_ms':[],'combine_ms':[],'render_ms':[],'query_ms':[],
                  'initial_build_serial':self.geometry_build_serial,'initial_generation':self.generation}
        return self.snapshot()

    def _finish(self,error=None):
        run=self.run
        if run is None:
            return
        self.last_run={key:value for key,value in run.items() if not isinstance(value,list)}
        for key,value in run.items():
            if isinstance(value,list):
                self.last_run[key]=stats(value)
        self.last_run.update(status='failed' if error else 'completed',success=error is None,
                             error=error,elapsed=time.clock()-run['start'],
                             geometry_build_serial=self.geometry_build_serial,generation=self.generation,
                             gpu_verified=False)
        self.run=None

    def on_frame(self,args):
        run=self.run
        if run is None:
            return
        now=time.clock()
        if now>=run['warm_until'] and run['previous'] is not None:
            run['interval_ms'].append((now-run['previous'])*1000.)
        run['previous']=now
        if now>=run['until']:
            self._finish()
            return
        run['frames']+=1
        try:
            if run['baseline']:
                pass
            elif run['dynamic']:
                self.load(self.slot_count,run['seed'],(self.generation+1)&MASK)
            else:
                count=min(self.slot_count,4096)
                start=(run['frames']*4096)%self.slot_count
                start=min(start,self.slot_count-count)
                self._write_query(start,count,min(64,count))
            if now>=run['warm_until']:
                for key in ('generation_ms','palette_ms','deserialize_ms','combine_ms','render_ms','query_ms'):
                    measured=self.timings.get(key,0.) if run['dynamic'] or key=='query_ms' else 0.
                    run[key].append(0. if run['baseline'] else measured)
                if run['frames']%15==0:
                    run['fps'].append(self.game.GetFps())
        except (RuntimeError,ValueError,TypeError) as error:
            traceback.print_exc()
            self._finish('%s: %s'%(type(error).__name__,error))

    def snapshot(self):
        return {'schema':'geometry_packet_probe_v1','ready':self.screen is not None and self.screen.ready,
                'seed':self.seed,'generation':self.generation,'slot_count':self.slot_count,
                'geometry_name':self.geometry_name,'geometry_build_serial':self.geometry_build_serial,
                'epoch':self.epoch,
                'screen_size':list(self.capture_size),
                'screen_size_source':'declared_capture_target_host_must_verify_native_pixels',
                'logical_screen_size':list(self.game.GetScreenSize()),'query':list(self.query_value),
                'display_rect_norm':[0,64./1080.,1,1000./1080.],
                'query_mode':self.query_mode,'stride':self.stride,
                'y_offset':self.y_offset,'query_count':self.query_count,
                'timings':dict(self.timings),'benchmark_running':self.run is not None,
                'last_run':self.last_run,'gpu_verified':False}

    status=snapshot

    def close(self):
        self._finish('Probe closed before benchmark completion')
        if self.screen is not None:
            self.screen.SetRemove()
            self.screen=None

    def Destroy(self):
        self.close()
        self.UnListenForEvent(api.GetEngineNamespace(),api.GetEngineSystemName(),
                              'GameRenderTickEvent',self,self.on_frame)
