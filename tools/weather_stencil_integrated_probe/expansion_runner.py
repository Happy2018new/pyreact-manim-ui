"""Same-instance512KiB integrated proof, gated by native64KiB compatibility."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from runner import Experiment, HERE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path, required=True)
    parser.add_argument('--compat-evidence', type=Path, required=True)
    args = parser.parse_args()
    prior_path = args.previous_evidence/'results.json'
    compat_path = args.compat_evidence/'compat-status.json'
    prior_bytes, compat_bytes = prior_path.read_bytes(), compat_path.read_bytes()
    prior, compat = json.loads(prior_bytes), json.loads(compat_bytes)
    if compat.get('failure') is not None or not all(compat.get(key) is True
            for key in ('ui_passed', 'outline_passed', 'joint_passed')):
        raise RuntimeError('Native UI, outline and joint64KiB gates must all pass before512KiB')
    args.evidence.mkdir(exist_ok=False)
    shutil.copyfile(args.previous_evidence/'launch.json', args.evidence/'launch.json')
    experiment = Experiment(args)
    failure = None
    try:
        before = experiment.call('same_instance_before_expansion')
        reference = prior['reports'][-1]['state']
        if before['identity'] != reference['identity'] or before['active_pages'] != reference['active_pages']:
            raise RuntimeError('Prior frozen64KiB identity or pages changed')
        if (before.get('known_fixture', {}).get('visible')
                or before.get('outline', {}).get('requested_enabled')
                or (before.get('ui_clip', {}).get('screen') or {}).get('actual_visible')):
            raise RuntimeError('Controlled known/UI/outline fixtures must be off before expansion')
        experiment.load(524288)
        frozen = experiment.state

        def assert_frozen():
            if (experiment.state['identity'] != frozen['identity']
                    or experiment.state['active_pages'] != frozen['active_pages']):
                raise RuntimeError('Frozen512KiB identity or active page list changed')

        def reads(prefix):
            result = []
            for mode in (1, 2, 3, 5, 4):
                result.append(experiment.capture(prefix+'_m%d' % mode, mode))
                assert_frozen()
            return result

        def measure(prefix, mode, environment):
            experiment.measure(prefix, mode)
            experiment.measurements[-1]['environment'] = environment
            experiment.save()
            assert_frozen()

        experiment.weather('n524288_prepare_clear', False)
        reads('n524288_clear')
        experiment.capture('n524288_hidden_identity_negative', 1, hide=True, expected=False)
        experiment.capture('n524288_hidden_visible_zero', 4, hide=True, visible_zero=True)
        experiment.capture('n524288_return_visible_actual', 4)
        experiment.call('n524288_known_fixture_on', 'probe.configure_known_fixture(True,True)')
        for mode in (7, 5):
            experiment.capture('n524288_fixture_alone_m%d' % mode, mode,
                               configuration='off', fixture=True)
        for mode in (1, 2, 3, 5, 6, 4):
            experiment.capture('n524288_fixture_encoded_m%d' % mode, mode, fixture=True)
        # Keep the full encoded RGB observation for independent blend/restore
        # code analysis; this frame intentionally differs from raw fixture RGB.
        experiment.capture('n524288_fixture_encoded_rgb_observation', 7, fixture=True, expected=False)
        negative = experiment.capture('n524288_fixture_alpha_mutation_negative', 5,
                                     fixture=True, expected=False, mutate_alpha=True)
        if negative['encoded_restored_alpha_mismatch_pixels'] != 1 or negative['data_error_pixels'] != 1:
            raise RuntimeError('One-pixel alpha mutation must reject exactly one source sample')
        experiment.capture('n524288_fixture_alpha_mutation_return', 5, fixture=True)
        experiment.call('n524288_known_fixture_off', 'probe.configure_known_fixture(False)')
        experiment.weather('n524288_rain_on', True)
        wet = reads('n524288_wet')
        if not next(row for row in wet if row['mode'] == 3)['alpha_not255_pixels']:
            raise RuntimeError('512KiB rain must expose actual non255 source alpha')
        for mode in ('baseline', 'visible'):
            measure('integrated512_rain', mode, 'rain')
        reads('n524288_postraintiming')
        experiment.weather('n524288_rain_off', False)
        reads('n524288_clear_return')
        for mode in ('baseline', 'restore', 'visible', 'dependent'):
            measure('integrated512_clear', mode, 'clear')
        reads('n524288_postcleartiming')
        experiment.capture('n524288_final_visible', 4)
    except Exception as error:
        failure = repr(error)
        raise
    finally:
        experiment.save()
        (args.evidence/'expansion-status.json').write_text(json.dumps({
            'failure': failure, 'reports': len(experiment.reports),
            'previous_results_file': str(prior_path.resolve()),
            'previous_results_sha256': hashlib.sha256(prior_bytes).hexdigest(),
            'compat_status_file': str(compat_path.resolve()),
            'compat_status_sha256': hashlib.sha256(compat_bytes).hexdigest(),
            'previous_results_unchanged': prior_path.read_bytes() == prior_bytes,
            'compat_status_unchanged': compat_path.read_bytes() == compat_bytes,
            'rain_reversion_required': experiment.weather_is_raining,
            'last_state': experiment.state, 'same_instance': True,
            'source_hashes': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in HERE.iterdir() if path.is_file()}}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
