"""Host-only evidence index; the failed original run result remains immutable."""
import argparse
import hashlib
import json
from pathlib import Path


def summarize(evidence):
    evidence = Path(evidence).resolve()
    original = json.loads((evidence/'rain_geometry.results.json').read_text(encoding='utf-8'))
    reports = original['reports']
    groups = {}
    phases = ('clear_default', 'clear_transparent', 'rain_default', 'rain_transparent', 'rain_return_default')
    for phase in phases:
        views = [r for r in reports if r['label'].startswith(phase+'_frame')]
        groups[phase] = {'captures': len(views), 'query_pixels': sum(r['checked_query_pixels'] for r in views),
            'guard_errors': sum(r['guard_errors'] for r in views),
            'q_bad': [r['bad_q'] for r in views if r['kind'] == 'q_alpha'],
            'q_bad_alpha_not255': [r['bad_q_alpha_not255'] for r in views if r['kind'] == 'q_alpha'],
            'q_bad_alpha255': [r['bad_q_alpha255'] for r in views if r['kind'] == 'q_alpha'],
            'alpha_not255': [r['alpha_not255'] for r in views if r['kind'] == 'q_alpha'],
            'alpha_offgrid': [r['alpha_offgrid'] for r in views if r['kind'] == 'q_alpha'],
            'identity_errors': [r['query_errors'] for r in views if r['kind'] == 'identity'],
            'dependent_errors': [r['query_errors'] for r in views if r['kind'] == 'dependent'],
            'max_block_exceptions': [r['max_block_exceptions'] for r in views if r['kind'] == 'block_alpha'],
            'overflow_source_pixels': [r['overflow_source_pixels'] for r in views if r['kind'] == 'block_alpha'],
            'alpha_restore_error_pixels': [r['alpha_restore_error_pixels'] for r in views if r['kind'] == 'block_alpha']}
    failure_state = evidence/'read_after_quiesce_failure.state.json'
    cleanup = (json.loads(failure_state.read_text(encoding='utf-8')) if failure_state.exists()
               else original['final_state'])
    amount = original.get('requested_transparency_amount', 1.0)
    loops = original.get('rain_loops', 5)
    failed = any(r.get('passed') is False for r in reports if r['label'].startswith('rain_transparent'))
    domain_run = original.get('domain_controls_run', True)
    summary = {'schema': 'rain_geometry_summary_v1',
        'conclusion': ('EnableActorBlockGeometryTransparent(True) with amount%r %s native rain payload corruption in this fixture.' %
                       (amount, 'did not solve' if failed else 'requires assessment of')),
        'matrix_completed': (all(groups[phase]['captures'] == 4*loops for phase in phases[2:]) and
                             all(groups[phase]['captures'] == 4 for phase in phases[:2])),
        'requested_transparency_amount': amount, 'rain_loops': loops,
        'clear_gate_passed': original.get('clear_gate_passed'),
        'transparent_candidate_passed': False if failed else original.get('transparent_candidate_passed'),
        'expansion_performed': False,
        'formal_fps_measured': False, 'game_runtime_file_writes': False,
        'continuous_updates': False, 'source_bundle_sha256': cleanup['source_bundle_sha256'],
        'native_effect_condition': 'Native config enable flags only disabled; actual native getters false in all captures.',
        'raw_q_sameframe_alpha_scope': 'Q and alpha share one raw sample. Other captures/frames are separate dynamic observations.',
        'render_queue_changed_proven': False,
        'original_rain_rgb_reference_available': False,
        'known_color_domain_valid': False,
        'domain_controls_run': domain_run,
        'known_color_domain_failure': ('All default/transparent/returned encoded captures equal original background exactly; writer was covered. This control cannot establish encoded/restored RGB accuracy or a transparency effect.' if domain_run else
            'Skipped: r1 known-color domain background covered writer in all modes; no RGB restoration accuracy claim.'),
        'groups': groups,
        'original_run_status': original['status'], 'original_run_error': original.get('error'),
        'cleanup_readonly_state': {key: cleanup[key] for key in ('writer_visible', 'native_background_visible',
            'native_attachment_visibility', 'codec_enabled_processes', 'native_reported_enabled', 'native_post_order')},
        'release': json.loads((evidence/'released_processes.json').read_text(encoding='utf-8-sig')),
        'metadata_manifest_discrepancy': (json.loads((evidence/'metadata_manifest_discrepancy.json').read_text(encoding='utf-8'))
                                        if (evidence/'metadata_manifest_discrepancy.json').exists() else None),
        'artifacts': {}}
    for name in ('rain_geometry.results.json', 'host_source_hashes.json', 'metadata_manifest_discrepancy.json',
        'rain_enabled.server.json', 'read_after_quiesce_failure.state.json', 'released_processes.json',
        'stop.stdout.log', 'stop_finalize_after_exit.log'):
        path = evidence/name
        if not path.exists():
            continue
        summary['artifacts'][name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    with (evidence/'rain_geometry.summary.json').open('x', encoding='utf-8') as output:
        json.dump(summary, output, indent=2)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(summarize(args.evidence), indent=2))
