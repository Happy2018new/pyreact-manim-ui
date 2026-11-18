# -*- coding: utf-8 -*-
"""Finite client-only controls. No event loop, filesystem writes or native input."""
import mod.client.extraClientApi as api

ScreenNode=api.GetScreenNodeCls()
ClientSystem=api.GetClientSystemCls()
KINDS=('rgb','alpha','reader')


class AlphaScreen(ScreenNode):
    def __init__(self,namespace,name,param):
        ScreenNode.__init__(self,namespace,name,param)
        factory=api.GetEngineCompFactory()
        self.actor=factory.CreateActorRender(None)
        self.game=factory.CreateGame(api.GetLevelId())
        self.ready=False
        self.controls={}
        self.state={}

    def Create(self):
        for kind in KINDS:
            parent=self.GetBaseUIControl('/'+kind)
            image=self.GetBaseUIControl('/'+kind+'/carrier').asImage()
            canvas=self.GetBaseUIControl('/'+kind+'/canvas')
            self.controls[kind]=(parent,image,canvas)
        self.ready=True

    def configure(self,writer='alpha',value=42,reader=False,offscreen=False,carrier_offscreen=False):
        if not self.ready or writer not in ('hidden','rgb','alpha') or not 0<=value<=255:
            raise ValueError('Unready screen or invalid finite configuration')
        width,height=self.game.GetScreenSize()
        x,y,w,h=width*.2,height*.25,width*.6,height*.5
        rectangle=(2*x/width-1,1-2*y/height,2*w/width,2*h/height)
        for index,kind in enumerate(KINDS):
            parent,image,canvas=self.controls[kind]
            parent.SetPosition((10000.,10000.) if offscreen and kind!='reader' else (x,y))
            parent.SetSize((w,h))
            canvas.SetPosition((0.,0.))
            canvas.SetSize((w,h))
            image.SetSpriteColor((float(value)/255.,0.25,0.75))
            image.SetPosition((10000.,10000.) if carrier_offscreen and kind!='reader' else (0.,0.))
            visible=bool(reader) if kind=='reader' else writer==kind
            parent.SetVisible(visible,False)
            identifier='pmanim_packet:slot_%03d'%index
            if not self.actor.SetEntityUIExtraUniforms(identifier,3,rectangle):
                raise RuntimeError('Rectangle uniform rejected')
            if not canvas.asNeteasePaperDoll().RenderEntity({'entity_identifier':identifier,
                    'scale':1.,'render_depth':-15,'init_rot_x':0.,'init_rot_y':0.,'init_rot_z':0.}):
                raise RuntimeError('RenderEntity rejected')
        self.UpdateScreen(True)
        self.state={'writer':writer,'value':value,'reader':bool(reader),'offscreen':bool(offscreen),
            'screen':[width,height],'roi':[x,y,w,h],'ndc_rectangle':list(rectangle),
            'requested_writer_position':[10000.,10000.] if offscreen else [x,y],
            'native_writer_position':list(self.controls['alpha' if writer=='hidden' else writer][0].GetPosition()),
            'carrier_offscreen':bool(carrier_offscreen),
            'native_carrier_position':list(self.controls['alpha' if writer=='hidden' else writer][1].GetPosition()),
            'clip_space_rectangle_held_fixed':True,'native_scissor':True,'current_color_source':'transparent preceding image'}
        return self.state


class ProbeSystem(ClientSystem):
    def __init__(self,namespace,name):
        ClientSystem.__init__(self,namespace,name)
        self.screen=None
        self.registered=False
        self.post=api.GetEngineCompFactory().CreatePostProcess(api.GetLevelId())
        self.installed=False
        self.connections=[]
        self.saved=[]
        self.post_mode='off'

    def open(self):
        if self.screen is None:
            if not self.registered:
                if not api.RegisterUI('pmanim_ui_alpha_probe','probe','ui_alpha_probe.runtime.AlphaScreen','pmanim_ui_alpha_probe.main'):
                    raise RuntimeError('RegisterUI rejected')
                self.registered=True
            self.screen=api.CreateUI('pmanim_ui_alpha_probe','probe',{'isHud':1})
            if self.screen is None:
                raise RuntimeError('CreateUI failed')
        return self.snapshot()

    def configure(self,writer='alpha',value=42,reader=False,offscreen=False,carrier_offscreen=False):
        self.screen.configure(writer,value,reader,offscreen,carrier_offscreen)
        return self.snapshot()

    def install_post(self):
        if self.installed:
            raise RuntimeError('Already installed')
        self.saved=[(name,self.post.CheckEnabledByName(name)) for name in self.post.GetPostProcessOrder() or []]
        for name,enabled in self.saved:
            if enabled and not self.post.SetEnableByName(name,False):
                raise RuntimeError('Baseline disable rejected')
        for index,kind in enumerate(('copy','t0','t1')):
            process={'name':'ui_alpha_'+kind,'enable':False,'paras':[],
                'pass_array':[{'render_target':{'width':1.,'height':1.},'material':'ui_alpha_'+kind,'depth_enable':False}]}
            if not self.post.AddPostProcess(process,index):
                raise RuntimeError('Postprocess rejected')
        self.installed=True
        return self.snapshot()

    def finish_post(self):
        self.connections.append(['TEXTURE_1','built_in_original_color','no_custom_link'])
        return self.set_post('off')

    def set_post(self,mode='off'):
        if mode not in ('off','t0','t1'):
            raise ValueError('Unknown post mode')
        for kind in ('copy','t0','t1'):
            enabled=mode==kind
            if not self.post.SetEnableByName('ui_alpha_'+kind,enabled):
                raise RuntimeError('Post selection rejected')
        self.post_mode=mode
        return self.snapshot()

    def snapshot(self):
        return {'schema':'finite_ui_alpha_v1','ready':self.screen is not None and self.screen.ready,
            'screen':dict(self.screen.state) if self.screen is not None else None,
            'post_installed':self.installed,'post_mode':self.post_mode,'connections':list(self.connections),
            'post_enabled':dict((kind,self.post.CheckEnabledByName('ui_alpha_'+kind))
                for kind in ('copy','t0','t1')) if self.installed else {},
            'game_runtime_file_writes':False,'continuous_update':False}

    def Destroy(self):
        if self.screen is not None:
            self.screen.SetRemove()
            self.screen=None
        if self.installed:
            for kind in ('copy','t0','t1'):
                self.post.SetEnableByName('ui_alpha_'+kind,False)
            for name,enabled in self.saved:
                if enabled:
                    self.post.SetEnableByName(name,True)
