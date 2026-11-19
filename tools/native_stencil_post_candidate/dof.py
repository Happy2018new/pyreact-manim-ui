"""Owner-invoked bounded DOF candidate checks; imports have no runtime effects.

Identity and active run in separate fresh startup projects. Active is statically
decoded, so every transition is carrier-all -> native-on -> native-off -> hide.
Only the caller's existing Experiment can contact its owned session.
"""
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image

try:
    from . import build_candidate as build
except ImportError:
    import build_candidate as build


HERE = Path(__file__).resolve().parent
STATUS = 'dof-identity-status.json'
PROFILES = (
    {'name': 'zero', 'center': False, 'focus': 2., 'scale': 0.},
    {'name': 'manual_near', 'center': False, 'focus': 0., 'scale': 15.},
    {'name': 'manual_far', 'center': False, 'focus': 100., 'scale': 15.},
    {'name': 'auto_center', 'center': True, 'focus': 2., 'scale': 15.},
    {'name': 'zero_return', 'center': False, 'focus': 2., 'scale': 0.},
)


def native_module():
    return build.module('candidate_original_native_helpers', HERE.parent / 'native_stencil_post_fixture/native_effects.py')


def _write(path, value):
    Path(path).write_bytes(build.json_bytes(value))


def camera_equal(left, right, tolerance=.001):
    for key in ('position', 'forward'):
        if (key not in left or key not in right or len(left[key]) != 3 or len(right[key]) != 3
                or not np.all(np.isfinite(left[key])) or not np.all(np.isfinite(right[key]))
                or np.max(np.abs(np.asarray(left[key])-np.asarray(right[key]))) > tolerance):
            return False
    return True


def image_delta(left, right, tolerance=2):
    a, b = np.asarray(left, dtype=np.int16), np.asarray(right, dtype=np.int16)
    if a.shape != (1080, 720, 3) or b.shape != a.shape:
        raise ValueError('Expected paired native 720x1080 RGB images')
    delta = np.abs(a-b)
    # Native UI/debug text is outside the fixture. The fixed source ROI and
    # its 8px guard are the predeclared comparison region, never a fitted mask.
    x, y, width, height = build.ROI
    region = delta[y-8:y+height+8, x-8:x+width+8]
    inside = delta[y:y+height, x:x+width]
    changed = np.any(region > tolerance, axis=2)
    inside_changed = int(np.count_nonzero(np.any(inside > tolerance, axis=2)))
    return {'pixels': int(region.shape[0]*region.shape[1]),
            'changed_pixels': int(np.count_nonzero(changed)),
            'fixture_changed_pixels': inside_changed,
            'guard_changed_pixels': int(np.count_nonzero(changed)) - inside_changed,
            'max_channel_delta': int(region.max()), 'tolerance': tolerance}


def _open_rgb(row):
    path = Path(row['capture_file'])
    if build.sha(path) != row['capture_sha256']:
        raise ValueError('Saved DOF PNG changed: ' + str(path))
    with Image.open(path) as image:
        return image.convert('RGB').copy()


def _capture_receipt(row):
    capture = row['capture_receipt']
    if (capture.get('ok') is not True or capture.get('backend') != 'Windows.Graphics.Capture'
            or capture.get('native_resolution') is not True
            or (capture.get('width'), capture.get('height')) != (720, 1080)
            or capture.get('agent_activation_allowed') is not False
            or type(capture.get('request_qpc_100ns')) is not int
            or type(capture.get('frame_qpc_100ns')) is not int
            or capture['frame_qpc_100ns'] < capture['request_qpc_100ns']
            or capture['request_qpc_100ns'] <= 0):
        raise ValueError('DOF capture provenance rejected')
    for key in ('background_before', 'background_after'):
        if capture.get(key, {}).get('window_noactivate') is not True:
            raise ValueError('DOF capture lacks noactivation')
    before, after = (capture[key]['foreground'] for key in ('background_before', 'background_after'))
    if any(before.get(key) != after.get(key) for key in ('hwnd', 'pid', 'identity')):
        raise ValueError('Foreground changed during DOF capture')


def verify_identity_gate(path, payload, native=None):
    """Reopen actual PNGs and fully re-decode late data; never trust pass flags."""
    native = native or native_module()
    path = Path(path).resolve()
    gate = build.read_json(path)
    if (gate.get('schema') != 'native_dof_candidate_run_v1' or gate.get('case') != 'dof-identity'
            or gate.get('failure') is not None or gate.get('cleanup_failure') is not None):
        raise ValueError('DOF identity run did not finish with clean cleanup')
    candidate = build.validate(gate['project'], 'dof-identity')
    if build.sha(Path(gate['project']) / build.RECEIPT) != gate['candidate_receipt_sha256']:
        raise ValueError('DOF identity candidate receipt changed')
    if hashlib.sha256(payload).hexdigest() != gate['payload_sha256'] or len(payload) != 65536:
        raise ValueError('Identity gate uses a different actual payload')
    rows = gate['profiles']
    if [row['profile'] for row in rows] != list(PROFILES):
        raise ValueError('Identity gate lacks frozen native profiles and zero return')
    late = 'stencil_integrated_after_depthoffield'
    images = []
    for row in rows:
        _capture_receipt(row)
        native._resident(row['state'], payload, rows[0]['state'])
        native._isolation(row['state'], 'depthoffield', late)
        if row['state']['mode'] != 'off' or row['state']['known_fixture']['varying_alpha'] is not False:
            raise ValueError('Identity profile is not a writer-free opaque source')
        if not camera_equal(rows[0]['camera'], row['camera']):
            raise ValueError('Identity camera moved across profiles')
        images.append(_open_rgb(row))
    zero = native.fixture_statistics(images[0], payload)
    if zero['original_error_gt2_pixels'] != 0:
        raise ValueError('Identity zero-blur image differs from the analytic source')
    changes = [image_delta(images[0], image)['fixture_changed_pixels'] for image in images[1:-1]]
    if max(changes) < 64:
        raise ValueError('Identity native nonzero blur has no bounded visual positive')
    returned = native.fixture_statistics(images[-1], payload)
    if (returned['original_error_gt2_pixels'] != 0
            or image_delta(images[0], images[-1])['fixture_changed_pixels'] != 0):
        raise ValueError('Native final zero-blur return did not reproduce the source')
    diagnostics = gate['diagnostics']
    if [row['mode'] for row in diagnostics] != [1, 2, 6]:
        raise ValueError('Identity gate lacks exhaustive late diagnostics')
    for row in diagnostics:
        _capture_receipt(row)
        native._resident(row['state'], payload, rows[0]['state'])
        native._isolation(row['state'], 'depthoffield', late)
        result = native.verify_module.verify(_open_rgb(row), row['mode'], payload,
                                             build.VIEWPORT, build.ROI, output_y=650)
        if result.get('exact') is not True:
            raise ValueError('Identity late PNG re-decoding failed')
    return {'accepted': True, 'identity_status': str(path), 'identity_status_sha256': build.sha(path),
            'native_dof_sha256': candidate['native_detail']['native_dof_sha256'],
            'profile_images_reopened': len(images), 'nonzero_changed_pixels': changes,
            'native_final_zero_return_verified': True,
            'actual_bytes_redecoded': len(payload), 'all_late_guards_redecoded': True,
            'automatic_mode_requested': True, 'separate_near_far_auto_poses_tested': False}


def initialize(experiment, case, identity_gate=None):
    """Initialize the already-owned fresh candidate; never launch or attach."""
    candidate = build.validate(experiment.args.project, case)
    native = native_module()
    if case == 'dof-active':
        if identity_gate is None:
            raise ValueError('Active initialization requires an accepted identity gate')
        # The fixed upload generator is host-side; verify before any SDK call.
        expected = native.verify_module.payload_bytes(65536)
        accepted = verify_identity_gate(identity_gate, expected, native)
        if accepted['native_dof_sha256'] != candidate['native_detail']['native_dof_sha256']:
            raise ValueError('Active native source differs from identity source')
    experiment.invoke([sys.executable, '-B', '-X', 'utf8', str(native.HOST), 'resize',
                       '--project', str(experiment.args.project), '--evidence', str(experiment.evidence),
                       '--width', '720', '--height', '1080'], 'candidate_resize')
    before = experiment.call('candidate_before_prepare')
    if before['pipeline_registered'] or before['oracle_installed']:
        raise RuntimeError('Candidate initialization requires a fresh instance')
    native.prepare_camera(experiment, candidate['effect'])
    experiment.weather('candidate_clear_weather', False, True)
    experiment.load(65536)
    experiment.viewport, experiment.roi, experiment.output_y = build.VIEWPORT, build.ROI, 650
    if case == 'bloom-control':
        native._chain(experiment, 'bloom', {}, initial=True)
        return experiment.call('bloom_candidate_initialized')
    # Full carrier is set before native enable in the static active variant.
    configuration = 'all' if case == 'dof-active' else 'off'
    experiment.call('dof_candidate_safe_initial_visibility', 'probe.configure(%r)' % configuration)
    _profile(experiment, native, PROFILES[0], {}, initial=True)
    return experiment.call('dof_candidate_initialized')


def _profile(experiment, native, profile, receipt, initial=False):
    code = """accepted=[('center_reset',probe.post.SetDepthOfFieldUseCenterFocus(False)),
('focus',probe.post.SetDepthOfFieldFocusDistance(%r)),
('near',probe.post.SetDepthOfFieldNearBlurScale(%r)),
('far',probe.post.SetDepthOfFieldFarBlurScale(%r)),
('radius',probe.post.SetDepthOfFieldBlurRadius(2.0)),
('center',probe.post.SetDepthOfFieldUseCenterFocus(%r)),
('enable',probe.post.SetEnableDepthOfField(True))]
""" % (profile['focus'], profile['scale'], profile['scale'], profile['center'])
    result = experiment.call('candidate_dof_profile_' + profile['name'], code,
        "{'accepted':accepted,'enabled':probe.post.CheckDepthOfFieldEnabled(),'state':probe.snapshot()}")
    if not all(ok is True for _, ok in result['accepted']) or result['enabled'] is not True:
        raise RuntimeError('Native DOF profile setter rejected')
    receipt.setdefault('profile_setters', []).append(result)
    time.sleep(.65)
    return native._chain(experiment, 'depthoffield', receipt, initial=initial)


def run(experiment, case, identity_gate=None):
    """Run only with an existing initialized Experiment from the lifecycle owner."""
    if case not in ('dof-identity', 'dof-active'):
        raise ValueError('Expected an isolated DOF case')
    native = native_module()
    candidate = build.validate(experiment.args.project, case)
    receipt = {'schema': 'native_dof_candidate_run_v1', 'case': case,
               'project': str(experiment.args.project.resolve()), 'failure': None,
               'cleanup_failure': None, 'status': 'not_started', 'profiles': [], 'diagnostics': [],
               'captures': [], 'compatibility_verified': False,
               'candidate_receipt_sha256': build.sha(experiment.args.project / build.RECEIPT),
               'payload_sha256': hashlib.sha256(experiment.payload).hexdigest(),
               'automatic_separate_near_far_poses_verified': False,
               'native_auto_inputs_preserved_by_source': True, 'runtime_file_writes': False}
    status_path = experiment.evidence / ('dof-identity-status.json' if case == 'dof-identity' else 'dof-active-status.json')
    try:
        baseline = None
        if case == 'dof-active':
            if identity_gate is None:
                raise ValueError('Active phase requires --identity-gate dof-identity-status.json')
            receipt['identity_gate'] = verify_identity_gate(identity_gate, experiment.payload, native)
            if receipt['identity_gate']['native_dof_sha256'] != candidate['native_detail']['native_dof_sha256']:
                raise ValueError('Identity and active use different native DOF math')
            baseline = build.read_json(identity_gate)
        reference = experiment.call('candidate_dof_initial')
        native._resident(reference, experiment.payload)
        receipt['resident_reference'] = {key: reference[key] for key in native.RESIDENT}
        configuration = 'all' if case == 'dof-active' else 'off'
        experiment.call('candidate_dof_safe_visibility', 'probe.configure(%r)' % configuration)
        for profile in PROFILES:
            late = _profile(experiment, native, profile, receipt)
            native._controls(experiment, late, configuration)
            row = native._capture(experiment, 'depthoffield', late, 'candidate_' + case + '_' + profile['name'],
                                  reference, receipt, lambda image: native.fixture_statistics(image, experiment.payload),
                                  configuration=configuration)
            row['profile'] = dict(profile)
            row['camera'] = experiment.call('candidate_dof_camera_' + profile['name'], expression=
                                           "{'position':probe.camera.GetPosition(),'forward':probe.camera.GetForward()}")
            if baseline is not None:
                original = baseline['profiles'][len(receipt['profiles'])]
                if not camera_equal(original['camera'], row['camera']):
                    raise RuntimeError('Identity/active native camera/depth origin differs')
                row['identity_comparison'] = image_delta(_open_rgb(original), _open_rgb(row))
            receipt['profiles'].append(row)
        late = _profile(experiment, native, PROFILES[0], receipt)
        for mode in (1, 2, 6):
            native._controls(experiment, late, 'all', mode)
            row = native._capture(experiment, 'depthoffield', late, 'candidate_' + case + '_late_m%d' % mode,
                reference, receipt, lambda image, selected=mode: native.verify_module.verify(
                    image, selected, experiment.payload, build.VIEWPORT, build.ROI, output_y=650),
                configuration='all', mode=mode)
            row['mode'] = mode
            receipt['diagnostics'].append(row)
        if not all(row.get('exact') is True for row in receipt['diagnostics']):
            raise RuntimeError('Candidate full payload/restored diagnostic failed')
        receipt['status'] = 'captured_pending_identity_gate' if case == 'dof-identity' else 'compared'
        if case == 'dof-active':
            passed = all(row['identity_comparison']['changed_pixels'] == 0 for row in receipt['profiles'])
            receipt.update(status='candidate_profile_match' if passed else 'candidate_profile_mismatch',
                           compatibility_verified=passed, tested_profiles_only=True)
    except Exception as error:
        receipt.update(failure=repr(error), status='candidate_failed')
    finally:
        # Independent cleanup actions: disabling native first is mandatory in
        # the active static decoder. Never hide the writer after failed disable.
        try:
            disabled = experiment.call('candidate_dof_disable_before_hide',
                'accepted=probe.post.SetEnableDepthOfField(False)',
                "{'accepted':accepted,'enabled':probe.post.CheckDepthOfFieldEnabled()}")
            receipt['cleanup_disable'] = disabled
            if disabled['accepted'] is not True or disabled['enabled'] is not False:
                raise RuntimeError('DOF disable failed; preserve active carrier for owner cleanup')
            cleanup_errors = []
            # Native disable can remove all dynamic registrations. Mark that
            # chain unready before visibility operations so stale SetParameter
            # calls cannot prevent hiding. The owner closes this instance.
            for label, code in (
                ('carrier_off', "probe.pipeline_ready=False\nprobe.configure('off')"),
                ('fixture_off', 'probe.configure_known_fixture(False)')):
                try:
                    receipt['cleanup_' + label] = experiment.call('candidate_dof_' + label, code)
                except Exception as error:
                    cleanup_errors.append(label + ': ' + repr(error))
            if cleanup_errors:
                raise RuntimeError('; '.join(cleanup_errors))
        except Exception as error:
            receipt['cleanup_failure'] = repr(error)
        _write(status_path, receipt)
        if case == 'dof-identity' and receipt['failure'] is None and receipt['cleanup_failure'] is None:
            try:
                verified = verify_identity_gate(status_path, experiment.payload, native)
                # A JSON file cannot embed its own final SHA. External active
                # validation computes it after this durable status is written.
                receipt['gate'] = {key: value for key, value in verified.items()
                                   if key != 'identity_status_sha256'}
                receipt['status'] = 'identity_phase_accepted'
            except Exception as error:
                receipt['gate'] = {'accepted': False, 'failure': repr(error)}
                receipt['status'] = 'identity_phase_rejected'
            _write(status_path, receipt)
        experiment.save()
    return receipt
