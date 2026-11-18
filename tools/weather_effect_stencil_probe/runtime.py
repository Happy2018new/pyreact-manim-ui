# -*- coding: utf-8 -*-
"""One stencil bit, frozen geometry pages, two public FrameAni readers."""
from geometry_atlas_probe.runtime import ProbeSystem as GeometryProbe
from geometry_atlas_probe.codec import encode_values


class ProbeSystem(GeometryProbe):
    def __init__(self,namespace,name):
        GeometryProbe.__init__(self,namespace,name)
        self.camera=self.factory.CreateCamera(self.level)
        self.effects=[]
        self.effect_controls=[]
        self.patterns={}
        self.selected='zero'
        self.mode='off'
        self.clear_enabled=False
        self.payload_enabled=False
        self.origin=None

    def prepare_camera(self):
        position=self.camera.GetPosition()
        self.origin=(int(position[0]),int(position[1])-1,int(position[2]))
        self.camera.DepartCamera()
        if not self.camera.SetCameraPos((self.origin[0],self.origin[1]+1.,self.origin[2])) or not self.camera.SetCameraRotation((8.,180.,0.)):
            raise RuntimeError('Fixed stencil camera rejected')
        return self.snapshot()

    def build_pages(self):
        if not self.ready or self.patterns:
            raise RuntimeError('Need one ready empty stencil probe')
        for pattern in ('zero','a','inverse','ones'):
            values=[0 if pattern=='zero' else (128 if pattern=='ones' or ((i%16+i//16)%2==0)==(pattern=='a') else 0) for i in range(256)]
            entries={}
            for kind in ('writer','check')+ (('clear',) if pattern=='zero' else ()):
                encoded=encode_values(values,'compact8')
                data=encoded['data']
                common={}
                for (identifier,aux),indices in data['common'].items():
                    suffix=identifier.rsplit('_',1)[-1]
                    target=('pmanim_geometry_atlas:quad_compact8_'+suffix if kind=='writer' else 'pmanim_geometry_stencil:'+kind+'_'+suffix)
                    common[(target,aux)]=indices
                data['common']=common
                palette=self.block.GetBlankBlockPalette()
                if palette is None or not palette.DeserializeBlockPalette(data):
                    raise RuntimeError('Stencil palette rejected')
                name='pmanim_stencil_'+pattern+'_'+kind
                result=self.geometry.CombineBlockPaletteToGeometry(palette,name,1)
                if not result or not self.render.AddActorBlockGeometry(result,(0.,0.,0.),(0.,0.,0.)):
                    raise RuntimeError('Stencil page attach rejected')
                if not self.render.SetActorBlockGeometryVisible(result,False):
                    raise RuntimeError('Stencil page initial hide rejected')
                entries[kind]=result
            self.patterns[pattern]=entries
        self.stride,self.slot_count=16,256
        self.layout=[256,16,96,192]
        self.dimensions=[8,720,1080,0]
        if not self._writer_controls():
            raise RuntimeError('Stencil geometry mapping rejected')
        position,forward=self.camera.GetPosition(),self.camera.GetForward()
        anchor=tuple(position[i]+forward[i]*4. for i in range(3))
        for kind,color in (('background',(0.,1.,1.,1.)),('masked',(1.,0.,1.,1.)),('positive',(1.,1.,0.,1.))):
            effect=self.CreateEngineSfxFromEditor('effects/stencil_'+kind+'.json',anchor,(0.,0.,0.),(4.,4.,4.))
            if effect is None:
                raise RuntimeError('Stencil reader effect rejected')
            control=self.factory.CreateFrameAniControl(effect)
            self.effects.append(effect)
            self.effect_controls.append(control)
            if not (control.SetFaceCamera(True) and control.SetLoop(True) and control.SetMixColor(color) and control.Stop()):
                raise RuntimeError('Stencil reader controls rejected')
        return self.configure('zero','off',False,False)

    def configure(self,pattern='zero',mode='late',clear=True,writer=True):
        if pattern not in self.patterns or mode not in ('off','source','baseline','positive','early','late'):
            raise ValueError('Invalid stencil controls')
        for pages in self.patterns.values():
            for name in pages.values():
                if not self.render.SetActorBlockGeometryVisible(name,False):
                    raise RuntimeError('Stencil page hide rejected')
        visible=[]
        if clear:
            visible.append(self.patterns['zero']['clear'])
        if writer:
            visible.append(self.patterns[pattern]['writer'])
        if mode=='source':
            visible.append(self.patterns[pattern]['check'])
        for name in visible:
            if not self.render.SetActorBlockGeometryVisible(name,True):
                raise RuntimeError('Stencil page show rejected')
        for i,control in enumerate(self.effect_controls):
            layer=1 if mode=='early' else (14 if i==0 else 15)
            show=(mode=='positive' and i==2) or (mode=='early' and i==1) or (mode=='baseline' and i==0) or (mode=='late' and i<2)
            if not control.SetLayer(layer) or not (control.Play() if show else control.Stop()):
                raise RuntimeError('Stencil reader layer/play rejected')
        self.selected,self.mode=pattern,mode
        self.clear_enabled,self.payload_enabled=bool(clear),bool(writer)
        return self.snapshot()

    def snapshot(self):
        result=GeometryProbe.snapshot(self)
        result.update({'schema':'weather_effect_stencil_bit_v1','source_roi':[96,192,128,128],
            'pattern':self.selected,'reader_mode':self.mode,'clear_enabled':self.clear_enabled,
            'payload_enabled':self.payload_enabled,'stencil_mask':128,'stencil_pages':self.patterns,
            'effects':list(self.effects),'camera_origin':self.origin,'runtime_file_writes':False,
            'native_post_flags':[(name,self.post.CheckEnabledByName(name)) for name in ('bloom','lensflare','depthoffield','gaussianblur','coloradjustment','vignette','lensstain','oldtv','scanmap')]})
        return result

    def Destroy(self):
        for effect,control in zip(self.effects,self.effect_controls):
            control.Stop()
            self.DestroyEntity(effect)
        self.effects=[]
        self.effect_controls=[]
        for pages in self.patterns.values():
            for name in pages.values():
                self.render.SetActorBlockGeometryVisible(name,False)
        GeometryProbe.Destroy(self)
        self.camera.ResetCameraPos()
        self.camera.UnDepartCamera()
