"""Bounded Bloom attachment retest using the frozen candidate image gates.

Importing this module performs no file reads, game operations or initialization.
The caller installs the owned materials into a *loaded* material registry and
supplies an initialized, owner-validated Bloom Experiment. This helper does not
launch/stop a game or mutate the frozen tools/native_stencil_post_candidate.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import time


FROZEN_BLOOM = Path(__file__).resolve().parents[1] / 'native_stencil_post_candidate/bloom.py'
FROZEN_BLOOM_SHA256 = '019082e082a2290f3fa77d0d3ef6bfb2c421fd5d2d430df61afc797fc5524e69'
STATUS_FILE = 'bloom_retest_status.json'


def candidate_module():
    """Load the reviewed host-only candidate, rejecting a changed dependency."""
    if hashlib.sha256(FROZEN_BLOOM.read_bytes()).hexdigest() != FROZEN_BLOOM_SHA256:
        raise RuntimeError('Frozen Bloom candidate source changed')
    spec = importlib.util.spec_from_file_location('frozen_bloom_retest_dependency', FROZEN_BLOOM)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resources():
    """Same owned shaders/materials; the retest builder owns registry loading."""
    return candidate_module().resources()


def _expression(base):
    """Full state/readbacks even before the owned names have been registered."""
    extra = (
        ",candidate_source_control=(probe.post.GetParameter(%r,'control') if %r in "
        "list(probe.post.GetPostProcessOrder() or []) else None),"
        "candidate_source_patch=(probe.post.GetParameter(%r,'patch') if %r in "
        "list(probe.post.GetPostProcessOrder() or []) else None),"
        "candidate_input_control=(probe.post.GetParameter(%r,'control') if %r in "
        "list(probe.post.GetPostProcessOrder() or []) else None)" %
        (base.SOURCE, base.SOURCE, base.SOURCE, base.SOURCE, base.INPUT, base.INPUT))
    return base._state_expression(False)[:-1] + extra + ')'


def _render_turn(state):
    value = state.get('render_event')
    if type(value) is not int or value < 0:
        raise RuntimeError('Setup requires a nonnegative integer render turn')
    return value


def _setup_state(base, state, layout, expected):
    order, flags = base._flags(state)
    if [name for name in order if flags[name]] != expected:
        raise RuntimeError('Bloom retest setup enabled order differs from the declared stage')
    if base.SOURCE in expected:
        if order.index(base.SOURCE) + 1 != order.index('bloom'):
            raise RuntimeError('Retest source must immediately precede original Bloom')
        control = [float(value) for value in layout['viewport']] + [1., 0.]
        if (state['candidate_source_control'] != control
                or state['candidate_source_patch'] != [float(value) for value in layout['patch']]):
            raise RuntimeError('Retest source parameters were not established')
    if base.INPUT in expected:
        if order.index(base.INPUT) <= order.index('bloom'):
            raise RuntimeError('Retest input diagnostic must follow original Bloom')
        if state['candidate_input_control'] != [0., 0., 0., 0.]:
            raise RuntimeError('Retest diagnostic parameter was not established')
    if (state.get('mode') != 'off' or state.get('payload_visible') is not False
            or state.get('clear_visible') is not False
            or state.get('known_fixture', {}).get('visible') is not False):
        raise RuntimeError('Retest carrier and ordinary fixture must be hidden')
    _render_turn(state)


def _stage(experiment, base, receipt, settle, layout, name, code, expected, after_event):
    row = experiment.call('bloom_retest_' + name, code,
                          "{'accepted':accepted,'state':" + _expression(base) + '}')
    stage = {'phase': name, 'request': row}
    receipt['setup_stages'].append(stage)  # Keep a rejected operation's evidence.
    base._accepted(row)
    # Readbacks in the AddPostProcess command are recorded, but readiness is
    # assessed after a render turn, when the new render attachment can exist.
    event = _render_turn(row['state'])
    if event <= after_event:
        raise RuntimeError('Each setup command must follow the previous render turn')
    settle()
    state = experiment.call('bloom_retest_' + name + '_ready', expression=_expression(base))
    stage['ready_state'] = state
    _setup_state(base, state, layout, expected)
    if _render_turn(state) <= event:
        raise RuntimeError('Bloom retest setup did not settle on a later render turn')
    return _render_turn(state)


def register_source_and_input(experiment, base, receipt, settle, layout, initial):
    """Create enabled passes, prime and link in separately observed commands.

    One link is attempted. No retry, alternative native slot, native parameter
    setter or native enable setter is used. Readbacks do not replace image gates.
    """
    event = _render_turn(initial)
    code = ("probe.configure('off')\nprobe.configure_known_fixture(False)\n"
            "order=list(probe.post.GetPostProcessOrder() or [])\n"
            "accepted=[(name,probe.post.SetEnableByName(name,False)) for name in order if name not in %r]" %
            (base.NATIVE,))
    event = _stage(experiment, base, receipt, settle, layout, 'isolate', code, ['bloom'], event)

    source = base.source_config(layout)
    source['enable'] = True  # Matches the existing successful native _chain definition.
    code = ("order=list(probe.post.GetPostProcessOrder() or [])\n"
            "accepted=[('add_source_enabled',probe.post.AddPostProcess(%r,order.index('bloom')))]" % source)
    event = _stage(experiment, base, receipt, settle, layout, 'add_source', code,
                   [base.SOURCE, 'bloom'], event)

    diagnostic = base._process(base.INPUT, [('control', [0., 0., 0., 0.])])
    diagnostic['enable'] = True
    code = "accepted=[('add_input_enabled',probe.post.AddPostProcess(%r))]" % diagnostic
    expected = [base.SOURCE, 'bloom', base.INPUT]
    event = _stage(experiment, base, receipt, settle, layout, 'add_input', code, expected, event)

    code = ("accepted=[('source_prime',probe.post.SetEnableByName(%r,True)),"
            "('input_prime',probe.post.SetEnableByName(%r,True))]" % (base.SOURCE, base.INPUT))
    event = _stage(experiment, base, receipt, settle, layout, 'prime', code, expected, event)

    before = experiment.call('bloom_retest_pre_link', expression=_expression(base))
    receipt['link_state_before'] = before
    _setup_state(base, before, layout, expected)
    if _render_turn(before) <= event:
        raise RuntimeError('Legal attachment link must follow the priming render turn')
    link = [base.SOURCE, 0, base.INPUT, 0, 3]
    row = experiment.call('bloom_retest_link',
        "accepted=[('source_to_diagnostic_T3',probe.post.PostPassResultToOtherPass(*%r))]" % link,
        "{'accepted':accepted,'state':" + _expression(base) + '}')
    receipt['source_attachment'] = dict(row, link=link)
    base._accepted(row)
    _setup_state(base, row['state'], layout, expected)
    if _render_turn(row['state']) < _render_turn(before):
        raise RuntimeError('Render turn regressed while linking the source attachment')


def run_bloom_retest(experiment, *, capture=None, settle=None, layout=None):
    """Run one bounded recovery; retain compatibility=None for every outcome.

    Precondition: the retest builder has registered the owned material names in
    the loaded postprocess.material and startup original Bloom is isolated.
    ``capture(experiment,label)->(JSON_metadata,RGB_array)`` and no-arg ``settle``
    are injectable for offline verification. Six source and three native image
    gates are exactly the frozen candidate gates; failed setup/source skips the
    native image phase. Lifecycle and project/session validation stay with owner.
    """
    receipt = {'schema': 'native_stencil_bloom_retest_v1', 'effect': 'bloom',
               'status': 'not_started', 'compatibility': None, 'failure': None,
               'source_input_gate_passed': False, 'captures': [], 'setup_stages': [],
               'native_stage_executed_observed': False, 'native_positive_response_observed': False,
               'native_configuration_modified': False, 'native_texture_slots_rebound': False,
               'synthetic_control_only': True, 'carrier_compatibility_tested': False,
               'timing_measured': False, 'max_attachment_link_attempts': 1,
               'lifecycle_owner_must_close_startup_variant': True,
               'frozen_bloom_sha256': FROZEN_BLOOM_SHA256,
               'recovery_scope': 'Loaded owned material registry plus split enabled registration/prime/link; causal native recovery unproven.'}
    base, initial, mutated = None, None, False
    try:
        base = candidate_module()
        layout = base._layout(layout)
        capture = base._capture if capture is None else capture
        settle = (lambda: time.sleep(.65)) if settle is None else settle
        receipt['layout'] = layout
        if list(experiment.viewport) != layout['viewport']:
            raise RuntimeError('Retest viewport differs from initialized Experiment')
        initial = experiment.call('bloom_retest_initial', expression=base._state_expression(False))
        order, flags = base._flags(initial)
        if base.SOURCE in order or base.INPUT in order:
            raise RuntimeError('Retest requires a fresh project without registered owned source/input names')
        if flags['bloom'] is not True or any(flags[name] for name in base.NATIVE if name != 'bloom'):
            raise RuntimeError('Original startup Bloom must be the sole enabled native effect')
        receipt['initial_state'] = initial
        mutated = True
        register_source_and_input(experiment, base, receipt, settle, layout, initial)
        rgb, alpha = [], []
        for label, selected in zip(('a', 'b', 'a_return'), base.ALPHAS):
            for kind, frames, mode in (('rgb', rgb, 0), ('alpha', alpha, 1)):
                frames.append(base._sample(experiment, receipt, capture, settle, layout,
                    'bloom_retest_source_' + label + '_' + kind, selected, True, mode))
        receipt['source_control'] = base.evaluate_source_control(rgb, alpha, layout)
        receipt['source_input_gate_passed'] = receipt['source_control']['passed']
        if not receipt['source_input_gate_passed']:
            receipt.update(status='source_control_unproven',
                           limitation='Declared source RGB/alpha attachment was not established; native phase skipped.')
            return receipt
        native = [base._sample(experiment, receipt, capture, settle, layout,
                    'bloom_retest_native_' + label, selected, False)
                  for label, selected in zip(('a', 'b', 'a_return'), base.ALPHAS)]
        receipt['native_response'] = base.evaluate_bloom_response(native, layout)
        observed = receipt['native_response']['passed']
        receipt.update(status='native_positive_control_observed' if observed else 'native_stage_unproven',
                       native_stage_executed_observed=observed, native_positive_response_observed=observed,
                       limitation=('Synthetic source-to-Bloom halo only; emissive materials and carrier coexistence remain untested.'
                                   if observed else 'No accepted bounded native halo witness; compatibility remains unknown.'))
    except Exception as error:
        receipt.update(status='helper_failed', failure=repr(error))
    finally:
        if mutated:
            try:
                receipt['cleanup'] = base._cleanup(experiment, initial)
            except Exception as error:
                receipt['cleanup_failure'] = repr(error)
                receipt.update(status='helper_failed', failure=receipt['failure'] or repr(error))
        (Path(experiment.evidence) / STATUS_FILE).write_text(
            json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        experiment.save()
    return receipt


run = run_bloom_retest
