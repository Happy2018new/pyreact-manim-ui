"""Finite, owner-bound bulk stencil research with full-image gates and memory receipts."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import zlib

import numpy as np
from PIL import Image

from memory import snapshot as memory_snapshot
from verify import payload_bytes, verify

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OWNER = 'manim-stencil-bulk'
LAYOUTS = {64: ([720, 1080], [8, 128, 256, 1]),
           65536: ([720, 1080], [8, 128, 512, 512]),
           262144: ([1080, 1440], [8, 128, 1024, 1024]),
           524288: ([2304, 1280], [8, 128, 2048, 1024])}
spec = importlib.util.spec_from_file_location('large_order_helpers', HERE.parent/'weather_effect_order_probe/runner.py')
order = importlib.util.module_from_spec(spec)
spec.loader.exec_module(order)
order.HERE, order.OWNER = HERE, OWNER


class Experiment(order.Experiment):
    def __init__(self, args):
        super().__init__(args)
        self.measurements, self.memories, self.loads, self.restorations = [], [], [], []
        self.payload, self.viewport, self.roi = None, None, None
        self.output_y = 64
        session = json.loads(Path(self.session).read_text(encoding='utf-8-sig'))
        if session['owner'] != OWNER or Path(session['project']).resolve() != args.project.resolve():
            raise RuntimeError('Owner/project identity mismatch')
        self.game_pid = session['game_pid']

    def save(self):
        result = {'schema': 'weather_stencil_large_v1', 'reports': self.reports,
                  'loads': self.loads, 'memory': self.memories,
                  'measurements': self.measurements, 'restorations': self.restorations}
        (self.evidence/'results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')

    def call(self, label, code='', expression='probe.snapshot()'):
        self.serial += 1
        name = '%03d_%s' % (self.serial, label)
        path = self.commands/(name+'.py')
        path.write_text("probe=api.GetSystem('pmanim_stencil_large','probe')\n"+code+
                        '\n_result=json.dumps('+expression+')\n', encoding='utf-8')
        self.invoke([sys.executable, '-B', '-X', 'utf8', str(HERE/'host.py'), 'call',
                     '--project', str(self.args.project.resolve()), '--evidence', str(self.evidence),
                     '--label', name, '--timeout', '120', '--code', str(path)], name)
        value = json.loads((self.evidence/(name+'.state.json')).read_text(encoding='utf-8'))
        if expression == 'probe.snapshot()':
            self.state = value
            if value.get('error'):
                raise RuntimeError(value['error'])
        return value

    def memory(self, label, required=False):
        result = dict(memory_snapshot(self.game_pid), label=label, time_unix=time.time())
        self.memories.append(result)
        self.save()
        print(json.dumps({'memory': label, 'available_commit': result['system_commit_available_bytes'],
                          'private_commit': result['process_private_commit_bytes'],
                          'preflight': result['preflight_passed']}), flush=True)
        if required and not result['preflight_passed']:
            raise RuntimeError('At least4GiB available commit is required before '+label)
        return result

    def wait_ready(self, label):
        for attempt in range(20):
            if self.call(label+'_ready_%02d' % attempt)['ready']:
                return
            time.sleep(.5)
        raise RuntimeError('Actor uniforms were not ready')

    def load(self, size):
        self.viewport, self.roi = LAYOUTS[size]
        # Native debug text extends belowY64 at the largest viewport.
        self.output_y = 128 if size == 524288 else 64
        self.payload = payload_bytes(size)
        prefix = 'n%d' % size
        self.invoke([sys.executable, '-B', '-X', 'utf8', str(HERE/'host.py'), 'resize',
                     '--project', str(self.args.project.resolve()), '--evidence', str(self.evidence),
                     '--width', str(self.viewport[0]), '--height', str(self.viewport[1])], prefix+'_resize')
        data_path = self.evidence/(prefix+'_actual_input.bin')
        data_path.write_bytes(self.payload)
        digest = hashlib.sha256(self.payload).hexdigest()
        self.memory(prefix+'_load_begin', True)
        self.call(prefix+'_load_begin', 'probe.load_begin(%d,%r,%r,%r)' % (size, digest, self.viewport, self.roi))
        # Each runtime call receives at most4096 actual bytes. Batching the calls
        # in a host command reduces connector overhead without a GPU/game seed.
        for batch in range(0, size, 65536):
            statements = []
            for offset in range(batch, min(batch+65536, size), 4096):
                statements.append('probe.load_chunk(%d,%r)' % (offset, list(self.payload[offset:offset+4096])))
            self.call(prefix+'_upload_%d' % batch, '\n'.join(statements))
        self.call(prefix+'_load_finish', 'probe.load_finish()')
        identity = self.state['identity']
        if identity['host_sha256'] != digest or identity['adler32'] != zlib.adler32(self.payload)&0xffffffff:
            raise RuntimeError('Frozen host/runtime byte identity mismatch')
        self.wait_ready(prefix)
        while self.state['next_native_page'] is not None:
            page = self.state['completed_plan_items']
            self.memory(prefix+'_prebuild_%d' % page, True)
            self.call(prefix+'_build_%d' % page, 'probe.build_next_page()')
            self.memory(prefix+'_postbuild_%d' % page)
        self.loads.append({'logical_bytes': size, 'viewport': self.viewport, 'roi': self.roi,
                           'input_sha256': digest, 'input_adler32': zlib.adler32(self.payload)&0xffffffff,
                           'input_file': str(data_path), 'payload_formula': 'SHA256(stencil-bulk-v1/N/blockIndex) concatenation',
                           'state_after_load': self.state})
        self.save()

    def capture(self, label, mode, slot=0, configuration='all', hide=False, expected=True, verify_pixels=True):
        code = 'probe.configure(%r)\nprobe.inspect(%d,%d,True)' % (configuration, mode, slot)
        if self.output_y != 64:
            code += "\nif not probe.post.SetParameter('stencil_large_oracle','output',%r): raise RuntimeError('Output origin rejected')" % ([0., float(self.output_y), float(self.viewport[0]), float(slot)],)
        if hide:
            code += '\nprobe.hide_payload()'
        self.call(label+'_controls', code)
        time.sleep(.6)
        self.call(label+'_settled')
        if any(enabled for _, enabled in self.state['native_post_flags']) or not self.state['oracle_enabled']:
            raise RuntimeError('Native post/oracle state gate rejected')
        self.invoke([sys.executable, '-B', '-X', 'utf8', str(HERE/'host.py'), 'capture',
                     '--project', str(self.args.project.resolve()), '--evidence', str(self.evidence),
                     '--label', label], label+'_capture')
        receipt = json.loads((self.evidence/(label+'.json')).read_text(encoding='utf-8'))
        if (not receipt['ok'] or receipt['backend'] != 'Windows.Graphics.Capture'
                or [receipt['width'], receipt['height']] != self.viewport
                or receipt['frame_qpc_100ns'] < receipt['request_qpc_100ns']
                or receipt.get('agent_activation_allowed') is not False):
            raise RuntimeError('Fresh passive capture/dimensions gate rejected')
        for key in ('background_before', 'background_after'):
            if not receipt.get(key, {}).get('window_noactivate'):
                raise RuntimeError('Native window noactivation receipt rejected')
        report = {'label': label, 'logical_bytes': len(self.payload), 'mode': mode, 'slot': slot,
                  'configuration': configuration, 'hidden_payload': hide, 'expected_asserted': expected,
                  'raining': self.weather_is_raining, 'state': self.state, 'capture_receipt': receipt,
                  'output_origin': [0, self.output_y],
                  'capture_file': str(self.evidence/(label+'.png'))}
        if verify_pixels:
            with Image.open(self.evidence/(label+'.png')) as source:
                report.update(verify(source.convert('RGB'), mode, self.payload, self.viewport, self.roi, output_y=self.output_y))
            if hide:
                report['negative_rejected'] = not report['exact']
        self.reports.append(report)
        self.save()
        print(json.dumps({k: report[k] for k in ('label', 'exact', 'error_pixels', 'alpha_not255_pixels', 'negative_rejected') if k in report}), flush=True)
        if verify_pixels and expected and not report['exact']:
            raise RuntimeError('Full-image correctness failed at '+label)
        if hide and not report['negative_rejected']:
            raise RuntimeError('Hidden geometry negative failed to reject')
        return report

    def restoration(self, prefix):
        labels = [prefix+'_off_before', prefix+'_restore', prefix+'_off_after']
        self.capture(labels[0], 0, configuration='off', verify_pixels=False, expected=False)
        self.capture(labels[1], 4, verify_pixels=False, expected=False)
        self.capture(labels[2], 0, configuration='off', verify_pixels=False, expected=False)
        arrays = []
        x, y, width, height = self.roi
        for label in labels:
            with Image.open(self.evidence/(label+'.png')) as source:
                arrays.append(np.asarray(source.convert('RGB'), dtype=np.int16)[y:y+height, x:x+width])
        drift = np.abs(arrays[0]-arrays[2])
        error_before, error_after = np.abs(arrays[1]-arrays[0]), np.abs(arrays[1]-arrays[2])
        result = {'logical_bytes': len(self.payload), 'labels': labels, 'source_pixels': width*height,
                  'baseline_drift_pixels': int(np.any(drift, axis=2).sum()),
                  'baseline_identical': bool(not np.any(drift)),
                  'restore_max_rgb_error_before': error_before.max(axis=(0,1)).tolist(),
                  'restore_max_rgb_error_after': error_after.max(axis=(0,1)).tolist(),
                  'restore_error_gt2_pixels_before': int(np.any(error_before>2, axis=2).sum()),
                  'restore_error_gt2_pixels_after': int(np.any(error_after>2, axis=2).sum()),
                  'separate_frame_scene_drift_qualification_required': bool(np.any(drift))}
        self.restorations.append(result)
        self.save()
        print(json.dumps({'restoration': result}), flush=True)

    def measure(self, prefix, mode):
        before = self.memory(prefix+'_'+mode+'_before')
        self.call(prefix+'_'+mode+'_start', 'probe.start_measurement(%r,25.,2.)' % mode)
        for attempt in range(15):
            time.sleep(3.)
            result = self.call(prefix+'_'+mode+'_poll_%02d' % attempt, expression='probe.measurement_result()')
            if not result['running']:
                if result['result'] is None:
                    raise RuntimeError('Measurement ended without result')
                after = self.memory(prefix+'_'+mode+'_after')
                self.measurements.append({'logical_bytes': len(self.payload), 'mode': mode,
                                          'memory_before': before, 'memory_after': after, **result['result']})
                self.save()
                print(json.dumps({'timing': mode, 'logical_bytes': len(self.payload),
                                  'intervals': result['result']['frame_interval_statistics'],
                                  'fps': result['result']['fps_statistics']}), flush=True)
                return
        raise RuntimeError('Measurement did not complete in45seconds')

    def suite(self, size):
        prefix = 'n%d' % size
        self.load(size)
        for slot in (0, 1):
            for mode in (1, 2, 3):
                self.capture(prefix+'_clear_t%d_m%d' % (slot, mode), mode, slot)
        self.capture(prefix+'_hidden_negative', 1, hide=True, expected=False)
        self.capture(prefix+'_return_positive', 1)
        if size == 64:
            return
        self.restoration(prefix)
        self.weather(prefix+'_rain_on', True)
        wet = []
        for slot in (0, 1):
            for mode in (1, 2, 3):
                report = self.capture(prefix+'_wet_t%d_m%d' % (slot, mode), mode, slot)
                if mode == 3:
                    wet.append(report)
        if not any(report['alpha_not255_pixels'] for report in wet):
            raise RuntimeError('Wet source must show actual non255 alpha in same-fetch oracle')
        self.weather(prefix+'_rain_off', False)
        self.capture(prefix+'_clear_return', 1)
        for mode in ('baseline', 'restore', 'dependent'):
            self.measure(prefix, mode)
        loaded = self.loads[-1]['state_after_load']
        for mode in (1, 2, 3):
            self.capture(prefix+'_posttiming_m%d' % mode, mode)
            if (self.state['identity'] != loaded['identity'] or self.state['active_pages'] != loaded['active_pages']):
                raise RuntimeError('Post-timing input or resident pages changed')
        self.call(prefix+'_timing_off', "probe.configure('off')\nprobe.inspect(0,0,True)")

    def run(self):
        self.call('initial')
        self.call('prepare', 'api.HideCrossHairGUI(True)\nprobe.prepare()')
        self.weather('prepare_clear', False, True)
        self.call('install_oracle', 'probe.install_oracle()')
        for size in self.args.capacities:
            self.suite(size)
        self.call('final_hidden', "probe.configure('off')\nprobe.inspect(0,0,False)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--capacities', type=lambda value: [int(x) for x in value.split(',')], default=[64, 65536, 262144, 524288])
    args = parser.parse_args()
    if args.capacities[0] != 64 or any(size not in LAYOUTS for size in args.capacities):
        raise ValueError('Start with64B smoke and choose supported capacities')
    experiment = Experiment(args)
    failure = None
    try:
        experiment.run()
    except Exception as error:
        failure = repr(error)
        raise
    finally:
        experiment.save()
        (args.evidence/'final-host-status.json').write_text(json.dumps({
            'reports': len(experiment.reports), 'last_state': experiment.state,
            'rain_reversion_required': experiment.weather_is_raining, 'failure': failure,
            'source_hashes': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in HERE.iterdir() if path.is_file()}}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
