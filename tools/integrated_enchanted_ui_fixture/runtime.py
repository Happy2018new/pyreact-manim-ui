# -*- coding: utf-8 -*-
"""Client-only native item widget; no custom glint shader or file I/O."""
import mod.client.extraClientApi as api
from .enchanted_ui_config import CONFIG

ScreenNode=api.GetScreenNodeCls()


class NativeItemScreen(ScreenNode):
    def __init__(self,namespace,name,param):
        ScreenNode.__init__(self,namespace,name,param)
        self.game=api.GetEngineCompFactory().CreateGame(api.GetLevelId())
        self.ready=False
        self.mode='off'
        self.receipt={}

    def Create(self):
        self.ready=True
        self.configure('off')

    def configure(self,mode='mixed'):
        if not self.ready or mode not in CONFIG['modes']:
            raise ValueError('Unready native item screen or unsupported mode')
        logical=self.game.GetScreenSize()
        view=self.game.GetScreenViewInfo()
        scale=(logical[0]/float(CONFIG['physical'][0]),logical[1]/float(CONFIG['physical'][1]))
        slots=[]
        for slot in CONFIG['slots']:
            path='/fixture/'+slot['id']
            expected=mode=='enchanted_all' or (mode=='mixed' and slot['role']=='enchanted')
            for suffix,rect in (('',slot['rect']),('/background',[0,0,88,88]),('/item',slot['renderer_local'])):
                control=self.GetBaseUIControl(path+suffix)
                if control is None:
                    raise RuntimeError('Missing native item fixture control: '+path+suffix)
                control.SetPosition((rect[0]*scale[0],rect[1]*scale[1]))
                control.SetSize((rect[2]*scale[0],rect[3]*scale[1]))
            item_base=self.GetBaseUIControl(path+'/item')
            renderer=item_base.asItemRenderer()
            if renderer is None:
                raise RuntimeError('Fixture did not resolve native ItemRenderer')
            accepted=renderer.SetUiItem(slot['item'],slot['aux'],bool(expected))
            if not accepted:
                raise RuntimeError('Native SetUiItem rejected: '+slot['id'])
            actual=renderer.GetUiItem()
            if (not isinstance(actual,dict) or actual.get('itemName')!=slot['item'] or
                    actual.get('auxValue')!=slot['aux'] or bool(actual.get('isEnchanted'))!=bool(expected)):
                raise RuntimeError('Native GetUiItem differs from requested enchant state: '+slot['id'])
            item_base.SetVisible(bool(slot['item_visible']),False)
            slots.append({'id':slot['id'],'role':slot['role'],'item_visible':bool(slot['item_visible']),
                'enchanted_requested':bool(expected),'accepted':bool(accepted),'item_getter':actual,
                'requested_physical':slot['renderer_rect'],'logical_position':list(item_base.GetPosition()),
                'logical_size':list(item_base.GetSize())})
        self.GetBaseUIControl('/fixture').SetVisible(mode!='off',False)
        self.UpdateScreen(True)
        self.mode=mode
        self.receipt={'ready':True,'mode':mode,'requested_visible':mode!='off',
            'actual_visible':self.GetBaseUIControl('/fixture').GetVisible(),'logical_screen':list(logical),
            'screen_view_info':list(view),'physical_target':list(CONFIG['physical']),
            'logical_per_physical':list(scale),'slots':slots,'route':CONFIG['route'],
            'stock_inventory_screen':False,'native_material_override':False,'runtime_file_writes':False}
        return self.snapshot()

    def snapshot(self):
        return dict(self.receipt)


class EnchantedFixture(object):
    def __init__(self,probe):
        self.probe=probe
        self.screen=None
        self.registered=False

    def open(self):
        if self.screen is None:
            if not self.registered:
                if not api.RegisterUI(CONFIG['namespace'],CONFIG['key'],CONFIG['class_path'],CONFIG['screen_def']):
                    raise RuntimeError('Native item fixture RegisterUI failed')
                self.registered=True
            self.screen=api.CreateUI(CONFIG['namespace'],CONFIG['key'],{'isHud':1})
            if self.screen is None:
                raise RuntimeError('Native item fixture CreateUI failed')
        return self.snapshot()

    def configure(self,mode='mixed'):
        if self.screen is None:
            if mode=='off': return self.snapshot()
            raise RuntimeError('Open native item fixture in a preceding managed call')
        return self.screen.configure(mode)

    def snapshot(self):
        return {'schema':CONFIG['schema'],'opened':self.screen is not None,'registered':self.registered,
            'screen':self.screen.snapshot() if self.screen is not None else None,'route':CONFIG['route'],
            'stock_inventory_screen':False,'source_roi':list(CONFIG['source_roi'])}

    def destroy(self):
        if self.screen is not None:
            self.screen.SetRemove()
            self.screen=None
        return self.snapshot()
