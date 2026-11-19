"""Offline byte-preservation and exhaustive four-symbol oracle regressions."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
from PIL import Image


HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


build = module('test_shadow_candidate_builder', HERE / 'build_candidate.py')
verify = module('test_shadow_candidate_oracle', HERE / 'verify.py')
payload_oracle = verify.shadow._PAYLOAD_VERIFY


def native_material():
    return (b'{\r\n  "materials": {"version":"1",\r\n'
        b'"shadow_front":{"stencilReadMask":255,"stencilWriteMask":1},\r\n'
        b'"shadow_back":{"stencilReadMask":255,"stencilWriteMask":1},\r\n'
        b'"shadow_overlay":{"stencilReadMask": 255,"stencilRef":1,"stencilWriteMask":0,'
        b'"frontFace":{"stencilFunc":"Equal"},"backFace":{"stencilFunc":"Equal"},'
        b'"blendSrc":"DestColor","blendDst":"Zero","other":"escaped \\\" } stays"},'
        b'"water_hole":{"untouched":true}}}\r\n')


class MaterialTests(unittest.TestCase):
    def test_exact_numeric_splice_all_three_masks(self):
        original = native_material()
        for mask in build.MASKS:
            candidate, receipt = build.patch_material(original, mask)
            self.assertEqual(json.loads(candidate)['materials']['shadow_overlay']['stencilReadMask'], mask)
            left, right = receipt['original_byte_span']
            self.assertEqual(candidate[:left], original[:left])
            self.assertEqual(candidate[left + len(str(mask)):], original[right:])
            self.assertEqual(candidate[:left] + b'255' + candidate[left + len(str(mask)):], original)
            self.assertEqual(json.loads(candidate)['materials']['shadow_front']['stencilReadMask'], 255)
            self.assertEqual(json.loads(candidate)['materials']['shadow_back']['stencilReadMask'], 255)
            if mask == 255:
                self.assertEqual(candidate, original)

    def test_reject_drift_ambiguous_field_and_bad_mask(self):
        for source in (native_material().replace(b'"stencilRef":1', b'"stencilRef":2'),
                       native_material().replace(b'"shadow_overlay":{', b'"shadow_overlay":{"stencilReadMask":255,')):
            with self.assertRaises(ValueError):
                build.patch_material(source, 63)
        for mask in (True, 0, 192, '63', 63.0, 191.0):
            with self.assertRaises(ValueError):
                build.patch_material(native_material(), mask)

    def test_static_truth_table_is_not_native_gate(self):
        expected = {255: [True, False, False, False], 191: [True, True, False, False], 63: [True] * 4}
        for mask, rows in expected.items():
            model = build.mask_model(mask)
            self.assertFalse(model['native_acceptance_gate'])
            self.assertEqual([row['equal_pass'] for row in model['rows']], rows)

    def test_offline_install_isolated_single_field_and_tamper_rejection(self):
        old_root = build.ROOT
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build.ROOT = root
            try:
                game = root / 'game/Minecraft.Windows.exe'
                source = game.parent / 'data/resource_packs/vanilla/materials/shadows.material'
                source.parent.mkdir(parents=True)
                source.write_bytes(native_material())
                game.write_bytes(b'OFFLINE TEST ONLY; NEVER EXECUTE')
                source_before = source.read_bytes()
                identities = []
                for mask in build.MASKS:
                    project = root / '.runtime' / ('mask%d' % mask) / 'project'
                    for folder in ('behavior_pack', 'resource_pack'):
                        (project / folder).mkdir(parents=True)
                        (project / folder / 'manifest.json').write_text(json.dumps({'header': {
                            'name': 'unchanged', 'uuid': folder}, 'modules': [{'uuid': folder + '/module'}]}))
                    (project / 'resource_pack/materials').mkdir()
                    (project / 'resource_pack/materials/sfx.material').write_bytes(b'FROZEN CARRIER')
                    (project / 'behavior_pack/runtime.py').write_bytes(b'# FROZEN RUNTIME\n')
                    (project / 'probe_resources.json').write_text(json.dumps({'native_compatibility': {'variant': 'carrier'}}))
                    settings = {'game_executable_path': str(game), 'included_mod_dirs': ['./']}
                    settings.update({key: False for key in ('auto_hot_reload_mods', 'auto_hot_reload_ui',
                                                           'auto_hot_reload_shaders', 'auto_hot_reload_materials')})
                    (project / '.mcdev.json').write_text(json.dumps(settings))
                    receipt = build.install(project, game, mask)
                    self.assertEqual(build.validate(project, mask), receipt)
                    self.assertEqual((project / 'resource_pack/materials/sfx.material').read_bytes(), b'FROZEN CARRIER')
                    self.assertEqual((project / 'behavior_pack/runtime.py').read_bytes(), b'# FROZEN RUNTIME\n')
                    self.assertEqual(source.read_bytes(), source_before)
                    identities.append(receipt['manifest_identities']['resource_pack']['header']['uuid'])
                    with self.assertRaises(ValueError):
                        build.install(project, game, mask)
                    (project / build.MATERIAL).write_bytes(b'TAMPER')
                    with self.assertRaises(ValueError):
                        build.validate(project, mask)
                self.assertEqual(len(set(identities)), 3)
            finally:
                build.ROOT = old_root


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name).resolve()
        self.payload = payload_oracle.payload_bytes(65536)
        self.viewport, self.roi = [720, 1080], [8, 128, 512, 512]
        self.plan = verify.shadow.make_plan(self.viewport, self.roi,
            [[480, 480], [570, 480], [570, 610], [480, 610]], [600, 400, 620, 450],
            [[620, 500], [650, 500], [650, 520], [620, 520]])
        self.off = np.full((1080, 720, 3), 160, dtype=np.uint8)
        self.on = self.off.copy()
        self.on[500:570, 495:540] = 110
        self.native = [Image.fromarray(self.off), Image.fromarray(self.on), Image.fromarray(self.off)]

    def tearDown(self):
        self.temp.cleanup()

    def reports(self, payload=None):
        payload = self.payload if payload is None else payload
        values = np.frombuffer(payload, dtype=np.uint8)
        digest = hashlib.sha256(payload).hexdigest()
        state = {'identity': {'host_sha256': digest, 'byte_count': 65536}, 'payload_visible': True,
                 'state': 'resident', 'ready': True, 'generation': 1,
                 'active_pages': ['b64', 'b128'], 'native_page_names': ['clear', 'b64', 'b128'],
                 'native_attempt_count': 3, 'native_records_reserved': 131073}
        reports = []
        for mode in (1, 3):
            image = self.on.copy()
            output = image[650:].reshape(-1, 3)
            output[:] = payload_oracle.GUARD
            if mode == 1:
                wide = values.astype(np.uint16)
                output[:65536] = np.column_stack((wide, (71 * wide + 43) % 256,
                                                  (131 * wide + 17) % 256)).astype(np.uint8)
            else:
                symbols = ((values[:, None] >> np.arange(0, 8, 2, dtype=np.uint8)) & 3).reshape(-1)
                output[:262144, 0] = symbols * 64
                output[:262144, 1] = 255
                output[:262144, 2] = 0
            path = self.directory / ('m%d.png' % mode)
            Image.fromarray(image).save(path)
            report = payload_oracle.verify(Image.fromarray(image), mode, payload, self.viewport, self.roi, output_y=650)
            report.update(label='m%d' % mode, capture_file=str(path), logical_bytes=65536,
                          configuration='all', state=copy.deepcopy(state))
            reports.append(report)
        return reports

    def test_all_four_groups_full_geometry_same_png_payload_and_guards_pass(self):
        result = verify.compare(self.native, self.native, self.plan, self.reports(), self.payload)
        self.assertTrue(result['pass'], result['errors'])
        self.assertTrue(result['all_four_symbol_groups_covered'])
        self.assertFalse(result['pixel_derived_acceptance_mask'])
        self.assertTrue(all(row['changed_shadow_pixels'] == 0 for row in result['groups']))
        self.assertTrue(all(row['native_shadow_pixels'] >= 24 for row in result['groups']))
        self.assertEqual([row['bits_bit128_bit64'] for row in result['groups']], ['00', '01', '10', '11'])

    def test_bit64_loss_is_observed_in01_and11_without_reselecting_samples(self):
        symbols = verify.symbol_map(self.payload, self.viewport, self.roi)
        changed = self.on.copy()
        native_shadow = verify._native_shadow_pixels(self.native, self.plan)
        changed[native_shadow & ((symbols == 1) | (symbols == 3))] = 160
        active = [self.native[0], Image.fromarray(changed), self.native[2]]
        result = verify.compare(self.native, active, self.plan, self.reports(), self.payload)
        self.assertFalse(result['pass'])
        self.assertTrue(result['all_four_symbol_groups_covered'])
        for row in result['groups']:
            self.assertEqual(row['changed_shadow_pixels'], row['native_shadow_pixels'] if row['symbol'] & 1 else 0)

    def test_unshadowed_receiver_and_outside_roi_mutations_are_rejected(self):
        for y, x in ((485, 490), (485, 550)):
            changed = self.on.copy()
            changed[y, x] = 140
            result = verify.compare(self.native, [self.native[0], Image.fromarray(changed), self.native[2]],
                                    self.plan, self.reports(), self.payload)
            self.assertFalse(result['pass'])

    def test_same_png_guard_or_full_data_mutation_rejected(self):
        for y, x in ((650, 0), (1079, 719)):
            reports = self.reports()
            path = Path(reports[0]['capture_file'])
            with Image.open(path) as image:
                changed = np.asarray(image).copy()
            changed[y, x, 2] ^= 1
            Image.fromarray(changed).save(path)
            result = verify.compare(self.native, self.native, self.plan, reports, self.payload)
            self.assertFalse(result['pass'])

    def test_missing_symbol_coverage_is_not_success(self):
        zero = bytes(65536)
        result = verify.compare(self.native, self.native, self.plan, self.reports(zero), zero)
        self.assertFalse(result['pass'])
        self.assertFalse(result['all_four_symbol_groups_covered'])

    def matrix_case(self, mask, shadow_loss=False):
        directory = self.directory / str(mask)
        directory.mkdir()
        old_directory = self.directory
        self.directory = directory
        data = self.reports()
        self.directory = old_directory
        active_on = self.on.copy()
        if shadow_loss:
            symbols = verify.symbol_map(self.payload, self.viewport, self.roi)
            sample = verify._native_shadow_pixels(self.native, self.plan)
            active_on[sample & ((symbols == 1) | (symbols == 3))] = 160
        paths = []
        reports = []
        frames = [self.off, self.on, self.off, self.off, active_on, self.off]
        for index, frame in enumerate(frames):
            path = directory / ('frame%d.png' % index)
            Image.fromarray(frame).save(path)
            paths.append(str(path))
            reports.append({'capture_file': str(path), 'mode': 0})
        reports += data
        for index, report in enumerate(reports):
            capture = {'ok': True, 'backend': 'Windows.Graphics.Capture', 'width': 720, 'height': 1080,
                       'pid': 1234, 'window': {'pid': 1234}, 'agent_activation_allowed': False,
                       'frame_qpc_100ns': index * 10 + 5, 'request_qpc_100ns': index * 10,
                       'background_before': {'window_noactivate': True},
                       'background_after': {'window_noactivate': True}}
            report['capture_receipt'] = capture
            Path(report['capture_file']).with_suffix('.json').write_text(json.dumps(capture))
        payload_file = directory / 'actual_input.bin'
        payload_file.write_bytes(self.payload)
        project = directory / 'project'
        candidate = {'mask': mask, 'project': str(project), 'source_sha256': 'ORIGINAL',
                     'unchanged_packaged_sha256': {'carrier': 'FROZEN'}}
        session_bytes = json.dumps({'owner': 'manim-native-stencil-compat', 'project': str(project),
                                    'game_pid': 1234}).encode()
        (directory / 'assigned-session-snapshot.json').write_bytes(session_bytes)
        states = [{'entity': 'cube', 'shadow_requested': enabled, 'native_position': [0, 0, 0],
                   'rotation': [0, 0], 'camera': {'position': [0, 0, 0]},
                   'receiver_revision': 'floor', 'static_entity': True} for enabled in (False, True, False)]
        all_paths = paths + [row['capture_file'] for row in data]
        status = {'mask': mask, 'candidate': candidate, 'operational_complete': True, 'failure': None,
                  'compatibility': True, 'classification': 'INTENTIONALLY FALSE SAVED CLAIM',
                  'candidate_package_unchanged': True, 'frozen_hover_helper_unchanged': True,
                  'plan': self.plan, 'native_captures': paths[:3], 'active_captures': paths[3:],
                  'payload_captures': all_paths[6:], 'actual_input_file': str(payload_file),
                  'actual_payload_sha256': hashlib.sha256(self.payload).hexdigest(),
                  'assigned_session_sha256': hashlib.sha256(session_bytes).hexdigest(),
                  'native_snapshots': states, 'active_snapshots': states,
                  'final_runtime_state': {'outline': {'entity': None}},
                  'capture_sha256': {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in all_paths}}
        (directory / 'shadow-candidate-status.json').write_text(json.dumps(status))
        (directory / 'shadow-recovery-status.json').write_text(json.dumps({'cleanup': {'floor': {'all_exact': True}}}))
        (directory / 'results.json').write_text(json.dumps({'reports': reports, 'loads': [{'input_file': str(payload_file)}]}))
        return directory, candidate

    def test_saved_matrix_replays_pixels_and_requires_original_negative_for_attribution(self):
        cases = {mask: self.matrix_case(mask, shadow_loss=mask == 255) for mask in (255, 191, 63)}
        receipts = {str(path / 'project'): receipt for path, receipt in cases.values()}
        with mock.patch.object(verify.build, 'validate', side_effect=lambda project, mask: receipts[project]):
            result = verify.compare_matrix({mask: row[0] for mask, row in cases.items()})
        self.assertTrue(result['operational_complete'], result['errors'])
        self.assertTrue(result['original_control_conflict_reproduced'])
        self.assertEqual(result['qualified_mask_repair_candidates'], [191, 63])
        self.assertFalse(result['cases'][0]['compatibility_recomputed'])  # Saved claim was deliberately true.
        active = cases[191][0] / 'frame4.png'
        with Image.open(active) as image:
            mutated = np.asarray(image).copy()
        mutated[505, 505] = 160
        Image.fromarray(mutated).save(active)
        with mock.patch.object(verify.build, 'validate', side_effect=lambda project, mask: receipts[project]):
            with self.assertRaises(ValueError):
                verify.compare_matrix({mask: row[0] for mask, row in cases.items()})

    def test_saved_matrix_no_original_conflict_does_not_qualify_a_repair(self):
        cases = {mask: self.matrix_case(mask) for mask in (255, 191, 63)}
        receipts = {str(path / 'project'): receipt for path, receipt in cases.values()}
        with mock.patch.object(verify.build, 'validate', side_effect=lambda project, mask: receipts[project]):
            result = verify.compare_matrix({mask: row[0] for mask, row in cases.items()})
        self.assertTrue(result['operational_complete'], result['errors'])
        self.assertEqual(result['observed_compatible_candidates'], [191, 63])
        self.assertFalse(result['original_control_conflict_reproduced'])
        self.assertEqual(result['qualified_mask_repair_candidates'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
