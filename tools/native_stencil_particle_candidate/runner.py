"""Run finite acceptance on an already launched, owner-bound particle candidate."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time

from PIL import Image

HERE = Path(__file__).resolve().parent
COMPAT = HERE.parent/'native_stencil_compat_probe'
OWNER = 'manim-native-stencil-compat'
PROCESSES = ('stencil_integrated_copy', 'stencil_integrated_restore', 'stencil_integrated_consumer')
LINKS = [[PROCESSES[0], 0, PROCESSES[1], 0, 3],
         [PROCESSES[0], 0, PROCESSES[2], 0, 3],
         [PROCESSES[1], 0, PROCESSES[2], 0, 4]]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


compat = module('independent_particle_owned_compat_runner', COMPAT/'runner.py')
verify = compat.integrated.verify_module


def frameani_helper():
    # The frozen helper imports its sibling by the historical name `runner`.
    previous = sys.modules.get('runner')
    sys.modules['runner'] = compat
    try:
        return module('independent_particle_native_frameani_cases', COMPAT/'frameani_runner.py')
    finally:
        if previous is None:
            sys.modules.pop('runner', None)
        else:
            sys.modules['runner'] = previous


def restore_frameani_wall(experiment, receipt):
    """Restore all 100 blocks; repair only the witnessed torch-aux0 orientation."""
    edits = receipt.get('edits', [])
    if (len(edits) != 100 or len({tuple(row['pos']) for row in edits}) != 100
            or any(not isinstance(row.get('before'), dict) or 'name' not in row['before'] for row in edits)):
        raise RuntimeError('FrameAni wall restoration requires all 100 distinct actual block backups')
    backup = [(row['pos'], row['before']) for row in edits]
    code = """factory=api.GetEngineCompFactory()
blocks=factory.CreateBlockInfo(api.GetLevelId())
states=factory.CreateBlockState(api.GetLevelId())
backup=%r
initial=[]
for pos,before in backup:
    blocks.SetBlockNew(tuple(pos),before,0,0,False,False)
    after=blocks.GetBlockNew(tuple(pos),0)
    initial.append({'pos':pos,'before':before,'after':after,'exact':after is not None and after.get('name')==before.get('name') and after.get('aux',0)==before.get('aux',0)})
expected=None
repairs=[]
for row in initial:
    before,after=row['before'],row['after']
    if row['exact'] or before.get('name')!='minecraft:torch' or before.get('aux',0)!=0 or after is None or after.get('name')!='minecraft:torch':
        continue
    if expected is None:
        expected=states.GetBlockStatesFromAuxValue('minecraft:torch',0)
    pos=tuple(row['pos'])
    state_before=states.GetBlockStates(pos,0)
    accepted=states.SetBlockStates(pos,expected,0) if expected=={'torch_facing_direction':'unknown'} else False
    current=blocks.GetBlockNew(pos,0)
    current_states=states.GetBlockStates(pos,0)
    exact=accepted and current is not None and current.get('name')=='minecraft:torch' and current.get('aux',0)==0 and current_states==expected
    repairs.append({'pos':pos,'before':after,'state_before':state_before,'accepted':accepted,'after':current,'states_after':current_states,'exact':bool(exact)})
final=[]
for pos,before in backup:
    after=blocks.GetBlockNew(tuple(pos),0)
    final.append({'pos':pos,'before':before,'after':after,'exact':after is not None and after.get('name')==before.get('name') and after.get('aux',0)==before.get('aux',0)})
_result=json.dumps({'schema':'candidate_frameani_wall_restore_v1','count':len(final),'all_exact':len(final)==100 and all(row['exact'] for row in final) and all(row['exact'] for row in repairs),'edits':final,'initial_mismatches':[row for row in initial if not row['exact']],'torch_aux0_recovery':{'expected_states':expected,'repairs':repairs},'mismatches':[row for row in final if not row['exact']]})
""" % (backup,)
    result = experiment.server('particle_frameani_restore_wall', code)
    if (result.get('count') != 100 or result.get('all_exact') is not True
            or len(result.get('edits', [])) != 100
            or not all(row.get('exact') is True for row in result['edits'])):
        raise RuntimeError('All 100 FrameAni wall positions must restore exactly after narrow torch-state recovery')
    return result


def run_frameani(experiment):
    helper = frameani_helper()
    # Change only this fresh imported module instance, never the frozen source.
    helper.restore_wall = restore_frameani_wall
    return helper.run(experiment)


def validate_assets(project):
    project = Path(project).resolve()
    receipt = json.loads((project/'particle_candidate_receipt.json').read_text(encoding='utf-8'))
    if (receipt.get('schema') != 'static_independent_particle_candidate_v1'
            or receipt.get('sfx_overlay_omitted') is not True
            or (project/'resource_pack/materials/sfx.material').exists()
            or len(receipt.get('hashes', {})) < 10):
        raise RuntimeError('A complete independent particle build with omitted SFX overlay is required')
    for relative, digest in dict(receipt['hashes'], **receipt['frozen_runtime_hashes']).items():
        path = (project/relative).resolve()
        if project not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Particle build artifact hash mismatch: '+relative)
    return receipt


class ParticleExperiment(compat.Experiment):
    """Reuse the established native owner, passive host and memory preflights."""
    def __init__(self, args):
        self.candidate = validate_assets(args.project)
        super().__init__(args)
        if self.variant != 'carrier':
            raise RuntimeError('Install the particle candidate on the carrier comparison build')

    def initialize(self):
        size = self.candidate['logical_bytes']
        layout = compat.integrated.bulk.LAYOUTS.get(size)
        if layout != (self.candidate['viewport'], self.candidate['roi']):
            raise RuntimeError('Standalone initialization supports frozen 64 KiB/256 KiB/512 KiB layouts only')
        self.invoke([sys.executable, '-B', '-X', 'utf8', str(COMPAT/'host.py'), 'resize',
                     '--project', str(self.args.project), '--evidence', str(self.evidence),
                     '--width', str(layout[0][0]), '--height', str(layout[0][1])], 'particle_resize')
        self.prepare_camera()
        self.weather('particle_prepare_clear', False, True)
        self.load(size)
        self.call('particle_install_pipeline', 'probe.install_pipeline()')
        time.sleep(.7)
        self.call('particle_finish_pipeline', 'probe.finish_pipeline()')
        return self.call('particle_fixed_camera_ready')

    def resume(self, previous_evidence):
        previous_evidence = Path(previous_evidence).resolve()
        prior = json.loads((previous_evidence/'results.json').read_text(encoding='utf-8'))
        loads = prior.get('loads', [])
        if not loads:
            raise RuntimeError('Previous evidence has no resident host payload to resume')
        load = copy.deepcopy(loads[-1])
        self.payload = Path(load['input_file']).read_bytes()
        if hashlib.sha256(self.payload).hexdigest() != load['input_sha256']:
            raise RuntimeError('Previous actual input bytes failed SHA256 validation')
        self.viewport, self.roi = load['viewport'], load['roi']
        self.loads.append(load)
        state = self.call('particle_resume_same_instance')
        if (state.get('state') != 'resident' or state.get('identity') != load['state_after_load']['identity']
                or state.get('active_pages') != load['state_after_load']['active_pages']):
            raise RuntimeError('Previous payload is not resident on this owned instance')
        self.save()
        return state


Experiment = ParticleExperiment


def resident(experiment, frozen):
    state = experiment.state
    keys = ('identity', 'active_pages', 'native_page_names', 'native_attempt_count',
            'native_records_reserved', 'actor_count')
    if (state.get('state') != 'resident' or state.get('ready') is not True
            or state.get('pipeline_ready') is not True or state.get('pipeline_enabled') is not True
            or state.get('error') is not None or state.get('measurement') is not None
            or any(state.get(key) != frozen.get(key) for key in keys)
            or state.get('effects') or any(flag for _, flag in state['native_post_flags'])
            or state.get('viewport') != experiment.candidate['viewport']
            or state.get('source_roi') != experiment.candidate['roi']
            or state.get('pipeline_links') != LINKS
            or state.get('particle_candidate', {}).get('sfx_overlay_omitted') is not True):
        raise RuntimeError('Frozen input/pages, independent carrier or integrated pipeline changed')


def replay(experiment, report):
    receipt = report['capture_receipt']
    if receipt['frame_qpc_100ns'] <= receipt['request_qpc_100ns']:
        raise RuntimeError('A strictly fresh passive frame is required')
    with Image.open(report['capture_file']) as source:
        image = source.convert('RGB')
        if report['mode'] == 4:
            result = verify.verify_visible(image, experiment.payload, experiment.viewport, experiment.roi,
                                           fixture=report['fixture'])
        else:
            result = verify.verify(image, report['mode'], experiment.payload,
                experiment.viewport, experiment.roi, output_y=report['output_origin'][1], fixture=report['fixture'])
    if not result['exact']:
        raise RuntimeError('Independent PNG replay failed: '+report['label'])
    return result


def check_frameani(experiment, outcome, stock_evidence=None):
    """The historical runner records failures; this wrapper requires every case."""
    cleanup = outcome.get('cleanup', {})
    if (outcome.get('complete') is not True or outcome.get('failure') is not None
            or cleanup.get('effects_destroyed') is not True
            or cleanup.get('wall', {}).get('all_exact') is not True
            or 'effect_error' in cleanup or 'wall_error' in cleanup):
        raise RuntimeError('Ordinary FrameAni acceptance requires exact world/effect cleanup')
    helper = frameani_helper()
    by_label = {row['label']: row for row in experiment.reports}
    cases = outcome.get('cases', [])
    expected = {(location, route, configuration) for location in ('inside', 'outside')
                for route in helper.ROUTES for configuration in ('off', 'all')}
    actual = {(row['location'], row['route'], row['configuration']) for row in cases}
    if len(cases) != 16 or actual != expected or not all(row.get('pass') is True for row in cases):
        raise RuntimeError('All sixteen source-inside/outside ordinary FrameAni positives must pass')
    stock = None
    if stock_evidence is not None:
        directory = Path(stock_evidence).resolve()
        stock_status = json.loads((directory/'frameani-status.json').read_text(encoding='utf-8'))
        stock_results = json.loads((directory/'results.json').read_text(encoding='utf-8'))
        stock_cases = stock_status.get('cases', [])
        if (stock_status.get('variant') != 'stock' or len(stock_cases) != 8
                or not all(row.get('pass') is True for row in stock_cases)):
            raise RuntimeError('Explicit stock baseline requires all eight native positives')
        stock = {(row['location'], row['route']): row for row in stock_cases}
        stock_reports = {row['label']: row for row in stock_results['reports']}
        if len(stock) != 8:
            raise RuntimeError('Explicit stock baseline must contain eight distinct location/route cases')
        for row in stock_cases:
            reports = [stock_reports[label] for label in row['capture_labels']]
            snapshots = helper.verify.compare_snapshots(*row['fixture_snapshots'])
            pixels = helper.verify.compare_visible(*helper.images(reports), row['fixture_snapshots'][1])
            if not snapshots['pass'] or not pixels['pass']:
                raise RuntimeError('Actual stock baseline PNG/snapshot replay failed: '+row['label'])
    checks = []
    for case in cases:
        before, on, after = [by_label[label] for label in case['capture_labels']]
        fixture = case['fixture_snapshots'][1]
        snapshots = helper.verify.compare_snapshots(*case['fixture_snapshots'])
        positive = helper.verify.compare_visible(*helper.images([before, on, after]), fixture)
        if not snapshots['pass'] or not positive['pass']:
            raise RuntimeError('Actual candidate FrameAni PNG/snapshot replay failed: '+case['label'])
        same_frame = []
        for label in case.get('payload_captures', []):
            report = by_label[label]
            payload = replay(experiment, report)
            pixels = helper.verify.compare_visible(*helper.images([before, report, after]), fixture)
            if not pixels['pass']:
                raise RuntimeError('Ordinary FrameAni missing in the same complete payload PNG: '+label)
            same_frame.append({'label': label, 'pixels': pixels, 'payload': payload})
        if len(same_frame) != 2 or {by_label[row['label']]['mode'] for row in same_frame} != {1, 3}:
            raise RuntimeError('Both mode1 and mode3 same-frame ordinary-effect witnesses are required')
        item = {'label': case['label'], 'pass': True, 'same_frame': same_frame}
        if stock is not None:
            native = stock[(case['location'], case['route'])]
            native_on = stock_reports[native['capture_labels'][1]]
            comparison = helper.verify.compare_to_native(*helper.images([native_on, on]), fixture)
            background = helper.verify.compare_to_native(*helper.images([
                stock_reports[native['capture_labels'][0]], before]), fixture)
            if not comparison['pass'] or not background['pass']:
                raise RuntimeError('Candidate differs from explicit stock route/background: '+case['label'])
            item.update(stock_comparison=comparison, stock_background=background)
            for row in same_frame:
                actual = by_label[row['label']]
                comparison = helper.verify.compare_to_native(*helper.images([native_on, actual]), fixture)
                if not comparison['pass']:
                    raise RuntimeError('Same-frame payload sprite differs from explicit stock: '+row['label'])
                row['stock_comparison'] = comparison
        checks.append(item)
    return checks


def run(experiment, previous_evidence=None, include_frameani=True, stock_evidence=None):
    """Accept an initialized Experiment; never launch, stop, resize, or allocate data pages."""
    candidate = validate_assets(experiment.args.project)
    status = {'schema': 'static_independent_particle_acceptance_v1', 'complete': False,
        'pass': False, 'failure': None, 'gates': [], 'frameani': None,
        'frameani_requested': bool(include_frameani),
        'stock_comparison_performed': bool(include_frameani and stock_evidence is not None),
        'compiled_viewport': candidate['viewport'], 'compiled_roi': candidate['roi'],
        'previous_evidence': str(previous_evidence) if previous_evidence is not None else None,
        'stock_evidence': str(stock_evidence) if stock_evidence is not None else None,
        'launch_or_stop_performed': False, 'native_shadow_fix_claimed': False,
        'static_residency_performance_measured': False}
    path = experiment.evidence/'particle-candidate-status.json'
    if path.exists():
        raise RuntimeError('Use fresh particle acceptance evidence; do not overwrite a prior result')
    frozen = experiment.call('particle_acceptance_initial')
    started_clear = not experiment.weather_is_raining

    def save():
        experiment.save()
        path.write_text(json.dumps(status, indent=2), encoding='utf-8')

    def capture(label, mode, **kwargs):
        # Reserve the upper native UI/outline/canary region on the 64 KiB layout.
        if candidate['viewport'] == [720, 1080]:
            kwargs.setdefault('output_y', 650)
        report = experiment.capture(label, mode, **kwargs)
        result = replay(experiment, report)
        resident(experiment, frozen)
        status['gates'].append({'label': label, 'pass': True, 'replay': result,
                                'particle_state': report['state']['particle_candidate']})
        save()
        return report

    try:
        resident(experiment, frozen)
        actual_input = Path(experiment.loads[-1]['input_file']).read_bytes() if experiment.loads else None
        if (not experiment.payload or actual_input != experiment.payload
                or hashlib.sha256(experiment.payload).hexdigest() != frozen['identity']['host_sha256']
                or len(experiment.payload) != candidate['logical_bytes']):
            raise RuntimeError('Acceptance requires the actual host input file and matching resident SHA256 identity')
        if not started_clear:
            raise RuntimeError('Begin bounded particle acceptance in clear weather')
        experiment.call('particle_reference_on', 'probe.configure_known_fixture(True,True)')
        for mode in (7, 5):
            capture('particle_reference_playing_m%d'%mode, mode, configuration='off', fixture=True)
        experiment.call('particle_reference_pause', 'probe.pause_particles()')
        for mode in (7, 5):
            capture('particle_reference_paused_m%d'%mode, mode, configuration='off', fixture=True)
        # These complete analytic pixels reject a second base blend as well as holes.
        for mode in (1, 3, 6, 5):
            capture('particle_fixture_playing_m%d'%mode, mode, fixture=True)
        experiment.call('particle_all_pause_after_positive', 'probe.pause_particles()')
        for repeat in range(2):
            for mode in (1, 3, 6, 5):
                report = capture('particle_fixture_paused_%d_m%d'%(repeat, mode), mode, fixture=True)
                draws = report['state']['particle_candidate']['draws']
                if len(draws) != 3 or not all(row['paused'] for row in draws.values()):
                    raise RuntimeError('Three surviving data draws must remain explicitly paused')
        experiment.call('particle_reference_off', 'probe.configure_known_fixture(False)')
        for mode in (1, 3, 5):
            capture('particle_natural_clear_m%d'%mode, mode)
        experiment.weather('particle_rain_on', True)
        wet = [capture('particle_natural_rain_m%d'%mode, mode) for mode in (1, 3, 5)]
        if next(row for row in wet if row['mode'] == 3).get('alpha_not255_pixels', 0) < 1:
            raise RuntimeError('Actual rainy source needs a nonopaque alpha witness')
        experiment.weather('particle_rain_off', False)
        for mode in (1, 3):
            capture('particle_natural_return_m%d'%mode, mode)
        if include_frameani:
            if candidate['viewport'] != [720, 1080] or candidate['roi'] != [8, 128, 512, 512]:
                raise RuntimeError('Ordinary FrameAni acceptance is bounded to the 64 KiB fixture layout')
            outcome = run_frameani(experiment)
            status['frameani'] = {'cases': check_frameani(experiment, outcome, stock_evidence), 'pass': True}
        # Revalidate after the ordinary-effect matrix has cycled off/all.
        for mode in (1, 3):
            capture('particle_final_playing_m%d'%mode, mode)
        experiment.call('particle_final_pause', 'probe.pause_particles()')
        for mode in (1, 3):
            capture('particle_final_paused_m%d'%mode, mode)
        status['complete'], status['pass'] = True, True
    except Exception as error:
        status['failure'] = repr(error)
        raise
    finally:
        if experiment.weather_is_raining:
            try:
                experiment.weather('particle_failure_rain_off', False)
            except Exception as error:
                status['rain_cleanup_failure'] = repr(error)
        status['rain_reversion_required'] = experiment.weather_is_raining
        status['last_state'] = experiment.state
        save()
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path)
    parser.add_argument('--stock-evidence', type=Path)
    parser.add_argument('--skip-frameani', action='store_true')
    parser.add_argument('--resume-resident', action='store_true')
    args = parser.parse_args()
    args.project, args.evidence = args.project.resolve(), args.evidence.resolve()
    if args.previous_evidence is not None:
        args.previous_evidence = args.previous_evidence.resolve()
        args.evidence.mkdir(exist_ok=False)
        shutil.copyfile(args.previous_evidence/'launch.json', args.evidence/'launch.json')
    experiment = ParticleExperiment(args)
    if args.resume_resident:
        if args.previous_evidence is None:
            raise RuntimeError('--resume-resident requires --previous-evidence')
        experiment.resume(args.previous_evidence)
    else:
        experiment.initialize()
    run(experiment, args.previous_evidence, not args.skip_frameani, args.stock_evidence)


if __name__ == '__main__':
    main()
