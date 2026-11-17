"""Statistics and scope safeguards for receipt-only atlas update summaries."""
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('atlas_update_summary',
    ROOT / 'tools/geometry_atlas_probe/summarize_updates.py')
SUMMARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUMMARY)


def fixture(static=False, sampled=False):
    uploads = []
    # Native total is always 11 ms; sums of separate stage p95/max are 18/20 ms.
    for first, second in zip((1., 2., 9., 10.), (10., 9., 2., 1.)):
        uploads.append({'timings': dict(generation_ms=3., encode_ms=4., palette_ms=4.,
                        deserialize_ms=first, combine_ms=second, attach_ms=0., total_ms=18.)})
    performance = dict(elapsed=8., frames=480, fps=dict(count=28, mean=60., min=59., max=61.),
                       interval_ms=dict(count=350, mean=20., p95=30., p99=40., max=60.,
                                        over_33_3_ms=3, over_50_ms=1))
    if not static:
        performance.update(success=True, duration_completed=True, truncated=False, budget_limited=False,
                           end_reason='duration', updates=4, published=4, skipped_updates=2, overruns=2,
                           pending_skips=0, effective_upload_hz=.5, effective_publish_hz=.5,
                           uploads=uploads, every_generation_pixel_verified=False,
                           upload_interval_ms={'mean': 2000.}, publish_interval_ms={'mean': 2000.})
    verification = dict(passed=True, full_query_coverage=not sampled, full_source_coverage=not sampled,
                        checked_cells=12288 if sampled else 16384,
                        source_index_coverage=12288 if sampled else 16384)
    dependent = dict(verification, full_source_coverage=False, source_index_coverage=10000)
    return dict(schema=SUMMARY.SCHEMA, name='case', status='completed', passed=True, static=static,
                payload_bytes=16384, policy='double', publish_delay_ms=0., requested_seconds=8.,
                requested_interval_ms=100., reuse_dataset=False, errors=[],
                complete_payload_verified=not sampled, performance=performance,
                initial_snapshot={'timings': dict(generation_ms=10., encode_ms=20., palette_ms=20.,
                                                 deserialize_ms=1., combine_ms=2., attach_ms=3., total_ms=36.)},
                controls={'final_identity': {'verification': verification},
                          'final_dependent': {'verification': dependent}})


class AtlasUpdateSummaryTests(unittest.TestCase):
    def row(self, case):
        return SUMMARY.summarize_case(case, 'case.updates.json', 'source-digest')

    def test_native_distribution_sums_each_upload_before_percentiles_and_keeps_fps_separate(self):
        row = self.row(fixture())
        self.assertEqual(11., row['cpu_native_mean_ms'])
        self.assertEqual(11., row['cpu_native_p95_ms'])
        self.assertEqual(11., row['cpu_native_p99_ms'])
        self.assertEqual(11., row['cpu_native_max_ms'])
        self.assertEqual(4., row['cpu_encode_mean_ms'])
        self.assertEqual(60., row['get_fps_mean'])
        self.assertEqual(50., row['render_event_hz'])
        self.assertEqual(3, row['render_intervals_over_33_3_ms'])
        self.assertEqual(1, row['render_intervals_over_50_ms'])
        self.assertEqual(.5, row['actual_publish_hz'])
        self.assertTrue(row['sustained_dynamic'])

    def test_sustained_requires_every_explicit_scheduler_condition(self):
        for key, value in (('success', False), ('duration_completed', False), ('truncated', True),
                           ('budget_limited', True), ('end_reason', 'max_updates'), ('end_reason', 'budget')):
            with self.subTest(key=key, value=value):
                case = fixture()
                case['performance'][key] = value
                row = self.row(case)
                self.assertFalse(row['sustained_dynamic'])
                self.assertTrue(row['sustained_exclusion_reasons'])
                self.assertTrue(row['final_generation_pixel_passed'])
        for key in ('success', 'duration_completed', 'truncated', 'budget_limited', 'end_reason'):
            with self.subTest(missing=key):
                case = fixture()
                del case['performance'][key]
                self.assertFalse(self.row(case)['sustained_dynamic'])

    def test_final_pixels_full_capacity_and_sustained_schedule_remain_distinct(self):
        case = fixture(sampled=True)
        row = self.row(case)
        self.assertEqual('sampled', row['verification_scope'])
        self.assertTrue(row['final_generation_pixel_passed'])
        self.assertFalse(row['complete_payload_verified'])
        self.assertTrue(row['sustained_dynamic'])
        self.assertFalse(row['every_generation_pixel_verified'])
        case['passed'] = False
        case['controls']['final_identity']['verification']['passed'] = False
        row = self.row(case)
        self.assertFalse(row['final_generation_pixel_passed'])
        self.assertTrue(row['sustained_dynamic'])
        self.assertFalse(row['all_render_frames_verified'])

    def test_static_single_initial_reference_is_not_a_dynamic_distribution(self):
        case = fixture(static=True)
        row = self.row(case)
        self.assertEqual('static', row['mode'])
        self.assertIsNone(row['measurement_success'])
        self.assertIsNone(row['duration_completed'])
        self.assertIsNone(row['end_reason'])
        self.assertIsNone(row['truncated'])
        self.assertIsNone(row['uploads'])
        self.assertIsNone(row['actual_publish_hz'])
        self.assertEqual(6., row['initial_cpu_native_ms'])
        self.assertEqual(20., row['initial_cpu_encode_ms'])
        self.assertIsNone(row['cpu_native_mean_ms'])
        self.assertEqual(0, row['cpu_upload_samples'])
        self.assertFalse(row['sustained_dynamic'])
        self.assertFalse(SUMMARY.SEMANTICS['cpu_is_gpu_latency'])

    def test_failed_operational_case_and_empty_samples_produce_missing_values_without_guessed_rates(self):
        case = fixture()
        case.update(status='failed', passed=False, performance=None, controls={}, initial_snapshot=None,
                    errors=[{'stage': 'open', 'error': 'transport timed out'}])
        row = self.row(case)
        self.assertEqual('none', row['verification_scope'])
        self.assertIsNone(row['render_event_hz'])
        self.assertIsNone(row['get_fps_mean'])
        self.assertIsNone(row['initial_cpu_native_ms'])
        self.assertIsNone(row['cpu_native_mean_ms'])
        self.assertFalse(row['sustained_dynamic'])
        self.assertEqual(case['errors'], row['case_errors'])

    def test_palette_alias_and_nonfinite_input_are_not_double_counted_or_emitted_as_numbers(self):
        case = fixture()
        del case['performance']['uploads'][0]['timings']['encode_ms']
        row = self.row(case)
        self.assertEqual(4., row['cpu_encode_mean_ms'])
        case['performance']['interval_ms']['mean'] = float('nan')
        self.assertIsNone(self.row(case)['render_event_hz'])
        case['performance']['uploads'][0]['timings']['attach_ms'] = float('inf')
        with self.assertRaisesRegex(ValueError, 'finite'):
            self.row(case)

    def test_json_csv_outputs_preserve_sources_and_record_malformed_raw_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / 'nested/case.updates.json'
            source.parent.mkdir()
            source.write_text(json.dumps(fixture()), encoding='utf-8')
            malformed = folder / 'broken.updates.json'
            malformed.write_bytes(b'{malformed raw')
            original = {source: source.read_bytes(), malformed: malformed.read_bytes()}
            json_path, csv_path = folder / 'summary.json', folder / 'summary.csv'
            with patch.object(sys, 'stdout', io.StringIO()):
                code = SUMMARY.main(['--evidence', str(folder), '--json', str(json_path), '--csv', str(csv_path)])
            self.assertEqual(1, code)
            report = json.loads(json_path.read_text())
            self.assertEqual(2, report['case_count'])
            self.assertEqual(1, report['summary_errors'])
            failed = next(row for row in report['cases'] if row.get('summary_error'))
            self.assertEqual(hashlib.sha256(original[malformed]).hexdigest(), failed['source_sha256'])
            self.assertFalse(failed['sustained_dynamic'])
            with csv_path.open(encoding='utf-8', newline='') as handle:
                rows = list(csv.DictReader(handle))
            valid = next(row for row in rows if row['name'] == 'case')
            self.assertEqual('50.0', valid['render_event_hz'])
            self.assertEqual('false', valid['every_generation_pixel_verified'])
            self.assertEqual('true', valid['sustained_dynamic'])
            self.assertEqual(original, {path: path.read_bytes() for path in original})

    def test_output_preflight_refuses_overwrite_aliases_and_case_suffix_before_any_write(self):
        report = {'cases': [self.row(fixture())]}
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            existing, new = folder / 'existing.csv', folder / 'new.json'
            existing.write_bytes(b'preserved')
            with self.assertRaisesRegex(ValueError, 'Preserve'):
                SUMMARY.write_outputs(report, new, existing)
            self.assertFalse(new.exists())
            self.assertEqual(b'preserved', existing.read_bytes())
            with self.assertRaisesRegex(ValueError, 'different'):
                SUMMARY.write_outputs(report, new, new)
            with self.assertRaisesRegex(ValueError, 'suffix'):
                SUMMARY.write_outputs(report, folder / 'new.updates.json')
            self.assertFalse((folder / 'new.updates.json').exists())

    def test_nonfinite_raw_error_field_becomes_a_hashed_failed_row_with_both_outputs_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / 'nan_error.updates.json'
            case = fixture()
            case['performance']['error'] = float('nan')
            raw = json.dumps(case).encode('utf-8')
            source.write_bytes(raw)
            json_path, csv_path = folder / 'summary.json', folder / 'summary.csv'
            with patch.object(sys, 'stdout', io.StringIO()):
                self.assertEqual(1, SUMMARY.main(['--evidence', str(folder), '--json', str(json_path),
                                                 '--csv', str(csv_path)]))
            report = json.loads(json_path.read_text())
            self.assertEqual(1, report['summary_errors'])
            self.assertTrue(report['cases'][0]['summary_error'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), report['cases'][0]['source_sha256'])
            self.assertEqual(raw, source.read_bytes())
            with csv_path.open(encoding='utf-8', newline='') as handle:
                self.assertEqual(1, len(list(csv.DictReader(handle))))
            with self.assertRaises(ValueError):
                SUMMARY.write_outputs({'cases': [], 'bad': float('nan')}, folder / 'never_created.json')
            self.assertFalse((folder / 'never_created.json').exists())


if __name__ == '__main__':
    unittest.main()
