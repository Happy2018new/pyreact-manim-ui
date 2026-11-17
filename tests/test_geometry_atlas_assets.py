"""Offline asset ownership and exact alpha-only scatter rasterization contracts."""
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
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
        for name in ('runtime.py', 'modMain.py', 'update_scheduler.py'):
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
                cube = model['bones'][0]['cubes'][0]
                self.assertEqual(cube['origin'], [0, template + .5, 0])
                self.assertEqual(cube['size'], [8, 0, 8])
            self.assertTrue((output / 'behavior_pack/geometry_atlas_probe/codec.py').is_file())
            scheduler = output / 'behavior_pack/geometry_atlas_probe/update_scheduler.py'
            self.assertEqual(scheduler.read_text(encoding='utf-8'), '# asset fixture\n')
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
            metadata = json.loads((output / 'probe_resources.json').read_text(encoding='utf-8'))
            self.assertEqual(metadata['max_payload_bytes'], 524288)
            self.assertEqual(metadata['encoding']['local_quad_span_xz'], [0, .5])
            self.assertEqual(metadata['encoding']['native_position_expectation'],
                             'inferred endpoint sets: X={i-1,i-.5}, Z={i-.5,i}; not a native vertex capture')
            self.assertEqual(metadata['encoding']['source_center'], [1., .5, .5])
            self.assertEqual(metadata['encoding']['center_basis'],
                             'native image calibration for this atlas template; not a general model rule')
            self.assertEqual(metadata['scatter']['uniform4'],
                             ['writer_visible', 'active_bank_selector', 'reserved', 'reserved'])
            self.assertEqual(metadata['scatter']['active_bank_selector'],
                             {'fresh': 0, 'bank0': 1, 'bank1': 2, 'pending_clip_all': 3})
            self.assertEqual(metadata['scatter']['bank_tag_uniform'], 'COMMON_BLOCK_GEO_FLOAT1_1')
            self.assertEqual(metadata['scatter']['bank_tag_values'], {'bank0': .25, 'bank1': .75})
            self.assertEqual(metadata['scatter']['record_decode'], 'floor(source.xz + 0.25)')
            self.assertEqual(metadata['scatter']['corner_decode'], '2*(source.xz-cell)')
            self.assertEqual(metadata['scatter']['large_atlas'],
                             {'max_payload_bytes': 524288, 'columns': 512, 'cell_px': 1,
                              'left_px': 8, 'top_px': 32, 'width_px': 720, 'height_px': 1080})

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
                for dx, dz in ((0, 0), (.5, 0), (0, .5),
                               (.5, 0), (.5, .5), (0, .5)):
                    vertices.extend((x + dx - stride / 2, y + (template + .5) / 16 - 8,
                                     z + dz - stride / 2, 1))
        layouts = [{'name': 'all_bytes', 'stride': stride, 'vertices': vertices,
                    'indices': list(range(len(values))), 'values': values, 'count': len(values),
                    'columns': 16, 'left': 12, 'top': 20, 'cell': 4, 'patch': 3,
                    'center': [stride / 2, 8, stride / 2]}]
        # Construct only the boundary records. Explicit fixture POSITION
        # carries each byte; no full-size payload texture supplies the bytes.
        edge_indices = [0, 1, 15, 16, 255, 256, 511, 512, 513, 1022, 1023,
                        1024, 4095, 4096, 65535, 65536, 131071, 131072,
                        262143, 262144, 524286, 524287]
        edge_values = [(index * 73 + 29) % 256 for index in edge_indices]
        for name, storage, calibrated in (('large_edges', 'f', False),
                                          ('calibrated_float32_edges', 'f', True),
                                          ('calibrated_binary16_edges', 'e', True)):
            center = [1, .5, .5] if calibrated else [512, 8, 512]
            edge_vertices = []
            for index, value in zip(edge_indices, edge_values):
                x, z = divmod(index, 1024)
                if calibrated:
                    # b4 same-geometry calibration and cold b7c use center
                    # (1,.5,.5). Assume these POSITION endpoint sets explicitly:
                    # X={x-1,x-.5}, Z={z-.5,z}, Y=bytePlane-.5. They are modeled
                    # inputs, not captured native vertices. JSON-local X to
                    # native POSITION conversion/reflection and vertex order
                    # remain unproven; do not infer them from desired-center.
                    x_positions, z_positions = (x - 1., x - .5), (z - .5, z)
                    position_y = value // 16 + (value % 16 + .5) / 16 - .5
                else:
                    # Separate ideal centered-palette input, not a native claim.
                    x_positions, z_positions = (x - 512., x - 511.5), (z - 512., z - 511.5)
                    position_y = value // 16 + (value % 16 + .5) / 16 - 8.
                for ix, iz in ((0, 0), (1, 0), (0, 1),
                               (1, 0), (1, 1), (0, 1)):
                    position = (x_positions[ix], position_y, z_positions[iz], 1)
                    # Model a binary16 input buffer independently of the
                    # browser's float32 upload. This tests robustness to such
                    # input quantization, not the native engine's vertex format.
                    stored = struct.unpack('<4' + storage, struct.pack('<4' + storage, *position))
                    self.assertEqual(stored, position)
                    edge_vertices.extend(stored)
            layouts.append({'name': name, 'stride': 1024, 'vertices': edge_vertices,
                            'indices': edge_indices, 'values': edge_values, 'count': 524288,
                            'columns': 512, 'left': 8, 'top': 32, 'cell': 1, 'patch': 1,
                            'center': center})
        cases = [dict(layout, version=version, vertex=shader(PROBE / 'scatter.vertex', version),
                      fragment=shader(PROBE / 'scatter.fragment', version))
                 for version in (100, 300) for layout in layouts]
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
          set('EXTRA_ACTOR_UNIFORM1',[c.stride,8,c.count,c.columns]);
          set('EXTRA_ACTOR_UNIFORM2',[c.left,c.top,c.cell,720]);
          set('EXTRA_ACTOR_UNIFORM3',[1080,...c.center]);
          let checks=0;
          for(const visible of [1,0]){
           for(const selector of [0,1,2,3]){
            for(const tag of [.25,.75]){
            gl.colorMask(true,true,true,true);gl.clearColor(17/255,53/255,97/255,1);gl.clear(gl.COLOR_BUFFER_BIT);
            gl.colorMask(false,false,false,true);gl.enable(gl.BLEND);
            gl.blendFuncSeparate(gl.ZERO,gl.ONE,gl.ONE,gl.ZERO);
            set('EXTRA_ACTOR_UNIFORM4',[visible,selector,0,0]);
            const bankLocation=gl.getUniformLocation(program,'COMMON_BLOCK_GEO_FLOAT1_1');
            if(bankLocation===null)throw Error('Bank tag uniform is missing from actual scatter shader');
            gl.uniform1f(bankLocation,tag);gl.drawArrays(gl.TRIANGLES,0,c.vertices.length/4);
            const rgba=new Uint8Array(720*1080*4);gl.readPixels(0,0,720,1080,gl.RGBA,gl.UNSIGNED_BYTE,rgba);
            const selected=visible&&(selector===0||selector===(tag<.5?1:2));
            for(let slot=0;slot<c.values.length;++slot){
              const index=c.indices[slot];
              const x=c.left+(index%c.columns)*c.cell+Math.floor(c.cell/2);
              const y=1079-(c.top+Math.floor(index/c.columns)*c.cell+Math.floor(c.cell/2));
              const expected=selected?c.values[slot]:255;
              const radius=Math.floor(c.patch/2);
              for(let dy=-radius;dy<=radius;++dy)for(let dx=-radius;dx<=radius;++dx){
                const p=((y+dy)*720+x+dx)*4;
                if(rgba[p]!==17||rgba[p+1]!==53||rgba[p+2]!==97||rgba[p+3]!==expected)
                  throw Error('GLES'+c.version+' '+c.name+' index '+index+' visible '+visible+
                    ' selector '+selector+' tag '+tag+' expected alpha '+expected+
                    ' got '+Array.from(rgba.slice(p,p+4)));
                ++checks;
              }
            }
            }
           }
          }
          if(gl.getError()!==gl.NO_ERROR)throw Error('Unexpected WebGL error');
          return {version:c.version,name:c.name,pixel_checks:checks};
        })'''
        with sync_playwright() as playwright:
            instance = playwright.chromium.launch(executable_path=str(browser), headless=True,
                args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
            try:
                result = instance.new_page().evaluate(javascript, cases)
            finally:
                instance.close()
        self.assertEqual(result, [
            {'version': version, 'name': layout['name'],
             'pixel_checks': len(layout['values']) * 2 * 4 * 2 * layout['patch'] ** 2}
            for version in (100, 300) for layout in layouts])


if __name__ == '__main__':
    unittest.main()
