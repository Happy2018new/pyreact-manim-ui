"""Same-instance native UI/outline continuation after successful integrated64KiB evidence."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import time
import traceback
import zlib

from PIL import Image
from runner import Experiment, HERE, verify_module


SIZE = 65536
OUTPUT_Y = 650
PROCESSES = ('stencil_integrated_copy', 'stencil_integrated_restore', 'stencil_integrated_consumer')
LINKS = [[PROCESSES[0], 0, PROCESSES[1], 0, 3],
         [PROCESSES[0], 0, PROCESSES[2], 0, 3],
         [PROCESSES[1], 0, PROCESSES[2], 0, 4]]


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ui_verify = _module('integrated_compat_ui_verify', HERE.parent/'integrated_ui_clip_fixture/verify.py')
outline_verify = _module('integrated_compat_outline_verify', HERE.parent/'integrated_outline_fixture/verify.py')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _tree(directory):
    return {str(path.relative_to(directory)): _sha(path.read_bytes())
            for path in directory.rglob('*') if path.is_file()}


def _sources():
    paths = [HERE/name for name in ('compat_runner.py', 'runner.py', 'verify.py', 'host.py')]
    paths += [HERE.parent/'integrated_ui_clip_fixture/verify.py',
              HERE.parent/'integrated_outline_fixture/verify.py',
              HERE.parent/'weather_stencil_large_probe/runner.py',
              HERE.parent/'weather_stencil_large_probe/memory.py',
              HERE.parent/'weather_effect_order_probe/runner.py']
    return {str(path.relative_to(HERE.parent)): _sha(path.read_bytes()) for path in paths}


def validate_previous(directory):
    directory = directory.resolve()
    paths = {name: directory/name for name in ('results.json', 'initial-status.json', 'launch.json')}
    data = {name: path.read_bytes() for name, path in paths.items()}
    results, status, launch = (json.loads(data[name]) for name in paths)
    if (status.get('failure', 'missing') is not None
            or status.get('rain_reversion_required') is not False):
        raise RuntimeError('Initial integrated suite must be successful and returned to clear weather')
    if launch.get('fps') != 60 or launch.get('agent_activation_allowed') is not False:
        raise RuntimeError('Previous launch must preserve60FPS and disallow agent activation')
    reports = results['reports']
    if any(report.get('expected_asserted') and report.get('exact') is False for report in reports):
        raise RuntimeError('Previous integrated evidence contains a failed asserted pixel gate')
    by_label = {report['label']: report for report in reports}
    for label in ['posttiming_m%d' % mode for mode in (1, 2, 3, 5)]+['final_visible']:
        if by_label.get(label, {}).get('exact') is not True:
            raise RuntimeError('Missing successful initial post-timing gate: '+label)
    loads = [load for load in results['loads'] if load['logical_bytes'] == SIZE]
    if len(loads) != 1:
        raise RuntimeError('Expected exactly one initial64KiB frozen load')
    load = loads[0]
    input_path = Path(load['input_file']).resolve()
    payload = input_path.read_bytes()
    expected = verify_module.payload_bytes(SIZE)
    if (payload != expected or load['input_sha256'] != _sha(payload)
            or load['input_adler32'] != zlib.adler32(payload)&0xffffffff):
        raise RuntimeError('Actual input evidence differs from the agreed host64KiB bytes')
    reference = status['last_state']
    identity = reference['identity']
    if (identity.get('byte_count') != SIZE or identity.get('host_sha256') != _sha(payload)
            or identity.get('adler32') != zlib.adler32(payload)&0xffffffff):
        raise RuntimeError('Previous final input identity differs from actual host bytes')
    for report in reports:
        if report.get('logical_bytes') == SIZE:
            _resident_gate(report['state'], reference, require_idle=False)
    _resident_gate(reference, reference)
    for profile in ('baseline', 'restore', 'visible', 'dependent'):
        timers = [row for row in results['measurements'] if row['mode'] == profile]
        if len(timers) != 1:
            raise RuntimeError('Expected one completed initial timer: '+profile)
        timer = timers[0]
        if (timer.get('identity') != identity or timer.get('post_pass_count') != 3
                or timer.get('resident_pages') != reference['native_page_names']
                or timer.get('requested_seconds') != 25. or timer.get('warm_seconds') != 2.
                or timer.get('elapsed_seconds', 0) < 27. or timer.get('sample_limit_reached') is not False
                or not timer.get('interval_ms') or not timer.get('fps_observations')
                or timer['frame_interval_statistics']['count'] != len(timer['interval_ms'])):
            raise RuntimeError('Initial timing evidence is incomplete or changed input: '+profile)
    return {'results': results, 'load': load, 'payload': payload, 'reference': reference,
            'frozen_tree': _tree(directory),
            'links': {'previous_evidence': str(directory),
                      **{name.replace('.', '_')+'_sha256': _sha(value) for name, value in data.items()},
                      'previous_input_file': str(input_path), 'previous_input_sha256': _sha(payload)}}


def _resident_gate(state, reference, require_idle=True):
    keys = ('identity', 'active_pages', 'native_page_names', 'native_attempt_count',
            'native_records_reserved', 'actor_count', 'effects')
    if (state.get('state') != 'resident' or state.get('ready') is not True or state.get('error') is not None
            or state.get('viewport') != [720, 1080] or state.get('source_roi') != [8, 128, 512, 512]
            or any(state.get(key) != reference.get(key) for key in keys)
            or (require_idle and state.get('measurement') is not None)
            or state.get('pipeline_ready') is not True or state.get('pipeline_enabled') is not True
            or state.get('pipeline_links') != LINKS
            or any(enabled for _, enabled in state.get('native_post_flags', []))):
        raise RuntimeError('Integrated64KiB frozen input, pages or three-pass pipeline changed')


class Compatibility(Experiment):
    def __init__(self, args, previous):
        self.previous = previous
        self.extra = {'schema': 'integrated_native_compatibility_v1', 'ui': [], 'outline': [], 'completed_stages': []}
        super().__init__(args)
        self.payload = previous['payload']
        self.viewport, self.roi = copy.deepcopy(previous['load']['viewport']), copy.deepcopy(previous['load']['roi'])
        self.output_y = 128
        copied_load = copy.deepcopy(previous['load'])
        input_path = self.evidence/'n65536_actual_input.bin'
        input_path.write_bytes(self.payload)
        copied_load.update(input_file=str(input_path), previous_input_file=previous['load']['input_file'])
        self.loads.append(copied_load)
        self.ui_receipt = json.loads((args.project/'ui_clip_fixture_receipt.json').read_text(encoding='utf-8'))
        if (self.ui_receipt['physical'] != self.viewport or len(self.ui_receipt['cases']) != 4
                or any(patch['rect'][1]+patch['rect'][3] > OUTPUT_Y
                       for case in self.ui_receipt['cases'] for patch in case['patches'])
                or SIZE*4 > self.viewport[0]*(self.viewport[1]-OUTPUT_Y)):
            raise RuntimeError('UI patches or complete source diagnostics do not fit the reserved output layout')
        self.save()

    def save(self):
        super().save()
        (self.evidence/'compatibility-extra.json').write_text(json.dumps(self.extra, indent=2), encoding='utf-8')

    def resident(self, label):
        state = self.call(label, "if not all(probe.post.CheckEnabledByName(name) for name in %r): raise RuntimeError('Three native processes must remain enabled')" % (PROCESSES,))
        _resident_gate(state, self.previous['reference'])
        return state

    def checked_capture(self, label, mode, ui=False, **kwargs):
        report = self.capture(label, mode, **kwargs)
        self.resident(label+'_resident')
        if ui:
            result = ui_verify.verify(report['capture_file'], self.ui_receipt)
            report['native_ui_oracle'] = result
            self.extra['ui'].append({'label': label, 'result': result})
            self.save()
            if not result['all_exact']:
                raise RuntimeError('Native UI clipping pixel gate failed at '+label)
        return report

    def outline_check(self, label, before, active, after):
        snapshots = [report['state']['outline'] for report in (before, active, after)]
        state_result = outline_verify.compare_snapshots(*snapshots)
        images = []
        for report in (before, active, after):
            with Image.open(report['capture_file']) as image:
                images.append(image.convert('RGB'))
        result = outline_verify.compare_outline(*images, self.roi, bounds=snapshots[1]['projected_bounds'])
        item = {'label': label, 'captures': [row['label'] for row in (before, active, after)],
                'snapshots': state_result, 'pixels': result}
        self.extra['outline'].append(item)
        self.save()
        if not state_result['pass'] or not result['pass']:
            raise RuntimeError('Native outline positive-control gate failed at '+label)
        if result['fixture_window'][3] > OUTPUT_Y:
            raise RuntimeError('Native outline observation window overlaps the diagnostic output')
        return item

    def outline_triplet(self, prefix, configuration, mode, ui=False):
        reports = []
        for suffix, enabled in (('off_before', False), ('on', True), ('off_after', False)):
            self.call(prefix+'_'+suffix+'_toggle', 'probe.configure_outline(%r)' % enabled)
            reports.append(self.checked_capture(prefix+'_'+suffix, mode, ui=ui,
                configuration=configuration, verify_pixels=mode != 0))
        self.outline_check(prefix, *reports)
        return reports

    def diagnostics(self, prefix, ui=False, outline_refs=None):
        for mode in (1, 2, 3, 5):
            report = self.checked_capture(prefix+'_m%d' % mode, mode, ui=ui, output_y=OUTPUT_Y)
            if outline_refs is not None:
                self.outline_check(prefix+'_m%d' % mode, outline_refs[0], report, outline_refs[2])

    def run(self):
        self.resident('compat_same_instance_initial')
        self.call('compat_fixture_off', 'probe.configure_known_fixture(False)')
        self.call('ui_open', 'probe.open_ui()')
        time.sleep(.7)
        self.call('ui_on', 'probe.configure_ui(True)')
        self.checked_capture('ui_baseline', 0, ui=True, configuration='off', verify_pixels=False)
        self.checked_capture('ui_visible', 4, ui=True)
        self.diagnostics('ui_data', ui=True)
        self.checked_capture('ui_return_visible', 4, ui=True)
        self.extra['completed_stages'].append('ui')
        self.save()
        self.call('ui_off', 'probe.configure_ui(False)')

        self.call('outline_prepare', 'probe.prepare_outline()')
        time.sleep(.7)
        self.resident('outline_ready')
        self.outline_triplet('outline_baseline', 'off', 0)
        active = self.outline_triplet('outline_active_visible', 'all', 4)
        self.call('outline_payload_on', 'probe.configure_outline(True)')
        self.diagnostics('outline_data', outline_refs=active)
        report = self.checked_capture('outline_return_visible', 4)
        self.outline_check('outline_return_visible', active[0], report, active[2])
        self.extra['completed_stages'].append('outline')
        self.save()

        self.call('joint_ui_on', 'probe.configure_ui(True)')
        joint = self.outline_triplet('joint_active_visible', 'all', 4, ui=True)
        self.call('joint_payload_on', 'probe.configure_outline(True)')
        self.diagnostics('joint_data', ui=True, outline_refs=joint)
        report = self.checked_capture('joint_return_visible', 4, ui=True)
        self.outline_check('joint_return_visible', joint[0], report, joint[2])
        self.extra['completed_stages'].append('joint')
        self.save()
        self.call('compat_both_off', 'probe.configure_ui(False)\nprobe.configure_outline(False)')
        self.checked_capture('compat_visible_return', 4)

        self.call('quantization_fixture_on', 'probe.configure_known_fixture(True,True)')
        self.checked_capture('quantization_encoded_t3', 7, fixture=True, expected=False)
        self.call('quantization_fixture_off', 'probe.configure_known_fixture(False)')
        self.checked_capture('compat_final_visible', 4)
        self.extra['completed_stages'].append('quantization_observation')
        self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path, required=True)
    args = parser.parse_args()
    args.project, args.evidence, args.previous_evidence = (path.resolve() for path in
        (args.project, args.evidence, args.previous_evidence))
    if (args.evidence == args.previous_evidence or args.previous_evidence in args.evidence.parents
            or args.evidence in args.previous_evidence.parents):
        raise ValueError('Compatibility needs a fresh evidence directory outside previous evidence')
    args.evidence.mkdir(parents=True, exist_ok=False)
    before = _sources()
    previous, experiment, failure, failure_trace = None, None, None, None
    try:
        previous = validate_previous(args.previous_evidence)
        shutil.copyfile(args.previous_evidence/'launch.json', args.evidence/'launch.json')
        experiment = Compatibility(args, previous)
        experiment.run()
    except Exception as error:
        failure, failure_trace = repr(error), traceback.format_exc()
    finally:
        if experiment is not None:
            experiment.save()
        unchanged = _tree(args.previous_evidence) == previous['frozen_tree'] if previous is not None else None
        source_hashes = _sources()
        if unchanged is False or source_hashes != before:
            failure = failure or 'Previous evidence or compatibility source files changed during continuation'
        status = {'failure': failure, 'failure_traceback': failure_trace,
            'links': previous['links'] if previous is not None else {},
            'previous_evidence_unchanged': unchanged, 'source_hashes_before': before,
            'source_hashes_after': source_hashes, 'sources_unchanged': source_hashes == before,
            'reports': len(experiment.reports) if experiment is not None else 0,
            'completed_stages': experiment.extra['completed_stages'] if experiment is not None else [],
            'last_state': experiment.state if experiment is not None else None,
            'frozen_reference_identity': previous['reference']['identity'] if previous is not None else None,
            'frozen_reference_active_pages': previous['reference']['active_pages'] if previous is not None else None,
            'frozen_reference_state': previous['reference'] if previous is not None else None,
            'ui_passed': experiment is not None and 'ui' in experiment.extra['completed_stages'],
            'outline_passed': experiment is not None and 'outline' in experiment.extra['completed_stages'],
            'joint_passed': experiment is not None and 'joint' in experiment.extra['completed_stages'],
            'rain_reversion_required': experiment.weather_is_raining if experiment is not None else None,
            'owned_game_left_for_parent_direction': True, 'launch_or_stop_performed': False}
        (args.evidence/'compat-status.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
        print(json.dumps({'failure': failure, 'completed_stages': status['completed_stages'],
                          'previous_evidence_unchanged': unchanged}), flush=True)
    return 1 if failure is not None else 0


if __name__ == '__main__':
    raise SystemExit(main())
