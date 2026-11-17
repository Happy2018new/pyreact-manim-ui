"""Summarize immutable *.updates.json receipts as compact JSON and/or CSV.

This reads recorded measurements; it does not replay pixels or contact a game.
CPU native time is deserialize + combine + attach for each individual upload.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys


SCHEMA = 'geometry_atlas_updates_case_v1'
NATIVE_STAGES = ('deserialize_ms', 'combine_ms', 'attach_ms')
CPU_STAGES = ('generation', 'encode', 'native', 'total')
QUANTILES = ('mean', 'p95', 'p99', 'max')
SEMANTICS = {
    'source': 'Recorded receipts only; source artifacts and pixels are not independently reverified.',
    'render_event_hz': '1000 / warmup-excluded render interval mean; not frames / elapsed.',
    'get_fps': 'Recorded GetFps samples, separate from render-event frequency.',
    'cpu_native': 'Per-upload deserialize_ms + combine_ms + attach_ms, then distribution statistics.',
    'cpu_quantiles': 'Sorted samples at floor((n-1)*q); no sum of stage percentiles.',
    'initial_cpu': 'One initial_snapshot preparation/submission reference; reused datasets may predate this case.',
    'cpu_is_gpu_latency': False,
    'actual_update_hz': 'Runtime effective upload/publish counts divided by full measurement elapsed time.',
    'sustained_dynamic': 'Successful full-duration scheduler run without truncation or budget stop; pixel correctness is separate.',
    'pixel_scope': 'Frozen final generation only; does not establish every generation or every render frame.',
    'thresholds': 'Interval counts use strict >33.3 ms and >50 ms.',
}


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def obj(value):
    return value if isinstance(value, dict) else {}


def statistics(values):
    ordered = sorted(values)
    if not ordered:
        return {key: None for key in QUANTILES}
    return {'mean': sum(ordered) / len(ordered), 'p95': ordered[int((len(ordered) - 1) * .95)],
            'p99': ordered[int((len(ordered) - 1) * .99)], 'max': ordered[-1]}


def cpu_values(timings):
    timings = obj(timings)
    native = [number(timings.get(key)) for key in NATIVE_STAGES]
    return {'generation': number(timings.get('generation_ms')),
            'encode': number(timings.get('encode_ms', timings.get('palette_ms'))),
            'native': sum(native) if all(value is not None for value in native) else None,
            'total': number(timings.get('total_ms'))}


def dynamic_cpu(performance):
    uploads = performance.get('uploads')
    if uploads is None:
        return [], None
    if not isinstance(uploads, list):
        raise ValueError('performance.uploads must be a list')
    records = [cpu_values(obj(upload).get('timings')) for upload in uploads]
    if any(any(value is None for value in record.values()) for record in records):
        raise ValueError('Each measured upload needs finite generation/encode/native/total CPU timings')
    return records, 'performance.uploads'


def sustained_qualification(case, performance):
    requirements = (
        ('dynamic_case', case.get('static') is False),
        ('measurement_success', performance.get('success') is True),
        ('duration_completed', performance.get('duration_completed') is True),
        ('not_truncated', performance.get('truncated') is False),
        ('not_budget_limited', performance.get('budget_limited') is False),
        ('duration_end_reason', performance.get('end_reason') == 'duration'),
    )
    reasons = [name for name, satisfied in requirements if not satisfied]
    return not reasons, reasons


def summarize_case(case, source, digest):
    if not isinstance(case, dict) or case.get('schema') != SCHEMA:
        raise ValueError('Expected source schema ' + SCHEMA)
    if type(case.get('static')) is not bool:
        raise ValueError('Case must explicitly identify static or dynamic measurement')
    performance = obj(case.get('performance'))
    identity = obj(obj(obj(case.get('controls')).get('final_identity')).get('verification'))
    dependent = obj(obj(obj(case.get('controls')).get('final_dependent')).get('verification'))
    full = (identity.get('full_query_coverage') is True and identity.get('full_source_coverage') is True and
            dependent.get('full_query_coverage') is True)
    sampled = not full and any(number(item.get('checked_cells')) for item in (identity, dependent))
    pixels = identity.get('passed') is True and dependent.get('passed') is True
    fps, intervals = obj(performance.get('fps')), obj(performance.get('interval_ms'))
    interval_mean = number(intervals.get('mean'))
    eligible, reasons = sustained_qualification(case, performance)
    static = case['static']
    row = dict(name=case.get('name'), source=str(source), source_sha256=digest,
               case_status=case.get('status'), case_passed=case.get('passed') is True,
               mode='static' if static else 'dynamic', policy=case.get('policy'),
               payload_bytes=number(case.get('payload_bytes')),
               verification_scope='full' if full else ('sampled' if sampled else 'none'),
               final_generation_pixel_passed=pixels,
               complete_payload_verified=case.get('complete_payload_verified') is True and full and pixels,
               identity_checked_cells=number(identity.get('checked_cells')),
               identity_source_indices=number(identity.get('source_index_coverage')),
               dependent_checked_cells=number(dependent.get('checked_cells')),
               dependent_source_indices=number(dependent.get('source_index_coverage')),
               every_generation_pixel_verified=False, all_render_frames_verified=False,
               requested_seconds=number(case.get('requested_seconds')),
               requested_interval_ms=number(case.get('requested_interval_ms')) if not static else None,
               publish_delay_ms=number(case.get('publish_delay_ms')),
               elapsed_seconds=number(performance.get('elapsed')), frames=number(performance.get('frames')),
               measurement_success=performance.get('success') if not static else None,
               duration_completed=performance.get('duration_completed') if not static else None,
               sustained_dynamic=eligible, sustained_exclusion_reasons=reasons,
               truncated=performance.get('truncated') if not static else None,
               budget_limited=performance.get('budget_limited') if not static else None,
               end_reason=performance.get('end_reason') if not static else None,
               get_fps_sample_count=number(fps.get('count')), get_fps_mean=number(fps.get('mean')),
               get_fps_min=number(fps.get('min')), get_fps_max=number(fps.get('max')),
               render_interval_count=number(intervals.get('count')),
               render_event_hz=1000. / interval_mean if interval_mean is not None and interval_mean > 0 else None,
               render_interval_mean_ms=interval_mean,
               render_interval_p95_ms=number(intervals.get('p95')),
               render_interval_p99_ms=number(intervals.get('p99')),
               render_interval_max_ms=number(intervals.get('max')),
               render_intervals_over_33_3_ms=number(intervals.get('over_33_3_ms')),
               render_intervals_over_50_ms=number(intervals.get('over_50_ms')),
               uploads=number(performance.get('updates')) if not static else None,
               publishes=number(performance.get('published')) if not static else None,
               actual_upload_hz=number(performance.get('effective_upload_hz')) if not static else None,
               actual_publish_hz=number(performance.get('effective_publish_hz')) if not static else None,
               upload_interval_mean_ms=number(obj(performance.get('upload_interval_ms')).get('mean')) if not static else None,
               publish_interval_mean_ms=number(obj(performance.get('publish_interval_ms')).get('mean')) if not static else None,
               skipped_updates=number(performance.get('skipped_updates')) if not static else None,
               overruns=number(performance.get('overruns')) if not static else None,
               pending_skips=number(performance.get('pending_skips')) if not static else None,
               measurement_error=performance.get('error'), case_errors=case.get('errors', []),
               initial_upload_reused=case.get('reuse_dataset') is True, summary_error=None)
    initial = cpu_values(obj(case.get('initial_snapshot')).get('timings'))
    records, timing_source = ([], None) if static else dynamic_cpu(performance)
    row.update(cpu_upload_samples=len(records), cpu_timing_source=timing_source)
    for stage in CPU_STAGES:
        row['initial_cpu_' + stage + '_ms'] = initial[stage]
        stats = statistics([record[stage] for record in records])
        for key in QUANTILES:
            row['cpu_' + stage + '_' + key + '_ms'] = stats[key]
    return row


def summarize(evidence):
    evidence = evidence.resolve()
    paths = sorted(evidence.rglob('*.updates.json'))
    if not paths:
        raise ValueError('No *.updates.json source receipts found')
    rows = []
    for path in paths:
        raw, digest = None, None
        try:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            case = json.loads(raw.decode('utf-8-sig'))
            row = summarize_case(case, path.relative_to(evidence).as_posix(), digest)
            # Raw error fields also need validation: json.loads accepts NaN.
            json.dumps(row, allow_nan=False)
            rows.append(row)
        except (OSError, ValueError, TypeError) as error:
            rows.append({'name': path.name[:-len('.updates.json')],
                         'source': path.relative_to(evidence).as_posix(), 'source_sha256': digest,
                         'summary_error': '%s: %s' % (type(error).__name__, error),
                         'sustained_dynamic': False, 'every_generation_pixel_verified': False,
                         'all_render_frames_verified': False})
    return {'schema': 'geometry_atlas_update_summary_v1', 'evidence': str(evidence),
            'case_count': len(rows), 'summary_errors': sum(row.get('summary_error') is not None for row in rows),
            'semantics': SEMANTICS, 'cases': rows}


def csv_value(value):
    if value is None:
        return ''
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')) if isinstance(value, (list, dict, bool)) else value


def write_outputs(report, json_path=None, csv_path=None):
    paths = [path.resolve() for path in (json_path, csv_path) if path is not None]
    if len(set(paths)) != len(paths):
        raise ValueError('JSON and CSV outputs must use different paths')
    if any(path.exists() or path.name.lower().endswith('.updates.json') for path in paths):
        raise ValueError('Preserve existing evidence; use new output paths without the .updates.json suffix')
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    if json_path is not None:
        with json_path.open('x', encoding='utf-8') as output:
            output.write(serialized + '\n')
    if csv_path is not None:
        fields = list(dict.fromkeys(key for row in report['cases'] for key in row))
        with csv_path.open('x', encoding='utf-8', newline='') as output:
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            writer.writerows({key: csv_value(value) for key, value in row.items()} for row in report['cases'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--json', type=Path, dest='json_path')
    parser.add_argument('--csv', type=Path, dest='csv_path')
    args = parser.parse_args(argv)
    try:
        report = summarize(args.evidence)
        write_outputs(report, args.json_path, args.csv_path)
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    if args.json_path is None and args.csv_path is None:
        json.dump(report, sys.stdout, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        print()
    else:
        print(json.dumps({'case_count': report['case_count'], 'summary_errors': report['summary_errors'],
                          'json': str(args.json_path) if args.json_path else None,
                          'csv': str(args.csv_path) if args.csv_path else None}))
    return 1 if report['summary_errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
