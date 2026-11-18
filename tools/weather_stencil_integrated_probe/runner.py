"""Owner-bound integrated copy/restore/T3 consumer experiment; no desktop input."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OWNER = 'manim-stencil-integrated'
sys.path.insert(0, str(HERE.parent/'weather_stencil_large_probe'))
spec = importlib.util.spec_from_file_location('integrated_bulk_host_helpers', HERE.parent/'weather_stencil_large_probe/runner.py')
bulk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bulk)
bulk.HERE, bulk.OWNER = HERE, OWNER
bulk.order.HERE, bulk.order.OWNER = HERE, OWNER
verify_spec = importlib.util.spec_from_file_location('integrated_verify', HERE/'verify.py')
verify_module = importlib.util.module_from_spec(verify_spec)
verify_spec.loader.exec_module(verify_module)


class Experiment(bulk.Experiment):
    def save(self):
        (self.evidence/'results.json').write_text(json.dumps({
            'schema': 'weather_stencil_integrated_v1', 'post_pass_count': 3,
            'reports': self.reports, 'loads': self.loads, 'memory': self.memories,
            'measurements': self.measurements, 'restorations': self.restorations}, indent=2), encoding='utf-8')

    def call(self, label, code='', expression='probe.snapshot()'):
        self.serial += 1
        name = '%03d_%s' % (self.serial, label)
        path = self.commands/(name+'.py')
        path.write_text("probe=api.GetSystem('pmanim_stencil_integrated','probe')\n"+code+
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

    def load(self, size):
        super().load(size)
        self.output_y = 128

    def capture(self, label, mode, configuration='all', hide=False, expected=True,
                fixture=False, visible_zero=False, verify_pixels=True, mutate_alpha=False, output_y=128):
        code = 'probe.configure(%r)\nprobe.inspect(%d,shape_enabled=%r,enabled=True,restore_enabled=%r)' % (
            configuration, mode, mode == 4, configuration == 'all')
        if hide:
            code += '\nprobe.hide_payload()'
        if mutate_alpha:
            code += "\nif not probe.post.SetParameter('stencil_integrated_restore','output',%r): raise RuntimeError('Alpha mutation control rejected')" % ([0.,128.,float(self.viewport[0]),2.],)
        if output_y != 128:
            code += "\nif not probe.post.SetParameter('stencil_integrated_consumer','output',%r): raise RuntimeError('Diagnostic origin rejected')" % ([0.,float(output_y),float(self.viewport[0]),float(mode==4)],)
        self.call(label+'_controls', code)
        time.sleep(.6)
        self.call(label+'_settled')
        if any(enabled for _, enabled in self.state['native_post_flags']):
            raise RuntimeError('Built-in post isolation rejected')
        self.invoke([sys.executable, '-B', '-X', 'utf8', str(HERE/'host.py'), 'capture',
                     '--project', str(self.args.project.resolve()), '--evidence', str(self.evidence),
                     '--label', label], label+'_capture')
        receipt = json.loads((self.evidence/(label+'.json')).read_text(encoding='utf-8'))
        if (not receipt['ok'] or receipt['backend'] != 'Windows.Graphics.Capture'
                or [receipt['width'], receipt['height']] != self.viewport
                or receipt['frame_qpc_100ns'] < receipt['request_qpc_100ns']
                or receipt.get('agent_activation_allowed') is not False
                or not all(receipt.get(key, {}).get('window_noactivate')
                           for key in ('background_before', 'background_after'))):
            raise RuntimeError('Fresh passive capture/noactivation/dimensions gate rejected')
        report = {'label': label, 'logical_bytes': len(self.payload), 'mode': mode,
                  'configuration': configuration, 'hidden_payload': hide, 'expected_asserted': expected,
                  'fixture': fixture, 'visible_zero_expected': visible_zero,
                  'single_pixel_alpha_mutation': mutate_alpha,
                  'raining': self.weather_is_raining, 'state': self.state, 'capture_receipt': receipt,
                  'output_origin': [0, output_y], 'source_texture': 'explicit copy process result in TEXTURE_3',
                  'restored_texture': 'explicit restore process result in TEXTURE_4',
                  'capture_file': str(self.evidence/(label+'.png'))}
        if verify_pixels:
            with Image.open(self.evidence/(label+'.png')) as source:
                image = source.convert('RGB')
                if mode == 4:
                    payload = bytes(len(self.payload)) if visible_zero else self.payload
                    report.update(verify_module.verify_visible(image, payload, self.viewport, self.roi, fixture=fixture))
                else:
                    report.update(verify_module.verify(image, mode, self.payload, self.viewport, self.roi,
                                                       output_y=output_y, fixture=fixture))
            if hide and mode != 4:
                report['negative_rejected'] = not report['exact']
        self.reports.append(report)
        self.save()
        print(json.dumps({key: report[key] for key in ('label', 'exact', 'error_pixels', 'alpha_not255_pixels',
                          'negative_rejected', 'shape_pixels') if key in report}), flush=True)
        if expected and verify_pixels and not report['exact']:
            raise RuntimeError('Integrated full-pixel gate failed at '+label)
        if hide and mode != 4 and not report['negative_rejected']:
            raise RuntimeError('Hidden geometry negative failed to reject')
        return report

    def run(self):
        self.call('initial')
        self.call('prepare', 'api.HideCrossHairGUI(True)\nprobe.prepare()')
        self.weather('prepare_clear', False, True)
        self.load(65536)
        self.call('install_pipeline', 'probe.install_pipeline()')
        time.sleep(.7)
        self.call('finish_pipeline', 'probe.finish_pipeline()')
        for mode in (1, 2, 3, 5):
            self.capture('clear_t3_m%d' % mode, mode)
        self.capture('clear_visible_actual', 4)
        self.capture('hidden_identity_negative', 1, hide=True, expected=False)
        self.capture('hidden_visible_zero', 4, hide=True, visible_zero=True)
        self.capture('return_visible_actual', 4)
        self.call('known_fixture_on', 'probe.configure_known_fixture(True,True)')
        for mode in (7, 5):
            self.capture('fixture_alone_m%d' % mode, mode, configuration='off', fixture=True)
        for mode in (1, 2, 3, 5, 6, 4):
            self.capture('fixture_encoded_m%d' % mode, mode, fixture=True)
        negative = self.capture('fixture_alpha_mutation_negative', 5, fixture=True,
                                expected=False, mutate_alpha=True)
        if negative['encoded_restored_alpha_mismatch_pixels'] != 1 or negative['data_error_pixels'] != 1:
            raise RuntimeError('Single-pixel alpha negative must fail at exactly one sample')
        self.capture('fixture_alpha_mutation_return', 5, fixture=True)
        self.call('known_fixture_off', 'probe.configure_known_fixture(False)')
        self.weather('rain_on', True)
        wet = []
        for mode in (1, 2, 3, 5, 4):
            wet.append(self.capture('wet_t3_m%d' % mode, mode))
        raw = next(report for report in wet if report['mode'] == 3)
        if raw['alpha_not255_pixels'] < 1:
            raise RuntimeError('Actual wet alpha witness missing')
        self.weather('rain_off', False)
        self.capture('clear_return_identity', 1)
        self.capture('clear_return_visible', 4)
        for mode in ('baseline', 'restore', 'visible', 'dependent'):
            self.measure('integrated64', mode)
        frozen = self.loads[-1]['state_after_load']
        for mode in (1, 2, 3, 5):
            self.capture('posttiming_m%d' % mode, mode)
            if self.state['identity'] != frozen['identity'] or self.state['active_pages'] != frozen['active_pages']:
                raise RuntimeError('Frozen input or active native pages changed')
        self.capture('final_visible', 4)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    experiment = Experiment(args)
    failure = None
    try:
        experiment.run()
    except Exception as error:
        failure = repr(error)
        raise
    finally:
        experiment.save()
        (args.evidence/'initial-status.json').write_text(json.dumps({
            'failure': failure, 'reports': len(experiment.reports), 'last_state': experiment.state,
            'rain_reversion_required': experiment.weather_is_raining,
            'owned_game_left_for_parent_compatibility_direction': True,
            'source_hashes': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in HERE.iterdir() if path.is_file()}}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
