"""Independent byte/gather fixtures and optional actual-shader desktop GPU tests."""
import argparse
import copy
import ctypes
import importlib.util
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageOps


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'tools/geometry_atlas_probe'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROBE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = load('geometry_atlas_independent_oracle', 'verify_capture.py')
with patch.dict(sys.modules, {'verify_capture': VERIFY}):
    RUNNER = load('geometry_atlas_case_controller', 'run_case.py')


def fixture_payload(seed, generation, slots):
    wrap = lambda value: ctypes.c_uint32(value).value
    values = []
    for index in range(slots):
        value = seed ^ wrap(generation * 0x9e3779b9) ^ wrap(index * 0x85ebca6b)
        for shift, multiplier in ((16, 0x7feb352d), (15, 0x846ca68b)):
            value = wrap((value ^ (value >> shift)) * multiplier)
        values.append((value ^ (value >> 16)) % 256)
    return values


def fixture(slots=137, start=0, count=None, mode=0, salt=17, salt2=53,
            generation=7, channel=0, direct=False, flip=1):
    count = min(slots - start, 4096) if count is None else count
    columns = min(64, slots)
    receipt = {'schema': 'geometry_atlas_probe_v1', 'seed': 123456789, 'generation': generation,
               'slot_count': slots, 'geometry_name': 'geometry_%d' % generation,
               'geometry_build_serial': generation, 'encoding': 'compact8',
               'screen_size': [720, 1080], 'display_rect_norm': [0, 64. / 1080., 1, 1000. / 1080.],
               'query': [start, count, mode, salt], 'layout': [slots, columns, 0, 0],
               'dimensions': [4, 720, 1080, salt2], 'orientation': [flip, channel, 0, 0],
               'direct_source': direct, 'packed_mode': mode + 4 * flip + 8 * channel + 16 * int(direct),
               'pipeline_ready': True, 'ready': True, 'writer_visible': True}
    values = fixture_payload(receipt['seed'], generation, slots)
    image = Image.new('RGBA', (720, 1080), (17, 53, 97, 255))
    draw, rows = ImageDraw.Draw(image), math.ceil(count / 64)
    indices, output = [], []
    for ordinal in range(count):
        index = start + ordinal
        if mode in (1, 2):
            index = (131 * index + salt) % slots
            if mode == 2:
                index = (index + 257 * values[index] + salt2) % slots
        indices.append(index)
        output.append(values[index])
        row, column = divmod(ordinal, 64)
        bounds = (math.ceil(column * 720 / 64 - .5), math.ceil(64 + row * 1000 / rows - .5),
                  math.ceil((column + 1) * 720 / 64 - .5) - 1,
                  math.ceil(64 + (row + 1) * 1000 / rows - .5) - 1)
        draw.rectangle(bounds, fill=(values[index],) * 3 + (255,))
    return receipt, image, indices, output


def args(directory):
    return argparse.Namespace(project=Path(directory) / 'project', evidence=Path(directory),
                              name='atlas_case', byte_count=137, seed=123456789, settle=0.,
                              channel='alpha', direct_source=False, flip_y=True)


class GeometryAtlasOracleTests(unittest.TestCase):
    def test_prng_golden_and_independent_gather_addresses(self):
        golden = [40, 41, 77, 92, 72, 53, 92, 99, 122, 200, 171, 159]
        self.assertEqual(golden, fixture_payload(123456789, 7, 12))
        self.assertEqual(golden, [VERIFY.expected_byte(123456789, 7, index) for index in range(12)])
        for mode in (0, 1, 2):
            receipt, image, indices, output = fixture(mode=mode)
            report = VERIFY.verify_image(receipt, image)
            with self.subTest(mode=mode):
                self.assertTrue(report['passed'])
                self.assertEqual(indices, report['source_indices'])
                self.assertEqual(output, report['expected_bytes'])
                self.assertEqual(137 * 36, report['checked_channels'])
                series = VERIFY.verify_reports(((receipt, report),))
                self.assertTrue(series['passed'])
                self.assertEqual(mode < 2, series['full_source_coverage'])

    def test_expected_payload_copies_and_observed_values_never_drive_indirection(self):
        receipt, image, _, _ = fixture(mode=2)
        receipt.update(payload=[255] * 137, expected_bytes=[255] * 137,
                       source_indices=[0] * 137, observed_bytes=[0] * 137)
        self.assertTrue(VERIFY.verify_image(receipt, image)['passed'])
        x, y = VERIFY.verify_image(receipt, image)['centers'][75]
        pixel = image.getpixel((x + 1, y - 1))
        image.putpixel((x + 1, y - 1), (pixel[0], pixel[1] ^ 1, pixel[2], pixel[3]))
        report = VERIFY.verify_image(receipt, image)
        self.assertFalse(report['passed'])
        self.assertEqual(1, report['failed_cells'])
        self.assertEqual(1, report['max_error'])

    def test_wrong_generation_salt_orientation_metadata_and_diagnostic_mode_rejected(self):
        receipt, image, _, _ = fixture(mode=2)
        for field, value in (('generation', 8), ('query', [0, 137, 2, 18]),
                              ('dimensions', [4, 720, 1080, 54])):
            with self.subTest(field=field):
                self.assertFalse(VERIFY.verify_image(dict(receipt, **{field: value}), image)['passed'])
        mutations = {'packed_mode': 0, 'orientation': [0, 0, 0, 0],
                     'query': [0, 137, 3, 17], 'screen_size': [720, 1079],
                     'pipeline_ready': False, 'seed': True, 'direct_source': 1}
        for field, value in mutations.items():
            with self.subTest(field=field), self.assertRaises(ValueError):
                VERIFY.verify_image(dict(receipt, **{field: value}), image)
        for color in ((0, 0, 0, 255), (255, 255, 255, 255), (64, 64, 64, 255), (255, 0, 255, 255)):
            self.assertFalse(VERIFY.verify_image(receipt, Image.new('RGBA', image.size, color))['passed'])

    def test_alpha_patch_and_partial_tail_full_coverage(self):
        pairs = []
        for start, count in ((0, 128), (128, 9)):
            receipt, image, _, _ = fixture(start=start, count=count, mode=1)
            pairs.append((receipt, VERIFY.verify_image(receipt, image)))
        self.assertTrue(VERIFY.verify_reports(reversed(pairs))['passed'])
        for bad in (pairs[:1], pairs + pairs[:1]):
            with self.assertRaises(ValueError):
                VERIFY.verify_reports(bad)
        receipt, image, _, _ = fixture()
        x, y = VERIFY.verify_image(receipt, image)['centers'][-1]
        pixel = image.getpixel((x - 1, y + 1))
        image.putpixel((x - 1, y + 1), pixel[:3] + (254,))
        failed = VERIFY.verify_image(receipt, image)
        self.assertFalse(failed['passed'])
        self.assertFalse(VERIFY.verify_reports(((receipt, failed),))['passed'])

    def test_red_and_direct_controls_are_explicit_and_do_not_claim_alpha(self):
        receipt, image, _, _ = fixture(channel=1, direct=True)
        report = VERIFY.verify_image(receipt, image)
        self.assertTrue(report['passed'])
        self.assertEqual('red', report['payload_channel'])
        self.assertFalse(report['alpha_channel_sampled'])
        self.assertTrue(report['direct_source'])


class GeometryAtlasRunnerTests(unittest.TestCase):
    def test_previous_generation_rejection_applies_to_complete_series_not_each_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            options = args(directory)
            options.byte_count = 4097
            runner = RUNNER.AtlasCase(options)
            receipt, _, _, _ = fixture(slots=4097, generation=2)
            runner.frozen = receipt

            def query(suffix, start, count, mode, salt, salt2):
                state, _, _, _ = fixture(slots=4097, start=start, count=count,
                                         generation=2, mode=mode, salt=salt, salt2=salt2)
                return state

            def capture(suffix, state, previous=None):
                _, image, _, _ = fixture(slots=4097, start=state['query'][0],
                                         count=state['query'][1], generation=2, salt=0, salt2=0)
                report = VERIFY.verify_image(state, image)
                # A singleton may coincide between distinct payload generations.
                return report, {'previous_generation_control': {'rejected': state['query'][0] == 0}}

            with patch.object(runner, 'query', side_effect=query), \
                    patch.object(runner, 'capture', side_effect=capture), patch.object(RUNNER.time, 'sleep'):
                runner.series('new_generation_identity', 0, 0, 0, previous=receipt)
            self.assertTrue(runner.controls['new_generation_identity']['passed'])
            self.assertTrue(runner.controls['new_generation_identity']['previous_generation_rejected'])

    def test_query_cannot_silently_keep_identity_or_change_source_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = RUNNER.AtlasCase(args(directory))
            receipt, _, _, _ = fixture(generation=1, mode=0, salt=0, salt2=0)
            runner.frozen = receipt
            with patch.object(runner, 'call', return_value=receipt), self.assertRaisesRegex(ValueError, 'controls'):
                runner.query('permutation', 0, 137, 1, 17, 0)
            wrong_source = dict(receipt, direct_source=True, packed_mode=20)
            with patch.object(runner, 'call', return_value=wrong_source), self.assertRaisesRegex(ValueError, 'controls'):
                runner.query('identity', 0, 137, 0, 0, 0)

    def test_new_capture_passes_current_oracle_and_rejects_previous_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = RUNNER.AtlasCase(args(directory))
            previous, _, _, _ = fixture(generation=7)
            receipt, image, _, _ = fixture(generation=8)
            label = 'atlas_case_new'
            (Path(directory) / (label + '.state.json')).write_text(json.dumps(receipt), encoding='utf-8')

            def capture(action, suffix, code=None):
                self.assertEqual('capture', action)
                image.save(Path(directory) / (label + '.png'))

            with patch.object(runner, 'host', side_effect=capture):
                report, summary = runner.capture('new', receipt, previous=previous)
            self.assertTrue(report['passed'])
            self.assertTrue(summary['previous_generation_control']['rejected'])
            self.assertFalse(summary['previous_generation_control']['passed'])
            self.assertTrue(Path(summary['verification_file']).is_file())

    def test_query_identity_changes_and_open_timeouts_are_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = RUNNER.AtlasCase(args(directory))
            receipt, _, _, _ = fixture()
            runner.frozen = receipt
            with self.assertRaisesRegex(ValueError, 'geometry'):
                runner.assert_frozen(dict(receipt, geometry_build_serial=8))
            with patch.object(runner, 'host', side_effect=TimeoutError('owner host timeout')):
                self.assertEqual(1, runner.run())
            report = json.loads(runner.output.read_text(encoding='utf-8'))
            self.assertEqual('failed', report['status'])
            self.assertEqual('open', report['stage'])
            self.assertIn('TimeoutError', report['errors'][0]['error'])


@unittest.skipUnless(importlib.util.find_spec('moderngl'), 'optional actual-shader desktop OpenGL diagnostic')
class GeometryAtlasDesktopGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import moderngl
        cls.gl = moderngl
        cls.context = moderngl.create_standalone_context(require=330)
        cls.vertex = '#version 330\nin vec2 pos;out vec2 uv;void main(){uv=pos*.5+.5;gl_Position=vec4(pos,0,1);}'
        cls.buffer = cls.context.buffer(struct.pack('8f', -1, -1, 1, -1, -1, 1, 1, 1))

    @classmethod
    def tearDownClass(cls):
        cls.buffer.release()
        cls.context.release()

    def program(self, filename):
        fragment = (PROBE / filename).read_text(encoding='utf-8')
        fragment = fragment.replace('// __multiversion__', '#version 330')
        fragment = fragment.replace('precision highp float;', '')
        fragment = fragment.replace('#include "fragmentVersionCentroidUV.h"', 'in vec2 uv;out vec4 output_color;')
        fragment = fragment.replace('gl_FragColor', 'output_color').replace('texture2D(', 'texture(')
        return self.context.program(vertex_shader=self.vertex, fragment_shader=fragment)

    def texture(self, receipt):
        data = bytearray((37, 83, 149, 211)) * (720 * 1080)
        values = fixture_payload(receipt['seed'], receipt['generation'], receipt['slot_count'])
        _, columns, left, top = receipt['layout']
        cell = receipt['dimensions'][0]
        for index, value in enumerate(values):
            row, column = divmod(index, columns)
            for dy in range(cell):
                for dx in range(cell):
                    x, y = left + column * cell + dx, 1079 - (top + row * cell + dy)
                    offset = (y * 720 + x) * 4
                    data[offset:offset + 4] = bytes((value ^ 255, 19, 47, value))
        texture = self.context.texture((720, 1080), 4, data=bytes(data))
        texture.filter = (self.gl.NEAREST, self.gl.NEAREST)
        texture.repeat_x = texture.repeat_y = False
        return texture

    def draw(self, program, receipt, original, selected):
        target = self.context.texture((720, 1080), 4)
        target.filter = (self.gl.NEAREST, self.gl.NEAREST)
        frame = self.context.framebuffer(color_attachments=[target])
        frame.use()
        self.context.viewport = (0, 0, 720, 1080)
        self.context.disable(self.gl.BLEND)
        original.use(location=1)
        if 'TEXTURE_1' in program:
            program['TEXTURE_1'].value = 1
        if 'TEXTURE_3' in program:
            selected.use(location=3)
            program['TEXTURE_3'].value = 3
        if 'EXTRA_VECTOR1' in program:
            start, count, _, salt = receipt['query']
            program['EXTRA_VECTOR1'].value = (start, count, receipt['packed_mode'], salt)
            program['EXTRA_VECTOR2'].value = receipt['layout']
            program['EXTRA_VECTOR3'].value = receipt['dimensions']
        vao = self.context.vertex_array(program, [(self.buffer, '2f', 'pos')])
        vao.render(self.gl.TRIANGLE_STRIP)
        image = ImageOps.flip(Image.frombytes('RGBA', (720, 1080), frame.read(components=4, alignment=1)))
        vao.release()
        frame.release()
        return image, target

    def test_actual_consumer_all_modes_and_wrong_selected_source(self):
        program = self.program('consumer.fragment')
        base, _, _, _ = fixture(slots=3072)
        source = self.texture(base)
        wrong = self.context.texture((720, 1080), 4, data=bytes((255, 0, 255, 64)) * (720 * 1080))
        for mode in (0, 1, 2):
            receipt, _, _, _ = fixture(slots=3072, mode=mode)
            image, target = self.draw(program, receipt, wrong, source)
            with self.subTest(mode=mode):
                self.assertTrue(VERIFY.verify_image(receipt, image)['passed'])
            target.release()
        image, target = self.draw(program, receipt, source, wrong)
        self.assertFalse(VERIFY.verify_image(receipt, image)['passed'])
        target.release()
        source.release()
        wrong.release()
        program.release()

    def test_actual_copy_preserves_alpha_and_direct_source_is_explicit(self):
        receipt, _, _, _ = fixture(slots=3072, mode=2)
        source = self.texture(receipt)
        copy_program = self.program('copy.fragment')
        _, copied = self.draw(copy_program, receipt, source, source)
        program = self.program('consumer.fragment')
        image, target = self.draw(program, receipt, source, copied)
        self.assertTrue(VERIFY.verify_image(receipt, image)['passed'])
        target.release()
        direct = dict(receipt, direct_source=True, packed_mode=receipt['packed_mode'] + 16)
        wrong = self.context.texture((720, 1080), 4, data=bytes((255, 0, 255, 64)) * (720 * 1080))
        image, target = self.draw(program, direct, source, wrong)
        self.assertTrue(VERIFY.verify_image(direct, image)['passed'])
        target.release()
        wrong.release()
        copied.release()
        source.release()
        copy_program.release()
        program.release()


if __name__ == '__main__':
    unittest.main()
