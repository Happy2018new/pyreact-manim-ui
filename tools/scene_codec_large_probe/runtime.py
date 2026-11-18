# -*- coding: utf-8 -*-
"""Single-generation static RGB/alpha codec with bounded in-memory geometry pages."""
import time
import mod.client.extraClientApi as api
from geometry_atlas_probe.codec import encode_values
from geometry_atlas_probe.scene_codec import payload_to_symbols
from geometry_atlas_probe.large_layout import plan_payload, page_payload
from geometry_atlas_probe.large_config import PROCESSES, SOURCE_BUNDLE_SHA256, FIXED_LOGICAL_BYTES, COMPAT_OVERLAY
from geometry_atlas_probe.update_scheduler import statistics

ClientSystem=api.GetClientSystemCls()


class ProbeSystem(ClientSystem):
    def __init__(self,namespace,system_name):
        ClientSystem.__init__(self,namespace,system_name)
        self.factory=api.GetEngineCompFactory()
        self.level=api.GetLevelId()
        self.game=self.factory.CreateGame(self.level)
        self.block=self.factory.CreateBlock(self.level)
        self.geometry=self.factory.CreateBlockGeometry(self.level)
        self.post=self.factory.CreatePostProcess(self.level)
        self.pages=[]
        self.plan=None
        self.dataset_serial=0
        self.seed,self.generation=54321,1
        self.base_alpha=255
        self.writer_visible=True
        self.pipeline_installed=False
        self.pipeline_ready=False
        self.connections=[]
        self.original_post_states=[]
        self.process_enabled={item['name']:False for item in PROCESSES}
        self.profile='unconfigured'
        self.query_value=[0,0,0]
        self.render_event=0
        self.error=None
        self.measurement=None
        self.last_measurement=None
        self.ListenForEvent(api.GetEngineNamespace(),api.GetEngineSystemName(),'GameRenderTickEvent',self,self.on_frame)

    def _idle(self):
        if self.measurement is not None:
            raise RuntimeError('Static measurement freezes all controls')
        if self.error:
            raise RuntimeError('Prior page error requires inspection: '+self.error)

    def _controls(self,page):
        roi=page['roi']
        active=self.writer_visible and page['loaded'] and page['dataset']==self.dataset_serial
        groups=((float(page['stride']),8.,float(page['record_count']),float(roi[2])),
            (float(roi[0]),float(roi[1]),1.,1080.),(1440.,1.,.5,.5),
            (float(active),0.,2.,float(page['record_base'])))
        return all(page['render'].SetEntityExtraUniforms(i+1,group) for i,group in enumerate(groups))

    def on_frame(self,args):
        self.render_event+=1
        for page in self.pages:
            if not page['ready']:
                page['ready']=self._controls(page)
        sample=self.measurement
        if sample is None:
            return
        now=time.clock()
        if now>=sample['warm_until']:
            if sample['previous_sample'] is not None:
                sample['interval_ms'].append((now-sample['previous_sample'])*1000.)
            sample['previous_sample']=now
            sample['frames']+=1
            if sample['frames']%15==0:
                sample['fps'].append(self.game.GetFps())
        if now>=sample['until']:
            self.last_measurement={'profile':self.profile,'warmup_seconds':sample['warmup'],
                'sample_seconds':now-sample['warm_until'],'elapsed_seconds':now-sample['start'],
                'frames':sample['frames'],'fps':statistics(sample['fps']),
                'interval_ms':statistics(sample['interval_ms'],True),'raw_fps_samples':list(sample['fps']),
                'raw_interval_ms':list(sample['interval_ms']),'pass_count':sum(self.process_enabled.values()),
                'enabled_processes':[name for name in self.process_enabled if self.process_enabled[name]],
                'seed':self.seed,'generation':self.generation,'dataset_serial':self.dataset_serial,
                'gpu_completion_fence':False,'continuous_updates':False}
            self.measurement=None

    def prepare(self,logical_bytes,seed=54321,generation=1):
        self._idle()
        if FIXED_LOGICAL_BYTES is not None and logical_bytes!=FIXED_LOGICAL_BYTES:
            raise ValueError('This project has a compile-fixed capacity and native overlay ROI')
        if self.plan and not all(p['loaded'] for p in self.pages if p['dataset']==self.dataset_serial):
            raise RuntimeError('Current dataset has unsubmitted pages; inspect it before another dataset')
        plan=plan_payload(logical_bytes,2)
        if self.dataset_serial>=2:
            raise RuntimeError('This owned probe permits two static datasets only')
        self.set_native_visible(False)
        self.dataset_serial+=1
        self.plan=plan
        self.seed,self.generation=int(seed)&0xffffffff,int(generation)&0xffffffff
        api.HideHudGUI(True)
        api.HideCrossHairGUI(True)
        camera=self.factory.CreateCamera(self.level)
        pos,forward=camera.GetPosition(),camera.GetForward()
        if pos is None or forward is None:
            raise RuntimeError('World camera not ready')
        anchor=tuple(pos[i]+forward[i]*3. for i in range(3))
        for planned in plan['pages']:
            entity=self.CreateClientEntityByTypeStr('pmanim_geometry_atlas:anchor',anchor,(0.,0.))
            if entity is None:
                raise RuntimeError('Page anchor creation failed')
            page=dict(planned,dataset=self.dataset_serial,seed=self.seed,generation=self.generation,
                roi=list(plan['roi']),entity=entity,render=self.factory.CreateActorRender(entity),
                loaded=False,attempted=False,ready=False,name='',native_visible=False,
                payload_fingerprint=None,timings={},upload_serial=0)
            self.factory.CreateModel(entity).SetEntityShadowShow(False)
            self.pages.append(page)
            page['ready']=self._controls(page)
        self.writer_visible=True
        self.profile='prepared'
        return self.snapshot()

    def upload_page(self,page_index):
        self._idle()
        current=[p for p in self.pages if p['dataset']==self.dataset_serial]
        page=current[int(page_index)]
        if page['attempted'] or not page['ready']:
            raise RuntimeError('Page already attempted or actor uniforms not ready')
        page['attempted']=True
        started=time.clock()
        payload=page_payload(self.plan,page['page'],self.seed,self.generation)
        generated=time.clock()
        page['payload_fingerprint']={'algorithm':'sum_u8_mod2^32','value':sum(payload)&0xffffffff}
        fingerprinted=time.clock()
        symbols=payload_to_symbols(payload,2)
        symbolized=time.clock()
        if len(symbols)!=page['record_count']:
            raise RuntimeError('Packed symbols disagree with the block-aligned page plan')
        encoded=encode_values(symbols,'compact8')
        data=encoded['data']
        data['common']={(name.replace('pmanim_geometry_packet:','pmanim_geometry_atlas:'),aux):indices
            for (name,aux),indices in data['common'].items()}
        packed=time.clock()
        palette=self.block.GetBlankBlockPalette()
        if palette is None or not palette.DeserializeBlockPalette(data):
            self.error='Palette rejected dataset%d page%d'%(self.dataset_serial,page['page'])
            raise RuntimeError(self.error)
        deserialized=time.clock()
        name='scene_large_d%d_g%d_page%02d'%(self.dataset_serial,self.generation,page['page'])
        result=self.geometry.CombineBlockPaletteToGeometry(palette,name,1)
        combined=time.clock()
        if not result:
            self.error='Native combine rejected '+name
            raise RuntimeError(self.error)
        page['name']=result
        if not page['render'].AddActorBlockGeometry(result,(0.,0.,0.),(0.,0.,0.)):
            self.error='Native attach rejected '+name
            raise RuntimeError(self.error)
        if not page['render'].SetActorBlockGeometryVisible(result,True):
            raise RuntimeError('Native visibility rejected '+name)
        page['loaded'],page['native_visible']=True,True
        page['upload_serial']=sum(int(p['loaded']) for p in self.pages)
        if not self._controls(page):
            raise RuntimeError('Loaded page controls rejected '+name)
        attached=time.clock()
        page['timings']={'generation_ms':(generated-started)*1000.,'fingerprint_ms':(fingerprinted-generated)*1000.,
            'symbols_ms':(symbolized-fingerprinted)*1000.,'encode_ms':(packed-symbolized)*1000.,
            'deserialize_ms':(deserialized-packed)*1000.,'combine_ms':(combined-deserialized)*1000.,
            'attach_ms':(attached-combined)*1000.,'total_ms':(attached-started)*1000.}
        page['upload_render_event']=self.render_event
        return self.snapshot()

    def _params(self,name,mode=0,start=0,count=None):
        if self.plan is None:
            raise RuntimeError('Prepare a payload before configuring codec parameters')
        logical=self.plan['logical_bytes']
        second=logical if name=='scene_large_consumer' else self.base_alpha
        count=logical if count is None else count
        for key,value in (('codec',[2,second,mode,start]),('roi',self.plan['roi']),
                ('physical',[1080,1440,1,count])):
            if not self.post.SetParameter(name,key,[float(v) for v in value]):
                raise RuntimeError('Post parameter rejected '+name+'/'+key)

    def install_pipeline(self):
        self._idle()
        if self.pipeline_installed:
            raise RuntimeError('Pipeline already installed')
        self.original_post_states=[(name,bool(self.post.CheckEnabledByName(name)))
            for name in (self.post.GetPostProcessOrder() or [])]
        for name,enabled in self.original_post_states:
            if enabled and not self.post.SetEnableByName(name,False):
                raise RuntimeError('Native post state disable rejected '+name)
        for index,item in enumerate(PROCESSES):
            if not self.post.AddPostProcess(item,index):
                raise RuntimeError('Custom process registration rejected '+item['name'])
        self.pipeline_installed=True
        return self.snapshot()

    def finish_pipeline(self):
        self._idle()
        if not self.pipeline_installed:
            raise RuntimeError('Install the custom processes in an earlier render turn')
        links=(('scene_large_encode','scene_large_decode',3),('scene_large_encode','scene_large_consumer',3),
            ('scene_large_encode','scene_large_integrity',3),('scene_large_decode','scene_large_integrity',4),
            ('scene_large_raw','scene_large_integrity',5))
        for source,target,slot in links:
            accepted=bool(self.post.PostPassResultToOtherPass(source,0,target,0,slot))
            self.connections.append([source,target,slot,accepted])
            if not accepted:
                raise RuntimeError('Custom pass result link rejected')
        self.pipeline_ready=True
        return self.set_profile('restore')

    def set_native_visible(self,visible):
        self._idle()
        self.writer_visible=bool(visible)
        for page in self.pages:
            show=bool(visible) and page['dataset']==self.dataset_serial and page['loaded']
            if page['loaded']:
                if not page['render'].SetActorBlockGeometryVisible(page['name'],show):
                    raise RuntimeError('Native page visibility rejected '+page['name'])
                page['native_visible']=show
            if not self._controls(page):
                raise RuntimeError('Page control upload rejected')
        return self.snapshot()

    def set_profile(self,profile):
        self._idle()
        if not self.pipeline_ready or profile not in ('baseline','writer','restore','identity','dependent','integrity','calibration','coordinates','screeninfo'):
            raise ValueError('Need a ready pipeline and a declared static profile')
        current=[p for p in self.pages if p['dataset']==self.dataset_serial]
        if not current or not all(p['loaded'] for p in current):
            raise RuntimeError('All current payload pages must be resident')
        self.set_native_visible(profile!='baseline')
        selected=['raw'] if profile in ('baseline','writer') else ['raw','encode','decode']
        if profile in ('identity','dependent','calibration'):
            selected.append('consumer')
        if profile in ('integrity','coordinates','screeninfo'):
            selected.append('integrity')
        for name in self.process_enabled:
            enable=name.replace('scene_large_','') in selected
            if not self.post.SetEnableByName(name,enable):
                raise RuntimeError('Custom pass visibility rejected '+name)
            self.process_enabled[name]=enable
            self._params(name)
        if profile in ('identity','dependent','calibration'):
            mode={'identity':0,'dependent':2,'calibration':3}[profile]
            self._params('scene_large_consumer',mode)
            self.query_value=[0,self.plan['logical_bytes'],mode]
        if profile in ('integrity','coordinates','screeninfo'):
            mode={'integrity':0,'coordinates':3,'screeninfo':4}[profile]
            self._params('scene_large_integrity',mode,count=self.plan['records'])
            self.query_value=[0,self.plan['records'],mode]
        self.profile=profile
        return self.snapshot()

    def start_static_measurement(self,seconds=25.,warmup=2.):
        self._idle()
        seconds,warmup=float(seconds),float(warmup)
        if not 20.<=seconds<=25. or not 2.<=warmup<=4.:
            raise ValueError('Require20..25sample seconds and2..4warmup seconds')
        if self.profile not in ('baseline','writer','restore','dependent'):
            raise ValueError('Only the declared static profiles are measured')
        now=time.clock()
        self.measurement={'start':now,'warm_until':now+warmup,'until':now+warmup+seconds,'warmup':warmup,
            'previous_sample':None,'frames':0,'fps':[],'interval_ms':[]}
        self.last_measurement=None
        return self.snapshot()

    def snapshot(self):
        pages=[{key:value for key,value in p.items() if key!='render'} for p in self.pages]
        current=[p for p in pages if p['dataset']==self.dataset_serial]
        timings=('generation_ms','fingerprint_ms','symbols_ms','encode_ms','deserialize_ms','combine_ms','attach_ms','total_ms')
        return {'schema':'scene_codec_large_probe_v1','error':self.error,'source_bundle_sha256':SOURCE_BUNDLE_SHA256,
            'fixed_logical_bytes':FIXED_LOGICAL_BYTES,'native_compat_overlay_installed':COMPAT_OVERLAY,
            'seed':self.seed,'generation':self.generation,'dataset_serial':self.dataset_serial,'payload_plan':self.plan,
            'pages':pages,'ready':bool(current) and all(p['ready'] for p in current),
            'all_current_pages_loaded':bool(current) and all(p['loaded'] for p in current),
            'logical_payload_bytes':self.plan['logical_bytes'] if self.plan else 0,
            'allocated_payload_bytes_current':self.plan['allocated_bytes'] if self.plan else 0,
            'allocated_payload_bytes_all_datasets':sum(p['payload_byte_count'] for p in pages if p['loaded']),
            'allocated_records_all_datasets':sum(p['record_count'] for p in pages if p['loaded']),
            'geometry_build_serial':sum(int(p['loaded']) for p in pages),
            'native_attempt_serial':sum(int(p['attempted']) for p in pages),
            'cumulative_current_timings':{key:sum(p['timings'].get(key,0.) for p in current) for key in timings},
            'writer_visible':self.writer_visible,'profile':self.profile,'query':list(self.query_value),
            'screen_size':[1080,1440],'logical_screen_size':list(self.game.GetScreenSize()),
            'diagnostic_layout':[8,128,1024,1],'guard_rect_native':[0,128,1080,1408],
            'pipeline_installed':self.pipeline_installed,'pipeline_ready':self.pipeline_ready,
            'enabled_processes':[name for name in self.process_enabled if self.process_enabled[name]],
            'custom_pass_count':sum(self.process_enabled.values()),'connections':list(self.connections),
            'prior_native_post_states':list(self.original_post_states),
            'native_post_effects_enabled':[name for name,enabled in self.original_post_states if self.post.CheckEnabledByName(name)],
            'measurement_running':self.measurement is not None,'last_measurement':self.last_measurement,
            'render_event':self.render_event,'game_runtime_file_writes':False,'continuous_updates':False,
            'native_visibility_receipt':'successful setters; no getter or GPU completion fence'}

    def quiesce(self):
        self._idle()
        self.set_native_visible(False)
        for name in self.process_enabled:
            if not self.post.SetEnableByName(name,False):
                raise RuntimeError('Quiesce failed '+name)
            self.process_enabled[name]=False
        self.profile='quiesced'
        return self.snapshot()

    def Destroy(self):
        self.UnListenForEvent(api.GetEngineNamespace(),api.GetEngineSystemName(),'GameRenderTickEvent',self,self.on_frame)
