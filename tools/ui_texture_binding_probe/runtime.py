# -*- coding: utf-8 -*-
"""Finite UI sampler controls, with no tick listener or runtime file writes."""
import mod.client.extraClientApi as api

ScreenNode=api.GetScreenNodeCls()
ClientSystem=api.GetClientSystemCls()
KINDS=('producer','bound','default')


class TextureScreen(ScreenNode):
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

    def configure(self,**options):
        receiver=options.get('receiver','default')
        slot=options.get('slot',0)
        query=options.get('query',0)
        seed=options.get('seed',42)
        writer=options.get('writer',True)
        sample_mode=options.get('sample_mode',2)
        flip=options.get('flip',False)
        writer_after=options.get('writer_after',False)
        carrier_offscreen=options.get('carrier_offscreen',False)
        if set(options)-set(('receiver','slot','query','seed','writer','sample_mode','flip','writer_after','carrier_offscreen')):
            raise ValueError('Unknown finite sampler option')
        if (not self.ready or receiver not in ('bound','default') or slot not in (0,1,2)
                or query not in (0,1,2) or sample_mode not in (1,2,3) or not 0<=seed<=255):
            raise ValueError('Invalid finite sampler configuration')
        width,height=self.game.GetScreenSize()
        rectangles={'producer':(.1,.15,.8,.2),'bound':(.1,.55,.8,.2),'default':(.1,.55,.8,.2)}
        source_uv=(.1,.65,.8,.2)
        for index,kind in enumerate(KINDS):
            parent,image,canvas=self.controls[kind]
            nx,ny,nw,nh=rectangles[kind]
            parent.SetPosition((nx*width,ny*height))
            parent.SetSize((nw*width,nh*height))
            parent.SetLayer(40 if kind=='producer' and writer_after else 10+index*10,False)
            canvas.SetPosition((0.,0.))
            canvas.SetSize((nw*width,nh*height))
            image.SetPosition((10000.,10000.) if carrier_offscreen and kind=='producer' else (0.,0.))
            image.SetSpriteColor((seed/255.,.25,.75) if kind=='producer' else (.5,.5,.5))
            visible=bool(writer) if kind=='producer' else receiver==kind
            parent.SetVisible(visible,False)
            mode=0 if kind=='producer' else sample_mode
            params=(float(mode),float(slot),float(query),1. if flip else 0.)
            identifier='pmanim_packet:slot_%03d'%index
            values=((1,params),(2,source_uv),(3,(2*nx-1,1-2*ny,2*nw,2*nh)))
            for uniform,value in values:
                if not self.actor.SetEntityUIExtraUniforms(identifier,uniform,value):
                    raise RuntimeError('UI sampler uniform rejected')
            if not canvas.asNeteasePaperDoll().RenderEntity({'entity_identifier':identifier,
                    'scale':1.,'render_depth':-15,'init_rot_x':0.,'init_rot_y':0.,'init_rot_z':0.}):
                raise RuntimeError('UI sampler RenderEntity rejected')
        self.UpdateScreen(True)
        self.state={'receiver':receiver,'slot':slot,'query':query,'seed':seed,'writer':bool(writer),
            'sample_mode':sample_mode,'flip':bool(flip),'writer_after':bool(writer_after),
            'screen':[width,height],'producer_roi':[width*.1,height*.15,width*.8,height*.2],
            'receiver_roi':[width*.1,height*.55,width*.8,height*.2],
            'source_uv':list(source_uv),'carrier_offscreen':bool(carrier_offscreen),
            'producer_position':list(self.controls['producer'][0].GetPosition()),
            'carrier_position':list(self.controls['producer'][1].GetPosition()),
            'receiver_position':list(self.controls[receiver][0].GetPosition()),
            'receiver_control_params':[sample_mode,slot,query,int(bool(flip))],
            'receiver_has_seed_uniform':False,'same_frame_draw_order':'receiver_then_producer' if writer_after else 'producer_then_receiver',
            'candidate_binding':'default entity slots exploratory' if receiver=='default' else 'explicit static render controller textures'}
        return self.state


class ProbeSystem(ClientSystem):
    def __init__(self,namespace,name):
        ClientSystem.__init__(self,namespace,name)
        self.screen=None
        self.hud=None
        self.world=None
        self.registered=False
        self.world_registered=False
        self.binding='hud'
        self.anchor=None
        self.post=api.GetEngineCompFactory().CreatePostProcess(api.GetLevelId())
        self.post_installed=False
        self.post_saved=[]
        self.post_control=[0,0]

    def open(self):
        if self.screen is None:
            if not self.registered:
                if not api.RegisterUI('pmanim_ui_texture_probe','probe',
                        'ui_texture_binding_probe.runtime.TextureScreen','pmanim_ui_texture_probe.main'):
                    raise RuntimeError('RegisterUI rejected')
                self.registered=True
            self.screen=api.CreateUI('pmanim_ui_texture_probe','probe',{'isHud':1})
            if self.screen is None:
                raise RuntimeError('CreateUI failed')
            self.hud=self.screen
        return self.snapshot()

    def bind_world(self):
        if self.world is None:
            factory=api.GetEngineCompFactory()
            game=factory.CreateGame(api.GetLevelId())
            camera=factory.CreateCamera(api.GetLevelId())
            position,forward=camera.GetPosition(),camera.GetForward()
            self.anchor=(game.GetCurrentDimension(),tuple(position[index]+forward[index]*6. for index in range(3)))
            if not self.world_registered:
                if not api.RegisterUI('pmanim_ui_texture_probe','probe_world',
                        'ui_texture_binding_probe.runtime.TextureScreen','pmanim_ui_texture_probe.main'):
                    raise RuntimeError('World UI registration rejected')
                self.world_registered=True
            self.world=api.CreateUI('pmanim_ui_texture_probe','probe_world',{'bindWorldPosition':self.anchor})
            if self.world is None:
                raise RuntimeError('World-bound CreateUI failed')
        self.hud.SetScreenVisible(False)
        self.screen=self.world
        self.binding='world'
        return self.snapshot()

    def bind_hud(self):
        if self.world is not None:
            self.world.SetScreenVisible(False)
        self.screen=self.hud
        self.hud.SetScreenVisible(True)
        self.binding='hud'
        return self.snapshot()

    def install_post(self):
        if self.post_installed:
            raise RuntimeError('Post oracle already installed')
        self.post_saved=[(name,self.post.CheckEnabledByName(name)) for name in self.post.GetPostProcessOrder() or []]
        for name,enabled in self.post_saved:
            if enabled and not self.post.SetEnableByName(name,False):
                raise RuntimeError('Native post disable rejected')
        process={'name':'ui_texture_oracle','enable':False,
            'paras':[{'name':'control','value':[0.,0.,0.,0.],'range':[0.,1.]}],
            'pass_array':[{'render_target':{'width':1.,'height':1.},'material':'ui_texture_oracle','depth_enable':False}]}
        if not self.post.AddPostProcess(process,0):
            raise RuntimeError('Post oracle rejected')
        self.post_installed=True
        return self.snapshot()

    def set_post(self,enabled=True,slot=0,alpha=False):
        if slot not in (0,1):
            raise ValueError('Post oracle supports native T0/T1')
        if not self.post.SetParameter('ui_texture_oracle','control',[float(slot),float(bool(alpha)),0.,0.]):
            raise RuntimeError('Post oracle parameter rejected')
        if not self.post.SetEnableByName('ui_texture_oracle',bool(enabled)):
            raise RuntimeError('Post oracle selection rejected')
        self.post_control=[slot,int(bool(alpha))]
        return self.snapshot()

    def configure(self,**kwargs):
        self.screen.configure(**kwargs)
        return self.snapshot()

    def snapshot(self):
        return {'schema':'finite_ui_texture_binding_v1','ready':self.screen is not None and self.screen.ready,
            'screen':dict(self.screen.state) if self.screen is not None else None,
            'game_runtime_file_writes':False,'continuous_update':False,
            'binding':self.binding,'world_anchor':self.anchor,'post_installed':self.post_installed,
            'post_enabled':self.post.CheckEnabledByName('ui_texture_oracle') if self.post_installed else False,
            'post_control':list(self.post_control)}

    def Destroy(self):
        for screen in (self.hud,self.world):
            if screen is not None:
                screen.SetRemove()
        self.screen=self.hud=self.world=None
        if self.post_installed:
            self.post.SetEnableByName('ui_texture_oracle',False)
            for name,enabled in self.post_saved:
                if enabled:
                    self.post.SetEnableByName(name,True)
