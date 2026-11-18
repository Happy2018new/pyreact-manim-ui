"""Read-only audit of static alpha performance receipts; no probe imports/MC.

Checks control and aggregate-record consistency. Raw timing vectors were not
retained by the probe, so this cannot independently recompute percentiles.
"""

import argparse
import ast
import hashlib
import json
from pathlib import Path


ALLOCATED = 2097152
PAGE = 65536


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(state):
    fields = ('seed', 'generation', 'slot_count', 'loaded_bytes', 'geometry_build_serial',
              'native_attempt_serial', 'geometry_names')
    result = {key: state[key] for key in fields}
    result['pages'] = [{key: page[key] for key in ('base', 'count', 'entity', 'name', 'seed',
        'generation', 'payload_fingerprint', 'upload_serial', 'loaded', 'attempted', 'ready')}
        for page in state['pages']]
    require(result['slot_count'] == result['loaded_bytes'] == ALLOCATED and len(result['pages']) == 32,
            'All controls must retain a complete allocated2MiB/32-page dataset')
    require(result['geometry_build_serial'] == result['native_attempt_serial'] == 32,
            'Native/build serial changed from the completed32-page prefix')
    for number, page in enumerate(result['pages']):
        require(page['base'] == number*PAGE and page['count'] == PAGE and page['upload_serial'] == number+1,
                'Page range or upload identity changed')
        require(page['loaded'] and page['attempted'] and page['ready'], 'Page readiness/residency incomplete')
    return result


def verify_controls(record, pages):
    state, controls = record['probe'], record['controls']
    active = pages*PAGE
    require(controls['allocated_bytes'] == ALLOCATED and controls['active_pages'] == pages and
            controls['active_prefix_bytes'] == active, 'Active/allocated control lengths disagree')
    require(controls['diagnostic_enabled'] is False and controls['pipeline_enabled'] is (pages > 0) and
            controls['baseline_has_resident_allocations_and32anchors'] is True,
            'Diagnostic/baseline contract differs from the declared test')
    visibility = controls['native_visibility']
    require(len(visibility) == 32, 'Need one accepted native visibility call for each page')
    for number, item in enumerate(visibility):
        require(item == {'page': number, 'name': state['pages'][number]['name'],
                         'visible': number < pages, 'accepted': True}, 'Native page visibility was rejected or differs')
    require(state['writer_visible'] is (pages > 0) and state['geometry_visible'] is (pages > 0) and
            state['pipeline_enabled'] is (pages > 0), 'Snapshot render controls disagree with accepted native calls')
    require(state['query'] == [0, active, 3, 37] and state['layout'] == [active, 2048, 8, 32],
            'Static test must use non-gather mode3 and the declared active prefix')
    require(state['measurement_running'] is False, 'Controls were changed during an active measurement')


def audit(directory):
    directory = directory.resolve()
    summary_path = directory/'static_perf.summary.json'
    summary = read(summary_path)
    require(summary['schema'] == 'geometry_atlas_large_static_perf_v1' and summary['status'] == 'passed' and
            summary['actual_sampling'] is True and summary['continuous_uploads'] is False,
            'Need a completed actual static performance run')
    require(summary['allocated_bytes_all_cases'] == ALLOCATED and summary['allocated_pages_all_cases'] == 32 and
            summary['screen_size'] == [2560, 1440], 'Allocated capacity or native resolution changed')
    require(summary['warmup_seconds'] == 2 and summary['sample_seconds'] == 25,
            'Expected the approved2s warmup/25s sample settings')
    require([case['active_pages'] for case in summary['cases']] == [0, 16, 24, 32], 'Missing or reordered static variants')
    states = {}
    artifacts = []
    frozen = None
    forbidden_calls = {'grow', 'upload_page', 'load', 'load_payload', 'begin_dataset',
                       'DeserializeBlockPalette', 'CombineBlockPaletteToGeometry', 'AddActorBlockGeometry'}
    events = summary['events']
    for serial, event in enumerate(events, 1):
        label = event['label']
        require(label.startswith('%03d_' % serial) and event['returncode'] == 0 and event['mutation_retried'] is False,
                'Event sequence failed or replayed a mutation')
        state_path = directory/Path(event['state_file']).name
        require(state_path.stem == label+'.state', 'Event/state filename mismatch')
        record = read(state_path)
        state = record.get('probe', record)
        current = identity(state)
        if frozen is None:
            frozen = current
        require(current == frozen, 'Payload/entity/geometry/serial identity changed during performance testing')
        require(state.get('error') is None, 'Runtime error in a performance receipt')
        command = directory/'commands'/(label+'.py')
        code = command.read_text(encoding='utf-8')
        parsed = ast.parse(code)
        calls = {node.func.attr for node in ast.walk(parsed)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        require(not (calls & forbidden_calls), 'A performance command rebuilds or uploads the payload')
        states[label] = record
        artifacts.append({'label': label, 'state_sha256': sha(state_path), 'command_sha256': sha(command)})
    source_receipts = list((directory.parent/'evidence-centered').glob('*_resident_2097152_dependent_settled.state.json'))
    require(len(source_receipts) == 1 and identity(read(source_receipts[0])) == frozen,
            'Performance dataset differs from the independently verified2MiB payload')
    case_reports = []
    for case in summary['cases']:
        pages = case['active_pages']
        controls_records = [record for label, record in states.items() if label.endswith('_native_prefix_%02d' % pages)]
        starts = [record for label, record in states.items() if label.endswith('_start_%02d' % pages)]
        samples = [record for label, record in states.items() if '_sample_status_%02d' % pages in label]
        require(len(controls_records) == len(starts) == 1 and samples, 'Case omitted controls/start/poll receipts')
        controlled = controls_records[0]
        verify_controls(controlled, pages)
        require(case['controls'] == controlled['controls'], 'Summary native controls differ from case receipt')
        require(starts[0]['measurement_running'] is True and starts[0]['last_measurement'] is None,
                'Measurement start did not reset the previous result')
        for state in starts+samples:
            require(state['writer_visible'] is (pages > 0) and state['geometry_visible'] is (pages > 0) and
                    state['pipeline_enabled'] is (pages > 0) and state['query'] == [0, pages*PAGE, 3, 37],
                    'Render/query controls changed during measurement')
        require(samples[-1]['measurement_running'] is False, 'Case never completed sampling')
        measurement = samples[-1]['last_measurement']
        require(case['measurement'] == measurement, 'Summary statistics differ from the final case receipt')
        require(measurement['warmup_seconds'] == 2 and 25 <= measurement['sample_seconds'] < 25.1 and
                abs(measurement['elapsed']-measurement['sample_seconds']-2) < 1e-7,
                'Warmup/sample timing is incomplete or inconsistent')
        require(measurement['query'] == [0, pages*PAGE, 3, 37] and measurement['slot_count'] == ALLOCATED and
                measurement['generation'] == frozen['generation'] and measurement['gpu_completion_fence'] is False,
                'Measurement refers to different controls/capacity/generation')
        interval, fps = measurement['interval_ms'], measurement['fps']
        require(measurement['frames'] == interval['count'] == 1501 and fps['count'] == 100 and
                fps['count'] == measurement['frames']//15, 'Render interval/engine sample counts disagree')
        require(interval['min'] <= interval['mean'] <= interval['max'] and
                interval['min'] <= interval['p95'] <= interval['p99'] <= interval['max'] and
                fps['min'] <= fps['mean'] <= fps['max'] and fps['min'] <= fps['p95'] <= fps['max'],
                'Aggregate statistics violate ordering bounds')
        require(all(interval[key] == 0 for key in ('over_25_ms', 'over_33_3_ms', 'over_50_ms')) and
                interval['max'] < 25, 'Tail count/max statistics are inconsistent')
        require(abs(interval['mean']*interval['count']/1000-measurement['sample_seconds']) < interval['max']/1000,
                'Summed render intervals disagree with the sample window beyond its boundary interval')
        case_reports.append({'active_pages': pages, 'active_prefix_bytes': pages*PAGE,
            'allocated_bytes': ALLOCATED, 'anchors_retained': 32,
            'native_visibility_calls_accepted': 32, 'pipeline_enabled': pages > 0, 'query_mode': 3,
            'warmup_seconds': measurement['warmup_seconds'], 'sample_seconds': measurement['sample_seconds'],
            'engine_fps_samples': fps['count'], 'render_intervals': interval['count'],
            'engine_fps_mean': fps['mean'], 'interval_mean_ms': interval['mean'],
            'interval_p99_ms': interval['p99'], 'interval_max_ms': interval['max'], 'over_25_ms': interval['over_25_ms'],
            'aggregate_statistics_equal_case_receipt': True,
            'rough_fps_from_interval_mean': 1000/interval['mean']})
    final_records = [record for label, record in states.items() if label.endswith('_quiesce')]
    require(len(final_records) == 1 and summary['final'] == final_records[0], 'Final summary/quiesce receipt differs')
    verify_controls(final_records[0], 0)
    prefix = directory.parent/directory.name
    environmental = {name: prefix.with_name(prefix.name+'.'+name+'.json')
                     for name in ('preflight', 'fps-cap', 'process-exit', 'stop-confirmed')}
    documents = {name: read(path) for name, path in environmental.items()}
    cap = documents['fps-cap']
    require(cap['gfx_max_framerate'] == 60 and cap['read_only_check'] is True,
            'Global60FPS cap evidence is missing')
    preflight = documents['preflight']
    active = [item for item in preflight['processes'] if item.get('ThreadCount', 0) > 0]
    require(len(active) == 1 and active[0]['ProcessId'] == preflight['active_game_pid'],
            'Preflight has another threaded research game')
    inert = [item for item in preflight['processes'] if item['ProcessId'] != preflight['active_game_pid']]
    for item in inert:
        require(all(item.get(key, 0) == 0 for key in
                    ('ThreadCount', 'HandleCount', 'VirtualSize', 'KernelModeTime', 'UserModeTime')),
                'A supposedly inert process retains execution/resources')
    stopped = documents['process-exit']
    require(stopped['owned_pid'] == preflight['active_game_pid'] and stopped['owned_process_absent'] is True and
            stopped['normal_stop_requested'] is True and stopped['force_used'] is False and
            documents['stop-confirmed']['state'] == 'stopped', 'Owned process/manager exit evidence is incomplete')
    return {'schema': 'independent_static_alpha_perf_audit_v1', 'passed': True,
            'summary': str(summary_path), 'summary_sha256': sha(summary_path),
            'frozen_payload_identity_sha256': hashlib.sha256(json.dumps(frozen, sort_keys=True).encode('utf-8')).hexdigest(),
            'capacity_source_receipt': str(source_receipts[0]), 'capacity_source_receipt_sha256': sha(source_receipts[0]),
            'case_receipts_and_commands_checked': len(artifacts), 'case_results': case_reports,
            'all_states_keep_identical2MiB_and32pages': True, 'continuous_uploads': False,
            'baseline_is_unallocated_fresh_game': False, 'baseline_retains_allocated_bytes': ALLOCATED,
            'baseline_retains_anchors': 32, 'final_quiesce_passed': True, 'fps_cap': 60,
            'raw_fps_and_interval_vectors_retained': False, 'percentiles_independently_recomputed': False,
            'aggregate_consistency_checked': True, 'gpu_timing_or_zero_cost_proven': False,
            'conclusion': 'No observable sustained frame-rate loss under60FPS cap for these static controls; not zero GPU cost',
            'environment': {'active_game_pid': preflight['active_game_pid'],
                            'other_threaded_games_at_preflight': 0, 'inert_process_records': len(inert),
                            'normal_exit_and_manager_stopped': True},
            'environmental_artifacts': [{'kind': name, 'path': str(path), 'sha256': sha(path)}
                                        for name, path in environmental.items()],
            'artifact_hashes': artifacts, 'probe_code_imported': False, 'MC_accessed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), 'Preserve prior audit results')
    try:
        result = audit(args.directory)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {'schema': 'independent_static_alpha_perf_audit_v1', 'passed': False,
                  'error': '%s: %s' % (type(error).__name__, error), 'MC_accessed': False}
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
        return 1
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'cases': len(result['case_results']),
                     'state_receipts': result['case_receipts_and_commands_checked'],
                     'output': str(args.output.resolve())}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
