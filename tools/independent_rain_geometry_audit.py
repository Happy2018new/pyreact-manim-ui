"""Offline independent replay of the saved rain/geometry-transparency experiment.

This host tool never imports a probe codec, builder or verifier and never contacts
Minecraft. Exact PNG data, guards, resource hashes and saved commands are checked.
Failure observations remain observations; they are not turned into audit errors.
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


SCREEN = (720, 1080)
PAYLOAD_BYTES = 65536
SOURCE_RECORDS = 87424
DOMAIN_RECORDS = 16384
ROI = [296, 192, 128, 683]
GUARD = [0, 128, 720, 1064]
IDENTITY_FIELDS = ('geometry_name', 'geometry_build_serial', 'native_attempt_serial',
                   'epoch', 'entity', 'generation', 'slot_count', 'rgb_bits',
                   'logical_payload_bytes', 'allocated_payload_bytes', 'payload_salt',
                   'codec_roi', 'code_domain_sweep', 'source_bundle_sha256')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def object_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode('utf-8')).hexdigest()


def histogram(values):
    return {str(int(key)): int(count) for key, count in sorted(Counter(values.tolist()).items())}


def payload_byte(indices):
    index = np.asarray(indices, dtype=np.int64)
    quotient, remainder = np.divmod(index, 251)
    value = ((index % 256) * 73 + (quotient % 256) * 19 + 29) % 256
    return np.where(index < PAYLOAD_BYTES, value, 0).astype(np.uint8)


def payload_symbols(count):
    """Three little-endian bytes form four 6-bit records; no probe bit loop."""
    groups = (count + 3) // 4
    data = payload_byte(np.arange(groups * 3)).astype(np.uint16).reshape(-1, 3)
    a, b, c = data.T
    symbols = np.column_stack((a & 63, (a >> 6) | ((b & 15) << 2),
                               (b >> 4) | ((c & 3) << 4), c >> 2))
    return symbols.ravel()[:count].astype(np.uint8)


def query_oracle(kind):
    address = np.arange(PAYLOAD_BYTES, dtype=np.int64)
    if kind == 'dependent':
        first = (131 * address + 29) % PAYLOAD_BYTES
        require(len(np.unique(first)) == PAYLOAD_BYTES, 'First indexed read is not a full permutation')
        address = (first + 257 * payload_byte(first).astype(np.int64) + 113) % PAYLOAD_BYTES
    values = payload_byte(address)
    return np.column_stack((values, values, values)), len(np.unique(address))


def domain_oracle(kind):
    ordinal = np.arange(DOMAIN_RECORDS, dtype=np.int64)
    x, symbol = ordinal % 256, ordinal // 256
    original = np.column_stack((x, (73 * x + 19) % 256, (151 * x + 47) % 256))
    digits = np.column_stack((symbol % 4, (symbol // 4) % 4, symbol // 16))
    # SourceAlpha=192/255: each channel is 64*p + round(63*C/255).
    quantized = (126 * original + 255) // 510
    if kind == 'domain_original':
        return original.astype(np.uint8)
    if kind == 'domain_encoded':
        return (64 * digits + quantized).astype(np.uint8)
    require(kind == 'domain_restored', 'Unknown known-color domain view')
    return ((510 * quantized + 63) // 126).astype(np.uint8)


def read_native(path):
    with Image.open(path) as image:
        require(image.size == SCREEN, 'Capture PNG is not native 720x1080: ' + str(path))
        return np.array(image.convert('RGBA'))


def decode_native(pixels, kind, count):
    require(pixels.shape == (1080, 720, 4), 'Unexpected PNG shape')
    require(0 < count <= 720 * 936, 'Query exceeds native diagnostic area')
    area = pixels[128:1064, :].reshape(-1, 4)
    query, guard = area[:count], area[count:]
    result = dict(kind=kind, checked_query_pixels=count, checked_guard_pixels=len(guard),
                  guard_errors=int(np.any(guard != [0, 0, 0, 255], axis=1).sum()),
                  query_alpha_not255=int((query[:, 3] != 255).sum()),
                  observed_rgba_sha256=hashlib.sha256(query.tobytes()).hexdigest())
    if kind == 'q_alpha':
        require(count == SOURCE_RECORDS, 'Q/A capture must cover every source record including padding')
        q, alpha, offgrid = query[:, :3].T
        require(int(q.max()) <= 63, 'Observed Q is not a packed 6-bit value')
        bad = q != payload_symbols(count)
        result.update(bad_q=int(bad.sum()), alpha_not255=int((alpha != 255).sum()),
                      bad_q_alpha_not255=int((bad & (alpha != 255)).sum()),
                      bad_q_alpha255=int((bad & (alpha == 255)).sum()), alpha_offgrid=int((offgrid != 0).sum()),
                      alpha_histogram=histogram(alpha), q_histogram=histogram(q),
                      query_errors=int((bad | (offgrid != 0)).sum()))
        result['bad_q_fraction_all_records'] = result['bad_q'] / count
        result['bad_q_fraction_non255_alpha'] = result['bad_q_alpha_not255'] / max(1, result['alpha_not255'])
    elif kind == 'block_alpha':
        require(count == SOURCE_RECORDS and count % 32 == 0, 'Block diagnostic must cover complete allocated source')
        counts, overflow, error = query[:, :3].T
        blocks = counts.reshape(-1, 32)
        require(int(counts.max()) <= 32, 'Invalid block exception count')
        expected_overflow = np.where(counts > 4, 255, 0)
        result.update(max_block_exceptions=int(counts.max()),
                      overflow_source_pixels=int((overflow != 0).sum()),
                      overflow_blocks=int((blocks[:, 0] > 4).sum()),
                      alpha_restore_error_pixels=int((error != 0).sum()),
                      maximum_alpha_restore_error=int(error.max()), block_count=len(blocks),
                      inconsistent_block_count_pixels=int((blocks != blocks[:, :1]).sum()),
                      overflow_flag_inconsistent_pixels=int((overflow != expected_overflow).sum()),
                      exception_count_histogram=histogram(blocks[:, 0]),
                      query_errors=int(((overflow != 0) | (error != 0)).sum()))
    else:
        expected = np.zeros((count, 3), dtype=np.uint8)
        if kind in ('identity', 'dependent'):
            require(count == PAYLOAD_BYTES, 'Payload query must cover all 65536 ordinals')
            expected, distinct = query_oracle(kind)
            result['distinct_final_addresses'] = distinct
        elif kind.startswith('domain_'):
            require(count == DOMAIN_RECORDS, 'Known-color domain query must cover all 16384 records')
            expected = domain_oracle(kind)
            original = domain_oracle('domain_original')
            original_low_restored = ((510 * (original.astype(np.int64) % 64) + 63) // 126).astype(np.uint8)
            result['matches_original_background_pixels'] = int(np.all(query[:, :3] == original, axis=1).sum())
            result['matches_background_low_bits_restored_pixels'] = int(np.all(query[:, :3] == original_low_restored, axis=1).sum())
        else:
            require(kind == 'alpha_error', 'Unknown capture kind: ' + kind)
        errors = np.max(np.abs(query[:, :3].astype(np.int16) - expected.astype(np.int16)), axis=1)
        result.update(query_errors=int((errors != 0).sum()), maximum_channel_error=int(errors.max()),
                      failures_first16=[dict(ordinal=int(i), expected=expected[i].tolist(), observed=query[i].tolist())
                                        for i in np.flatnonzero(errors)[:16]])
    result['passed'] = result['query_errors'] == result['guard_errors'] == result['query_alpha_not255'] == 0
    return result


def self_test():
    symbols = payload_symbols(SOURCE_RECORDS)
    bits = ((symbols[:, None].astype(np.uint64) >> np.arange(6, dtype=np.uint64)) & 1).astype(np.uint8).ravel()
    recovered = np.packbits(bits, bitorder='little')
    require(np.array_equal(recovered, payload_byte(np.arange(SOURCE_RECORDS * 3 // 4))), 'Independent packed stream roundtrip failed')
    require(not recovered[PAYLOAD_BYTES:].any(), 'Padding not zero')
    pixels = np.zeros((1080, 720, 4), dtype=np.uint8)
    pixels[:, :, 3] = 255
    data = pixels[128:1064].reshape(-1, 4)
    data[:SOURCE_RECORDS, 0] = symbols
    data[:SOURCE_RECORDS, 1] = 255
    require(decode_native(pixels, 'q_alpha', SOURCE_RECORDS)['passed'], 'Synthetic Q/A capture rejected')
    data[0, 0] ^= 1
    require(decode_native(pixels, 'q_alpha', SOURCE_RECORDS)['bad_q'] == 1, 'Single Q corruption missed')
    data[0, 0] ^= 1
    data[-1, 2] = 1
    require(decode_native(pixels, 'q_alpha', SOURCE_RECORDS)['guard_errors'] == 1, 'Single guard corruption missed')
    data[:] = [0, 0, 0, 255]
    data[0, 0] = 5
    block = decode_native(pixels, 'block_alpha', SOURCE_RECORDS)
    require(block['inconsistent_block_count_pixels'] == 31 and block['overflow_flag_inconsistent_pixels'] == 1,
            'Contradictory same-block exception/overflow diagnostic missed')
    encoded = domain_oracle('domain_encoded').astype(np.int64)
    symbols = np.arange(DOMAIN_RECORDS) // 256
    require(np.array_equal(encoded[:, 0] // 64 + 4 * (encoded[:, 1] // 64) + 16 * (encoded[:, 2] // 64), symbols),
            'Domain encoded symbols incorrect')
    return dict(independent_six_bit_pack_roundtrip=True, padding_zero=True,
                exact_synthetic_q_alpha=True, single_q_mutation_detected=True,
                single_guard_mutation_detected=True, block_diagnostic_contradiction_detected=True,
                all_domain_symbols_verified=True)


def audit_sources(project):
    manifest = load(project / 'source_manifest.json')
    require(object_sha(manifest['inputs']) == manifest['source_bundle_sha256'], 'Source input bundle hash differs')
    generated, metadata_discrepancies = [], []
    for relative, expected in manifest['generated_sha256'].items():
        path = project / relative
        require(path.is_file(), 'Generated project file missing: ' + relative)
        if relative == 'probe_resources.json' and sha(path) != expected:
            metadata = load(path)
            require(metadata['kind'] == 'rain_geometry_probe_v1' and metadata['rgb_bits'] == 2 and
                    metadata['logical_bytes'] == PAYLOAD_BYTES and metadata['payload_roi'] == ROI and
                    metadata['source_bundle_sha256'] == manifest['source_bundle_sha256'] and
                    metadata['game_runtime_file_writes'] is False and metadata['native_effects_off_config'] is True,
                    'Final overridden probe metadata has unexpected semantics')
            metadata_discrepancies.append(dict(file=relative, manifest_sha256=expected, actual_sha256=sha(path),
                explanation='Builder hashes base probe metadata before writing final rain-specific probe_resources.json. Original manifest is preserved; this metadata exception does not cover shader/material/runtime files.'))
            continue
        require(sha(path) == expected, 'Generated project source differs: ' + relative)
        generated.append(dict(file=relative, sha256=expected))
    resource = project / 'resource_pack'
    shader = resource / 'shaders/glsl/scene_codec_scatter.fragment'
    text = shader.read_text(encoding='utf-8')
    require('#define SCENE_CODEC_RGB_BITS 2' in text and 'EXTRA_ACTOR_UNIFORM4.w > 0.5' in text,
            'Fixed k2/background shader contract changed')
    require('payload / (symbols - 1.0)' in text and '(256.0 - 256.0 / symbols) / 255.0' in text,
            'Writer payload color/alpha formula changed')
    material = load(resource / 'materials/terrain.material')['materials']['pmanim_geometry_atlas:netease_block_as_entity_mesh']
    require(material['fragmentShader'] == 'shaders/glsl/scene_codec_scatter.fragment' and
            material['vertexShader'] == 'shaders/glsl/scene_codec_scatter.vertex' and
            material['blendSrc'] == 'SourceAlpha' and material['blendDst'] == 'OneMinusSrcAlpha' and
            material['alphaSrc'] == 'Zero' and material['alphaDst'] == 'One' and
            'DisableAlphaWrite' in material['+states'], 'Carrier material blend/alpha preservation differs')
    diagnostic = (resource / 'shaders/glsl/scene_codec_inspect.fragment').read_text(encoding='utf-8')
    expressions = ('raw=texture2D(TEXTURE_5,loc)', 'vec3(1.0,4.0,16.0)', 'observed/255.0',
                   'floor(alpha+0.5)/255.0', 'step(0.0001,abs(alpha-floor(alpha+0.5)))',
                   'count/255.0,step(4.5,count),abs(decoded.a-raw.a)', 'floor(index/32.0)*32.0')
    require(all(value in diagnostic for value in expressions), 'Same-frame Q/A or block diagnostic changed')
    native = load(resource / 'graphics_settings/post_process.json')
    require(all(p['enable'] is False for p in native['process_array']), 'Native startup effect enabled')
    native_inputs = [Path(name) for name in manifest['inputs'] if name.replace('\\', '/').endswith('/graphics_settings/post_process.json')]
    require(len(native_inputs) == 1, 'Native input config identity ambiguous')
    native_path = native_inputs[0]
    require(sha(native_path) == manifest['inputs'][str(native_path)]['sha256'], 'Original native config changed')
    expected_native = load(native_path)
    for process in expected_native['process_array']:
        process['enable'] = False
    require(native == expected_native, 'Native config has changes beyond disabling enable flags')
    rain_files = [p for p in resource.rglob('*') if p.is_file() and p.name.startswith('rain_snow')]
    require(not rain_files, 'This probe overrides native weather shaders')
    runtime = (project / 'behavior_pack/geometry_atlas_probe/runtime.py').read_text(encoding='utf-8')
    fixed_amount = 'SetActorBlockGeometryTransparency(self.geometry_name, 1.0)' in runtime
    variable_amount = 'SetActorBlockGeometryTransparency(self.geometry_name, amount)' in runtime
    require('EnableActorBlockGeometryTransparent(self.geometry_name, enabled)' in runtime and
            (fixed_amount or variable_amount),
            'Transparency controls target a different geometry/amount')
    if variable_amount:
        require('not 0. <= amount <= 1.' in runtime and 'math.isnan(amount)' in runtime and 'math.isinf(amount)' in runtime,
                'Variable transparency amount is not validated')
    return dict(source_bundle_sha256=manifest['source_bundle_sha256'], generated_files=generated,
                metadata_hash_discrepancies=metadata_discrepancies,
                writer_fragment_sha256=sha(shader), terrain_material_sha256=sha(resource / 'materials/terrain.material'),
                fixed_k2=True, original_blend_formula_preserved=True,
                one_immutable_project_used_for_all_phases=True, native_config_only_enable_flags_changed=True,
                native_weather_shader_override_absent=True,
                transparency_api_scope='Setters permit and adjust transparency; public API does not promise sorting after weather. There is no verified getter here.')


def state_identity(state):
    return {key: state[key] for key in IDENTITY_FIELDS}


def audit_state(state, source_bundle, kind=None):
    require(state['source_bundle_sha256'] == source_bundle, 'State uses a different source bundle')
    require(state['game_runtime_file_writes'] is False and state['direct_source'] is False and
            state['updates_running'] is False and state['error'] is None, 'State contains updates, direct source, game IO or error')
    require(state['screen_size'] == list(SCREEN), 'State physical screen differs')
    actual = dict(state['actual_post_states'])
    enabled_native = [name for name, enabled in actual.items() if enabled and not name.startswith('scene_codec_')]
    require(enabled_native == state['native_reported_enabled'] == [], 'Native effects are actually reported enabled')
    if kind is not None and kind != 'scene_visible':
        require(state['pipeline_ready'] and state['pipeline_installed'], 'Diagnostic pipeline not ready')
        require(all(actual.get('scene_codec_' + name) is True for name in ('raw', 'encode', 'decode')), 'Codec producer disabled')
        require(actual.get('scene_codec_fixture') is False and actual.get('scene_codec_diagnostic') is False,
                'Fixture/other diagnostic changes the source chain')
        output = 'consumer' if kind in ('identity', 'dependent') else 'inspect'
        other = 'inspect' if output == 'consumer' else 'consumer'
        require(actual.get('scene_codec_' + output) is True and actual.get('scene_codec_' + other) is False,
                'Wrong final diagnostic/consumer selected')
    return actual


def setter_calls(source):
    calls = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != 'set_transparent':
            continue
        require(isinstance(node.func.value, ast.Name) and node.func.value.id == 'probe', 'Unexpected setter target')
        args = [ast.literal_eval(item) for item in node.args]
        keyword = {item.arg: ast.literal_eval(item.value) for item in node.keywords}
        enabled = args[0] if args else keyword['enabled']
        amount = args[1] if len(args) > 1 else keyword.get('amount', 1.0)
        require(type(enabled) is bool and isinstance(amount, (int, float)) and 0 <= amount <= 1,
                'Saved setter arguments are outside the declared API scope')
        calls.append((node.lineno, enabled, amount))
    return [(enabled, amount) for _, enabled, amount in sorted(calls)]


def audit_commands(document, evidence, source_bundle):
    records, states, receipt_history, frozen, failed = [], {}, [], {}, []
    for event in document['events']:
        require(event['automatic_mutation_replay'] is False, 'Host mutation was automatically replayed')
        label = event['label']
        command = evidence / 'commands' / (label + '.py')
        if event['returncode'] != 0:
            require(event is document['events'][-1] and label.endswith('_quiesce') and command.is_file(),
                    'An evidence-producing host event failed: ' + label)
            require(command.read_text(encoding='utf-8').strip() == 'probe.quiesce()\n_result=json.dumps(probe.snapshot())',
                    'Failed final command was not solely cleanup')
            failed.append(dict(label=label, returncode=event['returncode'], command_sha256=sha(command),
                               event_source_hash_available=event.get('source_sha256') is not None,
                               log_sha256=sha(evidence / (label + '.log')),
                               scope='Cleanup failed after all recorded captures; final snapshot remains the last successful state, not a quiesce receipt.'))
            continue
        if command.exists():
            require(sha(command) == event['source_sha256'], 'Executed client command source hash differs')
            state_file = evidence / (label + '.state.json')
            state = load(state_file)
            audit_state(state, source_bundle)
            states[label] = state
            history = state['transparency_receipts']
            require(history[:len(receipt_history)] == receipt_history, 'Prior transparency setter receipts changed')
            new_receipts = history[len(receipt_history):]
            calls = setter_calls(command.read_text(encoding='utf-8'))
            require(len(new_receipts) == len(calls), 'Setter receipt count differs from actual saved commands')
            for receipt, (enabled, amount) in zip(new_receipts, calls):
                require(receipt['geometry_name'] == state['geometry_name'] and receipt['entity'] == state['entity'] and
                        receipt['amount'] == amount and receipt['enabled'] == enabled and
                        receipt['EnableActorBlockGeometryTransparent'] is True,
                        'Transparency setter did not target the current native geometry')
                if receipt['enabled']:
                    require(receipt['SetActorBlockGeometryTransparency'] is True, 'Transparency amount setter failed')
            receipt_history = history
            if history:
                require(state['transparent_requested'] == history[-1]['enabled'], 'Requested transparency not persistent in snapshot')
                enabled_receipts = [item for item in history if item['enabled']]
                if enabled_receipts and 'transparent_amount_requested' in state:
                    require(state['transparent_amount_requested'] == enabled_receipts[-1]['amount'],
                            'Requested transparency amount not persistent in snapshot')
            if state['logical_payload_bytes'] == PAYLOAD_BYTES and state['code_domain_sweep'] is False:
                identity = state_identity(state)
                key = state['geometry_name']
                require(key not in frozen or frozen[key] == identity, 'Payload geometry/data identity changed')
                frozen[key] = identity
            records.append(dict(label=label, command_sha256=sha(command), state_sha256=sha(state_file)))
            continue
        server = evidence / 'commands' / (label + '.server.py')
        if server.exists():
            if event.get('source_sha256') is not None:
                require(sha(server) == event['source_sha256'], 'Executed server command source hash differs')
            records.append(dict(label=label, server_command_sha256=sha(server),
                                bound_to_event_hash=event.get('source_sha256') is not None))
    return dict(commands=records, failed_final_cleanup_events=failed, transparency_receipts=receipt_history,
                frozen_payload_identity_count=len(frozen)), states


def audit_capture(entry, evidence, source_bundle):
    png, state_path = Path(entry['capture']), Path(entry['state'])
    require(png.parent.resolve() == evidence and state_path.parent.resolve() == evidence,
            'Capture/state belong to another evidence directory')
    require(sha(png) == entry['capture_sha256'], 'Capture differs from report hash')
    state = load(state_path)
    kind = entry['kind']
    audit_state(state, source_bundle, kind)
    require(state['actual_post_states'] == entry['actual_post_states'] and
            state['native_post_order'] == entry['native_order'] and
            state['transparent_requested'] == entry['transparent_requested'], 'Embedded diagnostic state differs')
    metadata_path = evidence / (entry['label'] + '.json')
    metadata = load(metadata_path)
    require(metadata['ok'] is True and metadata['backend'] == 'Windows.Graphics.Capture' and
            metadata['native_resolution'] is True and (metadata['width'], metadata['height']) == SCREEN and
            metadata['agent_activation_allowed'] is False and metadata['frame_qpc_100ns'] >= metadata['request_qpc_100ns'],
            'Capture lacks fresh passive native WGC metadata')
    for field in ('background_before', 'background_after'):
        require(metadata[field]['window_noactivate'] is True and metadata[field]['background_safe'] is True,
                'Background/noactivation metadata differs')
    pixels = read_native(png)
    binding = dict(label=entry['label'], capture_sha256=sha(png), state_sha256=sha(state_path),
                   capture_metadata_sha256=sha(metadata_path), pid=metadata['pid'])
    if kind == 'scene_visible':
        return binding | dict(kind=kind, pixel_oracle=False), state
    count = entry['checked_query_pixels']
    result = decode_native(pixels, kind, count)
    for key, value in result.items():
        if key in entry:
            require(value == entry[key], 'Independent PNG replay differs: ' + entry['label'] + '/' + key)
    require(result['guard_errors'] == 0 and result['query_alpha_not255'] == 0, 'Diagnostic guard/output alpha invalid')
    if kind == 'block_alpha':
        require(result['inconsistent_block_count_pixels'] == result['overflow_flag_inconsistent_pixels'] == 0,
                'Same-frame per-block count/overflow channels contradict each other')
    require(count == state['query'][1] and state['query'][0] == 0 and state['query'][3] == 0,
            'Diagnostic state/query count differs')
    expected_modes = {'domain_original': 11, 'domain_encoded': 11, 'domain_restored': 12,
                      'alpha_error': 20, 'q_alpha': 25, 'block_alpha': 24, 'identity': 3, 'dependent': 5}
    require(state['query'][2] == expected_modes[kind], 'Capture is not the requested native diagnostic mode')
    if kind in ('q_alpha', 'block_alpha', 'identity', 'dependent'):
        require(state['logical_payload_bytes'] == PAYLOAD_BYTES and state['payload_salt'] == 29 and
                state['rgb_bits'] == 2 and state['codec_roi'] == ROI and not state['code_domain_sweep'] and
                state['slot_count'] == SOURCE_RECORDS and state['writer_visible'], 'Payload recipe/ROI differs')
    else:
        require(state['code_domain_sweep'] and state['slot_count'] == DOMAIN_RECORDS and state['rgb_bits'] == 2,
                'Known-color domain recipe differs')
        require(state['writer_visible'] == (kind != 'domain_original'), 'Known-color view has wrong writer visibility')
    return binding | result | dict(transparent_requested=state['transparent_requested'],
                                   geometry_identity_sha256=object_sha(state_identity(state))), state


def phase_summary(captures, phase, loops):
    selected = [capture for capture in captures if capture['label'].startswith(phase + '_frame')]
    expected = {('%s_frame%02d_%s' % (phase, frame, kind))
                for frame in range(loops) for kind in ('q_alpha', 'block_alpha', 'identity', 'dependent')}
    require({capture['label'] for capture in selected} == expected, 'Incomplete finite phase matrix: ' + phase)
    by_kind = {kind: [capture for capture in selected if capture['kind'] == kind]
               for kind in ('q_alpha', 'block_alpha', 'identity', 'dependent')}
    q = by_kind['q_alpha']
    blocks = by_kind['block_alpha']
    bad, exposed = sum(c['bad_q'] for c in q), sum(c['alpha_not255'] for c in q)
    return dict(phase=phase, loops=loops, capture_count=len(selected), all_views_passed=all(c['passed'] for c in selected),
                bad_q_per_capture=[c['bad_q'] for c in q], bad_q_total=bad,
                non255_alpha_per_q_capture=[c['alpha_not255'] for c in q], non255_alpha_total=exposed,
                bad_q_with_alpha255_total=sum(c['bad_q_alpha255'] for c in q),
                bad_q_with_non255_alpha_total=sum(c['bad_q_alpha_not255'] for c in q),
                bad_q_fraction_all_source_records=bad / (SOURCE_RECORDS * loops),
                bad_q_fraction_non255_alpha=sum(c['bad_q_alpha_not255'] for c in q) / max(1, exposed),
                q_alpha_offgrid_total=sum(c['alpha_offgrid'] for c in q),
                block_max_exceptions=[c['max_block_exceptions'] for c in blocks],
                block_overflow_counts=[c['overflow_blocks'] for c in blocks],
                block_overflow_count_range=[min(c['overflow_blocks'] for c in blocks), max(c['overflow_blocks'] for c in blocks)],
                block_max_exception_range=[min(c['max_block_exceptions'] for c in blocks), max(c['max_block_exceptions'] for c in blocks)],
                block_overflow_total=sum(c['overflow_blocks'] for c in blocks),
                block_alpha_restore_error_counts=[c['alpha_restore_error_pixels'] for c in blocks],
                block_alpha_restore_error_total=sum(c['alpha_restore_error_pixels'] for c in blocks),
                block_structural_errors=sum(c['inconsistent_block_count_pixels'] + c['overflow_flag_inconsistent_pixels'] for c in blocks),
                identity_error_counts=[c['query_errors'] for c in by_kind['identity']],
                dependent_error_counts=[c['query_errors'] for c in by_kind['dependent']])


def audit_lifecycle(evidence, final, source_bundle, quiesce_succeeded):
    cleanup_file = evidence / 'read_after_quiesce_failure.state.json'
    cleanup = load(cleanup_file) if cleanup_file.exists() else final
    audit_state(cleanup, source_bundle)
    if cleanup_file.exists() or quiesce_succeeded:
        require(cleanup['writer_visible'] is False and cleanup['native_background_visible'] is False and
                not any(cleanup['native_attachment_visibility'].values()) and cleanup['codec_enabled_processes'] == [] and
                cleanup['native_reported_enabled'] == [], 'Post-cleanup read does not show hidden attachments/disabled effects')
    release_file = evidence / 'released_processes.json'
    require(release_file.exists(), 'Final offline audit requires a saved game release receipt')
    release = load(release_file)
    require(release['owned_pid_running'] is False and release['active_count'] == 0, 'Owned game release not established')
    return dict(owned_pid=release['owned_pid'], owned_pid_running=False, active_game_count=0,
                released_processes_sha256=sha(release_file),
                failed_quiesce_followed_by_saved_readonly_check=cleanup_file.exists(),
                readonly_cleanup_state_sha256=sha(cleanup_file) if cleanup_file.exists() else None,
                final_hidden_attachments_verified=cleanup['writer_visible'] is False and not any(cleanup['native_attachment_visibility'].values()),
                stopped_after_normal_stop_timeout_without_force=release.get('normal_stop_timed_out_then_process_exited_without_force'))


def audit_shader_material_comparison(evidence, project):
    comparison_file = evidence / 'r1_r2_shader_material_identity.json'
    if not comparison_file.exists():
        return None
    reference = project.parent.parent / (project.parent.name.rsplit('-r', 1)[0] + '-r1') / 'project'
    saved = load(comparison_file)
    rows = []
    for relative, pair in saved['files'].items():
        require(relative.replace('\\', '/').startswith(('materials/', 'shaders/')), 'Unexpected reference comparison file')
        previous, current = sha(reference / 'resource_pack' / relative), sha(project / 'resource_pack' / relative)
        require(previous == current == pair['r1'] == pair['r2'], 'Shader/material changed between amount experiments')
        rows.append(dict(file=relative, sha256=current))
    return dict(reference_project=str(reference), all_listed_files_identical=True, file_count=len(rows),
                files=rows, comparison_receipt_sha256=sha(comparison_file))


def audit(evidence, project):
    document_path = evidence / 'rain_geometry.results.json'
    document = load(document_path)
    require(document['schema'] == 'rain_geometry_experiment_v1', 'Wrong experiment schema')
    require(document['runtime_file_writes'] is False and document['continuous_updates'] is False and
            document['formal_fps_measured'] is False, 'Unexpected file IO/update/performance claims')
    source = audit_sources(project)
    commands, states = audit_commands(document, evidence, source['source_bundle_sha256'])
    captures, capture_states = [], {}
    for entry in document['reports']:
        result, state = audit_capture(entry, evidence, source['source_bundle_sha256'])
        captures.append(result)
        capture_states[entry['label']] = state
    domain = [c for c in captures if c['kind'].startswith('domain_') or c['kind'] == 'alpha_error']
    expected_domain = {'%s_%s' % (phase, view) for phase in
                       ('domain_default', 'domain_transparent', 'domain_return_default')
                       for view in ('original', 'encoded', 'restored', 'alpha_error')}
    domain_skipped = document.get('known_color_domain_skipped', False)
    require({c['label'] for c in domain} == (set() if domain_skipped else expected_domain),
            'Known-color default/transparent/return matrix incomplete')
    domain_names = {capture_states[c['label']]['geometry_name'] for c in domain}
    domain_entities = {capture_states[c['label']]['entity'] for c in domain}
    require(domain_skipped or len(domain_names) == len(domain_entities) == 1, 'Known-color phases rebuilt or replaced the geometry')
    has_rain = any(c['label'].startswith('rain_default_frame') for c in captures)
    candidate_amount = document.get('candidate_amount', 1.0)
    require(isinstance(candidate_amount, (int, float)) and 0 <= candidate_amount <= 1, 'Candidate amount outside0..1')
    rain_loops = document.get('rain_loops', 5)
    require(rain_loops in (3, 5), 'Undeclared rainy sample count')
    phase_spec = [('clear_default', False, 1), ('clear_transparent', True, 1)]
    if has_rain:
        phase_spec += [('rain_default', False, rain_loops), ('rain_transparent', True, rain_loops),
                       ('rain_return_default', False, rain_loops)]
    phases = [phase_summary(captures, name, loops) for name, transparent, loops in phase_spec]
    payload_captures = [c for c in captures if c['kind'] in ('q_alpha', 'block_alpha', 'identity', 'dependent')]
    identities = {object_sha(state_identity(capture_states[c['label']])) for c in payload_captures}
    require(len(identities) == 1 and commands['frozen_payload_identity_count'] == 1, 'Payload phases use different geometries/data')
    for name, transparent, _ in phase_spec:
        selected = [c for c in payload_captures if c['label'].startswith(name + '_frame')]
        require(all(c['transparent_requested'] == transparent for c in selected), 'Phase transparency request differs: ' + name)
        for capture in selected:
            state = capture_states[capture['label']]
            receipt = state['transparency_receipts'][-1]
            require(receipt['enabled'] == transparent and receipt['geometry_name'] == state['geometry_name'] and
                    receipt['entity'] == state['entity'] and receipt['render_event'] >= 0,
                    'Setter target or post-setter persistence window is inconsistent')
            if transparent:
                require(receipt['amount'] == candidate_amount, 'Actual tested amount differs from candidate')
    clear_phases = [p for p in phases if p['phase'].startswith('clear_')]
    clear_passed = all(p['all_views_passed'] for p in clear_phases)
    if 'clear_gate_passed' in document:
        require(document['clear_gate_passed'] == clear_passed, 'Declared clear gate differs from independent full payload checks')
    if 'requested_transparency_amount' in document:
        require(document['requested_transparency_amount'] == candidate_amount, 'Requested transparency amount metadata differs')
    if 'domain_controls_run' in document:
        require(document['domain_controls_run'] == (not domain_skipped), 'Domain metadata differs')
    require(has_rain or not clear_passed, 'No rainy suite despite a passing clear gate')
    expected_count = len(domain) + 8 + (12 * rain_loops + 1 if has_rain else 0)
    require(len(captures) == expected_count, 'Capture matrix size differs')
    rain = None
    visible = None
    if has_rain:
        rain = load(evidence / 'rain_enabled.server.json')
        require(rain['accepted'] is True and rain['local'] is True and rain['requested_rain'] is True and
                rain['after']['rainLevel'] == 1 and rain['after']['isWeatherCycle'] is False,
                'Actual local rain weather receipt is incomplete')
        server_source = (evidence / 'commands/rain_enabled.server.py').read_text(encoding='utf-8')
        require('SetDimensionLocalRain(0,1.0,12000000)' in server_source and
                'GetDimensionLocalWeatherInfo(0)' in server_source, 'Rain setter/getter command differs')
        visible = next(c for c in captures if c['kind'] == 'scene_visible')
        require(capture_states[visible['label']]['writer_visible'] is False, 'Visible rain screenshot does not hide writer')
    clear = load(evidence / 'prepare_clear_scene.server.json')
    require(clear['case'] == 'solid' and all(item[1] is True for item in clear['weather_calls']) and
            clear['rules_ok'] is True and clear['time_ok'] is True, 'Clear baseline fixture controls failed')
    initial = next(state for label, state in states.items() if label.endswith('_initial_native_state'))
    require(initial['native_reported_enabled'] == [], 'Native startup effects reported enabled')
    final = document['final_state']
    require(final == next(reversed(states.values())), 'Final envelope differs from last successful state')
    quiesce_succeeded = not commands['failed_final_cleanup_events']
    if quiesce_succeeded:
        require(final['writer_visible'] is False, 'Successful final quiesce kept writer visible')
    lifecycle = audit_lifecycle(evidence, final, source['source_bundle_sha256'], quiesce_succeeded)
    comparison = audit_shader_material_comparison(evidence, project)
    candidate = [c for c in captures if c.get('transparent_requested') is True]
    candidate_passed = all(c['passed'] for c in candidate)
    if 'transparent_candidate_passed' in document:
        require(candidate_passed == document['transparent_candidate_passed'] == document['expansion_allowed'],
                'Summary candidate gate differs from independent PNG results')
    by_phase = {p['phase']: p for p in phases}
    default_rain, transparent_rain, returned_rain = (by_phase.get(name) for name in
                                                    ('rain_default', 'rain_transparent', 'rain_return_default'))
    if not has_rain:
        conclusion = 'The transparent amount failed the clear-scene full-payload gate; the rainy matrix was correctly not started. It cannot be accepted as a preservation of the existing payload recipe.'
    elif transparent_rain['all_views_passed'] and candidate_passed:
        conclusion = 'All saved transparent-path payload/alpha diagnostics passed in this finite rain sample. Full original RGB preservation, weather ordering guarantee and 512 KiB/60 FPS remain unestablished.'
    elif transparent_rain['bad_q_total'] or any(transparent_rain['identity_error_counts']) or any(transparent_rain['dependent_error_counts']):
        conclusion = 'The transparent geometry path still corrupts RGB payload in saved rainy frames; it does not solve the rain compatibility failure.'
    else:
        conclusion = 'The transparent-path suite did not fully pass; inspect retained domain/alpha failures before any expansion.'
    return dict(schema='independent_rain_geometry_audit_v1', audit_passed=True,
                input_experiment_status=document['status'], no_game_contact=True, probe_encoder_or_verifier_imported=False,
                candidate_amount=candidate_amount, clear_payload_gate_passed=clear_passed, rainy_matrix_run=has_rain,
                source_audit=source, command_and_setter_audit=commands, captures=captures, phase_summaries=phases,
                audited_state_receipt_count=len(states), lifecycle_audit=lifecycle,
                shader_material_reference_comparison=comparison,
                capture_count=len(captures), diagnostic_capture_count=len(captures) - int(has_rain),
                total_query_pixels=sum(c.get('checked_query_pixels', 0) for c in captures),
                total_guard_pixels=sum(c.get('checked_guard_pixels', 0) for c in captures),
                guard_errors=sum(c.get('guard_errors', 0) for c in captures),
                known_color_domain_skipped=domain_skipped,
                known_color_default_all_passed=not domain_skipped and all(c['passed'] for c in domain if c['label'].startswith('domain_default_')),
                known_color_transparent_all_passed=not domain_skipped and all(c['passed'] for c in domain if c['label'].startswith('domain_transparent_')),
                known_color_return_default_all_passed=not domain_skipped and all(c['passed'] for c in domain if c['label'].startswith('domain_return_default_')),
                known_color_recipe_control_valid=not domain_skipped and all(c['passed'] for c in domain),
                known_color_encoded_equals_background_in_all_three_phases=not domain_skipped and all(
                    c['matches_original_background_pixels'] == DOMAIN_RECORDS for c in domain if c['kind'] == 'domain_encoded'),
                known_color_restored_equals_background_low_bits_model_in_all_three_phases=not domain_skipped and all(
                    c['matches_background_low_bits_restored_pixels'] == DOMAIN_RECORDS for c in domain if c['kind'] == 'domain_restored'),
                known_color_control_scope='If all three encoded views equal the known original background, the control did not expose the writer blend; do not attribute the common failure to transparency or claim blend-preservation from this domain.',
                transparent_observed_suite_passed=candidate_passed,
                rainy_transparent_observed_suite_passed=has_rain and transparent_rain['all_views_passed'],
                all_saved_failure_observations_retained=True, payload_geometry_identity_sha256=next(iter(identities)),
                payload_same_geometry_across_default_transparent_return=True,
                setter_persistence_scope='Successful setters on the same geometry followed by unchanged receipt history and later fresh native captures; no independent native transparency-state getter. Setter render_event is recorded, but capture snapshots do not serialize render_event, so a precise render-tick persistence interval cannot be reconstructed.',
                rain_receipt=rain, rain_receipt_sha256=sha(evidence / 'rain_enabled.server.json') if has_rain else None,
                clear_scene_receipt_sha256=sha(evidence / 'prepare_clear_scene.server.json'),
                visible_rain_capture=visible['label'] if has_rain else None, visible_rain_human_inspection_required=has_rain,
                default_rain_has_payload_errors=has_rain and default_rain['bad_q_total'] > 0,
                returned_default_rain_has_payload_errors=has_rain and returned_rain['bad_q_total'] > 0,
                cross_phase_comparison_scope='Dynamic rain is not the same frame across phases. Counts and alpha-exposure fractions are descriptive; no exact paired causal reduction estimate or render-order trace is established.',
                original_rain_rgb_same_frame_reference_available=False,
                full_original_rain_rgb_preservation_established=False,
                original_rgb_scope='Known-color controls were intended to check the blend/restore recipe but are invalid if their encoded outputs equal the background. Clear payload checks still verify payload transport; rainy payload/alpha checks do not establish correct original rainy RGB without an unencoded same-frame color reference.',
                weather_draw_order_established=False, native_bloom_compatibility_claimed=False,
                final_quiesce_succeeded=quiesce_succeeded,
                final_state_is_last_successful_snapshot=True,
                formal_performance_measured=False, large_512_kib_tested=False,
                conclusion=conclusion, input_results_sha256=sha(document_path), oracle_self_tests=self_test())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.evidence is not None:
        require(args.project is not None, 'Provide --project with --evidence')
        print(json.dumps(audit(args.evidence.resolve(), args.project.resolve()), indent=2, ensure_ascii=False))
        return
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return
    parser.error('Provide --self-test or --evidence with --project')


if __name__ == '__main__':
    main()
