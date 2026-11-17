"""Geometry codec boundaries and both centered native-position shader layouts."""
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'tools/geometry_packet_probe'


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROBE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CODEC = load_module('_geometry_codec_contract', 'codec.py')
BUILDER = load_module('_geometry_codec_builder_contract', 'build_probe.py')


def recovered_records(packet):
    """Decode native palette addresses independently of the encoder arithmetic."""
    z_size, x_size, height = packet['data']['volume']
    plane = z_size * x_size
    records = {}
    for (identifier, aux), addresses in packet['data']['common'].items():
        template = 0 if packet['encoding'] == 'legacy8' else int(identifier.rsplit('_', 1)[1])
        if aux != 0:
            raise AssertionError('Geometry byte blocks require aux zero')
        for address in addresses:
            y, horizontal = divmod(address, plane)
            x, z = divmod(horizontal, z_size)
            if not 0 <= y < height or not 0 <= x < x_size or not 0 <= z < z_size:
                raise AssertionError('Palette address exceeds declared volume')
            record = x * z_size + z
            if record in records:
                raise AssertionError('Two blocks share one record')
            records[record] = y if packet['encoding'] == 'legacy8' else 16 * y + template
    return records


class GeometryPacketCodecTests(unittest.TestCase):
    def test_all_256_byte_values_and_metadata(self):
        values = bytearray((index * 73 + 29) % 256 for index in range(256))
        for encoding, height, templates, encoding_id in (('legacy8', 256, 1, 0),
                                                          ('compact8', 16, 16, 1)):
            with self.subTest(encoding=encoding):
                packet = CODEC.encode_values(values, encoding)
                self.assertEqual(packet['encoding_id'], encoding_id)
                self.assertEqual(packet['record_count'], 256)
                self.assertEqual(packet['stride'], 16)
                self.assertEqual(packet['palette_height'], height)
                self.assertEqual(packet['template_count'], templates)
                self.assertEqual(packet['y_offset'], height / 2)
                self.assertEqual(packet['volume'], (16, 16, height))
                records = recovered_records(packet)
                self.assertEqual(set(records), set(range(256)))
                self.assertEqual(bytes(records[index] for index in range(256)), bytes(values))
                self.assertEqual(len(packet['data']['common']), templates)
                for field in ('extra', 'actor', 'states', 'extraStates'):
                    self.assertEqual(packet['data'][field], {})
                self.assertFalse(packet['data']['void'])
                self.assertTrue(packet['data']['eliminateAir'])
        self.assertEqual(CODEC.encode_values(values)['encoding'], 'compact8')

    def test_odd_sizes_preserve_record_identity_without_padding_blocks(self):
        for count, stride in ((1, 2), (3, 2), (17, 8), (137, 16), (273, 32),
                              (4097, 128), (65537, 512)):
            values = bytes((index * 19 + 247) % 256 for index in range(count))
            for encoding in CODEC.ENCODINGS:
                with self.subTest(count=count, encoding=encoding):
                    packet = CODEC.encode_values(values, encoding)
                    self.assertEqual(packet['stride'], stride)
                    records = recovered_records(packet)
                    self.assertEqual(len(records), count)
                    self.assertEqual(max(records), count - 1)
                    self.assertEqual(bytes(records[index] for index in range(count)), values)

    def test_maximum_budget_uses_sixteen_times_smaller_palette_volume(self):
        values = bytearray([255]) * CODEC.MAX_BYTES
        volumes = {}
        for encoding in CODEC.ENCODINGS:
            packet = CODEC.encode_values(values, encoding)
            self.assertEqual(packet['record_count'], 1048576)
            self.assertEqual(packet['stride'], 1024)
            volumes[encoding] = math.prod(packet['volume'])
            addresses = next(iter(packet['data']['common'].values()))
            self.assertEqual(len(addresses), CODEC.MAX_BYTES)
            self.assertEqual(addresses[0], volumes[encoding] - CODEC.MAX_BYTES)
            self.assertEqual(addresses[-1], volumes[encoding] - 1)
        self.assertEqual(volumes['legacy8'], 16 * volumes['compact8'])
        self.assertEqual(volumes['compact8'], 16777216)

    def test_integer_iterables_and_invalid_payloads(self):
        expected = CODEC.encode_values(bytearray([0, 15, 16, 255]))
        self.assertEqual(CODEC.encode_values(iter([0, 15, 16, 255])), expected)
        for values in (b'', [], bytearray(CODEC.MAX_BYTES + 1), [True], [False],
                       [-1], [256], [1.0], ['1'], 'abc', None, 3):
            with self.subTest(values_type=type(values)), self.assertRaises(ValueError):
                CODEC.encode_values(values)
        with self.assertRaises(ValueError):
            CODEC.encode_values((0 for _ in range(CODEC.MAX_BYTES + 1)))
        for encoding in ('', 'compact4', None, []):
            with self.subTest(encoding=encoding), self.assertRaises(ValueError):
                CODEC.encode_values([1], encoding)
        for encoding in CODEC.ENCODINGS:
            for template in (-1, 1 if encoding == 'legacy8' else 16, True, 1.0):
                with self.subTest(encoding=encoding, template=template), self.assertRaises(ValueError):
                    CODEC.template_identifier(encoding, template)

    def test_builder_emits_static_midpoint_planes_and_copies_pure_codec(self):
        with tempfile.TemporaryDirectory() as directory:
            output = BUILDER.build(Path(directory) / 'probe')
            metadata = json.loads((output / 'probe_resources.json').read_text(encoding='utf-8'))
            self.assertEqual(metadata['encoding']['default'], 'compact8')
            self.assertEqual(metadata['encoding']['supported'], ['legacy8', 'compact8'])
            self.assertEqual(metadata['encoding']['control_encoding_bit'], 1 << 21)
            self.assertEqual((output / 'behavior_pack/geometry_packet_probe/codec.py').read_text(encoding='utf-8'),
                             (PROBE / 'codec.py').read_text(encoding='utf-8'))
            blocks = json.loads((output / 'resource_pack/blocks.json').read_text(encoding='utf-8'))
            self.assertEqual(len(blocks) - 1, 17)
            for template in range(16):
                identifier = CODEC.template_identifier('compact8', template)
                self.assertEqual(blocks[identifier]['netease_model'], identifier)
                name = 'geometry_packet_quad_compact8_%02d.json' % template
                model = json.loads((output / 'resource_pack/models/netease_block' / name)
                                   .read_text(encoding='utf-8'))['netease:block_geometry']
                self.assertEqual(model['description']['identifier'], identifier)
                cube = model['bones'][0]['cubes'][0]
                self.assertEqual(cube['origin'], [-4, template + .5, -4])
                self.assertEqual(cube['size'], [8, 0, 8])
                local_y = cube['origin'][1] / 16
                self.assertEqual(local_y, (template + .5) / 16)
                self.assertGreater(local_y - template / 16, 0)
                self.assertGreater((template + 1) / 16 - local_y, 0)
            legacy = json.loads((output / 'resource_pack/models/netease_block/geometry_packet_quad.json')
                                .read_text(encoding='utf-8'))['netease:block_geometry']
            self.assertEqual(legacy['bones'][0]['cubes'][0]['origin'], [-4, 0, -4])


class GeometryPacketCompactShaderTests(unittest.TestCase):
    def test_native_centered_midpoints_render_all_bytes_with_both_gles_dialects(self):
        headers = Path(os.environ.get('PMANIM_GLSL_HEADERS',
            'D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.448891/data/shaders/glsl'))
        browser = Path(os.environ.get('PMANIM_CHROMIUM',
            'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'))
        if importlib.util.find_spec('playwright') is None or not headers.is_dir() or not browser.is_file():
            self.skipTest('Optional Playwright/Chromium/installed native GLSL headers unavailable')
        from playwright.sync_api import sync_playwright

        def source(path, version):
            def expand(value):
                return re.sub(r'^\s*#include\s+"([^"]+)".*$',
                    lambda match: expand((headers / match[1]).read_text(encoding='utf-8')),
                    value, flags=re.M)
            prefix = '#version 300 es\n' if version == 300 else '#version 100\n'
            prefix += '#define MCPE_NETEASE\n#define BLEND\n#define MAT4 highp mat4\n#define POS4 highp vec4\n'
            value = path.read_text(encoding='utf-8').replace('precision highp float;',
                'precision highp float;\nprecision highp int;', 1)
            return prefix + expand(value)

        # Build vertices from the emitted models and native palette addresses,
        # then subtract volume/2 just as the native PaperDoll input does.
        values = [(index * 73 + 29) % 256 for index in range(273)]
        cases = []
        with tempfile.TemporaryDirectory() as directory:
            output = BUILDER.build(Path(directory) / 'probe')
            models = {}
            for path in (output / 'resource_pack/models/netease_block').glob('*.json'):
                model = json.loads(path.read_text(encoding='utf-8'))['netease:block_geometry']
                models[model['description']['identifier']] = model['bones'][0]['cubes'][0]
            for encoding in CODEC.ENCODINGS:
                packet = CODEC.encode_values(values, encoding)
                stride, _, height = packet['volume']
                vertices = []
                for (identifier, _), addresses in packet['data']['common'].items():
                    cube = models[identifier]
                    local_y = cube['origin'][1] / 16
                    for address in addresses:
                        y, record = divmod(address, stride * stride)
                        x, z = divmod(record, stride)
                        for dx, dz in ((0, 0), (1, 0), (0, 1), (1, 0), (1, 1), (0, 1)):
                            vertices.extend((x + (cube['origin'][0] + dx * cube['size'][0]) / 16 - stride / 2,
                                             y + local_y - height / 2,
                                             z + (cube['origin'][2] + dz * cube['size'][2]) / 16 - stride / 2, 1))
                layout = stride + height * 2048 + packet['encoding_id'] * CODEC.ENCODING_LAYOUT_BIT
                for version in (100, 300):
                    cases.append({'encoding': encoding, 'version': version, 'vertices': vertices,
                                  'layout': layout, 'values': values,
                                  'vertex': source(PROBE / 'geometry_packet.vertex', version),
                                  'fragment': source(PROBE / 'geometry_packet.fragment', version)})

        javascript = '''cases => cases.map(c => {
          const canvas=document.createElement('canvas');canvas.width=720;canvas.height=1080;
          const gl=canvas.getContext(c.version===300?'webgl2':'webgl',
            {antialias:false,preserveDrawingBuffer:true});
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
          let checks=0;
          for(const [start,count,mode] of [[0,273,0],[128,128,0],[255,18,0],[17,3,0],
                                         [0,273,1],[0,273,2],[0,273,3]]){
            gl.clearColor(17/255,53/255,97/255,1);gl.clear(gl.COLOR_BUFFER_BIT);
            gl.uniform4f(gl.getUniformLocation(program,'CURRENT_COLOR'),start/16777216,
              ((count-1)+63*4096+mode*262144)/16777216,c.layout/8388608,1);
            gl.drawArrays(gl.TRIANGLES,0,c.vertices.length/4);
            for(let slot=0;slot<count;++slot){
              const x=Math.floor((slot%64+.5)*720/64);
              const y=1079-Math.floor(64+(Math.floor(slot/64)+.5)*1000/Math.ceil(count/64));
              const rgba=new Uint8Array(36);gl.readPixels(x-1,y-1,3,3,gl.RGBA,gl.UNSIGNED_BYTE,rgba);
              const id=start+slot;
              const expected=mode===0?c.values[id]:mode===1?id%256:mode===2?Math.floor(id/256)%256:255;
              for(let p=0;p<9;++p){
                if(rgba[p*4]!==expected||rgba[p*4+1]!==expected||rgba[p*4+2]!==expected||rgba[p*4+3]!==255)
                  throw Error(c.encoding+' GLES'+c.version+' slot '+id+' mode '+mode+
                    ': expected '+expected+' got '+Array.from(rgba));
                ++checks;
              }
            }
          }
          gl.deleteProgram(program);gl.getExtension('WEBGL_lose_context').loseContext();
          return {encoding:c.encoding,version:c.version,pixel_checks:checks};
        })'''
        with sync_playwright() as playwright:
            instance = playwright.chromium.launch(executable_path=str(browser), headless=True,
                args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
            try:
                result = instance.new_page().evaluate(javascript, cases)
            finally:
                instance.close()
        self.assertEqual(result, [{'encoding': encoding, 'version': version,
            'pixel_checks': (273 + 128 + 18 + 3 + 273 * 3) * 9}
            for encoding in CODEC.ENCODINGS for version in (100, 300)])


if __name__ == '__main__':
    unittest.main()
