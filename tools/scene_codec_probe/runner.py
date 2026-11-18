"""Owner-bound static scene codec checks; launch is a separate explicit action.

All expected bytes are computed on the host. Game code only builds in-memory
geometry and controls shaders; host evidence is saved separately. This runner
never starts a game, activates a window, or sends desktop input.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image

import codec
from layout import plan_payload

HERE = Path(__file__).resolve().parent
SYSTEM = 'pmanim_geometry_atlas_probe'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sample_pixels(image, count, native=False, consumer=False):
    image = image.convert('RGBA')
    if image.size != (720, 1080):
        raise ValueError('The fixture requires a native 720x1080 capture')
    rows = (count + 63) // 64
    samples = []
    for index in range(count):
        if native:
            x, y = index % 720, 128 + index // 720
            pixels = [image.getpixel((x, y))]
        else:
            row, column = divmod(index, 64)
            x = math.floor((column + .5) * 720 / 64)
            y = 128+math.floor((row + .5) * 936 / rows)
            pixels = [image.getpixel((x+dx, y+dy)) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
        samples.append(pixels)
    return samples


def compare(samples, expected, tolerance=0):
    if len(samples) != len(expected):
        raise ValueError('Expected oracle must cover every sample')
    errors, first = [], []
    for index, (patch, rgb) in enumerate(zip(samples, expected)):
        error = max(max(abs(actual[channel]-rgb[channel]) for channel in range(3))
                    for actual in patch)
        error = max(error, max(255-actual[3] for actual in patch))
        errors.append(error)
        if error > tolerance and len(first) < 20:
            first.append({'ordinal': index, 'expected_rgb': rgb, 'observed_rgba': patch[0], 'error': error})
    return {'passed': all(error <= tolerance for error in errors), 'checked_samples': len(samples),
            'mismatch_samples': sum(error > tolerance for error in errors),
            'maximum_channel_error': max(errors, default=0), 'tolerance': tolerance,
            'error_histogram': dict(sorted(Counter(errors).items())), 'first_failures': first,
            'observed_center_sha256': hashlib.sha256(bytes(c for patch in samples for c in patch[0])).hexdigest()}


def expected_query(index, mode, logical, salt):
    if mode:
        index = (131*index+29) % logical
    if mode == 2:
        index = (index+257*codec.payload_oracle(index, salt)+113) % logical
    value = codec.payload_oracle(index, salt)
    return (value, value, value)


class Experiment:
    def __init__(self, args):
        self.args = args
        self.evidence = args.evidence.resolve()
        self.commands = self.evidence / 'commands'
        self.commands.mkdir(parents=True, exist_ok=True)
        self.result = self.evidence / (args.name+'.results.json')
        if self.result.exists():
            raise ValueError('Preserve evidence by choosing a fresh case name')
        self.reports, self.events, self.state = [], [], {}

    def host(self, action, suffix, code=None):
        label = self.args.name+'_'+suffix
        command = [sys.executable, '-B', '-X', 'utf8', str(HERE/'host.py'), action,
                   '--project', str(self.args.project.resolve()), '--evidence', str(self.evidence),
                   '--label', label, '--timeout', '120']
        log_path = self.evidence/(label+'.'+action+'.log')
        event = {'action': action, 'label': label, 'log': str(log_path)}
        self.events.append(event)
        if code is not None:
            path = self.commands/(label+'.py')
            path.write_text("probe=api.GetSystem(%r,'probe')\n" % SYSTEM+code+
                            '\n_result=json.dumps(probe.snapshot())\n', encoding='utf-8')
            command += ['--code', str(path)]
            event['command_sha256'] = digest(path)
        with log_path.open('w', encoding='utf-8') as log:
            subprocess.run(command, check=True, stdin=subprocess.DEVNULL, stdout=log,
                           stderr=subprocess.STDOUT, timeout=140,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if action == 'call':
            self.state = json.loads((self.evidence/(label+'.state.json')).read_text(encoding='utf-8-sig'))
            if self.state.get('error'):
                raise RuntimeError(self.state['error'])
            return self.state
        return label

    def call(self, suffix, code):
        return self.host('call', suffix, code)

    def capture(self, suffix, code):
        state = self.call(suffix, code)
        time.sleep(self.args.settle)
        label = self.host('capture', suffix)
        path = self.evidence/(label+'.png')
        receipt_path = self.evidence/(label+'.json')
        receipt = json.loads(receipt_path.read_text(encoding='utf-8-sig'))
        if (receipt.get('ok') is not True or receipt.get('backend') != 'Windows.Graphics.Capture' or
                receipt.get('agent_activation_allowed') is not False or
                receipt.get('frame_qpc_100ns', -1) < receipt.get('request_qpc_100ns', 0)):
            raise ValueError('Capture receipt does not prove fresh passive WGC capture')
        if not (receipt.get('background_only') or receipt.get('user_foreground_allowed')):
            raise ValueError('No valid background or user foreground capture policy')
        with Image.open(path) as source:
            image = source.convert('RGBA')
        self.reports.append({'name': suffix, 'capture': str(path), 'capture_sha256': digest(path),
                             'state_sha256': digest(self.evidence/(label+'.state.json')),
                             'capture_receipt_sha256': digest(receipt_path),
                             'user_foreground_allowed': receipt.get('user_foreground_allowed'),
                             'background_before': receipt.get('background_before'),
                             'background_after': receipt.get('background_after'),
                             'state': state})
        return image, self.reports[-1]

    def checked(self, suffix, code, expected, native=False, consumer=False):
        image, report = self.capture(suffix, code)
        report.update(compare(sample_pixels(image, len(expected), native, consumer), expected))
        return report

    def setup(self):
        self.call('open', "if probe is None:\n    raise RuntimeError('Scene codec is not registered')\n"
                  "api.HideCrossHairGUI(True)\nprobe.open()")
        for attempt in range(30):
            if self.state.get('ready'):
                break
            time.sleep(.3)
            self.call('ready_%d' % attempt, '')
        if not self.state.get('ready'):
            raise RuntimeError('Actor uniforms did not become ready')
        if not self.state.get('pipeline_installed'):
            self.call('install', 'probe.install_pipeline()')
            time.sleep(.5)
        if not self.state.get('pipeline_ready'):
            self.call('finish', 'probe.finish_pipeline()')
        self.call('calibration_fixture', 'probe.fixture(0,bits=2,blocks=32)')
        expected = [(index % 256,)*3 for index in range(1024)]
        for native, mode in ((False, 7), (True, 17)):
            report = self.checked('calibration_'+str(mode), 'probe.inspect(%d,0,1024)' % mode,
                                  expected, native=native)
            if not report['passed']:
                raise ValueError('Exact output-byte calibration failed')
        count = 720*936
        expected = [(x % 256, (1079-y) % 256, x//256+4*((1079-y)//256))
                    for y in range(128, 1064) for x in range(720)]
        report = self.checked('gpu_fragment_coordinates', 'probe.inspect(21,0,%d,True)' % count,
                              expected, native=True)
        if not report['passed']:
            raise ValueError('GPU gl_FragCoord and passive native capture coordinates disagree')
        values = (720, 1080, round(16777216/720), round(16777216/1080))
        expected = [(value % 256, (value//256) % 256, value//65536) for value in values]
        report = self.checked('gpu_screen_info', 'probe.inspect(22,0,4,True)', expected, native=True)
        if not report['passed']:
            raise ValueError('GPU ScreenInfo does not match the declared native dimensions')

    def fixtures(self):
        count, blocks, salt = 1024, 32, 29
        for bits in (1, 2):
            logical = blocks*12*bits
            for fixture in (0, 1):
                prefix = 'fixture_k%d_mode%d' % (bits, fixture)
                self.call(prefix, 'probe.fixture(%d,bits=%d,blocks=%d,salt=%d)' %
                          (fixture, bits, blocks, salt))
                rgb = [tuple(codec.decode_rgb_channel(value, bits)[1]
                             for value in codec.fixture_rgba(index, bits, fixture, 255, salt)[:3])
                       for index in range(count)]
                alpha = [(codec.fixture_alpha(index, fixture),)*3 for index in range(count)]
                headers = []
                for block in range(blocks):
                    values = [codec.fixture_alpha(block*32+i, fixture) for i in range(32)]
                    payload = [codec.payload_oracle(block*12*bits+i, salt) for i in range(12*bits)]
                    headers.extend((value,)*3 for value in codec.encode_alpha_block(values, payload)['encoded'])
                self.checked(prefix+'_rgb', 'probe.inspect(2,0,%d)' % count, rgb)
                self.checked(prefix+'_alpha', 'probe.inspect(3,0,%d)' % count, alpha)
                self.checked(prefix+'_header', 'probe.inspect(4,0,%d)' % count, headers)
                for mode in (0, 1, 2):
                    expected = [expected_query(index, mode, logical, salt) for index in range(logical)]
                    self.checked(prefix+'_query%d' % mode, 'probe.query(0,%d,%d)' % (logical, mode),
                                 expected, consumer=True)
            for fixture in (2, 3):
                prefix = 'overflow_k%d_mode%d' % (bits, fixture)
                self.call(prefix, 'probe.fixture(%d,bits=%d,blocks=%d)' % (fixture, bits, blocks))
                self.checked(prefix+'_decode', 'probe.inspect(2,0,%d)' % count, [(255, 0, 255)]*count)
                self.checked(prefix+'_consumer', 'probe.query(0,%d,0)' % logical,
                             [(255, 0, 255)]*logical, consumer=True)

    def alpha(self):
        self.call('alpha_hide', 'probe.set_writer_visible(False)\nprobe.configure_codec()')
        gray, report = self.capture('alpha_gray', 'probe.diagnostic(0,True)')
        # Date/debug overlays are above y128; y1064 avoids bottom window corners.
        for name, image in (('whole_frame', gray), ('safe_rect', gray.crop((0, 128, 720, 1064)))):
            histogram = Counter(pixel[0] for pixel in image.getdata())
            report[name] = {'sample_count': image.width*image.height, 'histogram': dict(sorted(histogram.items())),
                            'modal_byte': histogram.most_common(1)[0][0],
                            'non_gray_pixels': sum(r != g or g != b for r, g, b, a in image.getdata())}
        base = report['safe_rect']['modal_byte']
        byte_samples = [pixel[0]/255. for pixel in gray.crop((0, 128, 720, 1064)).getdata()]
        report['quantized_alpha_distribution'] = codec.alpha_distribution(byte_samples, base)
        report['distribution_precision_limit'] = 'This histogram sees quantized output bytes; consult the separate shader residual flags.'
        grid, residual_report = self.capture('alpha_grid', 'probe.diagnostic(1,True)')
        region = grid.crop((0, 128, 720, 1064))
        residual_report.update(pixel_count=region.width*region.height,
                               off_unorm8_flag_pixels=sum(pixel[2] > 127 for pixel in region.getdata()),
                               maximum_residual_display_byte=max(pixel[1] for pixel in region.getdata()),
                               precision_claim='Shader residual diagnostic; screenshot is quantized UNORM8 evidence')
        self.call('alpha_base', 'probe.set_base_alpha(%d)' % base)
        block_image, block_report = self.capture('alpha_blocks', 'probe.diagnostic(2,True)')
        pixels = list(block_image.getdata())
        starts = range(128*720, 1064*720-31, 32)
        exception_counts = [int(pixels[index][0]*32/255.+.5) for index in starts]
        overflow = sum(pixels[index][1] > 127 for index in starts)
        valid = len(exception_counts)-overflow
        block_report.update(base_alpha=base, complete_blocks=len(exception_counts),
                            exception_count_histogram=dict(sorted(Counter(exception_counts).items())),
                            overflow_blocks=overflow, valid_blocks=valid,
                            conditional_alpha_payload_bytes=valid*24,
                            combined_rgb_input_bytes={'k1': valid*12, 'k2': valid*24},
                            note='Safe rect y128..1063; capacities are conditional on the selected base and <=4 exceptions/block.')
        return base

    def native(self):
        for bits in (1, 2):
            logical, salt = self.args.bytes, 29
            plan = plan_payload(logical, bits)
            prefix = 'native_k%d_bytes%d' % (bits, logical)
            self.call(prefix+'_load', 'probe.load_payload(%d,bits=%d,salt=%d)\nprobe.set_writer_visible(False)' %
                      (logical, bits, salt))
            count = plan['pixels']
            before, baseline = self.capture(prefix+'_baseline', 'probe.inspect(11,0,%d)' % count)
            again, stability = self.capture(prefix+'_baseline_repeat', 'probe.inspect(11,0,%d)' % count)
            baseline_samples = sample_pixels(before, count, native=True)
            stable_rgb = [patch[0][:3] for patch in baseline_samples]
            stability.update(compare(sample_pixels(again, count, native=True), stable_rgb))
            baseline_alpha_image, _ = self.capture(prefix+'_baseline_alpha', 'probe.inspect(10,0,%d)' % count)
            baseline_alpha = [patch[0][:3] for patch in sample_pixels(baseline_alpha_image, count, native=True)]
            restored, restore_report = self.capture(prefix+'_restored',
                'probe.set_writer_visible(True)\nprobe.inspect(12,0,%d)' % count)
            restore_report.update(compare(sample_pixels(restored, count, native=True), stable_rgb, tolerance=bits))
            restore_report['baseline_stable'] = stability['passed']
            restore_report['natural_scene_limitation'] = 'Separate captures; moving scene can change RGB. Does not exhaust x=0..255.'
            raw_alpha_image, raw_alpha_report = self.capture(prefix+'_writer_alpha', 'probe.inspect(10,0,%d)' % count)
            raw_alpha_report.update(compare(sample_pixels(raw_alpha_image, count, native=True), baseline_alpha))
            raw_alpha_report['limitation'] = 'Separate writer-off/on raw-alpha captures; subject to scene changes.'
            self.checked(prefix+'_same_frame_alpha_error', 'probe.inspect(20,0,%d)' % count,
                         [(0, 0, 0)]*count, native=True)
            for mode in (0, 1, 2):
                expected = [expected_query(index, mode, logical, salt) for index in range(logical)]
                self.checked(prefix+'_query%d' % mode, 'probe.query(0,%d,%d)' % (logical, mode+3),
                             expected, native=True, consumer=True)
            hidden = self.checked(prefix+'_hidden', 'probe.set_writer_visible(False)\nprobe.query(0,%d,3)' % logical,
                                  [expected_query(index, 0, logical, salt) for index in range(logical)],
                                  native=True, consumer=True)
            hidden['negative_control_rejected_payload'] = not hidden.pop('passed')
            hidden['passed'] = hidden['negative_control_rejected_payload']
            self.call(prefix+'_restore', 'probe.set_writer_visible(True)')

    def native_domain(self):
        for bits in (1, 2):
            count = 256*(1 << (3*bits))
            byte_count = count*3*bits//8
            for first in (False, True):
                prefix = 'domain_k%d_background_first%d' % (bits, first)
                self.call(prefix+'_load', 'probe.load_payload(%d,bits=%d,code_domain=True,background_first=%r)\n'
                          'probe.set_writer_visible(False)' % (byte_count, bits, first))
                original = [(i%256, ((i%256)*73+19)%256, ((i%256)*151+47)%256) for i in range(count)]
                self.checked(prefix+'_background', 'probe.inspect(11,0,%d)' % count, original, native=True)
                n = 1 << (8-bits)
                encoded = [tuple(n*((i//256 >> (channel*bits))&((1 << bits)-1))+
                                 (2*(n-1)*value+255)//510 for channel,value in enumerate(rgb))
                           for i,rgb in enumerate(original)]
                self.checked(prefix+'_encoded', 'probe.set_writer_visible(True)\nprobe.inspect(11,0,%d)' % count,
                             encoded, native=True)
                restored = [tuple((2*(value%n)*255+(n-1))//(2*(n-1)) for value in rgb) for rgb in encoded]
                report = self.checked(prefix+'_restored', 'probe.inspect(12,0,%d)' % count, restored, native=True)
                report['max_expected_original_error'] = max(abs(a-b) for p,q in zip(restored,original) for a,b in zip(p,q))
                self.checked(prefix+'_alpha_error', 'probe.inspect(20,0,%d)' % count, [(0,0,0)]*count, native=True)
                self.checked(prefix+'_background_return', 'probe.set_writer_visible(False)\nprobe.inspect(11,0,%d)' % count,
                             original, native=True)
                report = self.checked(prefix+'_background_hidden', 'probe.set_background_visible(False)\nprobe.inspect(11,0,%d)' % count,
                                      original, native=True)
                report['negative_control_rejected_background'] = not report.pop('passed')
                report['passed'] = report['negative_control_rejected_background']
                self.call(prefix+'_restore', 'probe.set_background_visible(True)')

    def static(self):
        logical, bits, salt = self.args.bytes, self.args.bits, 29
        frozen = self.call('static_load', 'probe.load_payload(%d,bits=%d,salt=%d)\nprobe.set_native_writer_visible(True)' %
                           (logical, bits, salt))
        for mode in (0, 2):
            report = self.checked('static_before_query%d' % mode, 'probe.query(0,%d,%d)' % (logical, mode+3),
                                  [expected_query(index, mode, logical, salt) for index in range(logical)],
                                  native=True, consumer=True)
            if not report['passed']:
                raise ValueError('Full native payload must pass before formal static FPS')
        disabled = "for name in probe.codec_processes:\n    if not probe.post.SetEnableByName(name,False):\n        raise RuntimeError('Static profile disable rejected')\n"
        for profile in ('baseline', 'writer', 'combo_restore', 'combo_dependent'):
            if profile == 'combo_restore':
                code = ("probe.set_native_writer_visible(True)\nprobe.configure_codec()\n"
                        "if not probe.post.SetEnableByName('scene_codec_inspect',False):\n"
                        "    raise RuntimeError('Restore-only output selection rejected')")
            elif profile == 'combo_dependent':
                code = 'probe.set_native_writer_visible(True)\nprobe.configure_codec()\nprobe.query(0,%d,5)' % logical
            else:
                code = disabled+'probe.set_native_writer_visible(%r)' % (profile == 'writer')
            self.call('static_'+profile+'_profile', code)
            time.sleep(1.)
            self.call('static_'+profile+'_start', 'probe.start_static_measurement(%r,2.)' % self.args.seconds)
            time.sleep(self.args.seconds+3)
            state = self.call('static_'+profile+'_result', '')
            same_geometry = all(state.get(key) == frozen.get(key) for key in
                                ('geometry_name', 'geometry_build_serial', 'logical_payload_bytes',
                                 'allocated_payload_bytes', 'codec_roi', 'payload_salt'))
            expected_enabled = (['scene_codec_raw', 'scene_codec_encode', 'scene_codec_decode']
                                if profile.startswith('combo_') else [])
            if profile == 'combo_dependent':
                expected_enabled.append('scene_codec_consumer')
            actual_visible = {name for name, visible in state.get('native_attachment_visibility', {}).items() if visible}
            expected_visible = {state['geometry_name']} if profile != 'baseline' else set()
            profile_matches = (set(state.get('codec_enabled_processes', [])) == set(expected_enabled) and
                               state.get('writer_visible') == (profile != 'baseline') and
                               actual_visible == expected_visible)
            self.reports.append({'name': 'static_'+profile+'_fps', 'measurement': state.get('last_measurement'),
                                 'static_payload': True, 'continuous_updates': False,
                                 'fps_limit': 60, 'geometry_identity_unchanged': same_geometry,
                                 'measurement_window': state.get('static_measurement_window'),
                                 'enabled_processes': state.get('codec_enabled_processes'),
                                 'post_pass_count': len(state.get('codec_enabled_processes', [])),
                                 'visible_native_attachments': sorted(actual_visible),
                                 'profile_controls_match': profile_matches,
                                 'passed': same_geometry and profile_matches and state.get('last_measurement') is not None,
                                 'profile': profile, 'state': state})
        report = self.checked('static_after_query2', 'probe.query(0,%d,5)' % logical,
                              [expected_query(index, 2, logical, salt) for index in range(logical)],
                              native=True, consumer=True)
        if not report['passed']:
            raise ValueError('Frozen payload failed after formal static FPS')

    def run(self):
        error = None
        try:
            if self.args.stage == 'setup':
                self.setup()
            else:
                getattr(self, self.args.stage)()
        except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as failure:
            error = '%s: %s' % (type(failure).__name__, failure)
        finally:
            result = {'schema': 'scene_codec_evidence_v1', 'stage': self.args.stage,
                      'reports': self.reports, 'events': self.events, 'error': error,
                      'passed': error is None and all(item.get('passed', True) for item in self.reports),
                      'runtime_file_writes': False, 'launch_performed': False}
            self.result.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'result': str(self.result), 'passed': result['passed'], 'error': error}))
        return 0 if result['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--stage', choices=('setup', 'fixtures', 'alpha', 'native', 'native_domain', 'static'), required=True)
    parser.add_argument('--bytes', type=int, default=65536)
    parser.add_argument('--bits', type=int, choices=(1, 2), default=2)
    parser.add_argument('--settle', type=float, default=.75)
    parser.add_argument('--seconds', type=float, default=25.)
    args = parser.parse_args()
    return Experiment(args).run()


if __name__ == '__main__':
    sys.exit(main())
