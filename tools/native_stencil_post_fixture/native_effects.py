"""Bounded original-native bloom/DOF observations on an owned 64 KiB carrier.

This module does not launch or stop a game. The lifecycle owner supplies its
Experiment. Expected compatibility failures are returned, never raised into a
different baseline/effect run. No native shader or material is patched here.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys
import time

import numpy as np
from PIL import Image


HERE = Path(__file__).resolve().parent
HOST = HERE.parent / 'native_stencil_compat_probe/host.py'
CORE = ('stencil_integrated_copy', 'stencil_integrated_restore', 'stencil_integrated_consumer')
NATIVE = ('bloom', 'lensflare', 'depthoffield', 'gaussianblur', 'coloradjustment',
          'vignette', 'lensstain', 'oldtv', 'scanmap')
RESIDENT = ('identity', 'logical_bytes', 'viewport', 'source_roi', 'generation',
            'active_pages', 'native_page_names', 'native_attempt_count', 'native_records_reserved')
VIEWPORT, ROI, OUTPUT_Y = [720, 1080], [8, 128, 512, 512], 650


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


verify_module = _module('native_post_integrated_verify', HERE.parent / 'weather_stencil_integrated_probe/verify.py')
assets = _module('native_post_startup_assets', HERE / 'assets.py')


def _effect(effect):
    effect = 'depthoffield' if effect == 'dof' else effect
    if effect not in ('bloom', 'depthoffield'):
        raise ValueError('Expected bloom or depthoffield')
    return effect


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _camera_sample_valid(sample):
    event = sample.get('render_event')
    if type(event) is not int or event < 0:
        return False
    for key in ('position', 'forward'):
        values = sample.get(key)
        if (not isinstance(values, (list, tuple)) or len(values) != 3
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in values)):
            return False
    norm = math.hypot(*sample['forward'])
    return math.isfinite(norm) and norm > 0.


def wait_camera(experiment, effect, phase='initial', after_render_event=None):
    """Require valid camera vectors on two render turns, at most 20 reads.

    The first native ticks may expose a position while GetForward is still
    None. Wall-clock delay alone is insufficient: the second valid sample
    must carry a strictly later render_event. No game state is changed here.
    """
    effect = _effect(effect)
    if phase not in ('initial', 'detached'):
        raise ValueError('Unknown native camera preparation phase')
    if after_render_event is not None and (type(after_render_event) is not int or after_render_event < 0):
        raise ValueError('Expected a nonnegative prior render turn')
    receipt = {'schema': 'native_stencil_camera_preflight_v1', 'effect': effect,
               'phase': phase, 'after_render_event': after_render_event,
               'ready': False, 'max_calls': 20, 'interval_seconds': .25,
               'calls_attempted': 0, 'observations': [], 'failure': None,
               'host_source_sha256': _sha(__file__)}
    candidate = None
    try:
        for attempt in range(20):
            receipt['calls_attempted'] += 1
            sample = experiment.call('native_%s_%s_camera_%02d' % (effect, phase, attempt), expression=
                "{'position':probe.camera.GetPosition(),'forward':probe.camera.GetForward(),'render_event':probe.render_event}")
            valid = (_camera_sample_valid(sample)
                     and (after_render_event is None or sample['render_event'] > after_render_event))
            receipt['observations'].append(dict(sample, valid=valid))
            if valid and candidate is not None and sample['render_event'] > candidate['render_event']:
                receipt.update(ready=True, first_ready_render_event=candidate['render_event'],
                               later_ready_render_event=sample['render_event'])
                return receipt
            if not valid:
                candidate = None
            elif candidate is None or sample['render_event'] < candidate['render_event']:
                candidate = sample
            if attempt < 19:
                time.sleep(.25)
        raise RuntimeError('Camera position/forward not ready on two render turns after 20 bounded reads')
    except Exception as error:
        receipt['failure'] = repr(error)
        raise
    finally:
        suffix = '' if phase == 'initial' else '_detached'
        _write(experiment.evidence / ('native_%s_camera_preflight%s.json' % (effect, suffix)), receipt)


def prepare_camera(experiment, effect):
    """Split native camera transition from anchor creation across render turns.

    Frozen prepare() immediately rereads GetForward after DepartCamera. Keep
    its public camera operations and final state, but poll the detached camera
    before using those vectors. A partial failure is recorded and never retried
    as if an existing origin implied complete initialization.
    """
    effect = _effect(effect)
    receipt = {'schema': 'native_stencil_camera_setup_v1', 'effect': effect,
               'ready': False, 'stage': 'initial', 'failure': None,
               'host_source_sha256': _sha(__file__)}
    try:
        initial = wait_camera(experiment, effect)
        receipt['initial'] = initial
        position = initial['observations'][-1]['position']
        origin = (int(position[0]), int(position[1])-1, int(position[2]))
        receipt['stage'] = 'request_detach'
        requested = experiment.call('native_%s_request_fixed_camera' % effect,
            "probe._idle()\n"
            "if probe.origin is not None or probe.anchor is not None or probe.clear_actor is not None or probe.actors: raise RuntimeError('Need fresh native camera setup')\n"
            "probe.origin=%r\n"
            "detached=probe.camera.DepartCamera()\n"
            "accepted=[probe.camera.SetCameraPos(%r),probe.camera.SetCameraRotation((8.,180.,0.))]" %
            (origin, (origin[0], origin[1]+1., origin[2])),
            "{'origin':list(probe.origin),'accepted':accepted,'detach_result':detached,'render_event':probe.render_event}")
        receipt['request'] = requested
        if (requested['origin'] != list(origin) or len(requested['accepted']) != 2
                or not all(value is True for value in requested['accepted'])):
            raise RuntimeError('Native detached camera position/rotation request rejected')
        receipt['stage'] = 'wait_detached'
        detached = wait_camera(experiment, effect, phase='detached',
                               after_render_event=requested['render_event'])
        receipt['detached'] = detached
        sample = detached['observations'][-1]
        # Use the validated sample rather than making another getter read in
        # the setup call. No anchor exists during the camera transition.
        position, forward = tuple(sample['position']), tuple(sample['forward'])
        anchor = tuple(position[i]+forward[i]*3. for i in range(3))
        if not all(math.isfinite(value) for value in anchor):
            raise RuntimeError('Detached camera produced a nonfinite anchor')
        receipt['stage'] = 'create_anchor'
        completed = experiment.call('native_%s_delayed_anchor' % effect,
            "probe._idle()\n"
            "if probe.origin!=%r or probe.anchor is not None or probe.clear_actor is not None: raise RuntimeError('Partial native camera setup changed')\n"
            "probe.anchor=%r\n"
            "api.HideHudGUI(True)\nprobe.native_hud_hidden=True\n"
            "probe.clear_actor=probe._new_actor('clear',0)\n"
            "api.HideCrossHairGUI(True)\nprobe.prepare()" % (origin, anchor),
            "{'origin':list(probe.origin),'anchor':list(probe.anchor),'clear_created':probe.clear_actor is not None,'hud_hidden':probe.native_hud_hidden,'render_event':probe.render_event}")
        receipt['completion'] = completed
        if (completed['origin'] != list(origin) or completed['anchor'] != list(anchor)
                or completed['clear_created'] is not True or completed['hud_hidden'] is not True
                or completed['render_event'] < sample['render_event']):
            raise RuntimeError('Delayed native anchor initialization rejected')
        receipt.update(ready=True, stage='complete')
        return receipt
    except Exception as error:
        receipt['failure'] = repr(error)
        raise
    finally:
        _write(experiment.evidence / ('native_%s_camera_setup.json' % effect), receipt)


def definition(name, material, size=65536, viewport=VIEWPORT, roi=ROI, output_y=128):
    params = [('control', [float(viewport[0]), float(viewport[1]), 0., float(size)]),
              ('roi', [float(value) for value in roi]),
              ('output', [0., float(output_y), float(viewport[0]), 0.])]
    return {'name': name, 'enable': True, 'paras': [
        {'name': parameter, 'value': value, 'range': [0., 2097152.]}
        for parameter, value in params], 'pass_array': [
            {'render_target': {'width': 1., 'height': 1.}, 'material': material, 'depth_enable': False}]}


def _startup(project, effect):
    """Bind actual startup inputs and reject substituted config/native overrides."""
    path = Path(project) / 'native_post_startup.json'
    receipt = assets.validate_startup(project, effect)
    if (receipt['effect'] != effect or receipt['startup_enabled_effects'] != [effect]
            or receipt['original_native_math'] is not True or receipt['original_pass_arrays'] is not True):
        raise RuntimeError('Original isolated startup receipt rejected')
    for relative, row in receipt['config_outputs'].items():
        if _sha(Path(project) / relative) != row['output_sha256']:
            raise RuntimeError('Startup post config changed after installation: ' + relative)
        if _sha(row['source_file']) != row['source_sha256']:
            raise RuntimeError('Installed native source config changed')
    if len(receipt['config_outputs']) != 2:
        raise RuntimeError('Both legacy and RNGL startup configs are required')
    return dict(receipt, receipt_sha256=_sha(path))


def _resident(state, payload, reference=None):
    """Validate complete resident evidence rather than accepting missing == missing."""
    if any(key not in state for key in RESIDENT):
        raise RuntimeError('Incomplete resident-state evidence')
    if (len(payload) != 65536 or state['logical_bytes'] != 65536
            or state['viewport'] != VIEWPORT or state['source_roi'] != ROI
            or state['state'] != 'resident' or state['ready'] is not True
            or state['identity']['host_sha256'] != hashlib.sha256(payload).hexdigest()
            or state['identity']['byte_count'] != len(payload)):
        raise RuntimeError('Expected the frozen actual 64 KiB carrier and fixed layout')
    for key in ('active_pages', 'native_page_names'):
        value = state[key]
        if (not isinstance(value, list) or not value or len(set(value)) != len(value)
                or any(not isinstance(name, str) or not name for name in value)):
            raise RuntimeError('Resident page names must be present and distinct')
    if not set(state['active_pages']).issubset(state['native_page_names']):
        raise RuntimeError('Active page is absent from resident native pages')
    for key in ('generation', 'native_attempt_count', 'native_records_reserved'):
        if type(state[key]) is not int or state[key] <= 0:
            raise RuntimeError('Invalid resident count: ' + key)
    if reference is not None and any(state[key] != reference[key] for key in RESIDENT):
        raise RuntimeError('Frozen payload or resident native geometry changed')


def _isolation(state, effect, late):
    rows = state['native_post_flags']
    if len(rows) != len(NATIVE) or {name for name, _ in rows} != set(NATIVE):
        raise RuntimeError('Complete native enable observations are required')
    flags = dict(rows)
    if flags[effect] is not True or any(flags[name] is not False for name in NATIVE if name != effect):
        raise RuntimeError('Requested original native effect is not isolated')
    required = [*CORE, effect, late]
    order = state['actual_post_order']
    if [name for name in order if name in required] != required:
        raise RuntimeError('Copy/restore/consumer/native/late order rejected')
    all_flags = state['native_test_all_flags']
    if [name for name, _ in all_flags] != order or [name for name, enabled in all_flags if enabled is True] != required:
        raise RuntimeError('Exactly the original custom chain, target native and late reader must be enabled')
    if any(type(enabled) is not bool for _, enabled in all_flags):
        raise RuntimeError('Post enabled observations must be Boolean')


def _chain(experiment, effect, receipt, initial=False):
    """Native setters run before this; they may erase dynamic registrations."""
    late = 'stencil_integrated_after_' + effect
    definitions = [definition(name, name) for name in CORE]
    late_definition = definition(late, CORE[-1], output_y=OUTPUT_Y)
    code = """probe._idle()
order=list(probe.post.GetPostProcessOrder() or [])
accepted=[]
for i,item in enumerate(%r):
    if item['name'] not in order:
        accepted.append((item['name'],probe.post.AddPostProcess(item,i)))
if %r not in order:
    accepted.append((%r,probe.post.AddPostProcess(%r)))
""" % (definitions, late, late, late_definition)
    if initial:
        code += """probe.pipeline_registered=%r
probe._pipeline_controls(0,False,False)
probe.pipeline_enabled=True
probe.pipeline_installed=True
probe.pipeline_ready=False
probe.pipeline_install_frame=probe.render_event
""" % (list(CORE),)
    registration = experiment.call('native_%s_registration' % effect, code,
                                   "{'accepted':accepted,'order':probe.post.GetPostProcessOrder()}")
    receipt.setdefault('chain_registrations', []).append(registration)
    if not all(accepted is True for _, accepted in registration['accepted']):
        raise RuntimeError('Original custom chain registration rejected')
    time.sleep(.65)
    if initial:
        experiment.call('native_%s_pipeline_finish' % effect, 'probe.finish_pipeline()')
    links = [(CORE[0], 0, CORE[1], 0, 3), (CORE[0], 0, CORE[2], 0, 3),
             (CORE[1], 0, CORE[2], 0, 4), (CORE[0], 0, late, 0, 3),
             (CORE[1], 0, late, 0, 4)]
    linked = experiment.call('native_%s_links' % effect,
        'linked=[(link,probe.post.PostPassResultToOtherPass(*link)) for link in %r]\n'
        'enabled=[(name,probe.post.SetEnableByName(name,True)) for name in %r]' % (links, [*CORE, late]),
        "{'links':linked,'enabled':enabled,'state':dict(probe.snapshot(),native_test_all_flags=[(name,probe.post.CheckEnabledByName(name)) for name in list(probe.post.GetPostProcessOrder() or [])])}")
    receipt.setdefault('chain_links', []).append(linked)
    if not all(ok is True for _, ok in linked['links'] + linked['enabled']):
        raise RuntimeError('Custom attachment links or enables rejected')
    _isolation(linked['state'], effect, late)
    return late


def initialize(experiment, effect):
    """Initialize a fresh startup variant without changing frozen game code.

    Call this instead of Experiment.initialize() for a startup-active variant.
    It uses the original copy/restore/consumer definitions and finish_pipeline.
    """
    effect = _effect(effect)
    startup = _startup(experiment.args.project, effect)
    if getattr(experiment, 'variant', None) != 'carrier':
        raise RuntimeError('Original native post test needs the carrier package known fixture')
    experiment.invoke([sys.executable, '-B', '-X', 'utf8', str(HOST), 'resize',
        '--project', str(experiment.args.project), '--evidence', str(experiment.evidence),
        '--width', '720', '--height', '1080'], 'native_' + effect + '_resize')
    initial = experiment.call('native_%s_before_prepare' % effect)
    if initial['pipeline_registered'] or initial['oracle_installed']:
        raise RuntimeError('Fresh initialization requires no custom pipeline yet')
    camera_setup = prepare_camera(experiment, effect)
    experiment.weather('native_%s_clear' % effect, False, True)
    experiment.load(65536)
    experiment.output_y = OUTPUT_Y
    receipt = {'startup': startup, 'camera_setup': camera_setup}
    _chain(experiment, effect, receipt, initial=True)
    _write(experiment.evidence / ('native_%s_initialize.json' % effect), receipt)
    return experiment.call('native_%s_initialized' % effect)


def fixture_statistics(image, payload, viewport=VIEWPORT, roi=ROI):
    """Exhaustive analytic restored and encoded RGB comparisons in the ROI."""
    array = np.asarray(image)
    if array.dtype != np.uint8 or array.shape != (viewport[1], viewport[0], 3):
        raise ValueError('Expected a native-size RGB uint8 image')
    if len(payload) * 4 != roi[2] * roi[3]:
        raise ValueError('Payload does not fill the source ROI')
    x, y, width, height = roi
    observed = array[y:y+height, x:x+width].reshape(-1, 3)
    original = verify_module.fixture_rgba(roi)[:, :3]
    quantized = (original.astype(np.int32) * 63 + 127) // 255
    source = np.frombuffer(payload, dtype=np.uint8)
    symbol = ((source[:, None] >> np.arange(4, dtype=np.uint8)[None, :] * 2) & 3).reshape(-1)
    encoded = quantized.copy()
    encoded[:, 0] += symbol.astype(np.int32) * 64
    restored_diff = np.abs(observed.astype(np.int16) - original.astype(np.int16))
    encoded_diff = np.abs(observed.astype(np.int16) - encoded)
    return {'fixture_pixels': int(original.shape[0]),
            'original_exact_pixels': int(np.count_nonzero(np.all(restored_diff == 0, axis=1))),
            'original_error_gt2_pixels': int(np.count_nonzero(np.any(restored_diff > 2, axis=1))),
            'original_max_rgb_error': restored_diff.max(axis=0).tolist(),
            'encoded_exact_pixels': int(np.count_nonzero(np.all(encoded_diff == 0, axis=1))),
            'encoded_error_pixels': int(np.count_nonzero(np.any(encoded_diff != 0, axis=1))),
            'encoded_max_rgb_error': encoded_diff.max(axis=0).tolist()}


def _capture(experiment, effect, late, label, reference, receipt, analysis=None,
             configuration='off', mode=0, varying=False):
    state = experiment.call(label + '_settled', expression=
        'dict(probe.snapshot(),native_test_all_flags=[(name,probe.post.CheckEnabledByName(name)) for name in list(probe.post.GetPostProcessOrder() or [])],native_test_late_control=probe.post.GetParameter(%r,"control"))' % late)
    _resident(state, experiment.payload, reference)
    _isolation(state, effect, late)
    fixture = state['known_fixture']
    if (state['mode'] != configuration or state['payload_visible'] is not (configuration == 'all')
            or state['clear_visible'] is not (configuration == 'all')
            or state['pipeline_ready'] is not True or state['pipeline_enabled'] is not True
            or state['restore_enabled'] is not (configuration == 'all')
            or state['consumer_mode'] != 0 or state['shape_enabled'] is not False
            or fixture['visible'] is not True or fixture['varying_alpha'] is not varying
            or fixture['roi'] != ROI
            or state['native_test_late_control'] != [720., 1080., float(mode), 65536.]):
        raise RuntimeError('Carrier visibility, restoration, fixture or late-reader controls differ')
    experiment.invoke([sys.executable, '-B', '-X', 'utf8', str(HOST), 'capture',
        '--project', str(experiment.args.project.resolve()), '--evidence', str(experiment.evidence),
        '--label', label], label + '_capture')
    path = experiment.evidence / (label + '.png')
    capture = json.loads((experiment.evidence / (label + '.json')).read_text(encoding='utf-8'))
    if (capture.get('ok') is not True or capture.get('backend') != 'Windows.Graphics.Capture'
            or capture.get('native_resolution') is not True
            or [capture.get('width'), capture.get('height')] != VIEWPORT
            or capture.get('pid') != experiment.game_pid
            or capture.get('window', {}).get('pid') != experiment.game_pid
            or capture.get('agent_activation_allowed') is not False
            or type(capture.get('request_qpc_100ns')) is not int
            or type(capture.get('frame_qpc_100ns')) is not int
            or capture['request_qpc_100ns'] <= 0
            or capture['frame_qpc_100ns'] < capture['request_qpc_100ns']
            or capture.get('window', {}).get('minimized') is not False
            or any(capture.get(key, {}).get('window_noactivate') is not True
                   for key in ('background_before', 'background_after'))):
        raise RuntimeError('Owned fresh passive native capture rejected')
    before = capture['background_before']['foreground']
    after = capture['background_after']['foreground']
    if any(before.get(key) != after.get(key) for key in ('hwnd', 'pid', 'identity')):
        raise RuntimeError('Foreground identity changed during capture')
    if Path(capture['file']).resolve() != path.resolve():
        raise RuntimeError('Capture receipt path is not the verified image')
    row = {'label': label, 'capture_file': str(path), 'capture_sha256': _sha(path),
           'capture_receipt': capture, 'state': state}
    receipt['captures'].append(row)
    with Image.open(path) as source:
        image = source.convert('RGB')
        if analysis is not None:
            row.update(analysis(image))
    return row


def _controls(experiment, late, configuration, mode=0, varying=False):
    controls = [720., 1080., float(mode), 65536.]
    experiment.call('native_%s_%s_m%d_controls' % (late, configuration, mode),
        'probe.configure(%r)\nprobe.inspect(0,enabled=True)\n'
        'probe.configure_known_fixture(True,%r)\n'
        'accepted=probe.post.SetParameter(%r,\'control\',%r)\n'
        'if not accepted: raise RuntimeError(\'Late native reader control rejected\')' %
        (configuration, varying, late, controls))
    time.sleep(.6)


def _dof_profile(experiment, receipt, positive=False, focus=2.):
    scale = 15. if positive else 0.
    code = """accepted=[('center',probe.post.SetDepthOfFieldUseCenterFocus(False)),
('focus',probe.post.SetDepthOfFieldFocusDistance(%r)),
('near',probe.post.SetDepthOfFieldNearBlurScale(%r)),
('far',probe.post.SetDepthOfFieldFarBlurScale(%r)),
('radius',probe.post.SetDepthOfFieldBlurRadius(2.0)),
('enable',probe.post.SetEnableDepthOfField(True))]
""" % (float(focus), scale, scale)
    row = experiment.call('native_dof_profile', code,
        "{'accepted':accepted,'dedicated_enabled':probe.post.CheckDepthOfFieldEnabled(),'state':probe.snapshot()}")
    receipt.setdefault('dof_profiles', []).append(dict(row, requested={'focus': focus, 'near': scale, 'far': scale, 'radius': 2.}))
    if not all(ok is True for _, ok in row['accepted']) or row['dedicated_enabled'] is not True:
        raise RuntimeError('Documented original DOF setter rejected its profile')
    time.sleep(.65)
    return _chain(experiment, 'depthoffield', receipt)


def classify(control, active, returned, diagnostics, positive_witness):
    """Keep a native raw-T1 failure distinct from an unproven execution stage."""
    stable = control['original_error_gt2_pixels'] == 0 and returned['original_error_gt2_pixels'] == 0
    full_data = ([row['mode'] for row in diagnostics] == [1, 2, 6]
                 and all(row['exact'] is True for row in diagnostics))
    raw = stable and full_data and active['encoded_error_pixels'] == 0 and active['original_error_gt2_pixels'] > 0
    if raw:
        status, compatibility = 'original_raw_t1_bypass_detected', False
    elif stable and full_data and active['original_error_gt2_pixels'] == 0 and positive_witness:
        status, compatibility = 'compatible_original_native_observed', True
    elif not stable:
        status, compatibility = 'analytic_identity_control_failed', None
    elif not full_data:
        status, compatibility = 'late_payload_or_restored_reference_failed', False
    elif active['original_error_gt2_pixels'] > 0:
        status, compatibility = 'original_native_output_differs', False
    else:
        status, compatibility = 'native_stage_unproven', None
    return {'status': status, 'compatibility': compatibility,
            'native_stage_executed_observed': bool(raw or positive_witness),
            'native_positive_response_observed': bool(positive_witness),
            'original_raw_t1_bypass_detected': bool(raw),
            'known_identity_controls_passed': bool(stable), 'late_full_data_passed': bool(full_data)}


def run(experiment, effect):
    """Run one independent effect; preserve expected failures in its own receipt.

    Requires install_startup() before launch and initialize() above, or an
    already initialized equivalent owned carrier. This function never launches,
    never changes source files, and returns its failure instead of aborting the
    caller's baseline/other-effect orchestration.
    """
    effect = _effect(effect)
    prefix = 'native_original_' + effect
    receipt = {'schema': 'native_stencil_original_post_v1', 'effect': effect,
               'status': 'not_started', 'compatibility': None, 'captures': [],
               'failure': None, 'timing_measured': False, 'capacity_tested': 65536,
               'alpha_packing': False, 'derived_native_patch': False,
               'host_source_sha256': _sha(__file__)}
    try:
        receipt['startup'] = _startup(experiment.args.project, effect)
        session_path = Path(experiment.session)
        session = json.loads(session_path.read_text(encoding='utf-8-sig'))
        if (session['owner'] != 'manim-native-stencil-compat'
                or Path(session['project']).resolve() != experiment.args.project.resolve()
                or session['game_pid'] != experiment.game_pid):
            raise RuntimeError('Native compatibility owner/project/PID binding rejected')
        receipt['owner_binding'] = {'owner': session['owner'], 'pid': session['game_pid'],
                                    'session_file': str(session_path), 'session_sha256': _sha(session_path)}
        if getattr(experiment, 'variant', None) != 'carrier':
            raise RuntimeError('Carrier variant required for genuine known-fixture source')
        reference = experiment.call(prefix + '_initial')
        _resident(reference, experiment.payload)
        receipt['resident_reference'] = {key: reference[key] for key in RESIDENT}
        late = _dof_profile(experiment, receipt) if effect == 'depthoffield' else _chain(experiment, effect, receipt)
        stats = lambda image: fixture_statistics(image, experiment.payload)
        identity = []
        for label, configuration in (('off_before', 'off'), ('active', 'all'), ('off_after', 'off')):
            _controls(experiment, late, configuration)
            identity.append(_capture(experiment, effect, late, prefix + '_' + label,
                                     reference, receipt, stats, configuration=configuration))
        diagnostics = []
        for mode in (1, 2, 6):
            _controls(experiment, late, 'all', mode)
            row = _capture(experiment, effect, late, prefix + '_late_m%d' % mode,
                reference, receipt, lambda image, selected=mode: verify_module.verify(
                    image, selected, experiment.payload, VIEWPORT, ROI, output_y=OUTPUT_Y),
                configuration='all', mode=mode)
            row.update(sampled_after_native_effect=True,
                       source_attachment='pre-native encoded copy T3',
                       restored_attachment='pre-native restored copy T4')
            diagnostics.append(row)
        # A flag alone is insufficient. Bounded controls ask the unchanged
        # original native stage for a visible response with the writer disabled.
        witnesses = []
        if effect == 'bloom':
            for varying in (False, True):
                _controls(experiment, late, 'off', varying=varying)
                row = _capture(experiment, effect, late, prefix + '_response_alpha_' + str(int(varying)),
                               reference, receipt, stats, varying=varying)
                witnesses.append(row)
            # Opaque/varying fixture RGB is identical, so a repeatable difference
            # between them is a native alpha-sensitive response, provided no
            # carrier is active and the configured original native stage is sole.
            with Image.open(witnesses[0]['capture_file']) as a, Image.open(witnesses[1]['capture_file']) as b:
                x, y, width, height = ROI
                delta = np.abs(np.asarray(a.convert('RGB'), dtype=np.int16)[y:y+height, x:x+width]
                               - np.asarray(b.convert('RGB'), dtype=np.int16)[y:y+height, x:x+width])
                changed = int(np.count_nonzero(np.any(delta > 2, axis=2)))
            positive = changed > 0
            receipt['bloom_alpha_response_pixels_gt2'] = changed
            _controls(experiment, late, 'off', varying=False)
            alpha_return = _capture(experiment, effect, late, prefix + '_response_alpha_return',
                                    reference, receipt, stats)
            with Image.open(witnesses[0]['capture_file']) as a, Image.open(alpha_return['capture_file']) as b:
                returned_equal = bool(np.array_equal(np.asarray(a.convert('RGB'))[y:y+height, x:x+width],
                                                    np.asarray(b.convert('RGB'))[y:y+height, x:x+width]))
            positive = positive and returned_equal
            receipt['bloom_opaque_return_identical'] = returned_equal
            receipt['bounded_native_response_attempts'] = 2
        else:
            positive = False
            for attempt, focus in enumerate((0., 100.)):
                late = _dof_profile(experiment, receipt, positive=True, focus=focus)
                _controls(experiment, late, 'off')
                row = _capture(experiment, effect, late, prefix + '_response_blur_%d' % attempt,
                               reference, receipt, stats)
                witnesses.append(row)
                positive = positive or row['original_error_gt2_pixels'] > 0
                if positive:
                    break
            late = _dof_profile(experiment, receipt)
            _controls(experiment, late, 'off')
            returned = _capture(experiment, effect, late, prefix + '_response_return_zero',
                                reference, receipt, stats)
            positive = positive and returned['original_error_gt2_pixels'] == 0
            receipt['bounded_native_response_attempts'] = len(witnesses)
        receipt['native_response_labels'] = [row['label'] for row in witnesses]
        receipt.update(classify(*identity, diagnostics, positive))
        if effect == 'bloom' and receipt['status'] == 'native_stage_unproven':
            receipt['limitation'] = 'Normal startup enable flag present; no native visual proof after two bounded alpha controls.'
    except Exception as error:
        receipt['failure'] = repr(error)
        receipt['status'] = 'helper_failed'
    finally:
        # Native setters can rebuild chains. Leave Bloom active for lifecycle
        # owner shutdown; there is no documented public native Bloom setter.
        try:
            cleanup = "probe.configure('off')\nprobe.configure_known_fixture(False)"
            if effect == 'depthoffield':
                cleanup += "\nprobe.post.SetEnableDepthOfField(False)"
            receipt['cleanup'] = experiment.call(prefix + '_fixture_off', cleanup)
        except Exception as error:
            receipt['cleanup_failure'] = repr(error)
        receipt['lifecycle_owner_must_close_startup_variant'] = True
        _write(experiment.evidence / (prefix + '_status.json'), receipt)
        if hasattr(experiment, 'extra'):
            experiment.extra.setdefault('native_post', []).append(receipt)
        experiment.save()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path, required=True)
    parser.add_argument('--effect', choices=('bloom', 'depthoffield', 'dof'), required=True)
    parser.add_argument('--initialize', action='store_true', help='Initialize a freshly launched startup variant')
    args = parser.parse_args()
    args.project, args.evidence = args.project.resolve(), args.evidence.resolve()
    args.evidence.mkdir(exist_ok=False)
    previous = args.previous_evidence.resolve()
    shutil.copyfile(previous / 'launch.json', args.evidence / 'launch.json')
    runner = _module('native_post_compat_runner', HERE.parent / 'native_stencil_compat_probe/runner.py')
    experiment = runner.Experiment(args)
    if args.initialize:
        initialize(experiment, args.effect)
    else:
        prior = json.loads((previous / 'results.json').read_text(encoding='utf-8'))
        load = prior['loads'][-1]
        experiment.payload = Path(load['input_file']).read_bytes()
        experiment.viewport, experiment.roi, experiment.output_y = VIEWPORT, ROI, OUTPUT_Y
    result = run(experiment, args.effect)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
