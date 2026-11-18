"""Host-only independent RGB-domain, duplicate-blend and historical audit.

No scene-codec implementation or verifier is imported. Integer fractions derive
the blend from the documented shader coefficient and UNORM8 target rounding.
Screenshots and receipts are read only; this tool never controls Minecraft.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def round_fraction(numerator, denominator):
    return (2 * numerator + denominator) // (2 * denominator)


def known_original(count):
    red = np.arange(count, dtype=np.int64) % 256
    return np.stack((red, (red * 73 + 19) % 256, (red * 151 + 47) % 256), axis=1)


def payload_digits(symbols, bits):
    return np.stack([(symbols >> (bits * channel)) % (1 << bits) for channel in range(3)], axis=1)


def blend(original, symbols, bits, draws=1):
    levels = 1 << (8 - bits)
    digits = payload_digits(symbols, bits)
    result = np.asarray(original, dtype=np.int64)
    for _ in range(draws):
        result = digits * levels + round_fraction(result * (levels - 1), 255)
    return result


def decode(encoded, bits):
    levels = 1 << (8 - bits)
    return round_fraction((encoded % levels) * 255, levels - 1)


def payload_byte(address, salt):
    return ((address % 256) * 73 + ((address // 251) % 256) * 19 + salt) % 256


def stream_symbols(count, bits, byte_count, salt):
    indices = np.arange(count, dtype=np.int64)
    result = np.zeros(count, dtype=np.int64)
    for shift in range(3 * bits):
        address = indices * (3 * bits) + shift
        byte_address = address // 8
        value = np.where(byte_address < byte_count, payload_byte(byte_address, salt), 0)
        result |= ((value >> (address % 8)) & 1) << shift
    return result


def read_pixels(path, state):
    with Image.open(path) as image:
        require(image.size == (720, 1080), 'Unexpected capture resolution: ' + str(path))
        pixels = np.asarray(image.convert('RGB'), dtype=np.int64)
    _, count, mode, _ = state['query']
    ordinal = np.arange(count)
    if mode >= 10 or mode in (3, 4, 5):
        xs, ys = ordinal % 720, 128 + ordinal // 720
    else:
        rows = (count + 63) // 64
        xs = np.floor((ordinal % 64 + .5) * 720 / 64).astype(int)
        ys = np.floor(128 + (ordinal // 64 + .5) * 936 / rows).astype(int)
    return pixels[ys, xs]


def comparison(observed, expected, tolerance=0):
    require(observed.shape == expected.shape, 'Comparison shape mismatch')
    delta = np.abs(observed - expected)
    errors = np.max(delta, axis=1)
    bad = errors > tolerance
    selected = np.flatnonzero(bad)
    return {'passed': not bool(np.any(bad)), 'checked_pixels': len(observed),
            'mismatch_pixels': int(np.count_nonzero(bad)),
            'maximum_channel_error': int(delta.max()) if delta.size else 0,
            'tolerance': tolerance,
            'error_histogram': {str(int(key)): int(value) for key, value in Counter(errors.tolist()).items()},
            'first_failures': [{'ordinal': int(index), 'expected': expected[index].tolist(),
                                'observed': observed[index].tolist()} for index in selected[:5]]}


def integrity(report, evidence):
    path = Path(report['capture'])
    require(path.resolve().parent == evidence, 'Capture is outside evidence directory')
    state_path, receipt_path = path.with_suffix('.state.json'), path.with_suffix('.json')
    checks = [(path, report['capture_sha256']), (state_path, report['state_sha256']),
              (receipt_path, report['capture_receipt_sha256'])]
    for file, expected in checks:
        require(sha(file) == expected, 'SHA256 mismatch: ' + str(file))
    state, receipt = load(state_path), load(receipt_path)
    require(state == report['state'], 'Embedded and saved state differ: ' + str(path))
    require(receipt['ok'] and receipt['backend'] == 'Windows.Graphics.Capture' and
            receipt['native_resolution'] and receipt['width'] == 720 and receipt['height'] == 1080,
            'Invalid native capture receipt: ' + str(path))
    require(receipt.get('agent_activation_allowed') is False, 'Agent activation permission changed')
    require(receipt['frame_qpc_100ns'] >= receipt['request_qpc_100ns'], 'Capture frame predates request')
    for label in ('background_before', 'background_after'):
        require(report[label]['window_noactivate'], 'Noactivation receipt absent')
        require(report[label]['background_safe'], 'Background capture rejected')
    require(state.get('game_runtime_file_writes') is False and state.get('direct_source') is False,
            'Unexpected game-file or direct-texture source')
    require(state.get('error') is None, 'Runtime state contains an error')
    return {'capture': path.name, 'sha256': report['capture_sha256'], 'pid': receipt['pid'],
            'hash_checks': 3, 'receipt_noactivation': True,
            'user_foreground_allowed': bool(report['user_foreground_allowed'])}


def event_integrity(document, evidence):
    count = 0
    for event in document.get('events', []):
        if 'command_sha256' not in event:
            continue
        path = evidence / 'commands' / (event['label'] + '.py')
        require(sha(path) == event['command_sha256'], 'Command SHA mismatch: ' + str(path))
        count += 1
    return count


def setup_audit(document, evidence):
    result = []
    for report in document['reports']:
        state = report['state']
        observed = read_pixels(report['capture'], state)
        count = state['query'][1]
        if report['name'] in ('calibration_7', 'calibration_17'):
            expected = np.repeat((np.arange(count) % 256)[:, None], 3, axis=1)
        elif report['name'] == 'gpu_fragment_coordinates':
            ordinal = np.arange(count)
            x, y_gl = ordinal % 720, 1079 - (128 + ordinal // 720)
            expected = np.stack((x % 256, y_gl % 256, x // 256 + 4 * (y_gl // 256)), axis=1)
        elif report['name'] == 'gpu_screen_info':
            values = np.array([720, 1080, (16777216 + 360) // 720, (16777216 + 540) // 1080])
            expected = np.stack((values % 256, values // 256 % 256, values // 65536), axis=1)
        else:
            raise ValueError('Unknown setup report: ' + report['name'])
        result.append({'name': report['name'], **comparison(observed, expected)})
    return result


def domain_audit(document):
    result = []
    for report in document['reports']:
        state, name = report['state'], report['name']
        bits, count = state['rgb_bits'], state['query'][1]
        require(state['code_domain_sweep'] and count == 256 * (1 << (3 * bits)), 'Incomplete RGB code domain')
        require('scene_codec_fixture' not in state['codec_enabled_processes'], 'Arithmetic producer fixture was enabled')
        observed = read_pixels(report['capture'], state)
        original, symbols = known_original(count), np.arange(count) // 256
        if name.endswith('_background_hidden'):
            check = comparison(observed, original)
            check['passed'] = check['mismatch_pixels'] == count
            check['expectation'] = 'Every pixel differs from the known geometry background when it is hidden'
            require(not state['native_background_visible'] and not state['writer_visible'], 'Hidden control has a visible producer')
        elif name.endswith('_alpha_error'):
            check = comparison(observed, np.zeros_like(original))
        elif name.endswith('_restored'):
            check = comparison(observed, decode(blend(original, symbols, bits), bits))
            check['vs_original'] = comparison(observed, original, tolerance=bits)
        elif name.endswith('_encoded'):
            check = comparison(observed, blend(original, symbols, bits))
            levels = 1 << (8 - bits)
            check['payload_high_bit_mismatches'] = int(np.count_nonzero(np.any(
                observed // levels != payload_digits(symbols, bits), axis=1)))
        else:
            check = comparison(observed, original)
            require(not state['writer_visible'] and state['native_background_visible'], 'Background reference producer state differs')
        check.update({'name': name, 'rgb_bits': bits, 'source_pixels': count,
                      'original_values_per_channel': 256, 'rgb_symbol_combinations': 1 << (3 * bits)})
        result.append(check)
    require(len(result) == 24, 'Expected four six-capture domain cases')
    return result


def duplicate_audit(document):
    result = []
    for report in document['reports']:
        state = report['state']
        require(state['rgb_bits'] == 2 and state['query'][1] == 16384, 'Unexpected duplicate scope')
        require(state['native_attachment_visibility'].get('intentional_duplicate_writer'), 'Duplicate draw receipt absent')
        original, symbols = known_original(16384), np.arange(16384) // 256
        single, double = blend(original, symbols, 2), blend(original, symbols, 2, draws=2)
        if report['name'] == 'restored':
            single, double = decode(single, 2), decode(double, 2)
        observed = read_pixels(report['capture'], state)
        result.append({'name': report['name'], 'double_blend': comparison(observed, double),
                       'single_blend_negative': comparison(observed, single),
                       'vs_original_within_2': comparison(observed, original, 2)})
    require(len(result) == 2, 'Expected two intentional-duplicate captures')
    return result


def frozen_audit(document):
    reports = {item['name']: item for item in document['reports']}
    pixels = {name: read_pixels(item['capture'], item['state']) for name, item in reports.items()}
    before, repeat = pixels['off_before'], pixels['off_repeat']
    state = reports['on_restored']['state']
    count, bits = len(before), state['rgb_bits']
    symbols = stream_symbols(count, bits, state['logical_payload_bytes'], state['payload_salt'])
    result = {'classification': 'separate natural frames; failed initial comparisons remain failed',
              'source_limitation': document.get('limitation'),
              'off_repeat_vs_off_before': comparison(repeat, before),
              'off_after_vs_off_before': comparison(pixels['off_after'], before),
              'off_after_vs_off_repeat': comparison(pixels['off_after'], repeat),
              'restored_vs_off_before_within_2': comparison(pixels['on_restored'], before, 2),
              'restored_vs_off_repeat_within_2': comparison(pixels['on_restored'], repeat, 2),
              'encoded_vs_single_from_off_before': comparison(pixels['on_encoded'], blend(before, symbols, bits)),
              'encoded_vs_single_from_off_repeat': comparison(pixels['on_encoded'], blend(repeat, symbols, bits)),
              'same_frame_alpha_error': comparison(pixels['alpha_sameframe'], np.zeros_like(before)),
              'payload_queries': []}
    for name, mode in (('query0', 0), ('query2', 2)):
        report = reports[name]
        state = report['state']
        address = np.arange(state['query'][1], dtype=np.int64)
        capacity = state['logical_payload_bytes']
        if mode:
            address = (131 * address + 29) % capacity
            address = (address + 257 * payload_byte(address, state['payload_salt']) + 113) % capacity
        expected = np.repeat(payload_byte(address, state['payload_salt'])[:, None], 3, axis=1)
        result['payload_queries'].append({'name': name, 'requests': len(address),
                                          'distinct_addresses': len(np.unique(address)),
                                          **comparison(pixels[name], expected)})
    result['historical_or_natural_scene_cause_proven'] = False
    return result


def source_audit(project):
    project = Path(project).resolve()
    paths = {name: project / relative for name, relative in {
        'terrain_material': 'resource_pack/materials/terrain.material',
        'scatter_fragment': 'resource_pack/shaders/glsl/scene_codec_scatter.fragment',
        'scatter_vertex': 'resource_pack/shaders/glsl/scene_codec_scatter.vertex',
        'runtime': 'behavior_pack/geometry_atlas_probe/runtime.py',
        'base_runtime': 'behavior_pack/geometry_atlas_probe/base_runtime.py',
        'process_config': 'behavior_pack/geometry_atlas_probe/scene_config.py',
    }.items()}
    text = {name: path.read_text(encoding='utf-8') for name, path in paths.items()}
    material = json.loads(text['terrain_material'])['materials']['pmanim_geometry_atlas:netease_block_as_entity_mesh']
    require(material['blendSrc'] == 'SourceAlpha' and material['blendDst'] == 'OneMinusSrcAlpha', 'Native blend coefficients changed')
    require('DisableAlphaWrite' in material['+states'] and 'Blending' in material['+states'], 'Native blend or alpha-write state changed')
    require('EXTRA_ACTOR_UNIFORM4.w > 0.5' in text['scatter_fragment'] and
            'geometryByte' in text['scatter_fragment'] and 'mod(x*73.0+19.0,256.0)' in text['scatter_fragment'],
            'Known original is not derived from the native geometry-byte branch')
    require('(float(self.background_visible), 0., 0., 1.)' in text['runtime'], 'Background geometry branch selection changed')
    require("identifier.replace('pmanim_geometry_packet:', 'pmanim_geometry_atlas:')" in text['runtime'],
            'Background palette no longer uses shared native geometry material')
    require('forward[index]*6.' in text['runtime'] and 'forward[index]*3.' in text['base_runtime'],
            'Independent physical anchor distances changed')
    require('gl_Position = vec4(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, 0.0, 1.0)' in text['scatter_vertex'],
            'Native geometry vertex screen projection changed')
    return {'project': str(project), 'source_sha256': {name: sha(path) for name, path in paths.items()},
            'material': material, 'known_original_route': 'native geometryByte branch selected by background actor uniform4.w=1',
            'writer_route': 'same native geometry material; actor uniform4.w=0, k from actor uniform4.z',
            'physical_anchor_distances': {'background': 6, 'writer': 3},
            'screen_projection': 'Both actors project matching ROI; independent anchor distances prevent assuming one actor.',
            'limitations': ['Static source + successful API receipts are not a GPU material/attachment getter.',
                            'Hidden-background and repeated creation-order captures provide the rendered negative control.']}


def audit(evidence, project):
    evidence = Path(evidence).resolve()
    names = ('setup_domain4.results.json', 'domain4.results.json', 'duplicate.results.json', 'frozen_natural.results.json')
    documents = [load(evidence / name) for name in names]
    receipts = [integrity(report, evidence) for document in documents for report in document['reports']]
    command_count = sum(event_integrity(document, evidence) for document in documents)
    setup, domain = setup_audit(documents[0], evidence), domain_audit(documents[1])
    duplicate, frozen = duplicate_audit(documents[2]), frozen_audit(documents[3])
    controlled_passed = all(item['passed'] for item in setup + domain)
    duplicate_passed = all(item['double_blend']['passed'] for item in duplicate)
    duplicate_negative_passed = all(not item['single_blend_negative']['passed'] for item in duplicate)
    natural_reference_passed = all(frozen[name]['passed'] for name in (
        'off_repeat_vs_off_before', 'off_after_vs_off_before',
        'restored_vs_off_before_within_2', 'encoded_vs_single_from_off_before'))
    result = {'kind': 'independent_scene_codec_domain_audit_v1', 'independent_of_probe_codec_and_verifier': True,
              'evidence': str(evidence), 'summary_sha256': {name: sha(evidence / name) for name in names},
              'equations': {'single': 'C1 = L*payload_digit + round(C0*(L-1)/255), L=2^(8-k)',
                            'double': 'C2 = L*payload_digit + round(C1*(L-1)/255), per-draw UNORM8 rounding',
                            'restore': 'round((encoded % L)*255/(L-1))',
                            'known_original': '(x, (73*x+19)%256, (151*x+47)%256), x=ordinal%256',
                            'domain_symbol': 'ordinal//256; all 2^(3*k) RGB combinations'},
              'capture_receipts': receipts, 'command_hashes_checked': command_count,
              'capture_file_hashes_checked': len(receipts) * 3,
              'source_provenance': source_audit(project), 'setup': setup, 'domain': domain,
              'intentional_duplicate': duplicate, 'frozen_natural': frozen,
              'controlled_domain_passed': controlled_passed,
              'intentional_double_blend_model_passed': duplicate_passed,
              'single_blend_rejected_for_duplicate': duplicate_negative_passed,
              'natural_initial_reference_comparisons_passed': natural_reference_passed,
              'all_observations_passed': controlled_passed and duplicate_passed and duplicate_negative_passed and natural_reference_passed,
              'limitations': ['The frozen natural-frame failures remain failures; separate frames are not atomic RGB references.',
                              'Zero byte-coded same-frame alpha-error images do not resolve subbyte error below the PNG quantization threshold, '
                              'and do not cover every possible source alpha.',
                              'The duplicate experiment identifies its intentional double-draw signature; it does not establish the historical root cause.',
                              'No performance conclusion is inferred from correctness capture FPS readings.']}
    return result


def historical_double_audit(evidence):
    evidence = Path(evidence).resolve()
    stems = ('native64k2_native_k2_bytes65536_baseline', 'native64k2_native_k2_bytes65536_restored')
    state = load(evidence / (stems[1] + '.state.json'))
    baseline, observed = [read_pixels(evidence / (stem + '.png'), state) for stem in stems]
    bits, logical, salt = state['rgb_bits'], state['logical_payload_bytes'], state['payload_salt']
    symbols = stream_symbols(len(baseline), bits, logical, salt)
    mask = np.any(np.abs(observed - baseline) > 2, axis=1)
    result = {'kind': 'historical_identical_double_blend_negative_control_v3',
              'independent_of_probe_codec_and_verifier': True,
              'source_sha256': {stem + suffix: sha(evidence / (stem + suffix)) for stem in stems
                                for suffix in ('.png', '.state.json')},
              'parameters': {'bits': bits, 'logical_bytes': logical, 'salt': salt, 'source_pixels': len(baseline)},
              'first_failure_pixels': int(np.count_nonzero(mask)), 'models': {},
              'model_assumption': 'The saved writer-off RGB is the exact source; the identical intended writer '
                                  'blends once or twice at each tested pixel, with UNORM8 rounding after each draw.',
              'causal_attribution': None}
    for draws in (1, 2):
        predicted = decode(blend(baseline, symbols, bits, draws), bits)
        exact = np.all(predicted[mask] == observed[mask], axis=1)
        within_two = np.all(np.abs(predicted[mask] - observed[mask]) <= 2, axis=1)
        result['models'][str(draws) + '_draw'] = {
            'failure_region_exact_matches': int(np.count_nonzero(exact)),
            'failure_region_exact_match_fraction': float(np.mean(exact)),
            'failure_region_matches_within_2': int(np.count_nonzero(within_two)),
            'failure_region_within_2_fraction': float(np.mean(within_two)),
            'failure_region_comparison': comparison(observed[mask], predicted[mask]),
            'full_roi_comparison': comparison(observed, predicted),
        }
    result['specific_identical_double_draw_explanation_matches'] = result['models']['2_draw']['failure_region_matches_within_2'] == int(mask.sum())
    result['conclusion'] = ('Use fit counts to assess only the exact identical-double-writer model. '
                            'No inference rules out other blend order, different sources, occlusion or frame changes.')
    return result


def self_test():
    for bits in (1, 2):
        count = 256 * (1 << (3 * bits))
        original, symbols = known_original(count), np.arange(count) // 256
        encoded = blend(original, symbols, bits)
        # Fractional reference derives source alpha and RGB separately.
        from fractions import Fraction
        levels, symbol_count = 1 << (8-bits), 1 << bits
        for index in range(0, count, 13):
            for channel in range(3):
                digit = int(payload_digits(symbols[index:index+1], bits)[0, channel])
                alpha = Fraction(256-levels, 255)
                value = Fraction(255*digit, symbol_count-1) * alpha + int(original[index, channel]) * (1-alpha)
                expected = (2*value.numerator+value.denominator) // (2*value.denominator)
                require(encoded[index, channel] == expected, 'Fraction oracle mismatch')
        require(comparison(encoded, encoded)['passed'], 'Identity comparison failed')
        mutated = encoded.copy()
        mutated[-1, 2] ^= 1
        require(not comparison(mutated, encoded)['passed'], 'Mutation was missed')
        require(np.max(np.abs(decode(encoded, bits)-original)) == bits, 'Restoration bound mismatch')
    return {'passed': True, 'cases': ['k1 fraction oracle', 'k2 fraction oracle', 'synthetic RGB mutations', 'restore error bounds']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--historical-input', type=Path)
    parser.add_argument('--historical-output', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test()))
    if args.input:
        require(args.project is not None and args.output is not None, 'Supply --project and --output')
        result = audit(args.input, args.project)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({key: result[key] for key in ('controlled_domain_passed', 'intentional_double_blend_model_passed',
                                                      'single_blend_rejected_for_duplicate', 'all_observations_passed')}))
    if args.historical_input:
        require(args.historical_output is not None and not args.historical_output.exists(), 'Supply a new --historical-output path')
        result = historical_double_audit(args.historical_input)
        args.historical_output.parent.mkdir(parents=True, exist_ok=True)
        args.historical_output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'historical_failure_pixels': result['first_failure_pixels'],
                          'identical_double_draw_model_matches': result['specific_identical_double_draw_explanation_matches']}))
