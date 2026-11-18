"""Host-only independent PNG/bitmask audit; never import the probe codecs.

Fixtures are arithmetic inputs, not hardware-blend evidence. Native geometry
receives a separate classification and must reject hidden-writer controls.
Known failed observations remain failed even when later captures recover.
"""

import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import numpy as np
from PIL import Image


SCREEN = (720, 1080)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def oracle(indices, salt):
    indices = np.asarray(indices, dtype=np.int64)
    return (((indices & 255) * 73 + ((indices // 251) & 255) * 19 + salt) & 255).astype(np.uint8)


def expected_addresses(count, mode, salt):
    address = np.arange(count, dtype=np.int64)
    if mode:
        address = (131 * address + 29) % count
    if mode == 2:
        address = (address + 257 * oracle(address, salt).astype(np.int64) + 113) % count
    return address


def round_ratio(numerator, denominator):
    return (2 * numerator + denominator) // (2 * denominator)


def expected_alpha(indices, mode, base):
    local = indices % 32
    result = np.full(len(indices), base, dtype=np.uint8)
    if mode == 1:
        for rank, position in enumerate((0, 7, 16, 31)):
            result[local == position] = (base + rank + 1) % 256
    elif mode == 2:
        for position in range(5):
            result[local == position] = (base + position + 1) % 256
    elif mode == 3:
        result = (indices % 256).astype(np.uint8)
    return result


def pack_alpha_independently(alpha, payload, base):
    require(len(alpha) == 32 and len(payload) <= 24, 'Invalid independent alpha block')
    positions = [index for index, value in enumerate(alpha) if value != base]
    require(len(positions) <= 4, 'Independent alpha overflow')
    mask = sum(1 << position for position in positions)
    header = [(mask >> (8 * group)) & 255 for group in range(4)]
    exceptions = [int(alpha[position]) for position in positions]
    return np.asarray(header + exceptions + [0] * (4-len(exceptions)) +
                      list(payload) + [0] * (24-len(payload)), dtype=np.uint8)


def unpack_alpha_independently(encoded, base):
    mask = sum(int(encoded[index]) << (index * 8) for index in range(4))
    require(bin(mask).count('1') <= 4, 'Overflow block must not silently decode')
    alpha = []
    rank = 0
    for position in range(32):
        exceptional = (mask >> position) & 1
        alpha.append(int(encoded[4+rank]) if exceptional else base)
        rank += exceptional
    return np.asarray(alpha, dtype=np.uint8), np.asarray(encoded[8:], dtype=np.uint8)


def read_pixels(path):
    with Image.open(path) as image:
        require(image.size == SCREEN, 'Require an unscaled native720x1080 PNG')
        return np.asarray(image.convert('RGBA'), dtype=np.uint8)


def extract(path, count, native):
    pixels = read_pixels(path)
    ordinal = np.arange(count, dtype=np.int64)
    if native:
        require(count <= 720 * 936, 'Native query exceeds its declared safe rectangle')
        return pixels[128+ordinal//720, ordinal%720][:, None, :]
    rows = (count+63)//64
    # Exact integer center coordinates; no dependency on runner math/floats.
    x = ((2*(ordinal % 64)+1)*720)//128
    y = 128 + ((2*(ordinal//64)+1)*936)//(2*rows)
    return np.stack([pixels[y+dy, x+dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)], axis=1)


def compare(samples, expected, tolerance=0):
    expected = np.asarray(expected, dtype=np.int16)
    if expected.ndim == 1:
        expected = np.repeat(expected[:, None], 3, axis=1)
    require(samples.shape[0] == expected.shape[0] and expected.shape[1] == 3, 'Incomplete pixel oracle')
    errors = np.max(np.abs(samples[:, :, :3].astype(np.int16)-expected[:, None, :]), axis=(1, 2))
    errors = np.maximum(errors, np.max(255-samples[:, :, 3].astype(np.int16), axis=1))
    failed = errors > tolerance
    return {'passed': not bool(np.any(failed)), 'checked_samples': len(samples),
            'sample_pixels_checked': int(samples.shape[0]*samples.shape[1]),
            'mismatch_samples': int(np.count_nonzero(failed)), 'maximum_channel_error': int(errors.max()),
            'tolerance': tolerance, 'error_histogram': dict(sorted(Counter(map(int, errors)).items())),
            'observed_first_patch_pixel_sha256': hashlib.sha256(samples[:, 0].tobytes()).hexdigest()}


def artifact_path(evidence, recorded):
    # Some ad-hoc followup records have mojibake in the absolute parent path;
    # filenames are ASCII. Resolve only an existing same-directory basename.
    path = evidence / Path(recorded).name
    require(path.is_file(), 'Missing evidence file: '+str(path))
    return path


def validate_artifact(evidence, report):
    path = artifact_path(evidence, report['capture'])
    state_path = path.with_suffix('.state.json')
    receipt_path = path.with_suffix('.json')
    state = load(state_path)
    receipt = load(receipt_path)
    require(state == report['state'], 'Embedded state differs from the frozen receipt')
    require(sha(path) == report['capture_sha256'] and sha(state_path) == report['state_sha256'] and
            sha(receipt_path) == report['capture_receipt_sha256'], 'Capture/state/WGC receipt hash mismatch')
    require(receipt.get('ok') is True and receipt.get('backend') == 'Windows.Graphics.Capture' and
            receipt.get('agent_activation_allowed') is False, 'Invalid passive native capture receipt')
    require(receipt.get('frame_qpc_100ns', -1) >= receipt.get('request_qpc_100ns', 0), 'Capture frame is stale')
    require(receipt.get('background_only') or receipt.get('user_foreground_allowed'), 'Capture policy missing')
    require(state.get('schema') == 'scene_codec_probe_v1' and state.get('screen_size') == list(SCREEN),
            'Unexpected codec receipt dimensions/schema')
    require(state.get('game_runtime_file_writes') is False and state.get('error') is None,
            'Runtime file/error contract failed')
    require(state.get('pipeline_ready') is True and all(link[3] is True for link in state['codec_connections']),
            'Forward dataflow is not ready')
    return path, state


def source_audit(project):
    package = project/'behavior_pack/geometry_atlas_probe'
    runtime = (package/'runtime.py').read_text(encoding='utf-8')
    parsed = ast.parse(runtime)
    methods = {node.name: node for node in ast.walk(parsed) if isinstance(node, ast.FunctionDef)}
    configure = ast.get_source_segment(runtime, methods['configure_codec'])
    upload = ast.get_source_segment(runtime, methods['load_payload'])
    parameters = methods['_params']
    default_mode = parameters.args.defaults[0]
    require(isinstance(default_mode, ast.Constant) and default_mode.value == 0, 'Encode mode default is not scene0')
    require("self._params(name)" in configure and "'scene_codec_fixture'" in configure and
            "enabled = name not in" in configure and "SetEnableByName(name, enabled)" in configure,
            'Cannot establish configure disables fixture and resets parameters')
    require('self.configure_codec()' in upload and "self.codec_mode = 'geometry_rgb'" in upload,
            'Native memory upload does not reset the fixture path')
    shaders = project/'resource_pack/shaders/glsl'
    encoder = (shaders/'scene_codec_alpha_block_encode.fragment').read_text(encoding='utf-8')
    consumer = (shaders/'scene_codec_payload_consumer.fragment').read_text(encoding='utf-8')
    require('EXTRA_VECTOR1.z > 0.5' in encoder and 'texture2D(TEXTURE_1, location)' in encoder,
            'Scene encoder source selector is unexpected')
    require('payloadOracle' not in encoder and 'payloadOracle' not in consumer,
            'A native data shader synthesizes the known oracle')
    material = load(project/'resource_pack/materials/terrain.material')['materials'][
        'pmanim_geometry_atlas:netease_block_as_entity_mesh']
    require(material['blendSrc'] == 'SourceAlpha' and material['blendDst'] == 'OneMinusSrcAlpha' and
            'DisableAlphaWrite' in material['+states'] and 'DisableRGBWrite' in material['-states'],
            'Native geometry blend/alpha-write material differs from the intended dataflow')
    raw = (shaders/'scene_codec_copy.fragment').read_text(encoding='utf-8')
    require('TEXTURE_1' in raw and 'payloadOracle' not in raw, 'Raw producer is not a live scene copy')
    files = [package/'runtime.py', package/'scene_config.py', shaders/'scene_codec_alpha_block_encode.fragment',
             shaders/'scene_codec_payload_consumer.fragment', shaders/'scene_codec_fixture.fragment',
             shaders/'scene_codec_scatter.fragment', project/'resource_pack/materials/terrain.material']
    return {'files': [{'path': str(path), 'sha256': sha(path)} for path in files],
            'fixture_disabled_after_native_upload_by_source_contract': True,
            'native_encoder_scene_mode': 0, 'native_shaders_synthesize_oracle': False,
            'direct_process_enabled_snapshot_available': False,
            'fixture_off_evidence': 'installed runtime reset plus unchanged hidden-writer negative control'}


def fixture_expectation(state, report_name, count):
    bits, base, salt = state['rgb_bits'], state['base_alpha'], state['payload_salt']
    fixture = int(state['codec_mode'].rsplit('_', 1)[1])
    index = np.arange(count, dtype=np.int64)
    if report_name.endswith('_query0') or report_name.endswith('_query1') or report_name.endswith('_query2'):
        mode = int(report_name[-1])
        return oracle(expected_addresses(count, mode, salt), salt)
    if report_name.startswith('overflow_'):
        require(fixture in (2, 3), 'Overflow control uses a compressible fixture')
        return np.tile((255, 0, 255), (count, 1))
    alpha = expected_alpha(index, fixture, base)
    if report_name.endswith('_alpha'):
        return alpha
    if report_name.endswith('_rgb'):
        value = index % 256
        rgb = np.column_stack((value, (73*value+19) % 256, (151*value+47) % 256))
        levels = 1 << (8-bits)
        quantized = round_ratio((levels-1)*rgb, 255)
        return round_ratio(255*quantized, levels-1)
    require(report_name.endswith('_header'), 'Unknown fixture observation')
    result = []
    for start in range(0, count, 32):
        block = start//32
        payload = oracle(np.arange(block*12*bits, (block+1)*12*bits), salt)
        encoded = pack_alpha_independently(alpha[start:start+32], payload, base)
        decoded_alpha, decoded_payload = unpack_alpha_independently(encoded, base)
        require(np.array_equal(decoded_alpha, alpha[start:start+32]) and
                np.array_equal(decoded_payload[:12*bits], payload), 'Independent alpha codec identity failed')
        result.extend(map(int, encoded))
    return result


def frozen_native(state):
    fields = ('geometry_name', 'entity', 'generation', 'epoch', 'native_attempt_serial',
              'geometry_build_serial', 'slot_count', 'codec_roi', 'logical_payload_bytes',
              'allocated_payload_bytes', 'rgb_bits', 'payload_salt', 'base_alpha')
    return {field: state[field] for field in fields}


def audit(evidence, project):
    evidence, project = evidence.resolve(), project.resolve()
    source = source_audit(project)
    summaries = []
    all_reports = []
    by_name = {}
    command_count = 0
    for summary_path in sorted(evidence.glob('*.results.json')):
        summary = load(summary_path)
        require(summary.get('error') is None, 'A completed stage contains an execution error')
        summaries.append({'path': str(summary_path), 'sha256': sha(summary_path), 'passed': summary.get('passed')})
        for event in summary.get('events', []):
            if event.get('command_sha256'):
                command = evidence/'commands'/(event['label']+'.py')
                require(sha(command) == event['command_sha256'], 'Injected control command hash mismatch')
                command_count += 1
        for report in summary.get('reports', []):
            if 'capture' not in report:
                continue
            path, state = validate_artifact(evidence, report)
            entry = {'summary': summary_path.name, 'name': report['name'], 'path': path,
                     'state': state, 'original': report}
            all_reports.append(entry)
            by_name[(summary_path.name, report['name'])] = entry
    require(all_reports, 'No native capture reports found')
    results = []
    native_groups = {}
    alpha_result = {}
    alpha_gray = None
    for entry in all_reports:
        state, name, report, path = entry['state'], entry['name'], entry['original'], entry['path']
        base = {'summary': entry['summary'], 'name': name, 'capture': str(path), 'sha256': sha(path)}
        stage_native = re.match(r'native_k([12])_bytes(\d+)_(.+)$', name)
        if stage_native:
            require(state['codec_mode'] == 'geometry_rgb' and not state['updates_running'] and
                    state['pending_upload'] is None, 'Native geometry was replaced by a fixture or update')
            key = (entry['summary'], int(stage_native[1]), int(stage_native[2]))
            native_groups.setdefault(key, {})[stage_native[3]] = entry
            continue
        if name.startswith('fixture_') or name.startswith('overflow_'):
            require(state['codec_mode'].startswith('independent_fixture_') and not state['writer_visible'],
                    'Fixture/native classification is inconsistent')
            count = state['query'][1]
            expected = fixture_expectation(state, name, count)
            result = compare(extract(path, count, False), expected)
            require(result['passed'], 'Independent fixture codec/overflow replay failed: '+name)
            results.append(dict(base, category='arithmetic_fixture_only', independent=result))
        elif name.startswith('alpha_'):
            region = read_pixels(path)[128:1064]
            require(not state['writer_visible'], 'Raw alpha observation has an active writer')
            if name == 'alpha_gray':
                alpha_gray = region[:, :, 0].copy()
                values, counts = np.unique(region[:, :, 0], return_counts=True)
                alpha_result['histogram'] = dict(zip(map(int, values), map(int, counts)))
                alpha_result['safe_pixels'] = int(region.shape[0]*region.shape[1])
                alpha_result['non_gray_pixels'] = int(np.count_nonzero(
                    np.any(region[:, :, :3] != region[:, :, 0, None], axis=2)))
                require(alpha_result['non_gray_pixels'] == 0, 'Raw-alpha histogram contains overlay/color contamination')
            elif name == 'alpha_grid':
                alpha_result['off_unorm8_flag_pixels'] = int(np.count_nonzero(region[:, :, 2] > 127))
                alpha_result['maximum_residual_display_byte'] = int(region[:, :, 1].max())
            elif name == 'alpha_blocks':
                blocks = region.reshape(-1, 32, 4)
                counts = (blocks[:, 0, 0].astype(np.int64)*32*2+255)//510
                overflow = blocks[:, 0, 1] > 127
                require(np.all((counts > 4) == overflow), 'Alpha block overflow flags disagree with count display')
                require(alpha_gray is not None, 'Raw alpha gray observation is missing')
                gray_exception_counts = np.count_nonzero(alpha_gray.reshape(-1, 32) != state['base_alpha'], axis=1)
                require(np.array_equal(counts, gray_exception_counts),
                        'GPU block counts disagree with independently counted raw alpha bytes')
                alpha_result['exception_count_histogram'] = dict(Counter(map(int, counts)))
                alpha_result['valid_blocks'] = int(np.count_nonzero(~overflow))
                alpha_result['overflow_blocks'] = int(np.count_nonzero(overflow))
                alpha_result['conditional_alpha_payload_bytes'] = int(np.count_nonzero(~overflow))*24
            results.append(dict(base, category='raw_scene_alpha_diagnostic'))
        elif name.startswith('calibration_') or name.startswith('gpu_'):
            count = state['query'][1]
            index = np.arange(count, dtype=np.int64)
            if name.startswith('calibration_'):
                expected = index % 256
            elif name == 'gpu_fragment_coordinates':
                x = index % 720
                y = 1079-(128+index//720)
                expected = np.column_stack((x % 256, y % 256, x//256+4*(y//256)))
            else:
                values = np.array((720, 1080, 23302, 15534))
                expected = np.column_stack((values % 256, (values//256) % 256, values//65536))
            result = compare(extract(path, count, state['query'][2] >= 10), expected)
            require(result['passed'], 'Native sampling/coordinate calibration failed')
            results.append(dict(base, category='output_coordinate_calibration', independent=result))
    group_results = []
    for (summary_name, bits, logical), members in sorted(native_groups.items()):
        required = ('baseline', 'baseline_repeat', 'baseline_alpha', 'restored', 'writer_alpha',
                    'same_frame_alpha_error', 'query0', 'query1', 'query2', 'hidden')
        require(all(name in members for name in required), 'Native case omitted a required control')
        initial = members['baseline']['state']
        pixels = initial['slot_count']
        frozen = frozen_native(initial)
        allocated = initial['allocated_payload_bytes']
        require(pixels*3*bits == allocated*8 and initial['codec_roi'][2]*initial['codec_roi'][3] == pixels,
                'Logical/allocated/geometry dimensions disagree')
        require(logical <= allocated and initial['logical_payload_bytes'] == logical and
                pixels % 32 == 0, 'Invalid logical/allocated block length')
        checks = {}
        samples = {key: extract(value['path'], pixels if key not in ('query0', 'query1', 'query2', 'hidden')
                                else logical, True) for key, value in members.items()}
        baseline_rgb = samples['baseline'][:, 0, :3]
        baseline_alpha = samples['baseline_alpha'][:, 0, :3]
        for key, value in members.items():
            state = value['state']
            require(frozen_native(state) == frozen, 'Geometry/array identity changed within a native test')
            should_show = key in ('restored', 'writer_alpha', 'same_frame_alpha_error', 'query0', 'query1', 'query2')
            require(state['writer_visible'] is should_show, 'Native writer visibility receipt is wrong')
            expected_modes = {'baseline': 11, 'baseline_repeat': 11, 'baseline_alpha': 10, 'restored': 12,
                'writer_alpha': 10, 'same_frame_alpha_error': 20, 'query0': 3, 'query1': 4, 'query2': 5, 'hidden': 3}
            require(state['query'][:3] == [0, logical if key.startswith('query') or key == 'hidden' else pixels,
                                          expected_modes[key]], 'Native query layout/mode mismatch')
        checks['baseline_repeat'] = compare(samples['baseline_repeat'], baseline_rgb)
        checks['restored_rgb'] = compare(samples['restored'], baseline_rgb, bits)
        checks['raw_alpha_preserved'] = compare(samples['writer_alpha'], baseline_alpha)
        checks['same_frame_alpha_restore'] = compare(samples['same_frame_alpha_error'], np.zeros(pixels, dtype=np.uint8))
        for mode in range(3):
            expected = oracle(expected_addresses(logical, mode, initial['payload_salt']), initial['payload_salt'])
            checks['query%d' % mode] = compare(samples['query%d' % mode], expected)
        checks['hidden_negative'] = compare(samples['hidden'], oracle(np.arange(logical), initial['payload_salt']))
        require(checks['hidden_negative']['mismatch_samples'] > logical*0.9, 'Hidden geometry did not reject the payload')
        require(all(checks[key]['passed'] for key in ('baseline_repeat', 'raw_alpha_preserved',
            'same_frame_alpha_restore', 'query0', 'query1', 'query2')), 'A native data/alpha/stability proof failed')
        for key in ('baseline_repeat', 'restored_rgb', 'raw_alpha_preserved', 'same_frame_alpha_restore'):
            original_key = {'restored_rgb': 'restored', 'raw_alpha_preserved': 'writer_alpha',
                            'same_frame_alpha_restore': 'same_frame_alpha_error'}.get(key, key)
            require(checks[key]['mismatch_samples'] == members[original_key]['original']['mismatch_samples'] and
                    checks[key]['maximum_channel_error'] == members[original_key]['original']['maximum_channel_error'],
                    'Original and independent RGB/alpha replay disagree')
        group_results.append({'summary': summary_name, 'rgb_bits': bits, 'logical_bytes': logical,
            'allocated_bytes': allocated, 'geometry_pixels': pixels, 'frozen_identity': frozen,
            'checks': checks, 'payload_and_alpha_passed': True,
            'rgb_bound_passed': checks['restored_rgb']['passed'], 'fixture_path_used': False,
            'rgb_comparison_uses_separate_scene_captures': True})
    followups = []
    scene_change_controls = []
    for summary in summaries:
        if 'followup' not in Path(summary['path']).name:
            continue
        members = {entry['name']: entry for entry in all_reports if entry['summary'] == Path(summary['path']).name}
        if not all(name in members for name in ('off_before', 'off_repeat', 'on_restored', 'on_encoded', 'off_after')):
            continue
        state = members['off_before']['state']
        count, bits, logical = state['slot_count'], state['rgb_bits'], state['logical_payload_bytes']
        require(all(entry['state']['codec_mode'] == 'geometry_rgb' and
                    frozen_native(entry['state']) == frozen_native(state) for entry in members.values()),
                'Followup changes the native array identity')
        values = {name: extract(entry['path'], count, True) for name, entry in members.items()}
        original = values['off_before'][:, 0, :3].astype(np.int64)
        encoded = values['on_encoded'][:, 0, :3].astype(np.int64)
        allocated = state['allocated_payload_bytes']
        payload = np.zeros(allocated, dtype=np.int64)
        payload[:logical] = oracle(np.arange(logical), state['payload_salt'])
        indices = np.arange(count)
        symbols = np.zeros(count, dtype=np.int64)
        for bit in range(3*bits):
            address = indices*3*bits+bit
            symbols |= ((payload[address//8] >> (address % 8)) & 1) << bit
        channel_payload = np.column_stack([(symbols >> (channel*bits)) & ((1 << bits)-1) for channel in range(3)])
        levels = 1 << (8-bits)
        expected_encoded = levels*channel_payload+round_ratio((levels-1)*original, 255)
        decoded = round_ratio((encoded % levels)*255, levels-1)
        checks = {'off_repeat': compare(values['off_repeat'], original),
                  'off_after': compare(values['off_after'], original),
                  'native_blended_rgb_exact': compare(values['on_encoded'], expected_encoded),
                  'restored_from_encoded_exact': compare(values['on_restored'], decoded),
                  'rgb_error_bound': compare(values['on_restored'], original, bits)}
        require(all(item['passed'] for item in checks.values()), 'Native blend followup failed')
        followups.append({'summary': Path(summary['path']).name, 'checks': checks,
                          'all_allocated_payload_bits_checked_in_raw_RGB': allocated*8,
                          'includes_zero_padding_bytes': allocated-logical, 'fixture_path_used': False})
    for summary in summaries:
        if 'steady' not in Path(summary['path']).name:
            continue
        members = {entry['name']: entry for entry in all_reports if entry['summary'] == Path(summary['path']).name}
        require(all(name in members for name in ('on', 'on_repeat', 'off_after')),
                'Steady visibility control is incomplete')
        state = members['on']['state']
        count, bits = state['slot_count'], state['rgb_bits']
        candidate = [entry for entry in all_reports if entry['name'] ==
            'native_k%d_bytes%d_baseline' % (bits, state['logical_payload_bytes']) and
            frozen_native(entry['state']) == frozen_native(state)]
        require(len(candidate) == 1, 'Steady followup has an ambiguous frozen baseline')
        baseline = extract(candidate[0]['path'], count, True)[:, 0, :3]
        checks = {}
        for name, entry in members.items():
            require(frozen_native(entry['state']) == frozen_native(state) and
                    entry['state']['codec_mode'] == 'geometry_rgb', 'Steady control changed the array')
            expected_visible = name != 'off_after'
            require(entry['state']['writer_visible'] is expected_visible, 'Steady writer visibility mismatch')
            checks[name] = compare(extract(entry['path'], count, True), baseline, bits if expected_visible else 0)
            require(checks[name]['mismatch_samples'] == entry['original']['mismatch_samples'] and
                    checks[name]['maximum_channel_error'] == entry['original']['maximum_channel_error'],
                    'Steady source-change replay differs from the recorded pixel facts')
        require(checks['on']['passed'] and checks['on_repeat']['passed'], 'Steady on frames exceed the RGB bound')
        scene_change_controls.append({'summary': Path(summary['path']).name, 'checks': checks,
            'off_after_matches_earlier_baseline': checks['off_after']['passed'],
            'cause_of_source_change_assigned': False,
            'interpretation': 'Separate natural-scene captures can differ; preserve initial RGB failures'})
    require(len(group_results) >= 4 and len(results) >= 39, 'Required fixture/alpha/native evidence is incomplete')
    failed_rgb = [{'summary': item['summary'], 'rgb_bits': item['rgb_bits'], 'logical_bytes': item['logical_bytes'],
        'mismatch_samples': item['checks']['restored_rgb']['mismatch_samples'],
        'maximum_channel_error': item['checks']['restored_rgb']['maximum_channel_error']}
        for item in group_results if not item['rgb_bound_passed']]
    return {'schema': 'independent_scene_codec_audit_v1', 'audit_completed': True,
            'all_initial_observations_passed': not failed_rgb,
            'native_payload_and_alpha_passed': True, 'initial_RGB_failures_preserved': failed_rgb,
            'native_blend_followups': followups, 'raw_alpha': alpha_result, 'native_groups': group_results,
            'steady_visibility_and_scene_change_controls': scene_change_controls,
            'fixture_calibration_and_alpha_captures': results, 'source_contract': source,
            'summary_files': summaries, 'control_command_hashes_checked': command_count,
            'capture_count': len(all_reports), 'probe_codec_or_verifier_imported': False,
            'mc_or_GPU_accessed': False, 'capacity_is_not_RGB_plus_alpha_sum': True,
            'fixture_passes_are_hardware_blend_evidence': False,
            'timing_or_FPS_claim': False,
            'scope': 'Known PNGs and code contracts; initial RGB transients retain failure status'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), 'Preserve previous audits; select a new output')
    try:
        result = audit(args.evidence, args.project)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {'schema': 'independent_scene_codec_audit_v1', 'audit_completed': False,
                  'error': '%s: %s' % (type(error).__name__, error),
                  'probe_codec_or_verifier_imported': False, 'mc_or_GPU_accessed': False}
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
        return 1
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'audit_completed': result['audit_completed'],
        'native_payload_and_alpha_passed': result['native_payload_and_alpha_passed'],
        'all_initial_observations_passed': result['all_initial_observations_passed'],
        'initial_RGB_failures': result['initial_RGB_failures_preserved'],
        'captures': result['capture_count'], 'output': str(args.output.resolve())}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
