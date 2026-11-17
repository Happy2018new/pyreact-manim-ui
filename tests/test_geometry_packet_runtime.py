"""Offline transport contracts; native packed precision still requires pixels."""
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch


ROOT=Path(__file__).resolve().parents[1]
PROBE=ROOT/'tools/geometry_packet_probe'


def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Base:
    def __init__(self,*args):
        self.events=[]

    def ListenForEvent(self,*args):
        self.events.append(args)

    def UnListenForEvent(self,*args):
        self.events.remove(args)


class Game:
    def GetScreenSize(self):
        return (360.,540.)

    def GetFps(self):
        return 60.


class Palette:
    def __init__(self,factory):
        self.factory=factory

    def DeserializeBlockPalette(self,data):
        self.factory.palettes.append(data)
        return self.factory.deserialize_ok


class Factory:
    def __init__(self):
        self.palettes=[]
        self.names=[]
        self.deserialize_ok=True
        self.combine_ok=True

    def CreateGame(self,level):
        return Game()

    def CreateBlock(self,level):
        return self

    def GetBlankBlockPalette(self):
        return Palette(self)

    def CreateBlockGeometry(self,level):
        return self

    def CombineBlockPaletteToGeometry(self,palette,name,mode):
        self.names.append(name)
        return name if self.combine_ok else None


class Screen:
    def __init__(self):
        self.ready=False
        self.image=self
        self.colors=[]
        self.draws=[]
        self.removed=False

    def SetSpriteColor(self,value):
        self.colors.append(value)

    def draw(self,name):
        self.draws.append(name)

    def SetRemove(self):
        self.removed=True


class GeometryRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.factory=Factory()
        self.screen=Screen()
        api=types.ModuleType('mod.client.extraClientApi')
        api.GetScreenNodeCls=lambda:Base
        api.GetClientSystemCls=lambda:Base
        api.GetEngineCompFactory=lambda:self.factory
        api.GetLevelId=lambda:'level'
        api.GetEngineNamespace=lambda:'Minecraft'
        api.GetEngineSystemName=lambda:'engine'
        api.RegisterUI=lambda *args:True
        api.CreateUI=lambda *args:self.screen
        self.modules=patch.dict(sys.modules,{'mod':types.ModuleType('mod'),
            'mod.client':types.ModuleType('mod.client'),'mod.client.extraClientApi':api})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.clock=patch.object(time,'clock',time.perf_counter,create=True)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.runtime=load_module('_geometry_runtime_contract',PROBE/'runtime.py')
        self.probe=self.runtime.ProbeSystem('probe','test')

    def ready(self,count=256,seed=54321,generation=1):
        self.probe.open()
        self.screen.ready=True
        return self.probe.load(count,seed,generation)

    def test_prng_fixed_goldens(self):
        # Fixed vectors were computed independently with JavaScript BigInt.
        self.assertEqual([self.runtime.byte_at(54321,1,i) for i in range(16)],
                         [33,179,44,158,134,246,161,47,107,10,162,246,22,181,70,61])
        self.assertEqual([self.runtime.byte_at(0,0,i) for i in (0,1,255,256,65535)],
                         [0,114,127,69,76])

    def test_native_palette_indices_carry_every_payload_byte(self):
        receipt=self.ready(1024)
        data=self.factory.palettes[-1]
        z_size,x_size,y_size=data['volume']
        self.assertEqual((z_size,x_size,y_size),(32,32,256))
        self.assertEqual(set(data['common']),{('pmanim_geometry_packet:quad',0)})
        recovered={}
        for address in next(iter(data['common'].values())):
            byte,plane=divmod(address,x_size*z_size)
            x,z=divmod(plane,z_size)
            record=x*z_size+z
            self.assertNotIn(record,recovered)
            recovered[record]=byte
        expected=bytes(self.runtime.byte_at(54321,1,i) for i in range(1024))
        self.assertEqual(bytes(recovered[i] for i in range(1024)),expected)
        self.assertNotIn('sha256',receipt)
        self.assertFalse(data['actor'])
        self.assertFalse(data['extra'])

    def test_query_keeps_payload_resident_and_packet_contains_controls_only(self):
        before=self.ready(8192)
        counts=(len(self.factory.palettes),len(self.factory.names),len(self.screen.draws))
        for start in (4096,0,127):
            state=self.probe.query(start,2048,64)
            for key in ('seed','generation','slot_count','geometry_name','geometry_build_serial','epoch'):
                self.assertEqual(state[key],before[key])
            red,green,blue=self.screen.colors[-1]
            self.assertEqual(round(red*16777216),start)
            self.assertEqual(round(green*16777216),2047+63*4096)
            self.assertEqual(round(blue*8388608),self.probe.stride+256*2048)
        self.assertEqual(counts,(len(self.factory.palettes),len(self.factory.names),len(self.screen.draws)))
        # Different bytes with the same layout/query produce the same query packet.
        color=self.screen.colors[-1]
        self.probe.load(8192,seed=100,generation=9)
        self.probe.query(127,2048,64)
        self.assertEqual(self.screen.colors[-1],color)

    def test_two_native_names_bound_rebuild_resources(self):
        for generation in range(1,7):
            self.ready(256,generation=generation)
        self.assertEqual(len(set(self.factory.names)),2)
        self.assertEqual(self.probe.geometry_build_serial,6)
        self.assertEqual(self.probe.generation,6)

    def test_dataset_epochs_isolate_cases_and_keep_two_banks_per_epoch(self):
        self.probe.begin_dataset()
        first=self.ready()
        first_names=set()
        for generation in range(2,6):
            state=self.probe.load(256,seed=17,generation=generation)
            self.assertEqual(state['epoch'],1)
            first_names.add(state['geometry_name'])
        self.assertEqual(len(first_names),2)
        self.assertTrue(all('epoch1_bank' in name for name in first_names))
        serial=self.probe.geometry_build_serial
        transition=self.probe.begin_dataset()
        self.assertEqual(transition['epoch'],2)
        self.assertEqual(transition['geometry_name'],'')
        self.assertEqual(transition['geometry_build_serial'],serial)
        with self.assertRaises(ValueError):
            self.probe.query(0,1,64)
        second_names=set()
        for generation in range(1,5):
            state=self.probe.load(256,seed=54321,generation=generation)
            second_names.add(state['geometry_name'])
        self.assertEqual(len(second_names),2)
        self.assertTrue(first_names.isdisjoint(second_names))
        before=self.probe.snapshot()
        self.probe.query(128,128,64)
        self.assertEqual(self.probe.snapshot()['epoch'],before['epoch'])
        self.assertEqual(self.probe.snapshot()['geometry_build_serial'],before['geometry_build_serial'])
        self.probe.start(seconds=2)
        with self.assertRaisesRegex(RuntimeError,'active benchmark'):
            self.probe.begin_dataset()
        self.assertEqual(self.probe.epoch,2)

    def test_async_open_and_failed_upload_do_not_publish_receipt(self):
        state=self.probe.open()
        self.assertFalse(state['ready'])
        with self.assertRaisesRegex(RuntimeError,'ready'):
            self.probe.load(256)
        self.assertFalse(self.factory.palettes)
        before=self.ready()
        self.factory.deserialize_ok=False
        with self.assertRaisesRegex(RuntimeError,'Deserialize'):
            self.probe.load(256,seed=7,generation=3)
        self.factory.deserialize_ok=True
        self.factory.combine_ok=False
        with self.assertRaisesRegex(RuntimeError,'Combine'):
            self.probe.load(256,seed=7,generation=3)
        self.assertEqual(self.probe.snapshot()['geometry_build_serial'],before['geometry_build_serial'])
        self.assertEqual(self.probe.snapshot()['generation'],before['generation'])
        for args in ((-1,1,64),(0,4097,64),(256,1,64),(0,1,65)):
            with self.assertRaises(ValueError):
                self.probe.query(*args)

    def test_capture_target_is_distinct_from_logical_ui_size_and_listener_cleans_up(self):
        state=self.ready()
        self.assertEqual(state['screen_size'],[720,1080])
        self.assertEqual(state['logical_screen_size'],[360.,540.])
        self.assertEqual(state['display_rect_norm'],[0,64/1080.,1,1000/1080.])
        self.assertEqual(len(self.probe.events),1)
        self.probe.Destroy()
        self.assertEqual(self.probe.events,[])
        self.assertTrue(self.screen.removed)


class GeometryBuilderTests(unittest.TestCase):
    def test_isolated_output_and_ownership_guard(self):
        builder=load_module('_geometry_builder_contract',PROBE/'build_probe.py')
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'probe'
            builder.build(output)
            receipt=json.loads((output/'probe_resources.json').read_text(encoding='utf-8'))
            self.assertFalse(receipt['production_resources_modified'])
            self.assertEqual(receipt['runtime']['package'],'geometry_packet_probe')
            self.assertFalse((output/'resource_pack/graphics_settings/post_process.json').exists())
            material=json.loads((output/'resource_pack/materials/terrain.material').read_text(encoding='utf-8'))
            self.assertIn('pmanim_geometry_packet:netease_block_as_entity_mesh',material['materials'])
            builder.build(output)
            unrelated=Path(directory)/'unrelated'
            unrelated.mkdir()
            important=unrelated/'keep.txt'
            important.write_text('keep',encoding='utf-8')
            with self.assertRaises(ValueError):
                builder.build(unrelated)
            (unrelated/builder.MARKER).write_text('{"kind":"foreign","version":1}',encoding='utf-8')
            with self.assertRaises(ValueError):
                builder.build(unrelated)
            self.assertEqual(important.read_text(encoding='utf-8'),'keep')
        with self.assertRaises(ValueError):
            builder.build(ROOT/'behavior_pack')


class GeometryShaderDialectTests(unittest.TestCase):
    def test_native_includes_compile_and_centered_positions_gles_100_and_300(self):
        headers=Path(os.environ.get('PMANIM_GLSL_HEADERS',
            'D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.448891/data/shaders/glsl'))
        browser=Path(os.environ.get('PMANIM_CHROMIUM',
            'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'))
        if importlib.util.find_spec('playwright') is None or not headers.is_dir() or not browser.is_file():
            self.skipTest('Optional Playwright/Chromium/installed native GLSL headers unavailable')
        from playwright.sync_api import sync_playwright

        def source(path,version):
            def expand(value):
                return re.sub(r'^\s*#include\s+"([^"]+)".*$',
                    lambda match:expand((headers/match[1]).read_text(encoding='utf-8')),
                    value,flags=re.M)
            prefix=('#version 300 es\n' if version==300 else '#version 100\n')
            prefix+='#define MCPE_NETEASE\n#define BLEND\n#define MAT4 highp mat4\n#define POS4 highp vec4\n'
            value=path.read_text(encoding='utf-8').replace('precision highp float;',
                'precision highp float;\nprecision highp int;',1)
            return prefix+expand(value)

        cases=[{'version':version,'vertex':source(PROBE/'geometry_packet.vertex',version),
                'fragment':source(PROBE/'geometry_packet.fragment',version)} for version in (100,300)]
        javascript='''cases => cases.map(c => {
          const canvas=document.createElement('canvas');
          canvas.width=720;canvas.height=1080;
          const gl=canvas.getContext(c.version===300?'webgl2':'webgl',
            {antialias:false,preserveDrawingBuffer:true});
          if(!gl)throw Error('Missing GLES '+c.version);
          const compile=(kind,text)=>{
            const shader=gl.createShader(kind);gl.shaderSource(shader,text);gl.compileShader(shader);
            if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS))throw Error(c.version+': '+gl.getShaderInfoLog(shader));
            return shader;
          };
          const program=gl.createProgram();
          gl.attachShader(program,compile(gl.VERTEX_SHADER,c.vertex));
          gl.attachShader(program,compile(gl.FRAGMENT_SHADER,c.fragment));
          gl.linkProgram(program);
          if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(c.version+': '+gl.getProgramInfoLog(program));
          gl.useProgram(program);gl.viewport(0,0,720,1080);gl.disable(gl.DITHER);
          const vertices=[];
          // Native input is centered by volume/2 on ALL axes. The affine byte
          // permutation covers all 256 values independently of runtime PRNG.
          for(let id=0;id<256;++id){
            const value=(id*73+29)%256,x=Math.floor(id/16)-8,z=id%16-8;
            for(const [dx,dz] of [[-.25,-.25],[.25,-.25],[-.25,.25],
                                  [.25,-.25],[.25,.25],[-.25,.25]])
              vertices.push(x+dx,value-128,z+dz,1);
          }
          const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
          gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(vertices),gl.STATIC_DRAW);
          const position=gl.getAttribLocation(program,'POSITION');
          gl.enableVertexAttribArray(position);gl.vertexAttribPointer(position,4,gl.FLOAT,false,0,0);
          let checks=0;
          for(const [start,count] of [[0,256],[128,128],[17,3]]){
            gl.clearColor(17/255,53/255,97/255,1);gl.clear(gl.COLOR_BUFFER_BIT);
            gl.uniform4f(gl.getUniformLocation(program,'CURRENT_COLOR'),start/16777216,
              ((count-1)+63*4096)/16777216,(16+256*2048)/8388608,1);
            gl.drawArrays(gl.TRIANGLES,0,vertices.length/4);
            for(let slot=0;slot<count;++slot){
              const x=Math.floor((slot%64+.5)*720/64);
              const y=1079-Math.floor(64+(Math.floor(slot/64)+.5)*1000/Math.ceil(count/64));
              const rgba=new Uint8Array(36);gl.readPixels(x-1,y-1,3,3,gl.RGBA,gl.UNSIGNED_BYTE,rgba);
              const expected=((start+slot)*73+29)%256;
              for(let p=0;p<9;++p){
                if(rgba[p*4]!==expected||rgba[p*4+1]!==expected||rgba[p*4+2]!==expected||rgba[p*4+3]!==255)
                  throw Error(c.version+' centered slot '+(start+slot)+': expected '+expected+' got '+Array.from(rgba));
                ++checks;
              }
            }
          }
          gl.deleteProgram(program);gl.getExtension('WEBGL_lose_context').loseContext();
          return {version:c.version,compiled:true,linked:true,pixel_checks:checks};
        })'''
        with sync_playwright() as playwright:
            instance=playwright.chromium.launch(executable_path=str(browser),headless=True,
                args=['--use-angle=swiftshader','--enable-unsafe-swiftshader'])
            try:
                result=instance.new_page().evaluate(javascript,cases)
            finally:
                instance.close()
        self.assertEqual(result,[{'version':v,'compiled':True,'linked':True,
                                 'pixel_checks':(256+128+3)*9} for v in (100,300)])


if __name__=='__main__':
    unittest.main()
