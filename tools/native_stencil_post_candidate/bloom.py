"""Synthetic source-to-original-Bloom control; host-only, inert on import.

``run_bloom_candidate(experiment)`` requires an initialized, owner-validated
Experiment and preinstalled ``resources()``. It neither initializes a game nor
changes native configs, materials, shaders, parameters, or enable flags. The
caller owns startup validation and the game lifecycle. This control establishes
only a synthetic native response, never carrier/emissive compatibility.
"""
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image


SOURCE = 'pmanim_bloom_candidate_source'
INPUT = 'pmanim_bloom_candidate_input'
NATIVE = ('bloom', 'lensflare', 'depthoffield', 'gaussianblur', 'coloradjustment',
          'vignette', 'lensstain', 'oldtv', 'scanmap')
ALPHAS = (1., 0., 1.)
DEFAULT_LAYOUT = {'viewport': [720, 1080], 'patch': [328, 508, 64, 64],
                  'halo_gap': 3, 'halo_radius': 64, 'guard_gap': 32}
HOST = Path(__file__).resolve().parents[1] / 'native_stencil_compat_probe/host.py'

SOURCE_FRAGMENT = '''// __multiversion__
precision highp float;
#include "fragmentVersionCentroidUV.h"
uniform vec4 EXTRA_VECTOR1; // viewport width, height, patch alpha, unused
uniform vec4 EXTRA_VECTOR2; // patch left, top, width, height (physical pixels)
void main() {
    vec2 point = floor(vec2(uv.x, 1.0 - uv.y) * EXTRA_VECTOR1.xy);
    vec2 end = EXTRA_VECTOR2.xy + EXTRA_VECTOR2.zw;
    float patch = float(point.x >= EXTRA_VECTOR2.x && point.y >= EXTRA_VECTOR2.y
                       && point.x < end.x && point.y < end.y);
    gl_FragColor = vec4(vec3(patch), mix(1.0, EXTRA_VECTOR1.z, patch));
}
'''
INPUT_FRAGMENT = '''// __multiversion__
precision highp float;
#include "fragmentVersionCentroidUV.h"
uniform sampler2D TEXTURE_3; // legal explicit source-pass result diagnostic
uniform vec4 EXTRA_VECTOR1; // mode: 0 RGB, 1 alpha displayed as RGB
void main() {
    vec4 source = texture2D(TEXTURE_3, uv);
    vec3 result = EXTRA_VECTOR1.x > 0.5 ? vec3(source.a) : source.rgb;
    gl_FragColor = vec4(result, 1.0);
}
'''


def resources():
    """Return only owned material definitions and GLSL filename/text pairs."""
    materials, shaders = {}, {}
    for name, fragment in ((SOURCE, SOURCE_FRAGMENT), (INPUT, INPUT_FRAGMENT)):
        filename = name + '.fragment'
        shaders[filename] = fragment
        materials[name] = {
            'vertexShader': 'shaders/uv_fullscreen.vertex',
            'fragmentShader': 'shaders/glsl/' + filename,
            'vertexFields': [{'field': 'Position'}, {'field': 'UV0'}],
            'samplerStates': [{'samplerIndex': 3, 'textureWrap': 'Clamp',
                               'textureFilter': 'Point'}] if name == INPUT else [],
            'states': ['DisableDepthTest', 'DisableDepthWrite'],
            '-states': ['DisableAlphaWrite', 'EnableAlphaToCoverage', 'Blending'],
            'msaaSupport': 'Both'}
    return {'materials': materials, 'shaders': shaders}


def _layout(layout=None):
    value = {key: list(item) if isinstance(item, list) else item
             for key, item in DEFAULT_LAYOUT.items()}
    if layout is not None:
        if set(layout) != set(value):
            raise ValueError('Layout must declare viewport, patch, halo_gap, halo_radius, guard_gap')
        value.update(layout)
    width, height = value['viewport']
    x, y, patch_width, patch_height = value['patch']
    numbers = [width, height, x, y, patch_width, patch_height,
               value['halo_gap'], value['halo_radius'], value['guard_gap']]
    if any(type(item) is not int for item in numbers):
        raise ValueError('Layout uses integer physical pixels')
    if min(width, height, patch_width, patch_height) < 1 or min(x, y, value['halo_gap']) < 0:
        raise ValueError('Invalid source patch or viewport')
    if value['halo_radius'] <= value['halo_gap'] or value['guard_gap'] < 1:
        raise ValueError('Require a nonempty halo ring and separated distant guard')
    padding = value['halo_radius'] + value['guard_gap']
    if min(x, y) <= padding or x + patch_width + padding >= width or y + patch_height + padding >= height:
        raise ValueError('Patch, halo and guard separation must fit strictly inside viewport')
    value['viewport'], value['patch'] = [width, height], [x, y, patch_width, patch_height]
    return value


def source_config(layout=None):
    """Disabled procedural source; ordinary predecessor chaining feeds Bloom T0."""
    value = _layout(layout)
    return _process(SOURCE, [
        ('control', [float(item) for item in value['viewport']] + [1., 0.]),
        ('patch', [float(item) for item in value['patch']])])


def _process(name, parameters):
    return {'name': name, 'enable': False,
            'paras': [{'name': key, 'value': value, 'range': [0., 16384.]}
                      for key, value in parameters],
            'pass_array': [{'render_target': {'width': 1., 'height': 1.},
                            'material': name, 'depth_enable': False}]}


def _rgb(frame, layout):
    value = np.asarray(frame)
    width, height = layout['viewport']
    if value.shape != (height, width, 3) or value.dtype.kind not in 'ui':
        raise ValueError('Expected full-viewport integer RGB capture')
    if np.any(value < 0) or np.any(value > 255):
        raise ValueError('RGB samples must be bytes')
    return value.astype(np.int16)


def _triplet(frames, layout):
    if len(frames) != 3:
        raise ValueError('Expected exactly A, B, A-return captures')
    return [_rgb(frame, layout) for frame in frames]


def _threshold(value, name, minimum=0, maximum=254):
    if type(value) is not int or value < minimum or value > maximum:
        raise ValueError(name + ' must be a bounded integer')


def _rectangle_mask(layout, padding=0):
    width, height = layout['viewport']
    x, y, patch_width, patch_height = layout['patch']
    mask = np.zeros((height, width), dtype=bool)
    mask[y-padding:y+patch_height+padding, x-padding:x+patch_width+padding] = True
    return mask


def evaluate_source_control(rgb_frames, alpha_frames, layout=None, tolerance=2):
    """Gate the source attachment using independent expected RGB/alpha images."""
    _threshold(tolerance, 'tolerance')
    layout = _layout(layout)
    rgb, alpha = _triplet(rgb_frames, layout), _triplet(alpha_frames, layout)
    patch = _rectangle_mask(layout)
    expected_rgb = np.repeat((patch.astype(np.int16) * 255)[:, :, None], 3, axis=2)
    rgb_errors = [int(np.any(np.abs(frame-expected_rgb) > tolerance, axis=2).sum()) for frame in rgb]
    alpha_errors = []
    for frame, selected in zip(alpha, ALPHAS):
        expected = np.full(expected_rgb.shape, 255, dtype=np.int16)
        expected[patch] = round(selected * 255)
        alpha_errors.append(int(np.any(np.abs(frame-expected) > tolerance, axis=2).sum()))
    identical = bool(np.array_equal(rgb[0], rgb[1]) and np.array_equal(rgb[0], rgb[2]))
    return {'passed': not any(rgb_errors + alpha_errors) and identical,
            'source_rgb_identical': identical, 'source_rgb_expected_error_pixels': rgb_errors,
            'source_alpha_expected_error_pixels': alpha_errors,
            'alpha_sequence': list(ALPHAS), 'tolerance': tolerance,
            'attachment': [SOURCE, 0, INPUT, 0, 3],
            'scope': 'Direct source attachment and immediate-predecessor contract; synthetic input only'}


def evaluate_bloom_response(frames, layout=None, tolerance=2, min_halo_pixels=16):
    """Require an outside-source signed halo, stable guards and full A return.

    The native final blend can use the original world scene, so this does not
    compare native RGB with the procedural source RGB. Alpha-zero gains fit
    legacy math; alpha-one gains fit RNGL math. Neither authenticates a branch.
    """
    _threshold(tolerance, 'tolerance')
    _threshold(min_halo_pixels, 'min_halo_pixels', 1, 16384)
    layout = _layout(layout)
    a, b, returned = _triplet(frames, layout)
    halo = (_rectangle_mask(layout, layout['halo_radius'])
            & ~_rectangle_mask(layout, layout['halo_gap']))
    guard = ~_rectangle_mask(layout, layout['halo_radius'] + layout['guard_gap'])
    difference = b - a
    # The white source should add/remove all RGB channels together. A local
    # colored world object or a transient in one corner is not a halo witness.
    positive = halo & np.all(difference > tolerance, axis=2)
    negative = halo & np.all(difference < -tolerance, axis=2)
    gains, losses = int(positive.sum()), int(negative.sum())
    dominant, other = max(gains, losses), min(gains, losses)
    coherent = dominant >= min_halo_pixels and other <= dominant * .02
    x, y, width, height = layout['patch']
    yy, xx = np.indices(halo.shape)
    sides = {'top': (yy < y) & (xx >= x) & (xx < x+width),
             'bottom': (yy >= y+height) & (xx >= x) & (xx < x+width),
             'left': (xx < x) & (yy >= y) & (yy < y+height),
             'right': (xx >= x+width) & (yy >= y) & (yy < y+height)}
    selected = positive if gains >= losses else negative
    side_pixels = {name: int((selected & mask).sum()) for name, mask in sides.items()}
    min_side_pixels = max(1, min_halo_pixels // 4)
    distributed = all(count >= min_side_pixels for count in side_pixels.values())
    guard_changes = int((guard & np.any(np.abs(difference) > tolerance, axis=2)).sum())
    return_changes = int(np.any(np.abs(returned-a) > tolerance, axis=2).sum())
    observed = coherent and distributed and guard_changes == 0 and return_changes == 0
    return {'passed': bool(observed), 'outside_patch_halo_pixels': dominant,
            'alpha_zero_gain_pixels': gains, 'alpha_one_gain_pixels': losses,
            'halo_direction_coherent': bool(coherent), 'halo_side_pixels': side_pixels,
            'halo_distributed_on_four_sides': bool(distributed),
            'min_halo_pixels_per_side': min_side_pixels, 'guard_changed_pixels': guard_changes,
            'a_return_changed_pixels': return_changes, 'a_return_stable': return_changes == 0,
            'guard_stable': guard_changes == 0, 'halo_mask_pixels': int(halo.sum()),
            'guard_mask_pixels': int(guard.sum()), 'tolerance': tolerance,
            'min_halo_pixels': min_halo_pixels,
            'response_direction': ('alpha_zero_gain' if gains > losses else 'alpha_one_gain') if observed else None,
            'renderer_branch_authenticated': False}


def _state_expression(parameters=True):
    extra = (",candidate_source_control=probe.post.GetParameter(%r,'control'),"
             "candidate_source_patch=probe.post.GetParameter(%r,'patch'),"
             "candidate_input_control=probe.post.GetParameter(%r,'control')" % (SOURCE, SOURCE, INPUT)) if parameters else ''
    return ('dict(probe.snapshot(),candidate_order=list(probe.post.GetPostProcessOrder() or []),'
            'candidate_flags=[(name,probe.post.CheckEnabledByName(name)) for name in '
            'list(probe.post.GetPostProcessOrder() or [])]' + extra + ')')


def _flags(state):
    order, rows = state['candidate_order'], state['candidate_flags']
    if (len(set(order)) != len(order) or [name for name, _ in rows] != order
            or any(type(enabled) is not bool for _, enabled in rows)):
        raise RuntimeError('Complete distinct order and Boolean enable observations required')
    if not set(NATIVE).issubset(order):
        raise RuntimeError('Native effect inventory is incomplete')
    return order, dict(rows)


def _require_state(state, layout, alpha, diagnostic, mode):
    order, flags = _flags(state)
    expected = [SOURCE, 'bloom'] + ([INPUT] if diagnostic else [])
    if [name for name in order if flags[name]] != expected:
        raise RuntimeError('Exactly procedural source, native Bloom and optional input diagnostic must be enabled')
    if order.index(SOURCE) + 1 != order.index('bloom') or order.index(INPUT) <= order.index('bloom'):
        raise RuntimeError('Source must immediately precede original Bloom; diagnostic must follow it')
    controls = [float(item) for item in layout['viewport']] + [float(alpha), 0.]
    if (state['candidate_source_control'] != controls
            or state['candidate_source_patch'] != [float(item) for item in layout['patch']]
            or state['candidate_input_control'] != [float(mode), 0., 0., 0.]):
        raise RuntimeError('Procedural input parameters/readback differ')
    if (state.get('mode') != 'off' or state.get('payload_visible') is not False
            or state.get('clear_visible') is not False
            or state.get('known_fixture', {}).get('visible') is not False):
        raise RuntimeError('Carrier and other fixture geometry must be hidden')


def _accepted(row):
    if not row['accepted'] or any(ok is not True for _, ok in row['accepted']):
        raise RuntimeError('Custom source/diagnostic operation rejected')


def _register(experiment, layout):
    source, diagnostic = source_config(layout), _process(INPUT, [('control', [0., 0., 0., 0.])])
    code = ("probe.configure('off')\nprobe.configure_known_fixture(False)\n"
            "order=list(probe.post.GetPostProcessOrder() or [])\n"
            "accepted=[(name,probe.post.SetEnableByName(name,False)) for name in order if name not in %r]\n"
            "accepted.append((%r,probe.post.AddPostProcess(%r,order.index('bloom'))))\n"
            "accepted.append((%r,probe.post.AddPostProcess(%r)))\n"
            "accepted.extend((name,probe.post.SetEnableByName(name,True)) for name in %r)" %
            (NATIVE, SOURCE, source, INPUT, diagnostic, (SOURCE, INPUT)))
    row = experiment.call('bloom_candidate_register', code,
                          "{'accepted':accepted,'render_event':probe.render_event}")
    _accepted(row)
    return row


def _capture(experiment, label):
    """Fresh passive capture using the existing host; no lifecycle operations."""
    experiment.invoke([sys.executable, '-B', '-X', 'utf8', str(HOST), 'capture',
        '--project', str(Path(experiment.args.project).resolve()),
        '--evidence', str(experiment.evidence), '--label', label], label + '_capture')
    path = Path(experiment.evidence) / (label + '.png')
    capture = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    if (capture.get('ok') is not True or capture.get('backend') != 'Windows.Graphics.Capture'
            or capture.get('native_resolution') is not True
            or [capture.get('width'), capture.get('height')] != list(experiment.viewport)
            or capture.get('pid') != experiment.game_pid
            or capture.get('window', {}).get('pid') != experiment.game_pid
            or capture.get('window', {}).get('minimized') is not False
            or capture.get('agent_activation_allowed') is not False
            or type(capture.get('request_qpc_100ns')) is not int
            or type(capture.get('frame_qpc_100ns')) is not int
            or capture['request_qpc_100ns'] <= 0
            or capture['frame_qpc_100ns'] < capture['request_qpc_100ns']
            or any(capture.get(key, {}).get('window_noactivate') is not True
                   for key in ('background_before', 'background_after'))):
        raise RuntimeError('Owned fresh passive native capture rejected')
    before, after = capture['background_before']['foreground'], capture['background_after']['foreground']
    if any(before.get(key) != after.get(key) for key in ('hwnd', 'pid', 'identity')):
        raise RuntimeError('Foreground identity changed during passive capture')
    if Path(capture['file']).resolve() != path.resolve():
        raise RuntimeError('Capture receipt path differs from image')
    with Image.open(path) as source:
        pixels = np.array(source.convert('RGB'))
    return {'label': label, 'capture_file': str(path), 'capture_receipt': capture}, pixels


def _sample(experiment, receipt, capture, settle, layout, label, alpha, diagnostic, mode=0):
    control = [float(item) for item in layout['viewport']] + [float(alpha), 0.]
    code = ("accepted=[('source_control',probe.post.SetParameter(%r,'control',%r)),"
            "('diagnostic_control',probe.post.SetParameter(%r,'control',%r)),"
            "('source_enable',probe.post.SetEnableByName(%r,True)),"
            "('diagnostic_enable',probe.post.SetEnableByName(%r,%r))]" %
            (SOURCE, control, INPUT, [float(mode), 0., 0., 0.], SOURCE, INPUT, diagnostic))
    requested = experiment.call(label + '_set', code,
                                "{'accepted':accepted,'render_event':probe.render_event}")
    _accepted(requested)
    settle()
    before = experiment.call(label + '_before', expression=_state_expression())
    _require_state(before, layout, alpha, diagnostic, mode)
    if type(before.get('render_event')) is not int or before['render_event'] <= requested['render_event']:
        raise RuntimeError('Source control did not settle on a later render turn')
    row, pixels = capture(experiment, label)
    after = experiment.call(label + '_after', expression=_state_expression())
    _require_state(after, layout, alpha, diagnostic, mode)
    if after['render_event'] < before['render_event']:
        raise RuntimeError('Render turn regressed during capture')
    row = dict(row, state_before=before, state_after=after, patch_alpha=alpha,
               input_diagnostic_enabled=diagnostic, input_diagnostic_mode=mode)
    receipt['captures'].append(row)
    return pixels


def _cleanup(experiment, initial):
    order, flags = _flags(initial)
    fixture = initial.get('known_fixture', {})
    code = ("probe.configure(%r)\nprobe.configure_known_fixture(%r,%r)\n"
            "order=list(probe.post.GetPostProcessOrder() or [])\n"
            "accepted=[(name,probe.post.SetEnableByName(name,False)) for name in %r if name in order]\n"
            "accepted.extend((name,probe.post.SetEnableByName(name,enabled)) for name,enabled in %r)" %
            (initial['mode'], fixture.get('visible', False), fixture.get('varying_alpha', True),
             (SOURCE, INPUT), [(name, flags[name]) for name in order if name not in NATIVE]))
    row = experiment.call('bloom_candidate_cleanup', code,
                          "{'accepted':accepted,'state':" + _state_expression(False) + '}')
    _accepted(row)
    _, returned = _flags(row['state'])
    if (any(returned.get(name) is not enabled for name, enabled in flags.items())
            or any(returned.get(name, False) is not False for name in (SOURCE, INPUT))):
        raise RuntimeError('Original enable states did not return')
    return row


def run_bloom_candidate(experiment, *, capture=None, settle=None, layout=None):
    """Run a bounded control on an already initialized, validated Experiment.

    ``capture(experiment, label) -> (JSON_metadata, RGB_array)`` and a no-arg
    ``settle()`` may be injected for offline tests. There are six source-control
    and three native captures. A failed source gate performs no native captures.
    Missing response always retains ``compatibility=None``.
    """
    capture = _capture if capture is None else capture
    settle = (lambda: time.sleep(.65)) if settle is None else settle
    receipt = {'schema': 'native_stencil_bloom_candidate_v1', 'effect': 'bloom',
               'status': 'not_started', 'compatibility': None, 'failure': None,
               'source_input_gate_passed': False, 'captures': [],
               'native_stage_executed_observed': False, 'native_positive_response_observed': False,
               'native_configuration_modified': False, 'native_texture_slots_rebound': False,
               'synthetic_control_only': True, 'carrier_compatibility_tested': False,
               'timing_measured': False, 'lifecycle_owner_must_close_startup_variant': True}
    initial, mutated = None, False
    try:
        layout = _layout(layout)
        receipt['layout'] = layout
        if list(experiment.viewport) != layout['viewport']:
            raise RuntimeError('Candidate viewport differs from initialized Experiment')
        initial = experiment.call('bloom_candidate_initial', expression=_state_expression(False))
        order, flags = _flags(initial)
        if SOURCE in order or INPUT in order:
            raise RuntimeError('Candidate requires fresh unregistered owned process names')
        if flags['bloom'] is not True or any(flags[name] for name in NATIVE if name != 'bloom'):
            raise RuntimeError('Original startup Bloom must be the sole enabled native effect')
        receipt['initial_state'] = initial
        mutated = True  # A rejected registration can still have changed earlier controls.
        receipt['registration'] = _register(experiment, layout)
        # Prime both custom passes before linking their attachment. No capture
        # is accepted while the diagnostic T3 is still unconnected.
        settle()
        linked = experiment.call('bloom_candidate_link',
            "accepted=[('source_to_diagnostic_T3',probe.post.PostPassResultToOtherPass(%r,0,%r,0,3))]" % (SOURCE, INPUT),
            "{'accepted':accepted,'render_event':probe.render_event}")
        _accepted(linked)
        if linked['render_event'] <= receipt['registration']['render_event']:
            raise RuntimeError('Source registration/linking did not cross a render turn')
        receipt['source_attachment'] = linked
        rgb, alpha = [], []
        for label, selected in zip(('a', 'b', 'a_return'), ALPHAS):
            for kind, frames, mode in (('rgb', rgb, 0), ('alpha', alpha, 1)):
                frames.append(_sample(experiment, receipt, capture, settle, layout,
                    'bloom_candidate_source_' + label + '_' + kind, selected, True, mode))
        receipt['source_control'] = evaluate_source_control(rgb, alpha, layout)
        receipt['source_input_gate_passed'] = receipt['source_control']['passed']
        if not receipt['source_input_gate_passed']:
            receipt.update(status='source_control_unproven',
                           limitation='Declared source RGB/alpha attachment was not established; native phase skipped.')
            return receipt
        native = [_sample(experiment, receipt, capture, settle, layout,
                          'bloom_candidate_native_' + label, selected, False)
                  for label, selected in zip(('a', 'b', 'a_return'), ALPHAS)]
        response = evaluate_bloom_response(native, layout)
        receipt['native_response'] = response
        observed = response['passed']
        receipt.update(status='native_positive_control_observed' if observed else 'native_stage_unproven',
                       native_stage_executed_observed=observed, native_positive_response_observed=observed)
        receipt['limitation'] = ('Synthetic source-to-Bloom halo only; real emissive materials and carrier coexistence remain untested.'
                                 if observed else 'No accepted bounded native halo witness; compatibility remains unknown.')
    except Exception as error:
        receipt.update(status='helper_failed', failure=repr(error))
    finally:
        if mutated:
            try:
                receipt['cleanup'] = _cleanup(experiment, initial)
            except Exception as error:
                receipt['cleanup_failure'] = repr(error)
                receipt.update(status='helper_failed', failure=receipt['failure'] or repr(error))
        (Path(experiment.evidence) / 'bloom_candidate_status.json').write_text(
            json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        experiment.save()
    return receipt


run = run_bloom_candidate
