"""Initialize an owned carrier, then verify bounded automatic Nether recovery."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time
import traceback

from PIL import Image

HERE = Path(__file__).resolve().parent
COMPAT = HERE.parent/'native_stencil_compat_probe'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def sources():
    paths = [p for p in HERE.iterdir() if p.is_file() and p.suffix in ('.py', '.md')]
    paths += [p for folder in ('weather_stencil_integrated_probe', 'weather_stencil_large_probe',
                              'native_stencil_compat_probe')
              for p in (HERE.parent/folder).iterdir() if p.is_file() and p.suffix == '.py']
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def current(experiment, label):
    value = experiment.call(label, expression=
        "{'dimension':probe.game.GetCurrentDimension(),'probe':probe.snapshot()}")
    experiment.state = value['probe']
    return value


def gate(state, identity, pages, serial=None, pair=None):
    recovery = state.get('dimension_recovery') or {}
    if (state.get('state') != 'resident' or not state.get('ready') or state.get('error') or
            state.get('identity') != identity or state.get('native_page_names') != pages or
            not state.get('pipeline_ready') or len(state.get('pipeline_links', [])) != 3):
        raise RuntimeError('Expected the same static bytes, resident pages and linked recovery pipeline')
    if serial is not None and (recovery.get('phase') != 'ready' or recovery.get('serial') != serial or
                               recovery.get('ready_serial') != serial or recovery.get('pair') != pair):
        raise RuntimeError('Recovery receipt is stale or belongs to a different dimension transition')


def raw_readback(experiment, label, original):
    """No probe mutation between the recovery receipt and this passive capture."""
    experiment.invoke([sys.executable, '-B', '-X', 'utf8', str(COMPAT/'host.py'), 'capture',
        '--project', str(experiment.args.project), '--evidence', str(experiment.evidence),
        '--label', label], label+'_capture')
    receipt = json.loads((experiment.evidence/(label+'.json')).read_text(encoding='utf-8'))
    if (receipt.get('ok') is not True or receipt.get('backend') != 'Windows.Graphics.Capture' or
            [receipt.get('width'), receipt.get('height')] != experiment.viewport or
            receipt.get('frame_qpc_100ns', 0) < receipt.get('request_qpc_100ns', 1) or
            receipt.get('agent_activation_allowed') is not False or
            not all(receipt.get(key, {}).get('window_noactivate')
                    for key in ('background_before', 'background_after'))):
        raise RuntimeError('Dimension readback requires a fresh passive owned noactivation capture')
    path = experiment.evidence/(label+'.png')
    with Image.open(path) as frame:
        verified = original.integrated.verify_module.verify(frame.convert('RGB'), 1, experiment.payload,
            experiment.viewport, experiment.roi, output_y=128, fixture=False)
    row = {'label': label, 'capture_file': str(path), 'capture_receipt': receipt,
           'state': experiment.state, 'no_probe_mutation_after_recovery': True, **verified}
    experiment.reports.append(row)
    experiment.save()
    if not row['exact']:
        raise RuntimeError('Automatic dimension recovery exact pixel readback failed at '+label)
    return row


def arm(experiment, label):
    # Use the frozen default output origin, which the automatic recovery restores.
    experiment.call(label, "probe.configure('all')\nprobe.inspect(1)")


def transit(experiment, label, target, position, player, identity, pages, original, progress=None):
    record = progress if progress is not None else {}
    before = current(experiment, label+'_before')
    source = before['dimension']
    serial = before['probe']['dimension_recovery']['serial']+1
    record.update(before=before, expected_serial=serial, arm_failure=None)
    try:
        arm(experiment, label+'_arm')
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        record['arm_failure'] = repr(error)
        if target != 0:
            raise
        # A broken renderer must not prevent the server return request.
    requested = experiment.server(label+'_request',
        "dimension=api.GetEngineCompFactory().CreateDimension(%r)\n"
        "accepted=dimension.ChangePlayerDimension(%d,%r)\n"
        "_result=json.dumps({'accepted':accepted})" % (player, target, tuple(position)))
    record['request'] = requested
    if requested.get('accepted') is not True:
        raise RuntimeError('Owned dimension request was rejected')
    for attempt in range(40):
        time.sleep(.6)
        value = current(experiment, label+'_poll_%02d'%attempt)
        record['last_state'] = value
        recovery = value['probe'].get('dimension_recovery', {})
        if value['probe'].get('error') or recovery.get('phase') == 'failed':
            if target == 0 and value['dimension'] != 0:
                continue
            raise RuntimeError('Automatic dimension recovery failed: '+repr(recovery))
        if (value['dimension'] == target and recovery.get('phase') == 'ready' and
                recovery.get('serial') == serial and recovery.get('ready_serial') == serial):
            gate(value['probe'], identity, pages, serial, [source, target])
            direct = raw_readback(experiment, label+'_automatic_exact', original)
            controls = experiment.data_checks(label+'_checked')
            if not controls or not all(report.get('exact') is True for report in controls):
                raise RuntimeError('Standard exact mode1/mode3 checks failed after dimension recovery')
            record.update(state=value, automatic_readback=direct,
                          standard_exact_checks=controls, pixel_verified=True)
            return record
    raise RuntimeError('Matching automatic dimension recovery did not become ready before host deadline')


def run(experiment, original, repeats=2, progress=None):
    if repeats not in (1, 2, 3):
        raise ValueError('Choose one to three bounded Nether round trips')
    experiment.initialize()
    first = current(experiment, 'dimension_candidate_initial')
    if (experiment.variant != 'carrier' or first['dimension'] != 0 or
            experiment.viewport != [720, 1080] or experiment.roi != [8, 128, 512, 512] or
            len(experiment.payload) != 65536 or 'dimension_recovery' not in first['probe']):
        raise RuntimeError('Candidate requires the controlled fresh Overworld 64 KiB carrier')
    identity, pages = first['probe']['identity'], first['probe']['native_page_names']
    gate(first['probe'], identity, pages)
    player = experiment.call('dimension_candidate_player', expression='api.GetLocalPlayerId()')
    location = experiment.server('dimension_candidate_position',
        "position=api.GetEngineCompFactory().CreatePos(%r).GetPos()\n"
        "_result=json.dumps(position)" % player)
    if not isinstance(location, (list, tuple)) or len(location) != 3:
        raise RuntimeError('Owned starting player position is unavailable')
    # ChangePlayerDimension documents integer target coordinates. The frozen
    # carrier camera is restored independently to its exact pre-transition pose.
    return_position = [int(value) for value in location]
    status = progress if progress is not None else {}
    status.update(initial=first, original_player_position=location,
                  requested_return_position=return_position, trips=[], pixel_verified=False,
                  end_tested=False, end_limitation='End omitted: this bounded candidate validates repeatable Nether poses only')
    arm(experiment, 'dimension_candidate_initial_arm')
    status['initial_readback'] = raw_readback(experiment, 'dimension_candidate_initial_exact', original)
    for index in range(repeats):
        row = {'index': index+1, 'outbound': {}, 'return': {},
               'outbound_failure': None, 'return_failure': None}
        status['trips'].append(row)
        try:
            row['outbound'] = transit(experiment, 'candidate_nether_%d'%index, 1,
                [0, 70, 0], player, identity, pages, original, row['outbound'])
        except (RuntimeError, ValueError, OSError, KeyError) as error:
            row['outbound_failure'] = repr(error)
        finally:
            now = current(experiment, 'candidate_return_decision_%d'%index)
            if now['dimension'] != 0:
                try:
                    row['return'] = transit(experiment, 'candidate_overworld_%d'%index, 0,
                        return_position, player, identity, pages, original, row['return'])
                except (RuntimeError, ValueError, OSError, KeyError) as error:
                    row['return_failure'] = repr(error)
            else:
                row['return_failure'] = 'Outbound did not leave Overworld; no return recovery was observed'
        if row['outbound_failure'] or row['return_failure']:
            raise RuntimeError('Dimension round trip failed: '+repr(row))
    status['pixel_verified'] = all(row['outbound']['pixel_verified'] and row['return']['pixel_verified']
                                   for row in status['trips'])
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path, required=True)
    parser.add_argument('--repeats', type=int, choices=(1, 2, 3), default=2)
    args = parser.parse_args()
    for key in ('project', 'evidence', 'previous_evidence'):
        setattr(args, key, getattr(args, key).resolve())
    if (args.evidence == args.previous_evidence or args.previous_evidence in args.evidence.parents or
            args.evidence in args.previous_evidence.parents):
        raise ValueError('Keep candidate evidence outside the preserved launch evidence')
    prior_path = args.previous_evidence/'launch.json'
    prior_bytes = prior_path.read_bytes()
    previous_files = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in args.previous_evidence.rglob('*') if p.is_file()}
    args.evidence.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(prior_path, args.evidence/'launch.json')
    before = sources()
    original, experiment, failure, trace, progress = None, None, None, None, {}
    try:
        installed = json.loads((args.project/'dimension_candidate_receipt.json').read_text(encoding='utf-8'))
        runtime = args.project/'behavior_pack/stencil_large/dimension_candidate.py'
        if (installed['runtime_sha256'] != hashlib.sha256(runtime.read_bytes()).hexdigest() or
                runtime.read_bytes() != (HERE/'runtime.py').read_bytes()):
            raise RuntimeError('Installed dimension candidate differs from the reviewed source')
        original = module('dimension_original_compat_runner', COMPAT/'runner.py')
        experiment = original.Experiment(args)
        run(experiment, original, args.repeats, progress)
    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as error:
        failure, trace = repr(error), traceback.format_exc()
    finally:
        if experiment is not None:
            experiment.save()
        after = sources()
        unchanged = previous_files == {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in args.previous_evidence.rglob('*') if p.is_file()}
        if not unchanged or before != after:
            failure = failure or 'Preserved evidence or reviewed sources changed'
        result = {'schema': 'static_dimension_candidate_run_v1', 'failure': failure,
            'failure_traceback': trace, 'result': progress,
            'pixel_verified': failure is None and progress.get('pixel_verified') is True,
            'last_state': experiment.state if experiment is not None else None,
            'previous_evidence': str(args.previous_evidence),
            'previous_launch_sha256': hashlib.sha256(prior_bytes).hexdigest(),
            'previous_evidence_unchanged': unchanged, 'sources_before': before, 'sources_after': after,
            'sources_unchanged': before == after, 'launch_or_stop_performed': False,
            'owned_game_retained_for_parent_cleanup': True,
            'initialization_performed': experiment is not None, 'continuous_update_tested': False}
        (args.evidence/'dimension-candidate-status.json').write_text(
            json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({'failure': failure, 'pixel_verified': result['pixel_verified']}), flush=True)
    return 1 if failure or not progress.get('pixel_verified') else 0


if __name__ == '__main__':
    raise SystemExit(main())
