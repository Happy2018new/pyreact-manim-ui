"""Offline sequential T0 proof and reopened-PNG gate regressions."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


runner = load('sequential_runner_under_test', HERE / 'runner.py')
fakes = load('sequential_frozen_test_support', HERE.parent / 'native_stencil_post_candidate/test_bloom.py')
base = fakes.bloom
LAYOUT = fakes.LAYOUT


class NoLinksPost(fakes.FakePost):
    def PostPassResultToOtherPass(self, *args):
        raise AssertionError('Sequential control must never explicitly connect textures')


class Experiment(fakes.FakeExperiment):
    def __init__(self, root, phase, *, bad_alpha=False, direction='alpha_zero_gain'):
        evidence, project = Path(root) / 'evidence', Path(root) / 'project'
        evidence.mkdir(parents=True)
        project.mkdir()
        (project / runner.BUILD_RECEIPT).write_text('offline synthetic build receipt', encoding='utf-8')
        super().__init__(evidence, direction=direction)
        self.args = SimpleNamespace(project=project)
        self.game_pid = 4132 if phase == 'source-control' else 4133
        self.session = Path(root) / 'assigned-session.json'
        self.session.write_text(json.dumps({'id': phase + '-session', 'owner': 'manim-native-stencil-compat',
                                            'project': str(project.resolve()), 'game_pid': self.game_pid,
                                            'state': 'ready'}), encoding='utf-8')
        self.phase, self.bad_alpha = phase, bad_alpha
        self.probe.post = NoLinksPost()
        self.probe.post.enabled['bloom'] = phase == 'native'
        self.initial_flags = self.probe.post.enabled.copy()
        self.capture_serial = 0
        self.reject_source = False
        self.command_text = {}

    def call(self, label, code='', expression='probe.snapshot()'):
        self.command_text[label] = code
        return super().call(label, code, expression)

    def capture(self, experiment, label):
        self.capture_labels.append(label)
        self.capture_serial += 1
        source = self.probe.post.parameters[runner.SOURCE]
        alpha = source['control'][2]
        if self.phase == 'source-control':
            mode = self.probe.post.parameters[runner.OBSERVER]['control'][0]
            rgb, alphas = fakes.source_images()
            pixels = (alphas if mode else rgb)[0 if alpha == 1. else 1].copy()
            if self.bad_alpha and mode and alpha == 0.:
                pixels[:] = 255
        else:
            pixels = fakes.native_images(self.direction)[0 if alpha == 1. else 1].copy()
        path = self.evidence / (label + '.png')
        base.Image.fromarray(pixels).save(path)
        foreground = {'hwnd': 11, 'pid': 22, 'identity': 'passive'}
        capture = {'ok': True, 'backend': 'Windows.Graphics.Capture', 'native_resolution': True,
                   'pid': self.game_pid, 'window': {'pid': self.game_pid, 'minimized': False},
                   'width': LAYOUT['viewport'][0], 'height': LAYOUT['viewport'][1],
                   'file': str(path), 'agent_activation_allowed': False,
                   'request_qpc_100ns': self.capture_serial * 100,
                   'frame_qpc_100ns': self.capture_serial * 100 + 1,
                   'background_before': {'window_noactivate': True, 'foreground': foreground.copy()},
                   'background_after': {'window_noactivate': True, 'foreground': foreground.copy()}}
        path.with_suffix('.json').write_text(json.dumps(capture), encoding='utf-8')
        return {'label': label, 'capture_file': str(path), 'capture_receipt': capture}, pixels


class SequentialRunnerTests(unittest.TestCase):
    def validator(self, project, phase):
        return {'fixture_identity': runner.fixture_identity(LAYOUT), 'game_executable_path': 'same-client.exe',
                'native_input_sources': {'native-shader': 'same-native-hash'}, 'resources_sha256': 'same-resources'}

    def run_phase(self, experiment, gate=None):
        return runner.run(experiment, experiment.phase, gate, capture=experiment.capture,
                          settle=experiment.settle, layout=LAYOUT, build_validator=self.validator)

    def source(self, root):
        experiment = Experiment(Path(root) / 'source', 'source-control')
        result = self.run_phase(experiment)
        self.assertEqual(result['status'], 'source_control_observed', result.get('failure'))
        return experiment, result, experiment.evidence / runner.STATUS_FILE

    def assert_restored(self, experiment):
        for name, flag in experiment.initial_flags.items():
            self.assertIs(experiment.probe.post.enabled[name], flag)
        for name in (runner.SOURCE, runner.OBSERVER):
            self.assertFalse(experiment.probe.post.enabled.get(name, False))
        self.assertEqual(experiment.probe.post.native_mutations, [])

    def test_source_control_proves_ordinary_t0_rgb_alpha_from_actual_pngs(self):
        with tempfile.TemporaryDirectory() as root:
            experiment, result, path = self.source(root)
            accepted = runner.verify_source_gate(path, runner.fixture_identity(LAYOUT), build_validator=self.validator)
            self.assertTrue(accepted['source_control']['passed'])
            self.assertEqual(len(result['captures']), 6)
            self.assertIsNone(result['compatibility'])
            self.assertTrue(accepted['cross_session_proof'])
            self.assert_restored(experiment)
            self.assertFalse(any('PostPassResultToOtherPass' in code for code in experiment.command_text.values()))

    def test_native_requires_reopened_source_proof_then_only_source_bloom(self):
        with tempfile.TemporaryDirectory() as root:
            source_exp, _, gate = self.source(root)
            native = Experiment(Path(root) / 'native', 'native')
            result = self.run_phase(native, gate)
            self.assertEqual(result['status'], 'native_positive_control_observed', result.get('failure'))
            self.assertEqual(len(result['captures']), 3)
            self.assertNotIn(runner.OBSERVER, native.probe.post.order)
            for row in result['captures']:
                self.assertEqual([name for name, flag in row['state_before']['seq_flags'] if flag],
                                 [runner.SOURCE, 'bloom'])
            self.assertIsNone(result['compatibility'])
            self.assert_restored(native)
            self.assert_restored(source_exp)

    def test_missing_gate_stops_native_before_transport(self):
        with tempfile.TemporaryDirectory() as root:
            native = Experiment(Path(root) / 'native', 'native')
            result = self.run_phase(native)
            self.assertEqual(result['status'], 'helper_failed')
            self.assertEqual(native.labels, [])
            self.assertEqual(native.capture_labels, [])
            self.assertIsNone(result['compatibility'])

    def test_bad_source_alpha_stays_unproven_and_cannot_gate_native(self):
        with tempfile.TemporaryDirectory() as root:
            source = Experiment(Path(root) / 'source', 'source-control', bad_alpha=True)
            result = self.run_phase(source)
            self.assertEqual(result['status'], 'source_control_unproven')
            native = Experiment(Path(root) / 'native', 'native')
            rejected = self.run_phase(native, source.evidence / runner.STATUS_FILE)
            self.assertEqual(rejected['status'], 'helper_failed')
            self.assertEqual(native.labels, [])
            self.assert_restored(source)

    def test_png_edit_with_updated_hash_is_redecoded_and_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            _, report, path = self.source(root)
            row = report['captures'][3]  # Alpha-zero sample should contain a black patch.
            with base.Image.open(row['capture_file']) as image:
                pixels = base.np.array(image.convert('RGB'))
            pixels[64, 72] = 255
            base.Image.fromarray(pixels).save(row['capture_file'])
            row['capture_sha256'] = runner.sha(row['capture_file'])
            path.write_bytes(runner.json_bytes(report))
            with self.assertRaisesRegex(ValueError, 'actual PNG RGB/alpha decode'):
                runner.verify_source_gate(path, runner.fixture_identity(LAYOUT), build_validator=self.validator)

    def test_wrong_layout_shader_identity_or_build_hash_rejects_gate(self):
        with tempfile.TemporaryDirectory() as root:
            source, report, path = self.source(root)
            original = copy.deepcopy(report)
            report['layout']['patch'][0] -= 1
            path.write_bytes(runner.json_bytes(report))
            with self.assertRaisesRegex(ValueError, 'fixture/layout/shader'):
                runner.verify_source_gate(path, runner.fixture_identity(LAYOUT), build_validator=self.validator)
            path.write_bytes(runner.json_bytes(original))
            (source.args.project / runner.BUILD_RECEIPT).write_text('changed build', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'build receipt/fixture'):
                runner.verify_source_gate(path, runner.fixture_identity(LAYOUT), build_validator=self.validator)

    def test_foreground_capture_pid_and_cleanup_tampering_rejected(self):
        mutations = [lambda r: r['captures'][0]['capture_receipt'].__setitem__('pid', 999),
                     lambda r: r['captures'][0]['capture_receipt']['background_after']['foreground'].__setitem__('pid', 999),
                     lambda r: r['captures'][0]['state_before']['seq_source_control'].__setitem__(2, 0.),
                     lambda r: r['cleanup']['state']['seq_flags'].__setitem__(-1, [runner.OBSERVER, True]),
                     lambda r: r['cleanup']['state'].__setitem__('mode', 'off'),
                     lambda r: r['cleanup']['state']['known_fixture'].__setitem__('varying_alpha', False)]
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as root:
                _, report, path = self.source(root)
                mutate(report)
                path.write_bytes(runner.json_bytes(report))
                with self.assertRaises(ValueError):
                    runner.verify_source_gate(path, runner.fixture_identity(LAYOUT), build_validator=self.validator)

    def test_repeated_image_path_and_stale_capture_sequence_rejected(self):
        for field in ('path', 'qpc'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as root:
                _, report, path = self.source(root)
                if field == 'path':
                    report['captures'][2]['capture_file'] = report['captures'][0]['capture_file']
                else:
                    report['captures'][1]['capture_receipt']['request_qpc_100ns'] = 1
                path.write_bytes(runner.json_bytes(report))
                with self.assertRaises(ValueError):
                    runner.verify_source_gate(path, runner.fixture_identity(LAYOUT), build_validator=self.validator)

    def test_no_native_response_is_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            _, _, gate = self.source(root)
            native = Experiment(Path(root) / 'native', 'native', direction=None)
            result = self.run_phase(native, gate)
            self.assertEqual(result['status'], 'native_stage_unproven')
            self.assertIsNone(result['compatibility'])
            self.assertFalse(result['native_stage_executed_observed'])
            self.assert_restored(native)

    def test_mismatched_native_client_is_rejected_before_transport(self):
        with tempfile.TemporaryDirectory() as root:
            _, _, gate = self.source(root)
            native = Experiment(Path(root) / 'native', 'native')

            def different_client(project, phase):
                built = self.validator(project, phase)
                if phase == 'native':
                    built['native_input_sources'] = {'native-shader': 'different-native-hash'}
                return built

            result = runner.run(native, 'native', gate, capture=native.capture, settle=native.settle,
                                layout=LAYOUT, build_validator=different_client)
            self.assertEqual(result['status'], 'helper_failed')
            self.assertIn('different installed client', result['failure'])
            self.assertEqual(native.labels, [])

    def test_assigned_source_session_and_raw_sidecar_are_reopened(self):
        for field in ('session', 'sidecar'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as root:
                source, report, path = self.source(root)
                if field == 'session':
                    data = json.loads(source.session.read_text())
                    data['game_pid'] = 999
                    source.session.write_text(json.dumps(data))
                else:
                    sidecar = Path(report['captures'][0]['capture_receipt_file'])
                    data = json.loads(sidecar.read_text())
                    data['pid'] = 999
                    sidecar.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    runner.verify_source_gate(path, runner.fixture_identity(LAYOUT), build_validator=self.validator)

    def test_capture_failure_restores_custom_flags(self):
        with tempfile.TemporaryDirectory() as root:
            source = Experiment(Path(root) / 'source', 'source-control')

            def failed_capture(*args):
                raise OSError('offline capture failure')

            result = runner.run(source, 'source-control', capture=failed_capture, settle=source.settle,
                                layout=LAYOUT, build_validator=self.validator)
            self.assertEqual(result['status'], 'helper_failed')
            self.assertIn('offline capture failure', result['failure'])
            self.assert_restored(source)

    def test_resources_use_only_t0_observer_and_native_shader_alias(self):
        resources = runner.resources()
        self.assertEqual(set(resources['materials']), {runner.SOURCE, runner.OBSERVER})
        self.assertIn('TEXTURE_0', runner.OBSERVER_FRAGMENT)
        self.assertNotIn('TEXTURE_3', runner.OBSERVER_FRAGMENT)
        for name, material in resources['materials'].items():
            self.assertEqual(material['fragmentShader'], 'shaders/' + name + '.fragment')


if __name__ == '__main__':
    unittest.main()
