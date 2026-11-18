"""Offline independent audit of the saved 256/512 KiB scene-codec experiment.

Only the standard library, NumPy and Pillow are imported. Probe encoders,
builders and verifiers are never imported or executed. No game is contacted.
The PNG oracle and payload/packing oracle are implemented here independently.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image


SCREEN = (1080, 1440)
SENTINEL = (8, 16, 32, 255)
PREFIX = 'scene_large_'
PAGE_FIELDS = ('dataset', 'page', 'record_base', 'record_count', 'payload_byte_base',
               'payload_byte_count', 'name', 'seed', 'generation', 'upload_serial',
               'payload_fingerprint', 'entity', 'stride', 'roi', 'upload_render_event')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    return digest(Path(path).read_bytes())


def byte_scalar(seed, generation, index):
    """32-bit PRNG specification, with explicit reduction after each multiply."""
    word = (seed ^ ((generation * 2654435769) % 2**32) ^
            ((index * 2246822507) % 2**32)) % 2**32
    word = ((word ^ (word >> 16)) * 2146121005) % 2**32
    word = ((word ^ (word >> 15)) * 2221713035) % 2**32
    return (word ^ (word >> 16)) % 256


def byte_vector(seed, generation, indices):
    index = np.asarray(indices, dtype=np.uint64)
    word = np.bitwise_xor(np.uint64(seed ^ ((generation * 2654435769) % 2**32)),
                         (index * np.uint64(2246822507)) % np.uint64(2**32))
    word = ((word ^ (word >> np.uint64(16))) * np.uint64(2146121005)) % np.uint64(2**32)
    word = ((word ^ (word >> np.uint64(15))) * np.uint64(2221713035)) % np.uint64(2**32)
    return ((word ^ (word >> np.uint64(16))) % np.uint64(256)).astype(np.uint8)


def independent_plan(logical):
    require(logical in (262144, 524288), 'Unexpected logical capacity')
    required = (logical + 23) // 24
    rows = (required + 21) // 22
    records = rows * 704
    pages = []
    for number, base in enumerate(range(0, records, 65536)):
        count = min(65536, records - base)
        stride = 2 ** math.ceil(math.log2(math.sqrt(count)))
        pages.append(dict(page=number, record_base=base, record_count=count,
                          payload_byte_base=base * 3 // 4, payload_byte_count=count * 3 // 4,
                          stride=stride, palette_height=16, palette_volume=stride**2 * 16))
    return dict(rgb_bits=2, logical_bytes=logical, block_bytes=24, block_pixels=32,
                block_aligned_bytes=required * 24, allocated_bytes=records * 3 // 4,
                padding_bytes=records * 3 // 4 - logical, required_blocks=required,
                allocated_blocks=records // 32, records=records, roi=[8, 128, 704, rows],
                screen_size=list(SCREEN), diagnostic_layout=[8, 128, 1024, 1],
                guard_rect_native=[0, 128, 1080, 1408], page_record_budget=65536,
                pages=pages, declared_palette_volume_sum=sum(p['palette_volume'] for p in pages))


def lookup_indices(logical, seed, generation, dependent):
    address = np.arange(logical, dtype=np.uint64)
    if dependent:
        address = (131 * address + 29) % logical
        # 131 is odd and both supported capacities are powers of two.
        require(np.unique(address).size == logical, 'Indexed first reads are not a permutation')
        first = byte_vector(seed, generation, address).astype(np.uint64)
        address = (address + 257 * first + 113) % logical
    return address


def expected_rgb(kind, logical, seed, generation, count):
    ordinal = np.arange(count, dtype=np.uint64)
    if kind in ('identity', 'dependent'):
        addresses = lookup_indices(logical, seed, generation, kind == 'dependent')
        values = byte_vector(seed, generation, addresses)
        return np.repeat(values[:, None], 3, axis=1), addresses
    if kind == 'calibration':
        return np.repeat((ordinal % 256).astype(np.uint8)[:, None], 3, axis=1), ordinal
    if kind == 'integrity':
        return np.zeros((count, 3), dtype=np.uint8), ordinal
    if kind == 'coordinates':
        horizontal = ordinal % 1024 + 8
        vertical = 1439 - (ordinal // 1024 + 128)
        values = np.column_stack((horizontal % 256, vertical % 256,
                                  horizontal // 256 + 8 * (vertical // 256)))
        return values.astype(np.uint8), ordinal
    require(kind == 'screeninfo', 'Unknown diagnostic kind')
    values = np.array([1080, 1440, (2**24 + 540) // 1080,
                       (2**24 + 720) // 1440], dtype=np.uint64)[ordinal % 4]
    return np.column_stack((values % 256, (values // 256) % 256,
                            values // 65536)).astype(np.uint8), ordinal


def inspect_pixels(pixels, rgb):
    count = len(rgb)
    ordinal = np.arange(count)
    x, y = ordinal % 1024 + 8, ordinal // 1024 + 128
    observed = pixels[y, x]
    errors = np.abs(observed[:, :3].astype(np.int16) - rgb.astype(np.int16))
    failed = np.any(errors != 0, axis=1) | (observed[:, 3] != 255)
    guard = np.zeros(pixels.shape[:2], dtype=bool)
    guard[128:1408, :] = True
    guard[y, x] = False
    return dict(passed=not failed.any() and not np.any(pixels[guard] != SENTINEL),
                checked_native_query_pixels=count, failed_query_pixels=int(failed.sum()),
                maximum_rgb_error=int(errors.max()), alpha_failures=int((observed[:, 3] != 255).sum()),
                magenta_invalid_block_pixels=int(np.all(observed[:, :3] == [255, 0, 255], axis=1).sum()),
                checked_guard_pixels=int(guard.sum()),
                failed_guard_pixels=int(np.any(pixels[guard] != SENTINEL, axis=1).sum()),
                expected_query_sha256=digest(rgb.tobytes()),
                observed_query_sha256=digest(observed[:, :3].tobytes()))


def statistics(values, intervals=False):
    ordered = sorted(values)
    require(ordered and all(math.isfinite(v) and v > 0 for v in ordered), 'Invalid raw timing vector')
    count = len(ordered)
    result = dict(count=count, mean=sum(ordered) / count, min=ordered[0], max=ordered[-1],
                  p95=ordered[((count - 1) * 95) // 100])
    if intervals:
        result.update(p99=ordered[((count - 1) * 99) // 100],
                      over_25_ms=sum(v > 25 for v in ordered),
                      over_33_3_ms=sum(v > 33.3 for v in ordered),
                      over_50_ms=sum(v > 50 for v in ordered))
    return result


def compare_statistics(actual, expected):
    require(actual.keys() == expected.keys(), 'Statistics fields changed')
    for key, value in actual.items():
        require(math.isclose(value, expected[key], rel_tol=1e-12, abs_tol=1e-9),
                'Raw-vector statistic disagrees: ' + key)


def page_identity(page):
    return {key: page[key] for key in PAGE_FIELDS}


def resident_identity(state):
    keys = ('source_bundle_sha256', 'seed', 'generation', 'dataset_serial',
            'logical_payload_bytes', 'allocated_payload_bytes_current',
            'allocated_payload_bytes_all_datasets', 'allocated_records_all_datasets',
            'geometry_build_serial', 'native_attempt_serial')
    return {key: state[key] for key in keys} | {'pages': [page_identity(p) for p in state['pages']]}


def check_chain(state, expected=None):
    actual = dict(state['actual_post_states'])
    require(len(actual) == len(state['actual_post_states']), 'Duplicate post-process state')
    require(set(actual) == set(state['actual_post_order']), 'Actual post order differs from state names')
    native = [name for name, on in actual.items() if on and not name.startswith(PREFIX)]
    enabled = {name for name, on in actual.items() if on and name.startswith(PREFIX)}
    require(not native and state['native_post_effects_enabled'] == [], 'Native effect is enabled')
    require(enabled == set(state['enabled_processes']) == set(state['declared_enabled_processes']),
            'Actual and declared custom passes disagree')
    require(len(enabled) == state['custom_pass_count'], 'Actual pass count differs')
    if expected is not None:
        require(enabled == set(expected), 'Unexpected active pass set')
    return sorted(enabled)


def audit_sources(project, evidence):
    manifest = load(project / 'source_manifest.json')
    require(digest(json.dumps(manifest['sources'], sort_keys=True).encode('utf-8')) ==
            manifest['source_bundle_sha256'], 'Invalid saved source bundle hash')
    package = project / 'behavior_pack/geometry_atlas_probe'
    shaders = project / 'resource_pack/shaders/glsl'
    paths = {'runtime.py': package / 'runtime.py', 'large_layout.py': package / 'large_layout.py',
             'scene_codec.py': package / 'scene_codec.py', 'scatter.vertex': shaders / 'scatter.vertex'}
    for name in ('scatter', 'raw', 'encode', 'decode', 'consumer', 'integrity'):
        paths[name + '.fragment'] = shaders / ('scene_large_' + name + '.fragment')
    checked = []
    for name, path in paths.items():
        info = manifest['sources'][name]
        require(sha(path) == info['sha256'] and path.stat().st_size == info['bytes'],
                'Saved project source disagrees with its build manifest: ' + name)
        checked.append(dict(file=str(path.resolve()), sha256=sha(path)))
    base = paths['scatter.vertex'].read_text(encoding='utf-8')
    paged = (shaders / 'scene_large_scatter.vertex').read_text(encoding='utf-8')
    insertion = 'vec2 grid = vec2(mod(record, columns), floor(record / columns));'
    expected = base.replace(insertion, 'record += EXTRA_ACTOR_UNIFORM4.w; // global record base after local validation\n'
                            '    ' + insertion)
    require(paged == expected and paged.index('record >= count') < paged.index('record +=') < paged.index(insertion),
            'Global page base is not applied after local record validation')
    scatter = paths['scatter.fragment'].read_text(encoding='utf-8')
    require('EXTRA_ACTOR_UNIFORM' not in scatter and '192.0/255.0' in scatter and
            'geometryByte*255.0' in scatter, 'Carrier fragment reuses actor controls or changed k2')
    consumer = paths['consumer.fragment'].read_text(encoding='utf-8')
    require('floor(address/24.0)*32.0+8.0+mod(address,24.0)' in consumer and
            '257.0*byteAt(address)+113.0' in consumer, 'GPU address or alpha payload layout changed')
    integrity = paths['integrity.fragment'].read_text(encoding='utf-8')
    for expression in ('abs(decoded.a-raw.a)', 'abs(decoded.r-coded.r)', 'texture2D(TEXTURE_5,location)',
                       'EXTRA_VECTOR2.z*EXTRA_VECTOR2.w', 'floor(gl_FragCoord.xy)', 'EXTRA_VECTOR4.z*16777216.0'):
        require(expression in integrity, 'Missing same-frame integrity/calibration expression: ' + expression)
    encoder = paths['encode.fragment'].read_text(encoding='utf-8')
    decoder = paths['decode.fragment'].read_text(encoding='utf-8')
    for expression in ('local < 4.0', 'local < 8.0', 'local - 8.0', 'slot < 32', 'value - EXTRA_VECTOR1.y'):
        require(expression in encoder, 'Alpha header encoder contract changed')
    require('count > 4.5' in decoder and 'start + 4.0 + rank' in decoder and
            'float alpha = EXTRA_VECTOR1.y' in decoder, 'Alpha header decoder contract changed')
    runtime = paths['runtime.py'].read_text(encoding='utf-8')
    require("selected=[] if profile in ('baseline','writer')" in runtime,
            'Expected saved old baseline implementation was changed')
    require('float(page[\'record_base\'])' in runtime and 'page_payload(self.plan,page[\'page\']' in runtime,
            'Runtime global base or page payload call changed')
    provenance = load(evidence / 'host_control_sources.json')
    require(provenance['native_package_runtime_differs_from_host_source'] is True and
            provenance['files']['runtime.py'] != sha(paths['runtime.py']), 'Host/package distinction missing')
    terrain = load(project / 'resource_pack/materials/terrain.material')['materials']['pmanim_geometry_atlas:netease_block_as_entity_mesh']
    require(terrain['fragmentShader'] == 'shaders/glsl/scene_large_scatter.fragment' and
            terrain['vertexShader'] == 'shaders/glsl/scene_large_scatter.vertex' and
            terrain['blendSrc'] == 'SourceAlpha' and terrain['blendDst'] == 'OneMinusSrcAlpha' and
            terrain['alphaSrc'] == 'Zero' and terrain['alphaDst'] == 'One' and
            'DisableAlphaWrite' in terrain['+states'], 'Carrier material blend/alpha preservation changed')
    native = load(project / 'resource_pack/graphics_settings/post_process.json')
    require(all(p['enable'] is False for p in native['process_array']), 'Startup native effects not all disabled')
    native_info = load(project / 'native_effects_off.manifest.json')
    require(native_info['generated_sha256'] == sha(project / 'resource_pack/graphics_settings/post_process.json'),
            'Isolated native config hash changed')
    return dict(source_bundle_sha256=manifest['source_bundle_sha256'], checked_sources=checked,
                paged_vertex_sha256=sha(shaders / 'scene_large_scatter.vertex'),
                global_record_base_after_local_validation=True, fixed_k2_fragment_no_actor_uniform_branch=True,
                saved_package_old_zero_pass_baseline_method=True,
                actual_measurements_controlled_by_saved_host_commands=True,
                host_provenance_sha256=sha(evidence / 'host_control_sources.json'),
                local_latest_runtime_treated_as_launched_package=False,
                native_startup_config_all_disabled=True, carrier_material_preserves_alpha=True)


def audit_payloads(evidence, states):
    pages_report, datasets = [], []
    for logical in (262144, 524288):
        plan = independent_plan(logical)
        complete = next(s for s in states.values() if s['logical_payload_bytes'] == logical and s['all_current_pages_loaded'])
        require(complete['payload_plan'] == plan, 'Saved plan differs from independent arithmetic')
        payload = byte_vector(complete['seed'], complete['generation'], np.arange(plan['allocated_bytes']))
        payload[logical:] = 0
        bits = np.unpackbits(payload, bitorder='little')
        symbols = (bits.reshape(-1, 6) * (1 << np.arange(6))).sum(axis=1).astype(np.uint8)
        reconstructed = np.packbits(((symbols[:, None] >> np.arange(6)) & 1).astype(np.uint8).ravel(), bitorder='little')
        require(len(symbols) == plan['records'] and np.array_equal(payload, reconstructed), 'Independent 6-bit stream roundtrip failed')
        # Alpha block offsets 0..7 are header; 8..31 hold these 24 payload bytes.
        packed = np.zeros((plan['allocated_blocks'], 32), dtype=np.uint8)
        packed[:, 8:] = payload.reshape(-1, 24)
        require(np.array_equal(packed[:, 8:].ravel(), payload) and not packed[:, :8].any(), 'Independent baseline-alpha header layout failed')
        require(not payload[logical:].any(), 'Allocated payload padding is nonzero')
        for page in (p for p in complete['pages'] if p['dataset'] == complete['dataset_serial']):
            planned = plan['pages'][page['page']]
            require(all(page[k] == v for k, v in planned.items()), 'Saved page differs from independent page plan')
            base, count = page['payload_byte_base'], page['payload_byte_count']
            values = payload[base:base + count]
            host = load(evidence / ('payload_%d_page%02d.host-oracle.json' % (logical, page['page'])))
            value_sum, host_sha = int(values.astype(np.uint64).sum()) % 2**32, digest(values.tobytes())
            require(page['payload_fingerprint'] == dict(algorithm='sum_u8_mod2^32', value=value_sum), 'Runtime page sum32 disagrees')
            require(host['sha256'] == host_sha and host['sum_u8_mod2^32'] == value_sum and
                    host['runtime_fingerprint'] == page['payload_fingerprint'], 'Host payload oracle hash/sum disagrees')
            require(all(host[k] == page[k] for k in ('page', 'record_base', 'record_count', 'payload_byte_base', 'payload_byte_count')),
                    'Host payload page coordinates disagree')
            local_bits = np.unpackbits(values, bitorder='little').reshape(-1, 6)
            local_symbols = (local_bits * (1 << np.arange(6))).sum(axis=1).astype(np.uint8)
            require(np.array_equal(local_symbols, symbols[page['record_base']:page['record_base'] + page['record_count']]),
                    'Page-local packed stream disagrees at global record base')
            if base:
                require(not np.array_equal(values, payload[:count]), 'PRNG page accidentally restarts from zero')
            pages_report.append(dict(logical_bytes=logical, dataset=page['dataset'], page=page['page'],
                                     record_base=page['record_base'], record_count=page['record_count'],
                                     payload_byte_base=base, payload_byte_count=count, sum32=value_sum, sha256=host_sha))
        datasets.append(dict(logical_bytes=logical, allocated_bytes=plan['allocated_bytes'],
                             source_records=plan['records'], pages=len(plan['pages']), padding_bytes=plan['padding_bytes'],
                             source_roi=plan['roi'], alpha_blocks=plan['allocated_blocks'],
                             header_slots_per_block=8, payload_slots_per_block=24,
                             allocated_payload_sha256=digest(payload.tobytes()), logical_payload_sha256=digest(payload[:logical].tobytes())))
    return dict(datasets=datasets, pages=pages_report, all_page_hashes_and_runtime_sum32_match=True,
                independent_little_endian_six_bit_packing_roundtrip=True,
                global_payload_index_used_across_pages=True, zero_padding_verified_on_cpu=True,
                baseline_alpha_header_zero_model_verified_on_cpu=True,
                alpha_header_scope='GPU screenshots expose same-frame decoded-alpha error and overflow status for all source records, not raw header bytes; exact zero header/padding is independently checked in CPU payload/model and shader source.')


def audit(evidence, project):
    document = load(evidence / 'large_codec.results.json')
    require(document['status'] == 'passed' and document['formal_fps_measured'] is True and
            document['runtime_file_writes'] is False and document['continuous_updates'] is False,
            'Unexpected experiment status or scope')
    source_report = audit_sources(project, evidence)
    states, state_hashes, command_hashes = {}, [], []
    for event in document['events']:
        require(event['returncode'] == 0 and event['automatic_mutation_replay'] is False, 'Host action failed or replayed')
        if event['action'] == 'call':
            command = evidence / 'large_commands' / (event['label'] + '.py')
            receipt = evidence / (event['label'] + '.state.json')
            require(sha(command) == event['command_sha256'], 'Executed saved command hash disagrees')
            states[event['label']] = load(receipt)
            state_hashes.append(dict(label=event['label'], sha256=sha(receipt)))
            command_hashes.append(dict(label=event['label'], sha256=sha(command)))
    frozen, historical = {}, {}
    for label, state in states.items():
        require(state['game_runtime_file_writes'] is False and state['continuous_updates'] is False and state['error'] is None,
                'Receipt has runtime IO, updates or error')
        require(state['source_bundle_sha256'] == source_report['source_bundle_sha256'], 'Receipt source identity differs')
        for page in state['pages']:
            if page['loaded']:
                key = (page['dataset'], page['page'])
                identity = page_identity(page)
                require(key not in historical or historical[key] == identity, 'A resident page identity changed')
                historical[key] = identity
                if page['dataset'] != state['dataset_serial']:
                    require(page['native_visible'] is False, 'Historical resident page is visible')
        if state['all_current_pages_loaded']:
            dataset = state['dataset_serial']
            identity = resident_identity(state)
            require(dataset not in frozen or frozen[dataset] == identity, 'Frozen payload/allocation identity changed')
            frozen[dataset] = identity
        if state['pipeline_ready'] and state['profile'] != 'quiesced':
            check_chain(state)
    payload_report = audit_payloads(evidence, states)
    captures, negatives, wrong_generation = [], [], []
    for entry in document['reports']:
        label, kind = entry['label'], entry['kind']
        receipt, png, verification = map(Path, (entry['receipt'], entry['capture'], entry['verification']))
        state = load(receipt)
        logical = state['logical_payload_bytes']
        require(state['payload_plan'] == independent_plan(logical) and state['screen_size'] == list(SCREEN), 'Capture plan/screen mismatch')
        require(state['profile'] == kind and state['all_current_pages_loaded'] and state['pipeline_ready'], 'Capture not ready for profile')
        mode = {'identity': 0, 'dependent': 2, 'calibration': 3, 'integrity': 0, 'coordinates': 3, 'screeninfo': 4}[kind]
        count = logical if kind in ('identity', 'dependent', 'calibration') else state['payload_plan']['records']
        require(state['query'] == [0, count, mode], 'Query does not cover the complete declared domain')
        require(state['diagnostic_layout'] == [8, 128, 1024, 1] and state['guard_rect_native'] == [0, 128, 1080, 1408], 'Changed diagnostic/guard')
        capture_receipt = load(evidence / (label + '.json'))
        require(capture_receipt['ok'] is True and capture_receipt['backend'] == 'Windows.Graphics.Capture' and
                capture_receipt['native_resolution'] is True and
                (capture_receipt['width'], capture_receipt['height']) == SCREEN and
                capture_receipt['frame_qpc_100ns'] >= capture_receipt['request_qpc_100ns'] and
                capture_receipt['agent_activation_allowed'] is False and capture_receipt['background_only'] is True,
                'Capture freshness/native/background metadata disagrees')
        with Image.open(png) as image:
            require(image.size == SCREEN, 'PNG is not native 1080x1440')
            pixels = np.asarray(image.convert('RGBA'))
        rgb, address = expected_rgb(kind, logical, state['seed'], state['generation'], count)
        result = inspect_pixels(pixels, rgb)
        saved = load(verification)
        for key, value in result.items():
            require(saved[key] == value, 'Independent PNG result disagrees with verifier: ' + label + '/' + key)
        require(saved['capture_sha256'] == sha(png) and saved['receipt_sha256'] == sha(receipt), 'PNG/state binding hash disagrees')
        require(result['passed'] == entry['expected_pass'] == entry['passed'] and result['failed_guard_pixels'] == 0,
                'Unexpected positive/negative or guard result')
        for key in ('failed_query_pixels', 'failed_guard_pixels', 'checked_native_query_pixels'):
            require(entry[key] == result[key], 'Experiment summary differs from independent pixels')
        report = dict(label=label, kind=kind, logical_bytes=logical, expected_pass=entry['expected_pass'],
                      **result, distinct_final_addresses=int(np.unique(address).size),
                      capture_sha256=sha(png), receipt_sha256=sha(receipt),
                      capture_metadata_sha256=sha(evidence / (label + '.json')), verifier_sha256=sha(verification))
        captures.append(report)
        if not entry['expected_pass']:
            require(result['failed_query_pixels'] > count * .9 and not any(p['native_visible'] for p in state['pages']),
                    'Hidden page negative control did not reject the expected payload')
            negatives.append(dict(label=label, failed_query_pixels=result['failed_query_pixels']))
        elif kind in ('identity', 'dependent'):
            wrong_rgb, _ = expected_rgb(kind, logical, state['seed'], state['generation'] + 1, count)
            wrong = inspect_pixels(pixels, wrong_rgb)
            saved_wrong = load(evidence / (label + '.wrong-generation.verify.json'))
            require(not wrong['passed'] and wrong['failed_query_pixels'] > count * .9, 'Different generation was accepted')
            for key, value in wrong.items():
                require(saved_wrong[key] == value, 'Different generation result differs: ' + label)
            wrong_generation.append(dict(label=label, failed_query_pixels=wrong['failed_query_pixels'],
                                         report_sha256=sha(evidence / (label + '.wrong-generation.verify.json'))))
    require(len(captures) == 19 and len(negatives) == 2 and len(wrong_generation) == 10, 'Incomplete screenshot/control set')
    for logical in (262144, 524288):
        for moment in ('before', 'after'):
            for kind in ('identity', 'dependent', 'integrity'):
                require(any(c['label'] == '%d_%s_%s' % (logical, moment, kind) and c['passed'] for c in captures), 'Missing complete before/after capture')
    samples = []
    for sample in document['samples']:
        logical, profile = sample['logical_bytes'], sample['runtime_profile']
        names = [PREFIX + 'raw'] if profile in ('baseline', 'writer') else [PREFIX + n for n in ('raw', 'encode', 'decode')]
        if profile == 'dependent':
            names.append(PREFIX + 'consumer')
        matching = [(label, state) for label, state in states.items() if re.match(r'^\d+_%d_%s_(controls|start|status)$' % (logical, profile), label)]
        require(matching and matching[0][0].endswith('_controls') and matching[1][0].endswith('_start') and
                matching[-1][0].endswith('_status'), 'Incomplete measured profile receipt sequence')
        for _, state in matching:
            check_chain(state, names)
            require(resident_identity(state) == frozen[state['dataset_serial']], 'Performance payload not frozen')
            require(sum(p['native_visible'] for p in state['pages']) == (0 if profile == 'baseline' else len(state['payload_plan']['pages'])),
                    'Measured writer/native attachment visibility differs')
        controls = (evidence / 'large_commands' / (matching[0][0] + '.py')).read_text(encoding='utf-8')
        if profile in ('baseline', 'writer'):
            require("enable=name=='scene_large_raw'" in controls and 'probe.set_profile(' not in controls and
                    "probe.profile=%r" % profile in controls and
                    'probe.set_native_visible(%r)' % (profile == 'writer') in controls,
                    'Actual copy control did not override old package profile implementation')
        else:
            require("probe.set_profile(%r)" % profile in controls, 'Unexpected executed profile control')
        start_command = (evidence / 'large_commands' / (matching[1][0] + '.py')).read_text(encoding='utf-8')
        require('probe.start_static_measurement(25.0,2.)' in start_command, 'Measurement is not 2s warmup/25s sample')
        measured = sample['measurement']
        require(matching[1][1]['measurement_running'] is True and matching[-1][1]['measurement_running'] is False and
                matching[-1][1]['last_measurement'] == measured, 'Raw sample differs from completed receipt')
        require(measured['warmup_seconds'] == 2 and 25 <= measured['sample_seconds'] < 25.1 and
                math.isclose(measured['elapsed_seconds'], measured['sample_seconds'] + 2, abs_tol=1e-9), 'Unexpected sample timing window')
        require(measured['frames'] == len(measured['raw_interval_ms']) + 1 and
                len(measured['raw_fps_samples']) == measured['frames'] // 15, 'Raw vector frame/sample count differs')
        first_frame_offset = measured['sample_seconds'] - sum(measured['raw_interval_ms']) / 1000
        require(0 <= first_frame_offset < .04, 'Warmup boundary/interval duration is inconsistent')
        fps = statistics(measured['raw_fps_samples'])
        intervals = statistics(measured['raw_interval_ms'], True)
        compare_statistics(fps, measured['fps'])
        compare_statistics(intervals, measured['interval_ms'])
        require(measured['pass_count'] == sample['custom_pass_count'] == len(names) and
                set(measured['enabled_processes']) == set(names) and measured['gpu_completion_fence'] is False,
                'Measured pass count, names or fence scope differs')
        require(sample['fps_cap'] == 60 and sample['continuous_updates'] is False and
                sample['native_effects_enabled'] is False, 'Performance scope differs')
        allocation = dict(payload_bytes_all_datasets=matching[-1][1]['allocated_payload_bytes_all_datasets'],
                          records_all_datasets=matching[-1][1]['allocated_records_all_datasets'],
                          anchor_count=len(matching[-1][1]['pages']))
        require(sample['same_allocations_for_all_profiles_of_this_dataset'] == allocation, 'Allocation summary differs')
        samples.append(dict(logical_bytes=logical, profile=sample['profile'], custom_pass_count=len(names),
                            actual_enabled_processes=sorted(names), native_actual_enabled=[], allocation=allocation,
                            warmup_seconds=2, sample_seconds=measured['sample_seconds'], frames=measured['frames'],
                            fps_recomputed=fps, interval_ms_recomputed=intervals,
                            first_frame_after_warmup_seconds=first_frame_offset,
                            interval_derived_fps=len(measured['raw_interval_ms']) * 1000 / sum(measured['raw_interval_ms']),
                            raw_interval_vector_sha256=digest(json.dumps(measured['raw_interval_ms']).encode('utf-8')),
                            raw_fps_vector_sha256=digest(json.dumps(measured['raw_fps_samples']).encode('utf-8')),
                            control_label=matching[0][0], completed_receipt_label=matching[-1][0],
                            frozen_identity_sha256=digest(json.dumps(resident_identity(matching[-1][1]), sort_keys=True).encode('utf-8'))))
    require(Counter((s['logical_bytes'], s['custom_pass_count']) for s in samples) ==
            Counter({(262144, 1): 2, (262144, 3): 1, (262144, 4): 1, (524288, 1): 2, (524288, 3): 1, (524288, 4): 1}), 'Incomplete profile set')
    restore = next(s for s in samples if s['logical_bytes'] == 262144 and s['profile'] == 'restore')
    require(math.isclose(restore['interval_ms_recomputed']['max'], 90.6435, abs_tol=1e-7) and
            restore['interval_ms_recomputed']['over_50_ms'] == 1, 'Historical long frame was removed or changed')
    final = document['final_state']
    require(final == states['141_quiesce'] and len(final['pages']) == 17 and
            all(p['loaded'] and not p['native_visible'] for p in final['pages']) and
            final['allocated_payload_bytes_all_datasets'] == 786720 and final['allocated_records_all_datasets'] == 1048960,
            'Final 17-page resident/quiesced allocation differs')
    release = load(evidence / 'released_processes.json')
    require(release['owned_pid_running'] is False and release['active_count'] == 0, 'Owned game release evidence missing')
    launch = load(evidence / 'launch.json')
    require(launch['fps'] == 60 and launch['background_only'] is True, 'Launch FPS/background condition differs')
    weather = load(evidence / 'fixed_clear_weather.decoded.json')
    require(all(weather[k] is True for k in ('local_weather_result', 'rain_result', 'thunder_result', 'time_result', 'rules_result', 'local_cycle_result')),
            'Clear fixed weather control failed')
    r1_path = evidence.parents[1] / 'scene-codec-large-native-20261118-r1/evidence/large_codec.results.json'
    r1 = load(r1_path)
    require(r1['status'] == 'failed' and r1['formal_fps_measured'] is False and r1['samples'] == [], 'Historical r1 failure changed')
    require(document['rain_compatibility_claimed'] is False and document['bloom_compatibility_claimed'] is False, 'Scope expanded to rain/native bloom')
    return dict(schema='independent_scene_codec_large_audit_v1', audit_passed=True,
                experiment_scope='Saved r2 fixed clear weather, native startup configuration and reported states disabled, static payloads; 60 FPS cap.',
                no_game_contact=True, probe_encoder_or_verifier_imported=False, game_runtime_file_writes=False,
                continuous_updates=False, source_audit=source_report, payload_audit=payload_report,
                native_output_size_verified=list(SCREEN), calibration_methods=['PNG dimensions', 'full grayscale ramp', 'GPU gl_FragCoord', 'GPU ScreenInfo'],
                captures=captures, positive_capture_count=sum(c['passed'] for c in captures),
                positive_query_pixel_count=sum(c['checked_native_query_pixels'] for c in captures if c['passed']),
                all_capture_guard_errors=sum(c['failed_guard_pixels'] for c in captures),
                hidden_negative_controls=negatives, wrong_generation_controls=wrong_generation,
                profiles=samples, quantile_convention='Sorted raw values at floor((count-1)*q), independently recomputed; no interpolation or trimming.',
                long_frame_preserved=dict(logical_bytes=262144, profile='restore', milliseconds=restore['interval_ms_recomputed']['max'],
                                          over_50_ms=1, excluded_samples=0, replacement_measurements=0),
                frozen_resident_payload_verified=True, final_resident_page_count=17,
                final_historical_256_pages=6, final_current_512_pages=11,
                final_allocated_payload_bytes=786720, final_allocated_records=1048960,
                native_visibility_scope='Successful native visibility setters plus saved receipts and hidden/restore pixel controls; no native visibility getter or GPU completion fence.',
                native_effect_state_scope='Disabled startup config and reported actual getters; does not establish native bloom/rain shader compatibility.',
                performance_scope='GetFps vectors and GameRenderTickEvent intervals; capped, about 25 s per profile, not isolated GPU timings or proof of absence of stutter.',
                owned_game_stopped=True, owned_pid=release['owned_pid'], released_processes_sha256=sha(evidence / 'released_processes.json'),
                historical_r1=dict(status=r1['status'], formal_fps_measured=False, sample_count=0, error=r1['error'],
                                   results_sha256=sha(r1_path)), rain_compatibility_claimed=False, bloom_compatibility_claimed=False,
                input_results_sha256=sha(evidence / 'large_codec.results.json'),
                audited_state_receipts=state_hashes, audited_host_commands=command_hashes)


def self_test():
    indices = np.array([0, 1, 23, 24, 49151, 49152, 262143, 524287, 2**32 - 1], dtype=np.uint64)
    for generation in (1, 2, 4294967295):
        require(byte_vector(54321, generation, indices).tolist() ==
                [byte_scalar(54321, generation, int(i)) for i in indices], 'Scalar/vector oracle cross-check failed')
    rgb, _ = expected_rgb('calibration', 262144, 54321, 1, 262144)
    pixels = np.full((1440, 1080, 4), SENTINEL, dtype=np.uint8)
    ordinal = np.arange(len(rgb))
    pixels[128 + ordinal // 1024, 8 + ordinal % 1024, :3] = rgb
    require(inspect_pixels(pixels, rgb)['passed'], 'Synthetic exact capture rejected')
    pixels[128, 8, 0] ^= 1
    require(inspect_pixels(pixels, rgb)['failed_query_pixels'] == 1, 'Query mutation missed')
    pixels[128, 8, 0] ^= 1
    pixels[1407, 0, 2] ^= 1
    require(inspect_pixels(pixels, rgb)['failed_guard_pixels'] == 1, 'Guard mutation missed')
    values = [16.] * 1494 + [90.6435]
    before, after = statistics(values, True), statistics(values[:-1], True)
    require(before['max'] == 90.6435 and before['over_50_ms'] == 1 and after['max'] == 16, 'Long frame control failed')
    try:
        compare_statistics(before, after)
    except ValueError:
        pass
    else:
        raise ValueError('Timing-vector mutation missed')
    require(independent_plan(262144)['records'] == 349888 and independent_plan(524288)['padding_bytes'] == 16,
            'Independent capacity arithmetic failed')
    return dict(scalar_vector_prng=True, exact_synthetic_capture=True, single_query_mutation_detected=True,
                single_guard_mutation_detected=True, removed_long_frame_detected=True, capacity_arithmetic=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
    if args.evidence is not None:
        require(args.project is not None and args.output is not None, 'Provide --project and --output')
        require(not args.output.exists(), 'Preserve existing evidence: output already exists')
        report = audit(args.evidence.resolve(), args.project.resolve())
        report['oracle_self_tests'] = self_test()
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({k: report[k] for k in ('audit_passed', 'positive_capture_count',
                                               'positive_query_pixel_count', 'final_resident_page_count')}, indent=2))
    elif not args.self_test:
        parser.error('Provide --self-test or the three audit paths')


if __name__ == '__main__':
    main()
