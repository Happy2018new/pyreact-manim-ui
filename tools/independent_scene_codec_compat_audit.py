"""Read-only independent stage-2 PNG, receipt, shader-hook and lifecycle audit.

This module imports neither the probe implementation nor its verifier. It never
launches or controls Minecraft. A failed scene or native hook stays failed.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


ROI = (296, 192, 128, 683)
SOURCE_PIXELS = 87424
PAYLOAD_BYTES = 65536
DOCUMENTS = {
    'real': 'carrier-evidence-v1/real6.results.json',
    'isolation': 'carrier-evidence-v1/rain_isolate1.results.json',
    'sameframe': 'carrier-evidence-v2b/sameframe1.results.json',
    'math': 'carrier-evidence-v2b/native_math1.results.json',
    'sentinel': 'native-sentinel-evidence-v1/sentinel1.results.json',
}


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pixels(path):
    with Image.open(path) as image:
        require(image.size == (720, 1080), 'Unexpected image dimensions: ' + str(path))
        return np.asarray(image.convert('RGB'), dtype=np.int64)


def diagnostic_samples(path, count):
    image = pixels(path)
    index = np.arange(count)
    return image[128 + index // 720, index % 720]


def source_roi_samples(path):
    left, top, width, height = ROI
    return pixels(path)[top:top+height, left:left+width].reshape(-1, 3)


def histogram(values):
    return {str(int(value)): int(count) for value, count in sorted(Counter(values.tolist()).items())}


def compare(observed, expected):
    require(observed.shape == expected.shape, 'Comparison shape mismatch')
    error = np.max(np.abs(observed - expected), axis=1)
    bad = np.flatnonzero(error)
    return {'passed': not len(bad), 'samples': len(error), 'mismatch_samples': int(len(bad)),
            'maximum_channel_error': int(error.max()) if len(error) else 0,
            'first_failures': [{'ordinal': int(index), 'observed': observed[index].tolist(),
                                'expected': expected[index].tolist()} for index in bad[:5]]}


def oracle_byte(address, salt=29):
    return ((address % 256) * 73 + ((address // 251) % 256) * 19 + salt) % 256


def oracle_symbols(count=SOURCE_PIXELS):
    index = np.arange(count, dtype=np.int64)
    result = np.zeros(count, dtype=np.int64)
    for bit in range(6):
        address = 6 * index + bit
        byte_index = address // 8
        value = np.where(byte_index < PAYLOAD_BYTES, oracle_byte(byte_index), 0)
        result |= ((value >> (address % 8)) & 1) << bit
    return result


def expected_query(mode):
    address = np.arange(PAYLOAD_BYTES, dtype=np.int64)
    if mode == 2:
        address = (131 * address + 29) % PAYLOAD_BYTES
        address = (address + 257 * oracle_byte(address) + 113) % PAYLOAD_BYTES
    values = oracle_byte(address)
    return np.repeat(values[:, None], 3, axis=1), int(len(np.unique(address)))


def check_report_integrity(report, directory):
    path = Path(report['capture']).resolve()
    require(path.parent == directory, 'Capture path does not match evidence directory')
    checks = [(path, 'capture_sha256'), (path.with_suffix('.state.json'), 'state_sha256'),
              (path.with_suffix('.json'), 'capture_receipt_sha256')]
    for file, field in checks:
        require(sha(file) == report[field], 'SHA256 mismatch: ' + str(file))
    state, receipt = load(checks[1][0]), load(checks[2][0])
    require(state == report['state'], 'Saved state differs from embedded report state')
    require(state.get('game_runtime_file_writes') is False and state.get('direct_source') is False,
            'Unexpected game runtime file writes or direct source')
    require(state.get('error') is None, 'Runtime error in successful capture')
    require(receipt['ok'] and receipt['backend'] == 'Windows.Graphics.Capture' and
            receipt['native_resolution'] and receipt['width'] == 720 and receipt['height'] == 1080,
            'Invalid native passive capture receipt')
    require(receipt.get('agent_activation_allowed') is False, 'Agent activation was permitted')
    require(receipt['frame_qpc_100ns'] >= receipt['request_qpc_100ns'], 'Captured stale frame predating request')
    for position in ('background_before', 'background_after'):
        require(report[position]['window_noactivate'] and report[position]['background_safe'], 'Unsafe capture window receipt')
    return {'file': path.name, 'sha256': report['capture_sha256'], 'pid': receipt['pid'],
            'hashes_checked': 3, 'noactivation': True, 'user_foreground_allowed': report['user_foreground_allowed']}


def check_commands(document, directory):
    count = 0
    for event in document.get('events', []):
        if 'command_sha256' in event:
            path = directory / 'commands' / (event['label'] + '.py')
            require(sha(path) == event['command_sha256'], 'Command SHA mismatch: ' + str(path))
            count += 1
    return count


def real_audit(document, directory):
    result = []
    reports = {item['name']: item for item in document['reports']}
    for case in ('water_glass', 'rain', 'glint_emissive', 'particle'):
        grid_report = reports[case + '_alpha_grid']
        grid = source_roi_samples(grid_report['capture'])
        alpha_hist = histogram(grid[:, 0])
        block_report = reports[case + '_alpha_blocks']
        blocks = source_roi_samples(block_report['capture'])[::32]
        exceptions = np.floor(blocks[:, 0] * 32 / 255 + .5).astype(int)
        exception_hist = histogram(exceptions)
        require(alpha_hist == grid_report['histogram'], 'Reported alpha histogram differs: ' + case)
        require(exception_hist == block_report['exception_histogram'], 'Reported block histogram differs: ' + case)
        same = diagnostic_samples(reports[case + '_alpha_sameframe']['capture'], SOURCE_PIXELS)
        entry = {'case': case, 'alpha_grid': {'samples': len(grid), 'histogram': alpha_hist,
                 'non255': int(np.count_nonzero(grid[:, 0] != 255)),
                 'offgrid_flags': int(np.count_nonzero(grid[:, 2] > 127)),
                 'maximum_displayed_residual': int(grid[:, 1].max())},
                 'alpha_blocks': {'blocks': len(blocks), 'exception_histogram': exception_hist,
                                  'max_exceptions': int(exceptions.max()),
                                  'overflow_blocks': int(np.count_nonzero(blocks[:, 1] > 127))},
                 'same_frame_alpha_error': compare(same, np.zeros_like(same)), 'queries': []}
        for suffix, mode in (('identity_after_native', 0), ('dependent_after_native', 2)):
            report = reports[case + '_' + suffix]
            expected, distinct = expected_query(mode)
            observed = diagnostic_samples(report['capture'], PAYLOAD_BYTES)
            check = compare(observed, expected)
            require(check['mismatch_samples'] == report['mismatch_samples'] and
                    check['maximum_channel_error'] == report['maximum_channel_error'], 'Reported payload results differ: ' + case)
            entry['queries'].append({'mode': mode, 'requests': PAYLOAD_BYTES, 'distinct_addresses': distinct, **check})
        native_file = directory / ('real6_' + case + '_native_states.execute.json')
        native = load(native_file)['result']['states']
        entry['native_states_before_late_queries'] = native
        require(dict(native)['scene_codec_raw'] and dict(native)['scene_codec_encode'] and dict(native)['scene_codec_decode'],
                'Codec source chain was not enabled')
        require(not dict(native)['scene_codec_inspect'] and not dict(native)['scene_codec_diagnostic'],
                'A diagnostic replaced restored output in native image checks')
        entry['native_receipt_sha256'] = sha(native_file)
        result.append(entry)
    return result


def isolation_audit(document, directory):
    result = []
    for report in document['reports']:
        name = report['name']
        if name == 'raw_rgb':
            rgb = diagnostic_samples(report['capture'], SOURCE_PIXELS)
            symbol = (rgb[:, 0] // 64) + 4 * (rgb[:, 1] // 64) + 16 * (rgb[:, 2] // 64)
            wrong = np.flatnonzero(symbol != oracle_symbols())
            result.append({'case': name, 'source_pixels': len(rgb), 'bad_payload_symbols': int(len(wrong)),
                           'source_bbox_local_inclusive': [int((wrong % 128).min()), int((wrong // 128).min()),
                                                          int((wrong % 128).max()), int((wrong // 128).max())]})
            continue
        mode = 2 if name == 'early_dependent' else 0
        expected, distinct = expected_query(mode)
        observed = diagnostic_samples(report['capture'], PAYLOAD_BYTES)
        result.append({'case': name, 'mode': mode, 'distinct_addresses': distinct, **compare(observed, expected)})
    off_path = directory / 'rain_isolate1_off_effects.execute.json'
    off = load(off_path)['result']
    require(off['bloom'] is False and off['dof'] is False and all(off['accepted']), 'Isolation native-off flags were not actually off')
    return {'captures': result, 'native_off_receipt': off, 'native_off_receipt_sha256': sha(off_path),
            'conclusion': 'Payload errors exist with both native flags off and in raw incoming RGB; native effects are not necessary for failure.'}


def sameframe_audit(document):
    result = []
    for report in document['reports']:
        data = diagnostic_samples(report['capture'], SOURCE_PIXELS)
        bad, non255, offgrid = data[:, 0] > 127, data[:, 1] != 255, data[:, 2] > 127
        entry = {'case': report['name'], 'pixels': len(data), 'bad_q': int(np.count_nonzero(bad)),
                 'non255_alpha': int(np.count_nonzero(non255)),
                 'bad_q_and_non255': int(np.count_nonzero(bad & non255)),
                 'bad_q_and_alpha255': int(np.count_nonzero(bad & ~non255)),
                 'residual_flags': int(np.count_nonzero(offgrid)),
                 'all_alpha_histogram': histogram(data[:, 1]), 'bad_alpha_histogram': histogram(data[bad, 1])}
        for field in ('bad_q', 'non255_alpha', 'bad_q_and_non255', 'bad_q_and_alpha255', 'residual_flags'):
            require(entry[field] == report[field], 'Same-frame summary differs: ' + report['name'] + '/' + field)
        state = report['state']
        require(state['logical_payload_bytes'] == PAYLOAD_BYTES and state['rgb_bits'] == 2 and state['payload_salt'] == 29,
                'Mode-23 hardcoded oracle does not match the actual writer dataset')
        require(state['writer_visible'] and not state['code_domain_sweep'], 'Mode-23 dataset is not native writer payload')
        result.append(entry)
    return {'cases': result, 'interpretation': 'In each sampled rain frame, every bad RGB symbol coincides with a non-255 raw alpha from the same sampled texel.',
            'causal_limit': 'Supports a later blended rain draw; does not expose an engine draw-call trace or establish a public reordering fix.',
            'precision_limit': 'Zero flags reflect a shader threshold and byte-coded PNG; no arbitrary higher-precision alpha guarantee.'}


def sentinel_audit(document, directory, project):
    result = []
    for report in document['reports']:
        crop = pixels(report['capture'])[128:1064].reshape(-1, 3)
        entry = {'requested_case': report['name'], 'pixels': len(crop),
                 'magenta': int(np.count_nonzero(np.all(crop == [255, 0, 255], axis=1))),
                 'cyan': int(np.count_nonzero(np.all(crop == [0, 255, 255], axis=1)))}
        require(entry['magenta'] == report['magenta'] and entry['cyan'] == report['cyan'], 'Sentinel color counts differ')
        if 'native_receipt' in report:
            native = report['native_receipt']
            entry['native_accepted'] = native['accepted']
            entry['actual_native_flags'] = dict(native['states'])
            # Labels reflect requested toggles. The off request was rejected.
            if report['name'] == 'off':
                entry['off_request_verified'] = not entry['actual_native_flags']['bloom'] and not entry['actual_native_flags']['depthoffield']
        result.append(entry)
    material = load(project / 'resource_pack/materials/postprocess.material')
    config = load(project / 'resource_pack/graphics_settings/post_process.json')
    source_checks = {}
    for effect, owned, color in (('bloom', 'pmanim_scene_compat_bloom_final', 'vec4(1.0,0.0,1.0,1.0)'),
                                ('depthoffield', 'pmanim_scene_compat_dof_final', 'vec4(0.0,1.0,1.0,1.0)')):
        process = next(item for item in config['process_array'] if item['name'] == effect)
        require(process['pass_array'][-1]['material'] == owned, 'Sentinel material not assigned to native final')
        path = project / 'resource_pack' / material[owned]['fragmentShader']
        source = path.read_text(encoding='utf-8')
        require(color in source and 'return;' in source.split('void main()', 1)[-1][:120], 'Sentinel does not return early')
        source_checks[effect] = {'fragment': str(path), 'sha256': sha(path),
                                 'material': owned, 'native_shaderPassName': process['pass_array'][-1].get('shaderPassName')}
        positive = directory / 'commands' / ('sentinel1_' + ('bloom' if effect == 'bloom' else 'dof') + '_positive_add.py')
        require("'material': '" + owned + "'" in positive.read_text(encoding='utf-8'), 'Positive custom pass uses a different material')
        source_checks[effect]['custom_positive_command_sha256'] = sha(positive)
    by_name = {item['requested_case']: item for item in result}
    return {'captures': result, 'source_checks': source_checks,
            'dof_derived_final_execution_observed': by_name['dof']['cyan'] > 670000,
            'bloom_native_derived_final_execution_observed': by_name['bloom']['magenta'] > 670000,
            'bloom_material_custom_execution_observed': by_name['bloom_custom_positive']['magenta'] > 670000,
            'conclusion': 'DOF native derived final executes. The bloom derived material executes as a custom pass, '
                          'but its sentinel is absent from native bloom in this tested path. Native bloom replacement is not established.',
            'label_correction': 'Requested off and DOF-only labels do not prove bloom was off; consult actual_native_flags.'}


def math_audit(document):
    images = {item['name']: source_roi_samples(item['capture']) for item in document['reports']}
    pairs = [('synthetic_alpha_255', 'synthetic_alpha_128'), ('synthetic_alpha_128', 'synthetic_alpha_127'),
             ('synthetic_alpha_127', 'synthetic_alpha_0'), ('synthetic_alpha_255', 'synthetic_alpha_0')]
    return {'roi': list(ROI), 'pairs': [{'first': first, 'second': second, **compare(images[first], images[second])}
                                       for first, second in pairs],
            'native_bloom_threshold_response_established': False,
            'exact_no_carrier_identity_equivalence_established': False,
            'conclusion': 'Do not interpret separate drifting scene images or alpha-fixture enable receipts as native bloom acceptance. '
                          'The ROI outputs are compared explicitly; no expected threshold split was established.'}


def lifecycle_audit(root):
    directory = root / 'carrier-evidence-v1'
    reset_path = directory / 'reset_probe_custom.execute.json'
    reset = load(reset_path)['result']
    added, after_bloom = reset[0][1], reset[1][2]
    require('scene_codec_decode' in added and 'scene_codec_decode' not in after_bloom, 'Native effect reset observation missing')
    rebuilt_path = directory / 'real6_rain_both_order.execute.json'
    rebuilt = load(rebuilt_path)['result']['order']
    require('scene_codec_decode' in rebuilt and 'scene_codec_compat_consumer_after' in rebuilt, 'Custom chain was not restored')
    require(rebuilt.index('scene_codec_decode') < rebuilt.index('bloom') < rebuilt.index('scene_codec_compat_consumer_after'),
            'Restored source/native/late consumer ordering invalid')
    return {'reset_receipt': str(reset_path), 'reset_sha256': sha(reset_path), 'observed_transitions': reset,
            'reinstalled_chain_receipt': str(rebuilt_path), 'reinstalled_chain_sha256': sha(rebuilt_path),
            'reinstalled_order': rebuilt,
            'conclusion': 'Native SetEnableByName can reset dynamically added processes, immediately or after settling. '
                          'Order must be checked and the custom chain reinstalled/reconnected before relying on private bindings.'}


def resource_audit(root):
    result = []
    for name, overlay_name in (('carrier-project-v1', 'carrier-overlay-v1'), ('carrier-project-v2', 'carrier-overlay-v2'),
                               ('native-sentinel-project-v1', 'native-sentinel-overlay-v1')):
        project, overlay = root / name, root / overlay_name
        manifest = load(project / 'scene_codec_compat_manifest.json')
        owned = load(overlay / 'resource_pack/materials/postprocess.material')
        installed = load(project / 'resource_pack/materials/postprocess.material')
        require(all(installed[key] == value for key, value in owned.items()), 'Installed derived materials differ from overlay')
        hashes = {path: {'manifest': expected, 'actual': sha(project / path),
                         'matches_manifest': expected == sha(project / path)}
                  for path, expected in manifest['output_sha256'].items()}
        result.append({'project': name, 'manifest_sha256': sha(project / 'scene_codec_compat_manifest.json'),
                       'resource_hashes': hashes, 'derived_material_entries_match_overlay': True,
                       'material_file_hash_note': 'Host installation merges prior custom entries, so whole-file material hash differs from the standalone overlay by design.',
                       'sentinel_hash_note': 'Sentinel project deliberately changes both final shader files after ordinary overlay construction; current shader hashes above are the diagnostic sources.'})
    inspect_path = root / 'carrier-project-v2/resource_pack/shaders/glsl/scene_codec_inspect.fragment'
    source = inspect_path.read_text(encoding='utf-8')
    require('raw=texture2D(TEXTURE_5,loc)' in source and 'oracleSymbol(index)' in source and
            'floor(alpha+0.5)/255.0' in source and 'step(0.0001,abs(alpha-floor(alpha+0.5)))' in source,
            'Same-frame diagnostic no longer obtains RGB and alpha from one sample')
    return {'projects': result, 'sameframe_diagnostic_source_sha256': sha(inspect_path),
            'sameframe_diagnostic_semantics': 'R=bad 6-bit payload symbol, G=raw alpha byte, B=off-byte-grid flag; known salt29/64KiB fixture only.'}


def process_receipts(root):
    result = []
    for directory, filename in (('carrier-evidence-v1', 'exit_check_detail.json'), ('carrier-evidence-v2', 'exit_check.json'),
                                ('carrier-evidence-v2b', 'exit_check.json'), ('native-sentinel-evidence-v1', 'exit_check.json')):
        path = root / directory / filename
        receipt = load(path)
        exit_code = receipt.get('exit_code')
        require(receipt.get('not_running') is True or (exit_code is not None and exit_code != 259),
                'Exit receipt does not establish process release: ' + str(path))
        launch_path = root / directory / 'launch.json'
        launch = load(launch_path)
        require(launch['fps'] == 60 and launch['background_only'], 'Launch did not declare 60 FPS/background')
        result.append({'evidence': directory, 'exit_receipt': receipt, 'exit_receipt_sha256': sha(path),
                       'launch_receipt_sha256': sha(launch_path),
                       'limitation': 'Saved process status evidence; audit does not query or operate live processes.'})
    return result


def audit(root):
    root = Path(root).resolve()
    documents = {name: load(root / relative) for name, relative in DOCUMENTS.items()}
    receipts, command_count = [], 0
    for name, document in documents.items():
        directory = (root / DOCUMENTS[name]).parent
        receipts.extend(check_report_integrity(report, directory) for report in document['reports'])
        command_count += check_commands(document, directory)
    return {'kind': 'independent_scene_codec_compat_audit_v1', 'independent_of_probe_codec_and_verifier': True,
            'audit_source_sha256': sha(Path(__file__)),
            'source_summary_sha256': {relative: sha(root / relative) for relative in DOCUMENTS.values()},
            'capture_count': len(receipts), 'capture_state_receipt_hashes_checked': len(receipts)*3,
            'command_hashes_checked': command_count, 'capture_receipts': receipts,
            'real_scenes': real_audit(documents['real'], root / 'carrier-evidence-v1'),
            'rain_isolation': isolation_audit(documents['isolation'], root / 'carrier-evidence-v1'),
            'rain_sameframe': sameframe_audit(documents['sameframe']),
            'native_sentinels': sentinel_audit(documents['sentinel'], root / 'native-sentinel-evidence-v1', root / 'native-sentinel-project-v1'),
            'native_math_attempt': math_audit(documents['math']), 'dynamic_chain_lifecycle': lifecycle_audit(root),
            'resources': resource_audit(root), 'owned_process_release': process_receipts(root),
            'all_native_compatibility_passed': False,
            'native_bloom_replacement_succeeded': False,
            'exact_identity_baseline_equivalence_established': False,
            'independent_visual_observations': {
                'water_glass': 'Water surface and glass panes visible over the wall/floor; sampled source alpha remains 255.',
                'rain': 'Rain streaks and splashes visibly overlap the scene; payload failure remains recorded.',
                'glint_emissive': 'Two glowstone blocks and a bow visible; server receipt confirms enchanted bow, not quantitative bloom activation.',
                'particle': 'Pink translucent particles visible in front of the wall and overlapping the carrier ROI; sampled alpha remains 255.'},
            'limits': ['This is a bounded observed-scene audit; rain is incompatible in this carrier configuration.',
                       'The identity package was built but not launched; exact no-carrier equivalence was not established.',
                       'DOF sentinel execution proves the hook executes, not complete native-math or image equivalence.',
                       'Native bloom sentinel absence prevents claiming the derived final sampler repair was applied.',
                       'All byte-coded alpha diagnostics have finite PNG/threshold precision.',
                       'No FPS or GPU-cost conclusion follows from these correctness screenshots.']}


def self_test():
    expected, distinct = expected_query(0)
    require(distinct == PAYLOAD_BYTES and compare(expected, expected)['passed'], 'Identity oracle failure')
    expected, distinct = expected_query(2)
    require(distinct == 48449, 'Dependent address coverage differs')
    mutant = expected.copy()
    mutant[31, 1] ^= 1
    require(compare(mutant, expected)['mismatch_samples'] == 1, 'PNG channel mutation missed')
    symbols = oracle_symbols()
    require(len(symbols) == SOURCE_PIXELS and symbols.max() <= 63, 'Symbol range invalid')
    return {'passed': True, 'dependent_distinct_addresses': distinct, 'synthetic_channel_mutation_detected': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test()))
    result = audit(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('capture_count', 'capture_state_receipt_hashes_checked',
                                                  'command_hashes_checked', 'all_native_compatibility_passed',
                                                  'native_bloom_replacement_succeeded')}))
