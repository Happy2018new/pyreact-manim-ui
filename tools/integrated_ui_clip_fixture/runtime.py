# -*- coding: utf-8 -*-
"""Client-only ordinary native JSON UI; no input, event loop, or file I/O."""
import mod.client.extraClientApi as api
from .ui_clip_fixture_config import CONFIG

ScreenNode=api.GetScreenNodeCls()


class NativeClipScreen(ScreenNode):
    def __init__(self,namespace,name,param):
        ScreenNode.__init__(self,namespace,name,param)
        self.game=api.GetEngineCompFactory().CreateGame(api.GetLevelId())
        self.ready=False
        self.visible=False
        self.receipt={}

    def Create(self):
        self.ready=True
        self.configure(False)

    def configure(self,visible):
        if not self.ready:
            raise RuntimeError('Native clip screen Create has not completed')
        logical=self.game.GetScreenSize()
        view=self.game.GetScreenViewInfo()
        scale=(float(logical[0])/CONFIG['physical'][0],float(logical[1])/CONFIG['physical'][1])
        if scale[0]<=0. or scale[1]<=0.:
            raise RuntimeError('Invalid native logical UI dimensions')
        positions=[]
        for case in CONFIG['cases']:
            root='/fixture/'+case['id']
            controls=((root,case['rect']), (root+'/backdrop',[0,0,96,64]),
                (root+'/clip',case['clip_rect_local']), (root+'/clip/child',case['child_rect_relative']))
            actual={}
            for path,rect in controls:
                control=self.GetBaseUIControl(path)
                control.SetPosition((rect[0]*scale[0],rect[1]*scale[1]))
                control.SetSize((rect[2]*scale[0],rect[3]*scale[1]))
                actual[path]={'logical_position':list(control.GetPosition()),'logical_size':list(control.GetSize())}
            positions.append({'id':case['id'],'expected_physical':case['rect'],'controls':actual})
        self.GetBaseUIControl('/fixture').SetVisible(bool(visible),False)
        self.UpdateScreen(True)
        self.visible=bool(visible)
        self.receipt={'ready':self.ready,'requested_visible':self.visible,
            'actual_visible':self.GetBaseUIControl('/fixture').GetVisible(),
            'logical_screen':list(logical),'screen_view_info':list(view),'physical_target':list(CONFIG['physical']),
            'logical_per_physical':list(scale),'cases':positions,'ordinary_native_images':True,
            'runtime_file_writes':False,'input_sent':False}
        return self.snapshot()

    def snapshot(self):
        return dict(self.receipt)


class UiClipFixture(object):
    def __init__(self,system):
        self.system=system
        self.screen=None
        self.registered=False

    def open(self):
        if self.screen is None:
            if not self.registered:
                accepted=api.RegisterUI(CONFIG['namespace'],CONFIG['key'],CONFIG['class_path'],CONFIG['screen_def'])
                if not accepted:
                    raise RuntimeError('Native UI clip fixture RegisterUI rejected')
                self.registered=True
            self.screen=api.CreateUI(CONFIG['namespace'],CONFIG['key'],{'isHud':1})
            if self.screen is None:
                raise RuntimeError('Native UI clip fixture CreateUI failed')
        return self.snapshot()

    def configure(self,visible):
        if self.screen is None:
            if visible:
                raise RuntimeError('Open native UI fixture before configuring visibility')
            return self.snapshot()
        return self.screen.configure(bool(visible))

    def snapshot(self):
        return {'schema':CONFIG['schema'],'opened':self.screen is not None,'registered':self.registered,
            'screen':self.screen.snapshot() if self.screen is not None else None,
            'source_roi':list(CONFIG['source_roi']),'physical_target':list(CONFIG['physical']),
            'fixture_only':True}

    def destroy(self):
        if self.screen is not None:
            self.screen.SetRemove()
            self.screen=None
        return self.snapshot()
