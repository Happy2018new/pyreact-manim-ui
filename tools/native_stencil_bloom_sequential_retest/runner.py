"""Two startup phases for a synthetic Bloom witness using ordinary T0 only.

No operation occurs on import. The lifecycle owner supplies fresh, independently
launched source-control/native projects. No native Bloom runtime setter or
explicit texture-result connection is used, including during initialization.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time


HERE = Path(__file__).resolve().parent
FROZEN_BLOOM = HERE.parent / 'native_stencil_post_candidate/bloom.py'
FROZEN_BLOOM_SHA256 = '019082e082a2290f3fa77d0d3ef6bfb2c421fd5d2d430df61afc797fc5524e69'
SOURCE = 'pmanim_bloom_candidate_source'
OBSERVER = 'pmanim_bloom_sequential_observer'
PHASES = ('source-control', 'native')
STATUS_FILE = 'bloom_sequential_status.json'
BUILD_RECEIPT = 'native_bloom_sequential_build.json'
OBSERVER_FRAGMENT = '''// __multiversion__
precision highp float;
#include "fragmentVersionCentroidUV.h"
uniform sampler2D TEXTURE_0; // preceding enabled custom pass, ordinary chaining
uniform vec4 EXTRA_VECTOR1; // mode: 0 source RGB, 1 source alpha as RGB
void main() {
    vec4 source = texture2D(TEXTURE_0, uv);
    gl_FragColor = vec4(EXTRA_VECTOR1.x > 0.5 ? vec3(source.a) : source.rgb, 1.0);
}
'''


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def candidate_module():
    if sha(FROZEN_BLOOM) != FROZEN_BLOOM_SHA256:
        raise ValueError('Frozen Bloom candidate source changed')
    return module('sequential_frozen_bloom', FROZEN_BLOOM)


def resources():
    """Owned source + T0 observer, using the installed native shader alias form."""
    original = candidate_module().resources()
    source = copy.deepcopy(original['materials'][SOURCE])
    source['fragmentShader'] = 'shaders/' + SOURCE + '.fragment'
    observer = copy.deepcopy(source)
    observer['fragmentShader'] = 'shaders/' + OBSERVER + '.fragment'
    observer['samplerStates'] = [{'samplerIndex': 0, 'textureWrap': 'Clamp', 'textureFilter': 'Point'}]
    return {'materials': {SOURCE: source, OBSERVER: observer},
            'shaders': {SOURCE + '.fragment': original['shaders'][SOURCE + '.fragment'],
                        OBSERVER + '.fragment': OBSERVER_FRAGMENT}}


def fixture_identity(layout=None):
    base = candidate_module()
    layout = base._layout(layout)
    bundle = resources()
    return hashlib.sha256(json_bytes({'layout': layout, 'source': base.source_config(layout),
                                     'materials': bundle['materials'], 'shaders': bundle['shaders']})).hexdigest()


def build_module():
    return module('sequential_build_helpers', HERE / 'build.py')


def _expression():
    return ("dict(probe.snapshot(),seq_order=list(probe.post.GetPostProcessOrder() or []),"
            "seq_flags=[(name,probe.post.CheckEnabledByName(name)) for name in list(probe.post.GetPostProcessOrder() or [])],"
            "seq_source_control=(probe.post.GetParameter(%r,'control') if %r in list(probe.post.GetPostProcessOrder() or []) else None),"
            "seq_source_patch=(probe.post.GetParameter(%r,'patch') if %r in list(probe.post.GetPostProcessOrder() or []) else None),"
            "seq_observer_control=(probe.post.GetParameter(%r,'control') if %r in list(probe.post.GetPostProcessOrder() or []) else None))" %
            (SOURCE, SOURCE, SOURCE, SOURCE, OBSERVER, OBSERVER))


def _inventory(base, state):
    order, rows = state['seq_order'], state['seq_flags']
    if (len(order) != len(set(order)) or [name for name, _ in rows] != order
            or any(type(enabled) is not bool for _, enabled in rows) or not set(base.NATIVE).issubset(order)):
        raise ValueError('Complete distinct post order and Boolean flags required')
    return order, dict(rows)


def _state(base, state, phase, layout, alpha=1., mode=0):
    order, flags = _inventory(base, state)
    expected = [SOURCE, OBSERVER] if phase == 'source-control' else [SOURCE, 'bloom']
    if [name for name in order if flags[name]] != expected:
        raise ValueError('Sequential enabled order differs from the declared startup phase')
    if phase == 'source-control':
        if order.index(SOURCE) + 1 != order.index(OBSERVER) or order[-1] != OBSERVER:
            raise ValueError('Source and terminal T0 observer must be directly adjacent')
        if state['seq_observer_control'] != [float(mode), 0., 0., 0.]:
            raise ValueError('Sequential observer mode differs')
    elif OBSERVER in order or order.index(SOURCE) + 1 != order.index('bloom'):
        raise ValueError('Native source must directly precede Bloom with observer absent')
    if (state['seq_source_control'] != [float(value) for value in layout['viewport']] + [float(alpha), 0.]
            or state['seq_source_patch'] != [float(value) for value in layout['patch']]):
        raise ValueError('Sequential source parameters differ')
    if (state.get('mode') != 'off' or state.get('payload_visible') is not False
            or state.get('clear_visible') is not False
            or state.get('known_fixture', {}).get('visible') is not False):
        raise ValueError('Synthetic control requires hidden carrier and ordinary fixtures')


def _accepted(row):
    if not row.get('accepted') or any(ok is not True for _, ok in row['accepted']):
        raise RuntimeError('Sequential custom operation rejected')


def _turn(state):
    value = state.get('render_event')
    if type(value) is not int or value < 0:
        raise ValueError('Nonnegative integer render turn required')
    return value


def _register(experiment, base, phase, layout, receipt, settle):
    before = experiment.call('bloom_seq_initial', expression=_expression())
    receipt['initial_state'] = before
    order, flags = _inventory(base, before)
    if SOURCE in order or OBSERVER in order:
        raise ValueError('Sequential phase requires fresh owned process names')
    native = ['bloom'] if phase == 'native' else []
    if [name for name in base.NATIVE if flags[name]] != native:
        raise ValueError('Native startup flags differ from the declared phase')
    code = ("probe.configure('off')\nprobe.configure_known_fixture(False)\n"
            "accepted=[(name,probe.post.SetEnableByName(name,False)) for name in %r]" %
            ([name for name in order if name not in base.NATIVE],))
    row = experiment.call('bloom_seq_isolate', code,
                          "{'accepted':accepted,'state':" + _expression() + '}')
    receipt['isolate'] = row
    # A truly fresh synthetic-only project has no custom names to disable.
    if any(ok is not True for _, ok in row['accepted']):
        raise RuntimeError('Sequential isolation rejected')
    settle()
    source = base.source_config(layout)
    source['enable'] = True
    source_code = ("order=list(probe.post.GetPostProcessOrder() or [])\n"
                   "accepted=[('source',probe.post.AddPostProcess(%r,%s))]" %
                   (source, "order.index('bloom')" if phase == 'native' else 'len(order)'))
    row = experiment.call('bloom_seq_add_source', source_code,
                          "{'accepted':accepted,'state':" + _expression() + '}')
    receipt['source_registration'] = row
    _accepted(row)
    settle()
    source_ready = experiment.call('bloom_seq_source_ready', expression=_expression())
    receipt['source_ready'] = source_ready
    if _turn(source_ready) <= _turn(row['state']):
        raise RuntimeError('Source did not settle after registration')
    if phase == 'source-control':
        observer = base._process(OBSERVER, [('control', [0., 0., 0., 0.])])
        observer['enable'] = True
        row = experiment.call('bloom_seq_add_observer',
            "accepted=[('observer',probe.post.AddPostProcess(%r))]" % observer,
            "{'accepted':accepted,'state':" + _expression() + '}')
        receipt['observer_registration'] = row
        _accepted(row)
        settle()
    ready = experiment.call('bloom_seq_ready', expression=_expression())
    receipt['ready_state'] = ready
    _state(base, ready, phase, layout)
    if _turn(ready) <= _turn(row['state']):
        raise RuntimeError('Sequential chain did not settle after registration')
    return before


def _sample(experiment, base, phase, layout, alpha, mode, label, receipt, capture, settle):
    code = "accepted=[('alpha',probe.post.SetParameter(%r,'control',%r))]" % (
        SOURCE, [float(value) for value in layout['viewport']] + [float(alpha), 0.])
    if phase == 'source-control':
        code += "\naccepted.append(('observer_mode',probe.post.SetParameter(%r,'control',%r)))" % (
            OBSERVER, [float(mode), 0., 0., 0.])
    requested = experiment.call(label + '_set', code,
                                "{'accepted':accepted,'state':" + _expression() + '}')
    _accepted(requested)
    settle()
    before = experiment.call(label + '_before', expression=_expression())
    _state(base, before, phase, layout, alpha, mode)
    if _turn(before) <= _turn(requested['state']):
        raise RuntimeError('Sequential sample did not cross a render turn')
    row, pixels = capture(experiment, label)
    after = experiment.call(label + '_after', expression=_expression())
    _state(base, after, phase, layout, alpha, mode)
    if _turn(after) < _turn(before):
        raise RuntimeError('Render turn regressed during sequential capture')
    path = Path(row['capture_file']).resolve()
    sidecar = path.with_suffix('.json')
    if json.loads(sidecar.read_text(encoding='utf-8')) != row['capture_receipt']:
        raise ValueError('Captured sidecar differs from the supplied passive capture receipt')
    row = dict(row, capture_file=str(path), capture_sha256=sha(path), state_before=before,
               state_after=after, patch_alpha=alpha, observer_mode=mode, phase=phase,
               capture_receipt_file=str(sidecar), capture_receipt_sha256=sha(sidecar))
    receipt['captures'].append(row)
    return pixels


def _capture_provenance(row, pid, layout, directory):
    c = row['capture_receipt']
    path = Path(row['capture_file']).resolve()
    if path.parent != directory or sha(path) != row['capture_sha256']:
        raise ValueError('Source gate PNG path/hash changed')
    sidecar = Path(row['capture_receipt_file']).resolve()
    if (sidecar != path.with_suffix('.json') or sha(sidecar) != row['capture_receipt_sha256']
            or json.loads(sidecar.read_text(encoding='utf-8')) != c):
        raise ValueError('Source gate raw capture sidecar changed')
    if (c.get('ok') is not True or c.get('backend') != 'Windows.Graphics.Capture'
            or c.get('native_resolution') is not True or type(pid) is not int or pid <= 0
            or c.get('pid') != pid or c.get('window', {}).get('pid') != pid
            or c.get('window', {}).get('minimized') is not False
            or [c.get('width'), c.get('height')] != layout['viewport']
            or Path(c.get('file', '')).resolve() != path
            or c.get('agent_activation_allowed') is not False
            or type(c.get('request_qpc_100ns')) is not int or c['request_qpc_100ns'] <= 0
            or type(c.get('frame_qpc_100ns')) is not int or c['frame_qpc_100ns'] < c['request_qpc_100ns']
            or any(c.get(key, {}).get('window_noactivate') is not True
                   for key in ('background_before', 'background_after'))):
        raise ValueError('Source gate passive capture provenance rejected')
    before, after = c['background_before']['foreground'], c['background_after']['foreground']
    if any(before.get(key) != after.get(key) for key in ('hwnd', 'pid', 'identity')):
        raise ValueError('Source gate foreground changed during capture')


def _restored_state(initial, returned):
    if any(returned.get(key) != initial.get(key) for key in ('mode', 'payload_visible', 'clear_visible')):
        raise ValueError('Sequential cleanup did not restore the original configuration')
    before, after = initial.get('known_fixture', {}), returned.get('known_fixture', {})
    if any(after.get(key) != before.get(key) for key in ('visible', 'varying_alpha')):
        raise ValueError('Sequential cleanup did not restore the ordinary fixture')


def _owner_binding(experiment, project):
    path = Path(experiment.session).resolve()
    original = json.loads(path.read_text(encoding='utf-8-sig'))
    if (original.get('owner') != 'manim-native-stencil-compat'
            or original.get('game_pid') != experiment.game_pid
            or Path(original.get('project', '')).resolve() != project):
        raise ValueError('Sequential owner/session/project/PID mismatch')
    value = {'owner': original['owner'], 'project': str(project), 'game_pid': original['game_pid'],
             'session_id': original['id'], 'assigned_session_file': str(path)}
    snapshot = Path(experiment.evidence) / 'bloom_seq_assigned_session.json'
    snapshot.write_bytes(json_bytes(value))
    return {'file': str(snapshot.resolve()), 'sha256': sha(snapshot)}


def verify_source_gate(path, expected_fixture, *, build_validator=None, expected_build=None):
    """Reopen all six actual PNGs, recheck states/provenance and re-decode RGBA."""
    base = candidate_module()
    path = Path(path).resolve()
    gate = json.loads(path.read_text(encoding='utf-8'))
    if (gate.get('schema') != 'native_bloom_sequential_run_v1' or gate.get('phase') != 'source-control'
            or gate.get('status') != 'source_control_observed' or gate.get('failure') is not None
            or gate.get('cleanup_failure') is not None or gate.get('fixture_identity') != expected_fixture):
        raise ValueError('Source gate did not complete the matching fixture cleanly')
    layout = base._layout(gate['layout'])
    if fixture_identity(layout) != expected_fixture:
        raise ValueError('Source gate fixture/layout/shader identity differs')
    validator = build_module().validate if build_validator is None else build_validator
    built = validator(gate['project'], 'source-control')
    if (built['fixture_identity'] != expected_fixture
            or sha(Path(gate['project']) / BUILD_RECEIPT) != gate['build_receipt_sha256']):
        raise ValueError('Source gate build receipt/fixture changed')
    if expected_build is not None and any(built.get(key) != expected_build.get(key) for key in
            ('game_executable_path', 'native_input_sources', 'resources_sha256')):
        raise ValueError('Source gate and native phase use different installed client/native inputs')
    binding = gate['owner_binding']
    snapshot = Path(binding['file']).resolve()
    if snapshot.parent != path.parent or sha(snapshot) != binding['sha256']:
        raise ValueError('Source gate assigned-session snapshot changed')
    owner = json.loads(snapshot.read_text(encoding='utf-8'))
    assigned = json.loads(Path(owner['assigned_session_file']).read_text(encoding='utf-8-sig'))
    if (owner.get('owner') != 'manim-native-stencil-compat' or owner.get('game_pid') != gate['game_pid']
            or Path(owner.get('project', '')).resolve() != Path(gate['project']).resolve()
            or assigned.get('id') != owner['session_id'] or assigned.get('owner') != owner['owner']
            or assigned.get('game_pid') != owner['game_pid']
            or Path(assigned.get('project', '')).resolve() != Path(gate['project']).resolve()):
        raise ValueError('Source gate PID is not bound to its assigned owner/project/session')
    rows = gate['captures']
    expected = [(alpha, mode) for alpha in base.ALPHAS for mode in (0, 1)]
    if len(rows) != len(expected) or len({Path(row['capture_file']).resolve() for row in rows}) != len(expected):
        raise ValueError('Source gate lacks all six RGB/alpha A/B/A captures')
    cleanup = gate.get('cleanup', {}).get('state', {})
    _, cleanup_flags = _inventory(base, cleanup)
    _, initial_flags = _inventory(base, gate['initial_state'])
    if (any(cleanup_flags.get(name) is not flag for name, flag in initial_flags.items())
            or cleanup_flags.get(SOURCE) is not False or cleanup_flags.get(OBSERVER) is not False):
        raise ValueError('Source gate lacks restored cleanup enable flags')
    _restored_state(gate['initial_state'], cleanup)
    rgb, alpha_frames = [], []
    last_frame = 0
    for row, (alpha, mode) in zip(rows, expected):
        if row['phase'] != 'source-control' or row['patch_alpha'] != alpha or row['observer_mode'] != mode:
            raise ValueError('Source gate sample sequence differs')
        _capture_provenance(row, gate['game_pid'], layout, path.parent)
        if row['capture_receipt']['request_qpc_100ns'] <= last_frame:
            raise ValueError('Source gate captures are not sequential fresh frames')
        last_frame = row['capture_receipt']['frame_qpc_100ns']
        for key in ('state_before', 'state_after'):
            _state(base, row[key], 'source-control', layout, alpha, mode)
        if _turn(row['state_after']) < _turn(row['state_before']):
            raise ValueError('Source gate render turn regressed')
        with base.Image.open(row['capture_file']) as image:
            pixels = base.np.array(image.convert('RGB'))
        (alpha_frames if mode else rgb).append(pixels)
    result = base.evaluate_source_control(rgb, alpha_frames, layout)
    if not result['passed']:
        raise ValueError('Source gate actual PNG RGB/alpha decode failed')
    return {'path': str(path), 'sha256': sha(path), 'fixture_identity': expected_fixture,
            'source_control': result, 'cross_session_proof': True,
            'limitation': 'Control-session source proof; native input response requires its own positive halo.'}


def _cleanup(experiment, base, initial):
    order, flags = _inventory(base, initial)
    fixture = initial.get('known_fixture', {})
    code = ("probe.configure(%r)\nprobe.configure_known_fixture(%r,%r)\n"
            "order=list(probe.post.GetPostProcessOrder() or [])\n"
            "accepted=[(name,probe.post.SetEnableByName(name,False)) for name in %r if name in order]\n"
            "accepted.extend((name,probe.post.SetEnableByName(name,enabled)) for name,enabled in %r)" %
            (initial['mode'], fixture.get('visible', False), fixture.get('varying_alpha', True),
             (SOURCE, OBSERVER), [(name, flags[name]) for name in order if name not in base.NATIVE]))
    row = experiment.call('bloom_seq_cleanup', code,
                          "{'accepted':accepted,'state':" + _expression() + '}')
    if any(ok is not True for _, ok in row['accepted']):
        raise RuntimeError('Sequential cleanup operation rejected')
    _, returned = _inventory(base, row['state'])
    if any(returned.get(name) is not flag for name, flag in flags.items()) or any(
            returned.get(name, False) is not False for name in (SOURCE, OBSERVER)):
        raise ValueError('Sequential original enable flags did not return')
    _restored_state(initial, row['state'])
    return row


def run(experiment, phase, source_gate=None, *, capture=None, settle=None, layout=None, build_validator=None):
    """Run one startup phase, with native gated before any Experiment call."""
    receipt = {'schema': 'native_bloom_sequential_run_v1', 'phase': phase, 'status': 'not_started',
               'failure': None, 'compatibility': None, 'captures': [], 'source_input_gate_passed': False,
               'native_stage_executed_observed': False, 'native_positive_response_observed': False,
               'native_runtime_setters_used': False, 'explicit_texture_links_used': False,
               'native_configuration_modified': False, 'synthetic_control_only': True,
               'capacity_tested': 0, 'carrier_compatibility_tested': False, 'timing_measured': False,
               'lifecycle_owner_must_close_startup_variant': True}
    base, initial = None, None
    try:
        if phase not in PHASES:
            raise ValueError('Unknown sequential startup phase')
        base = candidate_module()
        layout = base._layout(layout)
        validator = build_module().validate if build_validator is None else build_validator
        project = Path(experiment.args.project).resolve()
        built = validator(project, phase)
        identity = fixture_identity(layout)
        if built['fixture_identity'] != identity:
            raise ValueError('Built fixture differs from requested layout/resources')
        receipt.update(project=str(project), build_receipt_sha256=sha(project / BUILD_RECEIPT),
                       fixture_identity=identity, layout=layout, game_pid=experiment.game_pid)
        if phase == 'native':
            if source_gate is None:
                raise ValueError('Native phase requires the accepted source-control gate')
            receipt['source_gate'] = verify_source_gate(source_gate, identity, build_validator=validator,
                                                        expected_build=built)
            receipt['source_input_gate_passed'] = True
        receipt['owner_binding'] = _owner_binding(experiment, project)
        if list(experiment.viewport) != layout['viewport']:
            raise ValueError('Sequential viewport differs from initialized Experiment')
        capture = base._capture if capture is None else capture
        settle = (lambda: time.sleep(.65)) if settle is None else settle
        # Capture the original state before a partially accepted registration
        # can mutate it, so every post-validation failure has cleanup evidence.
        initial = experiment.call('bloom_seq_cleanup_reference', expression=_expression())
        _register(experiment, base, phase, layout, receipt, settle)
        if phase == 'source-control':
            rgb, alpha = [], []
            for label, selected in zip(('a', 'b', 'a_return'), base.ALPHAS):
                for kind, frames, mode in (('rgb', rgb, 0), ('alpha', alpha, 1)):
                    frames.append(_sample(experiment, base, phase, layout, selected, mode,
                        'bloom_seq_source_' + label + '_' + kind, receipt, capture, settle))
            result = base.evaluate_source_control(rgb, alpha, layout)
            receipt.update(source_control=result, source_input_gate_passed=result['passed'],
                           status='source_control_observed' if result['passed'] else 'source_control_unproven')
        else:
            frames = [_sample(experiment, base, phase, layout, selected, 0,
                        'bloom_seq_native_' + label, receipt, capture, settle)
                      for label, selected in zip(('a', 'b', 'a_return'), base.ALPHAS)]
            response = base.evaluate_bloom_response(frames, layout)
            observed = response['passed']
            receipt.update(native_response=response, native_positive_response_observed=observed,
                           native_stage_executed_observed=observed,
                           status='native_positive_control_observed' if observed else 'native_stage_unproven')
        receipt['limitation'] = ('Cross-session synthetic source proof and bounded native halo only; actual native '
                                 'input is established only by a positive response, compatibility remains unknown.')
    except Exception as error:
        receipt.update(status='helper_failed', failure=repr(error))
    finally:
        if initial is not None:
            try:
                receipt['cleanup'] = _cleanup(experiment, base, initial)
            except Exception as error:
                receipt.update(cleanup_failure=repr(error), status='helper_failed')
        (Path(experiment.evidence) / STATUS_FILE).write_bytes(json_bytes(receipt))
        experiment.save()
    return receipt


run_bloom_sequential = run


def initialize(experiment, phase):
    """Prepare a fresh camera/viewport only; no carrier upload or T3 pipeline."""
    build_module().validate(experiment.args.project, phase)
    base = candidate_module()
    native = module('sequential_native_camera_helpers', HERE.parent / 'native_stencil_post_fixture/native_effects.py')
    experiment.invoke([sys.executable, '-B', '-X', 'utf8', str(base.HOST), 'resize',
        '--project', str(experiment.args.project), '--evidence', str(experiment.evidence),
        '--width', '720', '--height', '1080'], 'bloom_seq_resize')
    before = experiment.call('bloom_seq_before_prepare')
    if before['pipeline_registered'] or before['oracle_installed']:
        raise ValueError('Sequential initialization requires a fresh instance')
    native.prepare_camera(experiment, 'bloom')
    experiment.weather('bloom_seq_clear', False, True)
    experiment.viewport, experiment.roi, experiment.payload = [720, 1080], [8, 128, 512, 512], b''
    return experiment.call('bloom_seq_initialized',
        "probe.viewport=[720,1080]\nprobe.roi=[8,128,512,512]\nprobe.configure('off')")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project', 'evidence', 'previous-evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--phase', choices=PHASES, required=True)
    parser.add_argument('--source-gate', type=Path)
    args = parser.parse_args()
    args.project, args.evidence = args.project.resolve(), args.evidence.resolve()
    built = build_module().validate(args.project, args.phase)
    if args.phase == 'native':
        if args.source_gate is None:
            parser.error('native requires --source-gate <source-control status JSON>')
        verify_source_gate(args.source_gate, built['fixture_identity'], expected_build=built)
    launch = args.previous_evidence.resolve() / 'launch.json'
    if not launch.is_file():
        parser.error('previous-evidence must contain the current owner launch.json')
    args.evidence.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(launch, args.evidence / 'launch.json')
    host_runner = module('sequential_owned_experiment', HERE.parent / 'native_stencil_compat_probe/runner.py')
    experiment = host_runner.Experiment(args)
    session = json.loads(Path(experiment.session).read_text(encoding='utf-8-sig'))
    if (session['owner'] != 'manim-native-stencil-compat' or session['game_pid'] != experiment.game_pid
            or Path(session['project']).resolve() != args.project):
        raise ValueError('Sequential owner/session/project/PID mismatch')
    initialize(experiment, args.phase)
    result = run(experiment, args.phase, args.source_gate)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
