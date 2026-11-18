import importlib.util
import copy
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'tools/scene_codec_large_probe'


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


layout=module('scene_large_layout_test',HERE/'layout.py')
codec=module('scene_large_codec_test',ROOT/'tools/scene_codec_probe/codec.py')
verify=module('scene_large_verify_test',HERE/'verify_capture.py')


def receipt(logical=262144):
    plan=layout.plan_payload(logical)
    pages=[dict(p,dataset=1,seed=54321,generation=1,loaded=True,name='page%02d'%p['page'],
        upload_serial=p['page']+1,payload_fingerprint={'algorithm':'sum_u8_mod2^32','value':0},entity='entity%02d'%p['page'])
        for p in plan['pages']]
    return {'schema':'scene_codec_large_probe_v1','screen_size':[1080,1440],
        'source_bundle_sha256':'test','seed':54321,'generation':1,'dataset_serial':1,
        'logical_payload_bytes':logical,'allocated_payload_bytes_current':plan['allocated_bytes'],
        'allocated_payload_bytes_all_datasets':plan['allocated_bytes'],
        'allocated_records_all_datasets':plan['records'],'geometry_build_serial':len(pages),
        'native_attempt_serial':len(pages),'all_current_pages_loaded':True,'pipeline_ready':True,
        'profile':'identity','query':[0,logical,0],
        'diagnostic_layout':[8,128,1024,1],'guard_rect_native':[0,128,1080,1408],
        'payload_plan':plan,'pages':pages}


class SceneCodecLargeTests(unittest.TestCase):
    def test_native_effect_isolation_preserves_passes_parameters_and_source(self):
        builder=module('scene_large_isolation_builder_test',HERE/'build_probe.py')
        original={'render_order':['bloom','depthoffield'],'process_array':[
            {'name':'bloom','enable':True,'paras':{'threshold':.5},
             'pass_array':[{'material':'threshold','render_target':{'width':.5,'height':.5}}]},
            {'name':'depthoffield','enable':False,'paras':{'focus':1.},
             'pass_array':[{'material':'depth_sample'}]}]}
        untouched=copy.deepcopy(original)
        isolated=builder.native_effects_off(original)
        self.assertEqual(original,untouched)
        self.assertEqual(isolated['render_order'],original['render_order'])
        self.assertTrue(all(item['enable'] is False for item in isolated['process_array']))
        for source,generated in zip(original['process_array'],isolated['process_array']):
            self.assertEqual({k:v for k,v in source.items() if k!='enable'},
                {k:v for k,v in generated.items() if k!='enable'})
        original['render_order'].append('unknown')
        with self.assertRaises(ValueError):
            builder.native_effects_off(original)

    def test_fixed_k2_fragment_cannot_consume_page_base_as_a_diagnostic_switch(self):
        source=(HERE/'scatter.fragment').read_text(encoding='utf-8')
        builder=(HERE/'build_probe.py').read_text(encoding='utf-8')
        self.assertNotIn('EXTRA_ACTOR_UNIFORM',source)
        self.assertNotIn('code_domain',source)
        self.assertNotIn('background',source)
        self.assertIn("'scatter.fragment':HERE/'scatter.fragment'",builder)
        for q in range(64):
            payload=(q%4,(q//4)%4,q//16)
            self.assertEqual(payload[0]+4*payload[1]+16*payload[2],q)
            self.assertTrue(all(0<=channel<=3 for channel in payload))

    def test_capacity_and_safe_roi(self):
        self.assertEqual(((524288+23)//24)*32,699072)
        self.assertLess(720*(1064-128),699072)
        for logical,rows,records,pages,padding in ((262144,497,349888,6,272),(524288,993,699072,11,16)):
            plan=layout.plan_payload(logical)
            self.assertEqual(plan['roi'],[8,128,704,rows])
            self.assertEqual(plan['records'],records)
            self.assertEqual(len(plan['pages']),pages)
            self.assertEqual(plan['padding_bytes'],padding)
            self.assertLessEqual(128+rows,1408)
            self.assertEqual(sum(p['record_count'] for p in plan['pages']),records)
            self.assertTrue(all(p['stride']<=256 and p['palette_height']==16 for p in plan['pages']))

    def test_full_arrays_pack_by_page_without_reset_or_cross_block_tail(self):
        for logical in (262144,524288):
            with self.subTest(logical=logical):
                plan=layout.plan_payload(logical)
                recovered=bytearray()
                for index,page in enumerate(plan['pages']):
                    values=layout.page_payload(plan,index)
                    self.assertEqual(page['record_base']%32,0)
                    self.assertEqual(page['record_count']%32,0)
                    self.assertEqual(page['payload_byte_base']%24,0)
                    self.assertEqual(len(values),page['payload_byte_count'])
                    symbols=codec.payload_to_symbols(values,2)
                    self.assertEqual(len(symbols),page['record_count'])
                    self.assertEqual(codec.symbols_to_payload(symbols,2,len(values)),values)
                    recovered.extend(values)
                expected=verify.expected_bytes(54321,1,np.arange(logical,dtype=np.uint64)).tobytes()
                self.assertEqual(bytes(recovered[:logical]),expected)
                self.assertEqual(recovered[logical:],bytearray(plan['padding_bytes']))

    def test_float32_every_address_and_every_source_record(self):
        for logical in (262144,524288):
            with self.subTest(logical=logical):
                integer=np.arange(logical,dtype=np.uint64)
                f=integer.astype(np.float32)
                a16=np.mod(f*16,np.float32(logical))
                a128=np.mod(a16*8,np.float32(logical))
                indexed=np.mod(a128+3*f+29,np.float32(logical))
                indexed_integer=(131*integer+29)%logical
                self.assertTrue(np.array_equal(indexed.astype(np.uint64),indexed_integer))
                first=verify.expected_bytes(54321,1,indexed_integer)
                dependent=np.mod(indexed+257*first.astype(np.float32)+113,np.float32(logical))
                exact=(indexed_integer+257*first.astype(np.uint64)+113)%logical
                self.assertTrue(np.array_equal(dependent.astype(np.uint64),exact))
                self.assertEqual(np.unique(indexed_integer).size,logical)
                block=np.floor(dependent/24).astype(np.uint64)*32
                self.assertTrue(np.array_equal(block,(exact//24)*32))
                plan=layout.plan_payload(logical)
                record=np.arange(plan['records'],dtype=np.uint64)
                source_x=(record%704+8).astype(np.float32)
                source_y=(record//704+128).astype(np.float32)
                uvx=(source_x+.5)/np.float32(1080)
                uvy=(source_y+.5)/np.float32(1440)
                self.assertTrue(np.array_equal(np.floor(uvx*1080),source_x))
                self.assertTrue(np.array_equal(np.floor(uvy*1440),source_y))
                flipped=np.float32(1.)-uvy
                self.assertTrue(np.array_equal(np.floor((np.float32(1.)-flipped)*1440),source_y))

    def test_alpha_block_four_exceptions_and_overflow_rejection(self):
        payload=bytearray(range(24))
        alpha=bytearray([255]*32)
        for position,value in ((0,0),(7,23),(16,128),(31,254)):
            alpha[position]=value
        encoded=codec.encode_alpha_block(alpha,payload)
        self.assertFalse(encoded['overflow'])
        decoded=codec.decode_alpha_block(encoded['encoded'])
        self.assertEqual(decoded['alpha'],alpha)
        self.assertEqual(decoded['payload'],payload)
        alpha[12]=1
        self.assertTrue(codec.encode_alpha_block(alpha,payload)['overflow'])

    def test_verifier_checks_last_byte_border_and_wrong_generation(self):
        state=receipt()
        n=state['logical_payload_bytes']
        array=np.empty((1440,1080,4),dtype=np.uint8)
        array[:]=[8,16,32,255]
        expected=verify.expected_bytes(54321,1,np.arange(n)).reshape(n//1024,1024)
        array[128:128+n//1024,8:1032,:3]=expected[:,:,None]
        self.assertTrue(verify.verify_image(state,Image.fromarray(array),'identity')['passed'])
        wrong=dict(state,generation=2,pages=[dict(p,generation=2) for p in state['pages']])
        self.assertFalse(verify.verify_image(wrong,Image.fromarray(array),'identity')['passed'])
        array[128+n//1024-1,1031,0]^=1
        result=verify.verify_image(state,Image.fromarray(array),'identity')
        self.assertEqual(result['failed_query_pixels'],1)
        self.assertEqual(result['failures_first16'][0]['ordinal'],n-1)
        array[800,0,0]^=1
        self.assertEqual(verify.verify_image(state,Image.fromarray(array),'identity')['failed_guard_pixels'],1)

    def test_bad_counts_dimensions_and_page_identity_rejected(self):
        with self.assertRaises(ValueError):
            layout.plan_payload(524289)
        with self.assertRaises(ValueError):
            layout.plan_payload(524288,1)
        state=receipt()
        with self.assertRaises(ValueError):
            verify.validate(state,(720,1080))
        state['pages'][1]['record_base']=0
        with self.assertRaises(ValueError):
            verify.validate(state,(1080,1440))

    def test_runtime_two_datasets_global_uniforms_native_visibility_and_static_freeze(self):
        class Actor:
            def __init__(self):
                self.uniforms={}
                self.visibility={}
            def SetEntityExtraUniforms(self,index,group):
                self.uniforms[index]=tuple(group)
                return True
            def AddActorBlockGeometry(self,name,*unused):
                self.visibility[name]=True
                return True
            def SetActorBlockGeometryVisible(self,name,visible):
                self.visibility[name]=visible
                return True
        class Palette:
            def DeserializeBlockPalette(self,data):
                self.volume=data['volume']
                return True
        class Native:
            def GetBlankBlockPalette(self):
                return Palette()
            def CombineBlockPaletteToGeometry(self,palette,name,unsupported_mode):
                self_test.assertLessEqual(palette.volume[0],256)
                self_test.assertEqual(palette.volume[2],16)
                return name
            def GetScreenSize(self):
                return [270.,360.]
            def GetFps(self):
                return 60.
            def SetEntityShadowShow(self,value):
                return True
            def GetPosition(self):
                return (0.,64.,0.)
            def GetForward(self):
                return (0.,0.,1.)
        class Post:
            def __init__(self):
                self.enabled={'bloom':True}
                self.params={}
                self.zero_custom_transitions=0
            def GetPostProcessOrder(self):
                return list(self.enabled)
            def CheckEnabledByName(self,name):
                return self.enabled.get(name,False)
            def SetEnableByName(self,name,value):
                active_before=any(enabled for n,enabled in self.enabled.items() if n.startswith('scene_large_'))
                self.enabled[name]=value
                active_after=any(enabled for n,enabled in self.enabled.items() if n.startswith('scene_large_'))
                if active_before and not active_after:
                    self.zero_custom_transitions+=1
                return True
            def AddPostProcess(self,item,index):
                self.enabled[item['name']]=False
                return True
            def PostPassResultToOtherPass(self,*unused):
                return True
            def SetParameter(self,name,key,value):
                self.params[name,key]=value
                return True
        class Factory:
            def __init__(self):
                self.actors={}
                self.native=Native()
                self.post=Post()
            def CreateActorRender(self,entity):
                return self.actors.setdefault(entity,Actor())
            def CreatePostProcess(self,level):
                return self.post
            def CreateGame(self,level): return self.native
            def CreateBlock(self,level): return self.native
            def CreateBlockGeometry(self,level): return self.native
            def CreateModel(self,entity): return self.native
            def CreateCamera(self,level): return self.native
        class Client:
            def __init__(self,*unused): self.next_entity=0
            def ListenForEvent(self,*unused): pass
            def UnListenForEvent(self,*unused): pass
            def CreateClientEntityByTypeStr(self,*unused):
                self.next_entity+=1
                return str(self.next_entity)
        self_test=self
        factory=Factory()
        api=types.ModuleType('mod.client.extraClientApi')
        api.GetClientSystemCls=lambda:Client
        api.GetEngineCompFactory=lambda:factory
        api.GetLevelId=lambda:'level'
        api.GetEngineNamespace=lambda:'Minecraft'
        api.GetEngineSystemName=lambda:'engine'
        api.HideHudGUI=lambda value:None
        api.HideCrossHairGUI=lambda value:None
        config=types.ModuleType('geometry_atlas_probe.large_config')
        config.PROCESSES=[{'name':'scene_large_'+name} for name in ('raw','encode','decode','consumer','integrity')]
        config.SOURCE_BUNDLE_SHA256='test'
        config.FIXED_LOGICAL_BYTES=None
        config.COMPAT_OVERLAY=False
        packet=module('scene_large_packet_test',ROOT/'tools/geometry_packet_probe/codec.py')
        scheduler=module('scene_large_stats_test',ROOT/'tools/geometry_atlas_probe/update_scheduler.py')
        modules={'mod':types.ModuleType('mod'),'mod.client':types.ModuleType('mod.client'),
            'mod.client.extraClientApi':api,'geometry_atlas_probe':types.ModuleType('geometry_atlas_probe'),
            'geometry_atlas_probe.codec':packet,'geometry_atlas_probe.scene_codec':codec,
            'geometry_atlas_probe.large_layout':layout,'geometry_atlas_probe.large_config':config,
            'geometry_atlas_probe.update_scheduler':scheduler}
        with mock.patch.dict(sys.modules,modules):
            runtime=module('scene_large_runtime_test',HERE/'runtime.py')
        now={'value':0.}
        with mock.patch.object(runtime.time,'clock',lambda:now['value'],create=True):
            probe=runtime.ProbeSystem('test','test')
            for logical in (262144,524288):
                probe.prepare(logical)
                for page_index in range(len(probe.plan['pages'])):
                    probe.upload_page(page_index)
                if not probe.pipeline_installed:
                    probe.install_pipeline()
                    probe.finish_pipeline()
                probe.set_profile('identity')
                current=[p for p in probe.pages if p['dataset']==probe.dataset_serial]
                self.assertEqual(sum(p['native_visible'] for p in probe.pages),len(current))
                for p in current:
                    self.assertEqual(p['render'].uniforms[4][3],p['record_base'])
                    self.assertEqual(p['render'].uniforms[4][2],2.)
                frozen=verify.payload_identity(probe.snapshot())
                probe.set_profile('baseline')
                self.assertEqual(sum(p['native_visible'] for p in probe.pages),0)
                self.assertEqual(probe.snapshot()['custom_pass_count'],1)
                self.assertEqual(probe.snapshot()['enabled_processes'],['scene_large_raw'])
                self.assertEqual(probe.snapshot()['native_post_effects_enabled'],[])
                with mock.patch.dict(sys.modules,{'verify_capture':verify}):
                    runner=module('scene_large_runner_copy_test',HERE/'runner.py')
                for profile in ('writer','baseline'):
                    exec(runner.copy_profile_controls(profile),{'probe':probe})
                    self.assertEqual(probe.snapshot()['enabled_processes'],['scene_large_raw'])
                    self.assertEqual(sum(p['native_visible'] for p in probe.pages),
                        len(current) if profile=='writer' else 0)
                    self.assertEqual(verify.payload_identity(probe.snapshot()),frozen)
                probe.set_profile('restore')
                self.assertEqual(probe.snapshot()['custom_pass_count'],3)
                probe.set_profile('dependent')
                self.assertEqual(probe.snapshot()['custom_pass_count'],4)
                self.assertEqual(verify.payload_identity(probe.snapshot()),frozen)
                self.assertEqual(factory.post.zero_custom_transitions,0)
            self.assertEqual(len(probe.pages),17)
            probe.start_static_measurement(25.,2.)
            with self.assertRaises(RuntimeError):
                probe.set_profile('baseline')
            for frame in range(1,1621):
                now['value']=frame/60.
                probe.on_frame({})
            result=probe.last_measurement
            self.assertEqual(result['warmup_seconds'],2.)
            self.assertEqual(result['sample_seconds'],25.)
            self.assertEqual(result['fps']['count'],100)
            self.assertEqual(len(result['raw_interval_ms']),1500)
            probe.quiesce()
            self.assertFalse(any(p['native_visible'] for p in probe.pages))


if __name__=='__main__':
    unittest.main()
