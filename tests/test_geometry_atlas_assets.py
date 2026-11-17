"""Offline asset ownership and exact alpha-only scatter rasterization contracts."""
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'tools/geometry_atlas_probe'
SPEC = importlib.util.spec_from_file_location('_geometry_atlas_asset_contract', PROBE / 'build_probe.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class GeometryAtlasAssetsTests(unittest.TestCase):
    def fixture(self, temporary):
        """Builder tests isolate assets from the separately owned game runtime."""
        source = Path(temporary) / 'source'
        source.mkdir()
        for name in ('scatter.vertex', 'scatter.fragment'):
            (source / name).write_bytes((PROBE / name).read_bytes())
        for name in ('runtime.py', 'modMain.py'):
            (source / name).write_text('# asset fixture\n', encoding='utf-8')
        for name in ('consumer.fragment', 'copy.fragment', 'poison.fragment'):
            (source / name).write_text('// post fixture\n', encoding='utf-8')
        return source

    def test_owned_output_seventeen_midpoint_models_and_alpha_write_mask(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = self.fixture(temporary)
            output = Path(temporary) / 'atlas'
            with patch.object(BUILDER, 'HERE', source):
                BUILDER.build(output)
                BUILDER.build(output)
                with self.assertRaisesRegex(ValueError, 'different atlas configuration'):
                    BUILDER.build(output, rgb_writer=True)
            materials = json.loads((output / 'resource_pack/materials/terrain.material')
                                   .read_text(encoding='utf-8'))['materials']
            writer = materials['pmanim_geometry_atlas:netease_block_as_entity_mesh']
            self.assertIn('DisableRGBWrite', writer['+states'])
            self.assertEqual(writer['-states'], ['DisableAlphaWrite', 'EnableAlphaToCoverage'])
            self.assertEqual(writer['-defines'], ['ALPHA_TEST'])
            self.assertEqual([writer[key] for key in ('blendSrc', 'blendDst', 'alphaSrc', 'alphaDst')],
                             ['Zero', 'One', 'One', 'Zero'])
            blocks = json.loads((output / 'resource_pack/blocks.json').read_text(encoding='utf-8'))
            self.assertEqual(len(blocks) - 1, 17)
            self.assertTrue(all(key.startswith('pmanim_geometry_atlas:')
                                for key in blocks if key != 'format_version'))
            for template in range(16):
                name = 'geometry_atlas_quad_compact8_%02d.json' % template
                model = json.loads((output / 'resource_pack/models/netease_block' / name)
                                   .read_text(encoding='utf-8'))['netease:block_geometry']
                self.assertEqual(model['bones'][0]['cubes'][0]['origin'], [-4, template + .5, -4])
            self.assertTrue((output / 'behavior_pack/geometry_atlas_probe/codec.py').is_file())
            self.assertFalse((output / 'behavior_pack/geometry_packet_probe').exists())
            self.assertFalse((output / 'resource_pack/graphics_settings/post_process.json').exists())
            post = json.loads((output / 'resource_pack/materials/postprocess.material')
                              .read_text(encoding='utf-8'))
            self.assertEqual(set(post), {'pmanim_geometry_atlas_copy', 'pmanim_geometry_atlas_poison',
                                        'pmanim_geometry_atlas_consumer'})
            for material in post.values():
                self.assertNotIn('Blending', material['states'])
                self.assertIn('DisableAlphaWrite', material['-states'])
                self.assertTrue((output / 'resource_pack' / material['fragmentShader']).is_file())
            pipeline = json.loads((output / 'behavior_pack/geometry_atlas_probe/pipeline.json')
                                  .read_text(encoding='utf-8'))
            self.assertEqual(pipeline['name'], 'pmanim_geometry_atlas_gather')
            self.assertFalse(pipeline['enable'])
            self.assertEqual([parameter['name'] for parameter in pipeline['paras']],
                             ['query', 'layout', 'dimensions'])
            self.assertEqual([item['material'] for item in pipeline['pass_array']],
                             ['pmanim_geometry_atlas_copy', 'pmanim_geometry_atlas_poison',
                              'pmanim_geometry_atlas_consumer'])

    def test_rgb_debug_material_and_foreign_output_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = self.fixture(temporary)
            with patch.object(BUILDER, 'HERE', source):
                output = BUILDER.build(Path(temporary) / 'rgb', rgb_writer=True)
                material = json.loads((output / 'resource_pack/materials/terrain.material')
                                      .read_text(encoding='utf-8'))['materials']
                writer = material['pmanim_geometry_atlas:netease_block_as_entity_mesh']
                self.assertNotIn('DisableRGBWrite', writer['+states'])
                self.assertEqual([writer['blendSrc'], writer['blendDst']], ['One', 'Zero'])
                unrelated = Path(temporary) / 'unrelated'
                unrelated.mkdir()
                keep = unrelated / 'keep.txt'
                keep.write_text('preserve', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'ownership marker'):
                    BUILDER.build(unrelated)
                self.assertEqual(keep.read_text(encoding='utf-8'), 'preserve')

    def test_native_headers_scatter_every_byte_into_alpha_and_preserve_rgb(self):
        headers = Path(os.environ.get('PMANIM_GLSL_HEADERS',
            'D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.448891/data/shaders/glsl'))
        browser = Path(os.environ.get('PMANIM_CHROMIUM',
            'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'))
        if importlib.util.find_spec('playwright') is None or not headers.is_dir() or not browser.is_file():
            self.skipTest('Optional Playwright/Chromium/native GLSL headers unavailable')
        from playwright.sync_api import sync_playwright

        def shader(path, version):
            def expand(value):
                return re.sub(r'^\s*#include\s+"([^"]+)".*$',
                    lambda match: expand((headers / match[1]).read_text(encoding='utf-8')),
                    value, flags=re.M)
            prefix = '#version 300 es\n' if version == 300 else '#version 100\n'
            prefix += '#define MCPE_NETEASE\n#define BLEND\n#define MAT4 highp mat4\n#define POS4 highp vec4\n'
            value = path.read_text(encoding='utf-8').replace('precision highp float;',
                'precision highp float;\nprecision highp int;', 1)
            return prefix + expand(value)

        codec = BUILDER.PACKET_BUILDER.CODEC
        values = [(index * 73 + 29) % 256 for index in range(273)]
        packet = codec.encode_values(values)
        stride = packet['stride']
        vertices = []
        for (identifier, _), addresses in packet['data']['common'].items():
            template = int(identifier.rsplit('_', 1)[1])
            for address in addresses:
                y, record = divmod(address, stride * stride)
                x, z = divmod(record, stride)
                for dx, dz in ((-.25, -.25), (.25, -.25), (-.25, .25),
                               (.25, -.25), (.25, .25), (-.25, .25)):
                    vertices.extend((x + dx - stride / 2, y + (template + .5) / 16 - 8,
                                     z + dz - stride / 2, 1))
        cases = [{'version': version, 'vertex': shader(PROBE / 'scatter.vertex', version),
                  'fragment': shader(PROBE / 'scatter.fragment', version),
                  'stride': stride, 'vertices': vertices, 'values': values} for version in (100, 300)]
        javascript = '''cases => cases.map(c => {
          const canvas=document.createElement('canvas');canvas.width=720;canvas.height=1080;
          const gl=canvas.getContext(c.version===300?'webgl2':'webgl',
            {alpha:true,premultipliedAlpha:false,antialias:false,preserveDrawingBuffer:true});
          if(!gl)throw Error('Missing GLES '+c.version);
          const compile=(kind,text)=>{
            const shader=gl.createShader(kind);gl.shaderSource(shader,text);gl.compileShader(shader);
            if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(shader));
            return shader;
          };
          const program=gl.createProgram();
          gl.attachShader(program,compile(gl.VERTEX_SHADER,c.vertex));
          gl.attachShader(program,compile(gl.FRAGMENT_SHADER,c.fragment));gl.linkProgram(program);
          if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));
          gl.useProgram(program);gl.viewport(0,0,720,1080);gl.disable(gl.DITHER);
          const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
          gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(c.vertices),gl.STATIC_DRAW);
          const position=gl.getAttribLocation(program,'POSITION');
          gl.enableVertexAttribArray(position);gl.vertexAttribPointer(position,4,gl.FLOAT,false,0,0);
          const set=(name,data)=>gl.uniform4fv(gl.getUniformLocation(program,name),data);
          set('EXTRA_ACTOR_UNIFORM1',[c.stride,8,c.values.length,16]);
          set('EXTRA_ACTOR_UNIFORM2',[12,20,4,720]);
          set('EXTRA_ACTOR_UNIFORM3',[1080,c.stride/2,8,c.stride/2]);
          let checks=0;
          for(const visible of [1,0]){
            gl.colorMask(true,true,true,true);gl.clearColor(17/255,53/255,97/255,1);gl.clear(gl.COLOR_BUFFER_BIT);
            gl.colorMask(false,false,false,true);gl.enable(gl.BLEND);
            gl.blendFuncSeparate(gl.ZERO,gl.ONE,gl.ONE,gl.ZERO);
            set('EXTRA_ACTOR_UNIFORM4',[visible,0,0,0]);gl.drawArrays(gl.TRIANGLES,0,c.vertices.length/4);
            for(let slot=0;slot<c.values.length;++slot){
              const x=12+(slot%16)*4+2,y=1079-(20+Math.floor(slot/16)*4+2);
              const rgba=new Uint8Array(36);gl.readPixels(x-1,y-1,3,3,gl.RGBA,gl.UNSIGNED_BYTE,rgba);
              const expected=visible?c.values[slot]:255;
              for(let p=0;p<9;++p){
                if(rgba[p*4]!==17||rgba[p*4+1]!==53||rgba[p*4+2]!==97||rgba[p*4+3]!==expected)
                  throw Error('GLES'+c.version+' slot '+slot+' visible '+visible+' expected alpha '+expected+' got '+Array.from(rgba));
                ++checks;
              }
            }
          }
          return {version:c.version,pixel_checks:checks};
        })'''
        with sync_playwright() as playwright:
            instance = playwright.chromium.launch(executable_path=str(browser), headless=True,
                args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
            try:
                result = instance.new_page().evaluate(javascript, cases)
            finally:
                instance.close()
        self.assertEqual(result, [{'version': version, 'pixel_checks': 273 * 2 * 9}
                                  for version in (100, 300)])


if __name__ == '__main__':
    unittest.main()
