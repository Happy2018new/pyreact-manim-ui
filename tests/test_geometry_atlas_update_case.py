"""Offline contracts for autonomous update measurement and frozen pixel audits."""
import copy
import ctypes
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'tools/geometry_atlas_probe'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROBE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = load('atlas_update_pixels', 'verify_capture.py')
with patch.dict(sys.modules, {'verify_capture': VERIFY}):
    CASE = load('atlas_update_base_case', 'run_case.py')
with patch.dict(sys.modules, {'verify_capture': VERIFY, 'run_case': CASE}):
    RUNNER = load('atlas_autonomous_case', 'run_update_case.py')


def arguments(folder, **kwargs):
    values = dict(project=folder / 'project', evidence=folder, name='updates', byte_count=137,
                  seed=123456789, seconds=8., interval_ms=100., max_updates=2, policy='double',
                  publish_delay_ms=150., static=False, reuse_dataset=False, full=False,
                  settle=0., channel='alpha', direct_source=False, flip_y=True)
    values.update(kwargs)
    return types.SimpleNamespace(**values)


def receipt(slots=137, generation=1):
    columns, cell = (16, 4) if slots <= 256 else ((64, 4) if slots <= 12288 else (256, 2))
    state = dict(schema='geometry_atlas_probe_v1', seed=123456789, generation=generation,
                 slot_count=slots, geometry_name='bank_%d' % ((generation - 1) % 2),
                 geometry_build_serial=generation, encoding='compact8', ready=True, error=None,
                 pipeline_ready=True, pipeline_installed=True, connection=True, epoch=1,
                 screen_size=[720, 1080], display_rect_norm=[0, 64. / 1080., 1, 1000. / 1080.],
                 layout=[slots, columns, 8, 64], dimensions=[cell, 720, 1080, 91], center=[.5, .5, .5],
                 orientation=[1, 0, 0, 0], direct_source=False, packed_mode=6,
                 query=[0, min(slots, 4096), 2, 37], writer_visible=True,
                 updates_running=False, measurement_running=False, pending_upload=None,
                 update_policy='double', publish_delay_ms=150., update_run_serial=0,
                 last_updates=None, last_measurement=None, native_hud_hidden=True)
    state['upload_history'] = [upload(state)]
    return state


def upload(state):
    return dict(seed=state['seed'], generation=state['generation'], slot_count=state['slot_count'],
                encoding=state['encoding'], name=state['geometry_name'], serial=state['geometry_build_serial'])


def render(state, generation=None):
    """Fixture computes uint32 bytes and both gather hops without verifier calls."""
    generation = state['generation'] if generation is None else generation
    wrap = lambda number: ctypes.c_uint32(number).value
    values = []
    for index in range(state['slot_count']):
        value = state['seed'] ^ wrap(generation * 0x9e3779b9) ^ wrap(index * 0x85ebca6b)
        for shift, multiplier in ((16, 0x7feb352d), (15, 0x846ca68b)):
            value = wrap((value ^ (value >> shift)) * multiplier)
        values.append((value ^ (value >> 16)) % 256)
    image = Image.new('RGBA', (720, 1080), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    start, count, mode, salt = state['query']
    rows = math.ceil(count / 64)
    for ordinal in range(count):
        index = start + ordinal
        if mode:
            index = (131 * index + salt) % len(values)
            if mode == 2:
                index = (index + 257 * values[index] + state['dimensions'][3]) % len(values)
        row, column = divmod(ordinal, 64)
        bounds = (math.ceil(column * 720 / 64 - .5), math.ceil(64 + row * 1000 / rows - .5),
                  math.ceil((column + 1) * 720 / 64 - .5) - 1,
                  math.ceil(64 + (row + 1) * 1000 / rows - .5) - 1)
        draw.rectangle(bounds, fill=(values[index],) * 3 + (255,))
    return image


class FakeProbe:
    def __init__(self, slots=137):
        self.state = receipt(slots)
        self.pending_snapshots = 0
        self.calls = []

    def snapshot(self):
        if self.state['updates_running'] or self.state['measurement_running']:
            if self.pending_snapshots:
                self.finish()
            else:
                self.pending_snapshots += 1
        return copy.deepcopy(self.state)

    def open(self):
        self.calls.append('open')

    def begin_dataset(self, encoding):
        self.calls.append('begin_dataset')
        self.state.update(generation=0, slot_count=0, geometry_name='', upload_history=[],
                          epoch=self.state['epoch'] + 1)

    def configure_updates(self, policy, publish_delay_ms):
        self.state.update(update_policy=policy, publish_delay_ms=publish_delay_ms)

    def load(self, slots, seed, generation):
        serial = self.state['geometry_build_serial'] + 1
        history = self.state['upload_history']
        options = {key: self.state[key] for key in ('epoch', 'update_policy', 'publish_delay_ms', 'update_run_serial',
                                                  'last_updates', 'last_measurement')}
        self.state = receipt(slots, generation)
        self.state.update(options, seed=seed, geometry_build_serial=serial)
        self.state['upload_history'] = history + [upload(self.state)]

    def query(self, start, count, mode, salt, salt2, flip_y, channel_mode, direct_source):
        self.state.update(query=[start, count, mode, salt], orientation=[int(flip_y), channel_mode, 0, 0],
                          direct_source=direct_source,
                          packed_mode=mode + 4 * int(flip_y) + 8 * channel_mode + 16 * int(direct_source))
        self.state['dimensions'][3] = salt2

    def start_updates(self, duration_seconds, interval_ms, max_updates):
        self.calls.append('start_updates')
        self.duration, self.interval, self.maximum = duration_seconds, interval_ms, max_updates
        self.state.update(updates_running=True, last_updates=None,
                          update_run_serial=self.state['update_run_serial'] + 1)
        self.pending_snapshots = 0

    def start_measurement(self, seconds):
        self.calls.append('start_measurement')
        self.duration = seconds
        self.state.update(measurement_running=True, last_measurement=None)
        self.pending_snapshots = 0

    def finish(self):
        metrics = dict(elapsed=self.duration + .1, frames=480,
                       fps=dict(count=28, mean=60., min=59., max=61., p95=61.),
                       interval_ms=dict(count=420, mean=16.67, min=15., max=21., p95=19., over_25_ms=0))
        if self.state['measurement_running']:
            metrics.update({key: copy.deepcopy(self.state[key]) for key in
                            ('generation', 'geometry_name', 'geometry_build_serial', 'query')})
            self.state.update(measurement_running=False, last_measurement=metrics)
            return
        records = []
        for _ in range(2):
            self.state['generation'] += 1
            self.state['geometry_build_serial'] += 1
            self.state['geometry_name'] = 'bank_%d' % ((self.state['generation'] - 1) % 2)
            records.append(upload(self.state))
        self.state['upload_history'].extend(records)
        metrics.update(success=True, error=None, status='completed', run_serial=self.state['update_run_serial'],
                       duration_seconds=self.duration, interval_ms_requested=self.interval,
                       requested_max_updates=self.maximum, duration_completed=True, end_reason='max_updates',
                       updates=2, published=2, skipped_updates=0, uploads=records,
                       budget_limited=False, timings={'combine_ms': {'count': 2, 'mean': 3., 'p95': 4., 'max': 4.}})
        metrics.update({key: copy.deepcopy(self.state[key]) for key in
                        ('seed', 'generation', 'geometry_name', 'geometry_build_serial', 'query', 'publish_delay_ms')})
        metrics.update(policy=self.state['update_policy'], salt2=self.state['dimensions'][3])
        self.state.update(updates_running=False, last_updates=metrics)


class FakeHost:
    def __init__(self, folder, probe, stale=False, malformed=False):
        self.folder, self.probe = folder, probe
        self.stale, self.malformed = stale, malformed
        self.events = []

    def __call__(self, command, **kwargs):
        action = command[5]
        label = command[command.index('--label') + 1]
        self.events.append((action, label))
        kwargs['stdout'].write('fake owner-bound host\n')
        if action == 'call':
            path = self.folder / (label + '.state.json')
            if self.malformed:
                path.write_text('{raw malformed receipt', encoding='utf-8')
                return types.SimpleNamespace(returncode=0)
            code = Path(command[command.index('--code') + 1]).read_text(encoding='utf-8')
            api = types.SimpleNamespace(GetSystem=lambda *_: self.probe, HideCrossHairGUI=lambda _: True)
            namespace = {'api': api, 'json': json}
            exec(compile(code, '<fake game callback>', 'exec'), namespace)
            path.write_text(namespace['_result'], encoding='utf-8')
        else:
            generation = self.probe.state['generation'] - 1 if self.stale else None
            render(self.probe.state, generation=generation).save(self.folder / (label + '.png'))
            (self.folder / (label + '.json')).write_text('{"native_resolution":true}', encoding='utf-8')
        return types.SimpleNamespace(returncode=0)


class GeometryAtlasUpdateCaseTests(unittest.TestCase):
    def run_case(self, folder, probe=None, **options):
        probe = probe or FakeProbe(options.get('byte_count', 137))
        host = FakeHost(folder, probe, stale=options.pop('stale', False))
        case = RUNNER.UpdateCase(arguments(folder, **options))
        with patch.object(CASE.subprocess, 'run', host), patch.object(RUNNER.time, 'sleep'), \
                patch.object(sys, 'stdout', io.StringIO()):
            code = case.run()
        return code, json.loads(case.output.read_text()), host

    def test_dynamic_run_measures_without_intermediate_ipc_then_verifies_and_rejects_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            code, report, host = self.run_case(folder)
            self.assertEqual(0, code, report['errors'])
            self.assertTrue(report['complete_payload_verified'])
            self.assertEqual(137, report['verified_payload_capacity_bytes'])
            self.assertEqual(3, report['final_snapshot']['generation'])
            self.assertEqual('max_updates', report['performance']['end_reason'])
            self.assertEqual(0, report['host_requests_between_start_and_terminal'])
            start = host.events.index(('call', 'updates_benchmark_start'))
            self.assertEqual(('call', 'updates_benchmark_end'), host.events[start + 1])
            for series in report['controls'].values():
                self.assertTrue(series['passed'])
                self.assertTrue(series['previous_generation_rejected'])
            for relative, digest in report['artifact_sha256'].items():
                self.assertEqual(hashlib.sha256((folder / relative).read_bytes()).hexdigest(), digest)
            self.assertFalse(report['all_render_frames_verified'])

    def test_dependent_stale_generation_recomputes_both_hops_at_nonzero_query_offset(self):
        state = receipt(137, 3)
        state['query'] = [17, 97, 2, 37]
        old = dict(upload(state), generation=2, serial=2, name='bank_1')
        state['upload_history'] = [old, upload(state)]
        image = render(state, generation=2)
        result = RUNNER.classify_observed(state, image, state['upload_history'])
        self.assertEqual('stale_generation', result['classification'])
        self.assertEqual([2], result['matched_generations'])
        self.assertFalse(result['final_generation_match'])
        self.assertFalse(result['offset_search_used'])
        center = VERIFY.verify_image(RUNNER.candidate_receipt(state, old), image)['centers'][0]
        pixel = image.getpixel((center[0] + 1, center[1]))
        image.putpixel((center[0] + 1, center[1]), pixel[:3] + (254,))
        result = RUNNER.classify_observed(state, image, state['upload_history'])
        self.assertEqual('unmatched', result['classification'])

    def test_failed_final_payload_is_preserved_and_classified_as_old_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            code, report, _ = self.run_case(Path(directory), stale=True)
            self.assertEqual(1, code)
            self.assertFalse(report['complete_payload_verified'])
            for series in report['controls'].values():
                self.assertFalse(series['passed'])
                window = series['windows'][0]
                self.assertEqual('stale_generation', window['classification'])
                self.assertEqual([2], window['matched_generations'])
                self.assertTrue(Path(window['classification_file']).exists())

    def test_sampled_identity_and_dependent_windows_do_not_claim_full_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            code, report, _ = self.run_case(Path(directory), byte_count=16384)
            self.assertEqual(0, code, report['errors'])
            self.assertFalse(report['complete_payload_verified'])
            self.assertIsNone(report['verified_payload_capacity_bytes'])
            self.assertTrue(report['sampled_verification_only'])
            identity = report['controls']['final_identity']['verification']
            self.assertEqual(12288, identity['query_ordinal_coverage'])
            self.assertEqual(12288, identity['source_index_coverage'])
            self.assertFalse(identity['full_query_coverage'])
            dependent = report['controls']['final_dependent']['verification']
            self.assertLess(dependent['source_index_coverage'], dependent['query_ordinal_coverage'])

    def test_static_run_uses_measurement_without_uploading_more_generations(self):
        with tempfile.TemporaryDirectory() as directory:
            probe = FakeProbe()
            code, report, _ = self.run_case(Path(directory), probe, static=True)
            self.assertEqual(0, code, report['errors'])
            self.assertEqual(report['initial_snapshot']['generation'], report['final_snapshot']['generation'])
            self.assertIn('start_measurement', probe.calls)
            self.assertNotIn('start_updates', probe.calls)

    def test_reuse_dataset_keeps_epoch_and_fixed_double_names_across_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            folder, probe = Path(directory), FakeProbe()
            code, first, _ = self.run_case(folder, probe)
            self.assertEqual(0, code)
            code, second, _ = self.run_case(folder, probe, name='updates_reuse', reuse_dataset=True)
            self.assertEqual(0, code, second['errors'])
            self.assertEqual(first['final_snapshot']['epoch'], second['final_snapshot']['epoch'])
            self.assertEqual(first['final_snapshot']['generation'], second['initial_snapshot']['generation'])
            self.assertEqual(1, probe.calls.count('begin_dataset'))
            self.assertEqual({'bank_0', 'bank_1'}, {item['name'] for item in second['submitted_source_history']})

    def test_new_static_dataset_ignores_the_prior_epochs_dynamic_result_history(self):
        with tempfile.TemporaryDirectory() as directory:
            folder, probe = Path(directory), FakeProbe()
            code, _, _ = self.run_case(folder, probe)
            self.assertEqual(0, code)
            code, report, _ = self.run_case(folder, probe, name='static_other_size', static=True, byte_count=257)
            self.assertEqual(0, code, report['errors'])
            self.assertTrue(report['complete_payload_verified'])
            self.assertEqual({257}, {item['slot_count'] for item in report['submitted_source_history']})

    def test_malformed_receipt_retains_raw_bytes_hash_and_failed_case(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            host = FakeHost(folder, FakeProbe(), malformed=True)
            case = RUNNER.UpdateCase(arguments(folder))
            with patch.object(CASE.subprocess, 'run', host), patch.object(sys, 'stdout', io.StringIO()):
                self.assertEqual(1, case.run())
            report = json.loads(case.output.read_text())
            raw = folder / 'updates_open.state.json'
            self.assertEqual(b'{raw malformed receipt', raw.read_bytes())
            self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(), report['artifact_sha256'][raw.name])
            self.assertEqual('failed', report['events'][0]['status'])
            self.assertTrue(report['errors'])

    def test_failed_host_missing_receipt_is_recorded_and_missing_capture_provenance_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            case = RUNNER.UpdateCase(arguments(folder))
            with patch.object(CASE.subprocess, 'run', side_effect=OSError('transport failed')), \
                    patch.object(sys, 'stdout', io.StringIO()):
                self.assertEqual(1, case.run())
            report = json.loads(case.output.read_text())
            self.assertEqual([{'label': 'updates_open', 'kind': 'state_file',
                               'path': 'updates_open.state.json'}], report['missing_event_artifacts'])
            self.assertIn('updates_open.call.log', report['artifact_sha256'])
            self.assertFalse(report['complete_payload_verified'])
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            case = RUNNER.UpdateCase(arguments(folder))
            host = FakeHost(folder, FakeProbe())

            def missing_provenance(command, **kwargs):
                result = host(command, **kwargs)
                if command[5] == 'capture':
                    label = command[command.index('--label') + 1]
                    (folder / (label + '.json')).unlink()
                return result

            with patch.object(CASE.subprocess, 'run', missing_provenance), patch.object(RUNNER.time, 'sleep'), \
                    patch.object(sys, 'stdout', io.StringIO()):
                self.assertEqual(1, case.run())
            report = json.loads(case.output.read_text())
            self.assertTrue(any(item['kind'] == 'capture_metadata_file' for item in report['missing_event_artifacts']))
            self.assertTrue(any(path.endswith('.png') for path in report['artifact_sha256']))
            self.assertFalse(report['complete_payload_verified'])

    def test_existing_prefix_artifacts_and_late_host_collisions_are_never_overwritten(self):
        for relative in ('updates_orphan.png', 'commands/updates_orphan.py'):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                path = folder / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'original')
                with self.assertRaisesRegex(ValueError, 'Preserve previous evidence'):
                    RUNNER.UpdateCase(arguments(folder))
                self.assertEqual(b'original', path.read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            case = RUNNER.UpdateCase(arguments(folder))
            path = folder / 'updates_late.call.log'
            path.write_bytes(b'original')
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                case.call('late', '')
            self.assertEqual(b'original', path.read_bytes())

    def test_running_or_pending_state_cannot_be_declared_frozen(self):
        for mutation in ({'updates_running': True}, {'measurement_running': True}, {'pending_upload': {}}):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                case = RUNNER.UpdateCase(arguments(Path(directory)))
                state = receipt()
                state.update(mutation)
                with self.assertRaises(ValueError):
                    case.assert_frozen(state)

    def test_history_requires_exact_final_identity_and_consistent_real_integer_metadata(self):
        for mutation in ('missing_final', 'boolean_generation', 'different_slots', 'different_encoding', 'malformed_run'):
            with self.subTest(mutation=mutation):
                state = receipt()
                if mutation == 'missing_final':
                    state['upload_history'][0]['generation'] = 2
                elif mutation == 'boolean_generation':
                    state['upload_history'][0]['generation'] = True
                elif mutation == 'different_slots':
                    state['upload_history'][0]['slot_count'] += 1
                elif mutation == 'different_encoding':
                    state['upload_history'][0]['encoding'] = 'other'
                else:
                    state['last_updates'] = ['malformed']
                with self.assertRaises(ValueError):
                    RUNNER.source_history(state)

    def test_wrong_terminal_config_or_dataset_and_nonfinite_elapsed_fail_before_capture(self):
        for mutation in ('seed', 'query', 'elapsed', 'run_serial', 'interval', 'duration', 'running'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                probe = FakeProbe()
                original = probe.finish

                def finish():
                    original()
                    if mutation == 'seed':
                        probe.state['seed'] += 1
                    elif mutation == 'query':
                        probe.state['query'][3] += 1
                    elif mutation == 'running':
                        probe.state['updates_running'] = True
                    else:
                        key, value = {'elapsed': ('elapsed', float('nan')), 'run_serial': ('run_serial', 999),
                                      'interval': ('interval_ms_requested', 500.),
                                      'duration': ('duration_completed', False)}[mutation]
                        probe.state['last_updates'][key] = value

                probe.finish = finish
                code, report, host = self.run_case(Path(directory), probe)
                self.assertEqual(1, code)
                self.assertTrue(report['errors'])
                self.assertFalse(any(action == 'capture' for action, _ in host.events))
                self.assertFalse(report['complete_payload_verified'])

    def test_fractional_requested_interval_survives_runtime_unit_rounding(self):
        with tempfile.TemporaryDirectory() as directory:
            probe = FakeProbe()
            original = probe.finish

            def finish():
                original()
                probe.state['last_updates']['interval_ms_requested'] = .12345 / 1000. * 1000.

            probe.finish = finish
            code, report, _ = self.run_case(Path(directory), probe, interval_ms=.12345)
            self.assertEqual(0, code, report['errors'])

    def test_window_plan_and_cli_validation_reject_invalid_parameters_before_host_calls(self):
        self.assertEqual([(0, 4096), (4096, 4096), (8192, 4096)], RUNNER.planned_windows(12288))
        full = RUNNER.planned_windows(16385, full=True)
        self.assertEqual(16385, sum(count for _, count in full))
        self.assertEqual((16384, 1), full[-1])
        for option in (['--name', '../bad'], ['--seconds', '1'], ['--interval-ms', 'nan'],
                       ['--publish-delay-ms', 'inf'], ['--max-updates', '0'],
                       ['--bytes', str(VERIFY.MAX_SLOTS + 1)], ['--seed', '-1']):
            with self.subTest(option=option), patch.object(sys, 'stderr', io.StringIO()), \
                    patch.object(RUNNER, 'UpdateCase') as case:
                with self.assertRaises(SystemExit) as raised:
                    RUNNER.main(['--project', 'unused', '--evidence', 'unused', '--name', 'safe'] + option)
                self.assertEqual(2, raised.exception.code)
                case.assert_not_called()


if __name__ == '__main__':
    unittest.main()
