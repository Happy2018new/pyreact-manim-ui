# -*- coding: utf-8 -*-
"""Bounded arbitrary64B through two geometry stencil bits and three late draws."""
from geometry_atlas_probe.runtime import ProbeSystem as GeometryProbe
from geometry_atlas_probe.codec import encode_values


class ProbeSystem(GeometryProbe):
    def __init__(self,namespace,name):
        GeometryProbe.__init__(self,namespace,name)
        self.camera=self.factory.CreateCamera(self.level)
        self.effects=[]
        self.controls=[]
        self.pages=[]
        self.active_pages=[]
        self.clear_page=None
        self.payload=[0]*64
        self.generation=0
        self.background=False
        self.mode='off'
        self.payload_visible=False
        self.origin=None
        self.oracle_installed=False
        self.oracle_enabled=False
        self.oracle_mode=0
        self.oracle_slot=0

    def prepare(self):
        position=self.camera.GetPosition()
        self.origin=(int(position[0]),int(position[1])-1,int(position[2]))
        self.camera.DepartCamera()
        if not self.camera.SetCameraPos((self.origin[0],self.origin[1]+1.,self.origin[2])) or not self.camera.SetCameraRotation((8.,180.,0.)):
            raise RuntimeError('Fixed camera rejected')
        return self.open()

    def page(self,values,kind):
        encoded=encode_values(values,'compact8')
        data=encoded['data']
        common={}
        for (identifier,aux),indices in data['common'].items():
            suffix=identifier.rsplit('_',1)[-1]
            target='pmanim_stencil_packed:'+kind+'_'+suffix
            common[(target,aux)]=indices
        data['common']=common
        palette=self.block.GetBlankBlockPalette()
        if palette is None or not palette.DeserializeBlockPalette(data):
            raise RuntimeError('Packed stencil palette rejected')
        name='pmanim_stencil_packed_%s_%d'%(kind,len(self.pages))
        result=self.geometry.CombineBlockPaletteToGeometry(palette,name,1)
        if not result or not self.render.AddActorBlockGeometry(result,(0.,0.,0.),(0.,0.,0.)):
            raise RuntimeError('Packed stencil geometry rejected')
        if not self.render.SetActorBlockGeometryVisible(result,False):
            raise RuntimeError('Packed stencil page hide rejected')
        self.pages.append(result)
        return result

    def create(self):
        if not self.ready or self.effects:
            raise RuntimeError('Need a ready empty packed probe')
        self.stride,self.slot_count=16,256
        self.layout=[256,16,96,192]
        self.dimensions=[8,720,1080,0]
        self.clear_page=self.page(list(range(256)),'clear')
        position,forward=self.camera.GetPosition(),self.camera.GetForward()
        anchor=tuple(position[i]+forward[i]*4. for i in range(3))
        for kind,color in (('base',(0.,0.,0.,192./255.)),('bit64',(64./255.,0.,0.,1.)),('bit128',(128./255.,0.,0.,1.))):
            effect=self.CreateEngineSfxFromEditor('effects/stencil_packed_'+kind+'.json',anchor,(0.,0.,0.),(4.,4.,4.))
            if effect is None:
                raise RuntimeError('Packed stencil effect rejected')
            control=self.factory.CreateFrameAniControl(effect)
            self.effects.append(effect)
            self.controls.append(control)
            if not (control.SetFaceCamera(True) and control.SetLoop(True) and control.SetMixColor(color) and control.Stop()):
                raise RuntimeError('Packed stencil frame controls rejected')
        self.write([0]*64)
        return self.configure('off',False)

    def mapping(self):
        if not self._writer_controls() or not self.render.SetEntityExtraUniforms(4,(1.,0.,float(self.background),0.)):
            raise RuntimeError('Packed stencil geometry mapping rejected')

    def write(self,values):
        if not isinstance(values,(list,tuple)) or len(values)!=64:
            raise ValueError('Expected exactly64integer bytes')
        if any(not isinstance(value,(int,long)) or not 0<=value<=255 for value in values):
            raise ValueError('Payload values must be bytes')
        if len(self.pages)>40:
            raise RuntimeError('Bounded geometry budget exhausted')
        symbols=[((values[index//4]>>(2*(index%4)))&3)*64 for index in range(256)]
        new_pages=[self.page(symbols,'bit64'),self.page(symbols,'bit128')]
        for name in self.active_pages:
            if not self.render.SetActorBlockGeometryVisible(name,False):
                raise RuntimeError('Previous packed payload hide rejected')
        self.active_pages=new_pages
        self.payload=list(values)
        self.generation+=1
        return self.configure(self.mode,self.background)

    def configure(self,mode='all',background=False):
        if mode not in ('off','fixture','all') or len(self.controls)!=3:
            raise ValueError('Invalid packed stencil control')
        self.mode,self.background=mode,bool(background)
        self.mapping()
        if not self.render.SetActorBlockGeometryVisible(self.clear_page,mode!='off'):
            raise RuntimeError('Packed clear visibility rejected')
        for name in self.active_pages:
            if not self.render.SetActorBlockGeometryVisible(name,mode=='all'):
                raise RuntimeError('Packed writer visibility rejected')
        self.payload_visible=mode=='all'
        for index,control in enumerate(self.controls):
            if not control.SetLayer(13+index) or not (control.Play() if mode=='all' else control.Stop()):
                raise RuntimeError('Packed layer/play rejected')
        return self.snapshot()

    def hide_payload(self):
        for name in self.active_pages:
            if not self.render.SetActorBlockGeometryVisible(name,False):
                raise RuntimeError('Packed negative hide rejected')
        self.payload_visible=False
        return self.snapshot()

    def install_oracle(self):
        if self.oracle_installed:
            raise RuntimeError('Oracle already installed')
        if any(self.post.CheckEnabledByName(name) for name in ('bloom','lensflare','depthoffield','gaussianblur','coloradjustment','vignette','lensstain','oldtv','scanmap')):
            raise RuntimeError('Native post effects not isolated')
        process={'name':'stencil_packed_oracle','enable':False,'paras':[
            {'name':'control','value':[720.,1080.,0.,0.],'range':[0.,1048576.]},
            {'name':'roi','value':[96.,192.,128.,128.],'range':[0.,1048576.]},
            {'name':'output','value':[0.,600.,720.,1.],'range':[0.,1048576.]}],
            'pass_array':[{'render_target':{'width':1.,'height':1.},'material':'stencil_packed_copy','depth_enable':False},
                {'render_target':{'width':1.,'height':1.},'material':'stencil_packed_oracle','depth_enable':False}]}
        if not self.post.AddPostProcess(process,0):
            raise RuntimeError('Packed oracle registration rejected')
        self.oracle_installed=True
        return self.snapshot()

    def inspect(self,mode=0,slot=0,enabled=True):
        if not self.oracle_installed or mode not in (0,1,2,3) or slot not in (0,1):
            raise ValueError('Invalid packed oracle controls')
        if not self.post.SetParameter('stencil_packed_oracle','control',[720.,1080.,float(slot),float(mode)]):
            raise RuntimeError('Packed oracle parameters rejected')
        if not self.post.SetEnableByName('stencil_packed_oracle',bool(enabled)):
            raise RuntimeError('Packed oracle enable rejected')
        self.oracle_mode,self.oracle_slot,self.oracle_enabled=mode,slot,bool(enabled)
        return self.snapshot()

    def snapshot(self):
        return {'schema':'weather_stencil_packed64_v1','ready':self.ready,'error':self.error,
            'source_roi':[96,192,128,128],'logical_bytes':64,'geometry_records_per_page':256,
            'page_names':list(self.pages),'active_pages':list(self.active_pages),'clear_page':self.clear_page,
            'payload':list(self.payload),'generation':self.generation,'effects':list(self.effects),
            'mode':self.mode,'payload_visible':self.payload_visible,'known_background':self.background,'camera_origin':self.origin,
            'oracle_installed':self.oracle_installed,'oracle_mode':self.oracle_mode,'oracle_slot':self.oracle_slot,
            'oracle_enabled':self.post.CheckEnabledByName('stencil_packed_oracle') if self.oracle_installed else False,
            'actual_post_order':list(self.post.GetPostProcessOrder() or []),
            'native_post_flags':[(name,self.post.CheckEnabledByName(name)) for name in ('bloom','lensflare','depthoffield','gaussianblur','coloradjustment','vignette','lensstain','oldtv','scanmap')],
            'runtime_file_writes':False,'continuous_update':False,'performance_claimed':False}

    def Destroy(self):
        for effect,control in zip(self.effects,self.controls):
            control.Stop()
            self.DestroyEntity(effect)
        if self.oracle_installed:
            self.post.SetEnableByName('stencil_packed_oracle',False)
        GeometryProbe.Destroy(self)
        self.camera.ResetCameraPos()
        self.camera.UnDepartCamera()
