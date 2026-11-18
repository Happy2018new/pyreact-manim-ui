"""Same-instance512KiB rain timing after the complete primary correctness suite."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import zlib

from runner import Experiment, HERE, LAYOUTS
from verify import payload_bytes


SIZE = 524288
MIN_AVAILABLE_COMMIT = 4 * 1024 ** 3


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _sources():
    return {path.name: _sha(path.read_bytes())
            for path in HERE.iterdir() if path.is_file()}


def validate_previous(directory):
    """Read-only gate; a partial or failed primary suite cannot start this run."""
    directory = directory.resolve()
    results_path = directory / 'results.json'
    status_path = directory / 'continuation-status.json'
    if not status_path.is_file():
        status_path = directory / 'final-host-status.json'
    launch_path = directory / 'launch.json'
    results_bytes, status_bytes = results_path.read_bytes(), status_path.read_bytes()
    launch_bytes = launch_path.read_bytes()
    launch = json.loads(launch_bytes)
    if launch.get('fps') != 60 or launch.get('agent_activation_allowed') is not False:
        raise RuntimeError('Primary launch must retain60FPS and disallow agent activation')
    results, status = json.loads(results_bytes), json.loads(status_bytes)
    if ('failure' not in status or status['failure'] is not None
            or status.get('rain_reversion_required') is not False):
        raise RuntimeError('Primary suite must be complete, successful and returned to clear weather')
    reports = results['reports']
    if any(report.get('expected_asserted') and report.get('exact') is not True
           for report in reports):
        raise RuntimeError('Primary results contain a failed asserted pixel gate')
    selected = [report for report in reports if report['logical_bytes'] == SIZE]
    by_label = {report['label']: report for report in selected}
    required = ['n524288_%s_t%d_m%d' % (weather, slot, mode)
                for weather in ('clear', 'wet') for slot in (0, 1) for mode in (1, 2, 3)]
    required += ['n524288_return_positive', 'n524288_clear_return']
    required += ['n524288_posttiming_m%d' % mode for mode in (1, 2, 3)]
    for label in required:
        report = by_label.get(label)
        if report is None or report.get('exact') is not True or report.get('expected_asserted') is not True:
            raise RuntimeError('Missing successful primary512KiB gate: ' + label)
    negative = by_label.get('n524288_hidden_negative', {})
    if negative.get('negative_rejected') is not True:
        raise RuntimeError('Primary512KiB hidden geometry negative did not reject')
    for slot in (0, 1):
        report = by_label['n524288_wet_t%d_m3' % slot]
        if not report.get('raining') or report.get('alpha_not255_pixels', 0) < 1:
            raise RuntimeError('Primary wet source lacks a same-fetch non255alpha witness')
    last = selected[-1]
    output_origin = last.get('output_origin')
    if (not isinstance(output_origin, list) or len(output_origin) != 2
            or output_origin[0] != 0 or output_origin[1] not in (64, 128)):
        raise RuntimeError('Primary diagnostic output origin must be explicit and supported')
    output_y = output_origin[1]
    identity, active_pages = last['state']['identity'], last['state']['active_pages']
    payload = payload_bytes(SIZE)
    digest, checksum = _sha(payload), zlib.adler32(payload) & 0xffffffff
    if (identity['byte_count'] != SIZE or identity['host_sha256'] != digest
            or identity['adler32'] != checksum):
        raise RuntimeError('Primary512KiB input is not the agreed actual host byte array')
    for report in selected:
        if (report['state']['identity'] != identity
                or report['state']['active_pages'] != active_pages):
            raise RuntimeError('Primary512KiB reports do not share frozen input and resident pages')
        if report.get('exact') is True and report.get('output_origin') != output_origin:
            raise RuntimeError('Primary512KiB exact frames do not share one diagnostic output origin')
    measurements = [item for item in results['measurements'] if item['logical_bytes'] == SIZE]
    for mode in ('baseline', 'restore', 'dependent'):
        candidates = [item for item in measurements if item['mode'] == mode]
        if len(candidates) != 1:
            raise RuntimeError('Expected one completed primary512KiB timer for ' + mode)
        item = candidates[0]
        if (item.get('identity') != identity or item.get('requested_seconds') != 25.
                or item.get('warm_seconds') != 2. or item.get('elapsed_seconds', 0.) < 27.
                or item.get('sample_limit_reached') is not False
                or len(item.get('interval_ms', [])) < 1
                or len(item.get('fps_observations', [])) < 1
                or item['frame_interval_statistics']['count'] != len(item['interval_ms'])):
            raise RuntimeError('Primary512KiB timer is incomplete or has different input: ' + mode)
    loads = [item for item in results['loads'] if item['logical_bytes'] == SIZE]
    if len(loads) != 1 or loads[0]['input_sha256'] != digest or loads[0]['input_adler32'] != checksum:
        raise RuntimeError('Expected one frozen primary512KiB load receipt')
    input_path = Path(loads[0]['input_file'])
    input_data = input_path.read_bytes()
    if input_data != payload:
        raise RuntimeError('Primary input evidence differs from the agreed actual host bytes')
    final_state = status.get('last_state', {})
    if (final_state.get('identity') != identity or final_state.get('active_pages') != active_pages
            or final_state.get('measurement') is not None or final_state.get('error') is not None):
        raise RuntimeError('Primary final status is inconsistent or still measuring')
    return {'results': results, 'last_report': last, 'load': loads[0], 'payload': payload,
            'output_y': output_y,
            'links': {'previous_results_file': str(results_path),
                      'previous_results_sha256': _sha(results_bytes),
                      'previous_status_file': str(status_path),
                      'previous_status_sha256': _sha(status_bytes),
                      'previous_launch_file': str(launch_path),
                      'previous_launch_sha256': _sha(launch_bytes),
                      'previous_input_file': str(input_path.resolve()),
                      'previous_input_sha256': _sha(input_data)},
            'frozen_files': [(results_path, results_bytes), (status_path, status_bytes),
                             (launch_path, launch_bytes), (input_path, input_data)]}


def _resident_gate(state, reference):
    keys = ('identity', 'active_pages', 'native_page_names', 'native_attempt_count',
            'native_records_reserved', 'actor_count', 'effects')
    if (state.get('state') != 'resident' or state.get('ready') is not True
            or state.get('measurement') is not None or state.get('error') is not None
            or state.get('viewport') != LAYOUTS[SIZE][0]
            or state.get('source_roi') != LAYOUTS[SIZE][1]
            or any(state.get(key) != reference.get(key) for key in keys)):
        raise RuntimeError('Frozen512KiB resident input/allocation identity changed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path, required=True)
    args = parser.parse_args()
    args.evidence = args.evidence.resolve()
    if args.evidence == args.previous_evidence.resolve():
        raise ValueError('Rain continuation needs a fresh evidence directory')
    args.evidence.mkdir(parents=True, exist_ok=False)
    experiment, previous, failure = None, None, None
    source_hashes_before = _sources()
    links, verified_measurements = {}, []
    try:
        previous = validate_previous(args.previous_evidence)
        links = previous['links']
        shutil.copyfile(args.previous_evidence / 'launch.json', args.evidence / 'launch.json')
        experiment = Experiment(args)
        experiment.payload = previous['payload']
        experiment.viewport, experiment.roi = copy.deepcopy(LAYOUTS[SIZE])
        experiment.output_y = previous['output_y']
        experiment.loads.append(copy.deepcopy(previous['load']))
        (args.evidence / 'n524288_actual_input.bin').write_bytes(experiment.payload)
        state = experiment.call('same_instance_initial')
        reference = previous['last_report']['state']
        _resident_gate(state, reference)
        # After primary cleanup, this native build no longer accepts parameter
        # changes or re-enable on that custom process. Re-register the same
        # public two-pass definition once, outside both warmup and sampling.
        experiment.call('reregister_same_oracle',
                        'probe.oracle_installed=False\nprobe.install_oracle()\nprobe.inspect(0,0,True)')
        preflight = experiment.memory('n524288_rain_timing_preflight', True)
        if (preflight['preflight_passed'] is not True
                or preflight['system_commit_available_bytes'] < MIN_AVAILABLE_COMMIT):
            raise RuntimeError('Rain continuation requires at least4GiB available system commit')
        experiment.weather('n524288_timing_rain_on', True)
        for mode in ('baseline', 'restore'):
            experiment.memory('n524288_rain_' + mode + '_preflight', True)
            experiment.measure('n524288_rain', mode)
            item = experiment.measurements[-1]
            if (item['identity'] != reference['identity']
                    or item['resident_pages'] != reference['native_page_names']
                    or item['native_attempt_count'] != reference['native_attempt_count']):
                raise RuntimeError('Rain timer did not retain the same input and native allocations')
            _resident_gate(experiment.call('n524288_rain_' + mode + '_resident_check'), reference)
            verified_measurements.append(mode)
        for slot in (0, 1):
            report = experiment.capture('n524288_rain_timing_t%d_m3' % slot, 3, slot)
            if report['alpha_not255_pixels'] < 1:
                raise RuntimeError('Rain timing source lacks actual same-fetch non255alpha at T%d' % slot)
            _resident_gate(experiment.state, reference)
        experiment.capture('n524288_rain_timing_identity', 1)
        experiment.weather('n524288_timing_rain_off', False)
        for slot in (0, 1):
            for mode in (1, 3):
                experiment.capture('n524288_rain_timing_clear_t%d_m%d' % (slot, mode), mode, slot)
                _resident_gate(experiment.state, reference)
        experiment.call('final_hidden', "probe.configure('off')\nprobe.inspect(0,0,False)")
        _resident_gate(experiment.state, reference)
    except Exception as error:
        failure = repr(error)
        raise
    finally:
        if experiment is not None:
            experiment.save()
        (args.evidence / 'rain-measurement-vectors.json').write_text(json.dumps({
            'measurements': experiment.measurements if experiment is not None else [],
            'same_allocations_required': True,
            'same_allocations_baseline_and_restore_verified': verified_measurements == ['baseline', 'restore'],
            'warm_seconds': 2., 'requested_seconds': 25.,
            'diagnostic_output_y': previous['output_y'] if previous is not None else None,
            'weather': 'rain', 'fps_cap': 60, 'fps_cap_is_performance_proof': False,
        }, indent=2), encoding='utf-8')
        unchanged = (all(path.read_bytes() == data for path, data in previous['frozen_files'])
                     if previous is not None else None)
        (args.evidence / 'rain-timing-status.json').write_text(json.dumps({
            'reason': 'Same-instance512KiB natural rain baseline and restoration timing after the complete primary suite',
            **links, 'previous_results_and_status_unchanged': unchanged,
            'failure': failure, 'reports': len(experiment.reports) if experiment is not None else 0,
            'rain_reversion_required': experiment.weather_is_raining if experiment is not None else False,
            'last_state': experiment.state if experiment is not None else None,
            'source_hashes_before': source_hashes_before, 'source_hashes': _sources(),
            'normal_game_cleanup_deferred_to_owner': True,
        }, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
