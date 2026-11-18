"""Existing-entity compatibility retry with exact native material alias resolution."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import traceback

import compat_runner as original
from PIL import Image


REQUIRED_MATERIALS = {'entity_alphatest_netease', 'netease_entity_alphatest_outline_base',
                      'netease_entity_alphatest_outline'}


def resolved_snapshot(snapshot):
    """Only the documented native .skinning suffix is accepted as an alias."""
    value = copy.deepcopy(snapshot)
    raw = snapshot.get('registered_material_values')
    canonical = [name[:-9] if name.endswith('.skinning') else name for name in raw]
    matched = len(canonical) == 3 and set(canonical) == REQUIRED_MATERIALS
    value['native_material_recipe_present'] = matched
    value['material_resolution'] = {'raw_values': raw, 'canonical_values': canonical,
        'original_recipe_flag': snapshot.get('native_material_recipe_present'),
        'precise_skinning_alias_only': True, 'actual_three_required_names_match': matched}
    return value


def validate_recovery_inputs(previous, failed_directory, backdrop_path):
    status_path = failed_directory/'compat-status.json'
    status_bytes = status_path.read_bytes()
    status = json.loads(status_bytes)
    if status.get('failure') is None:
        raise RuntimeError('Recovery must preserve and link an actual failed compatibility run')
    original._resident_gate(status['last_state'], previous['reference'])
    outline = status['last_state'].get('outline') or {}
    if not outline.get('entity') or not outline.get('registered'):
        raise RuntimeError('Failed run must retain its existing registered outline entity')
    backdrop_bytes = backdrop_path.read_bytes()
    backdrop = json.loads(backdrop_bytes)
    expected = {(x,y,3) for x in range(-5,5) for y in range(-61,-51)}
    edits = backdrop.get('edits', [])
    if (backdrop.get('block_count') != 100 or len(edits) != 100
            or {tuple(edit['pos']) for edit in edits} != expected
            or any(edit.get('exact') is not True or edit.get('after', {}).get('name') != 'minecraft:stone'
                   for edit in edits) or backdrop.get('rules_ok') is not True or backdrop.get('time_ok') is not True
            or backdrop.get('no_camera_or_actor_changes') is not True):
        raise RuntimeError('Static backdrop must have100 exact stone edits and unchanged camera/actors')
    return {'outline': outline, 'failed_tree': original._tree(failed_directory),
        'backdrop_bytes': backdrop_bytes, 'links': {
            'original_failed_evidence': str(failed_directory),
            'original_failed_status_sha256': original._sha(status_bytes),
            'original_failure': status['failure'], 'static_backdrop_receipt': str(backdrop_path),
            'static_backdrop_sha256': original._sha(backdrop_bytes),
            'static_backdrop_block_count': 100}}


class Recovery(original.Compatibility):
    def __init__(self, args, previous, provenance):
        self.provenance = provenance
        super().__init__(args, previous)
        self.extra.update(schema='integrated_native_compatibility_recovery_v1',
            provenance=provenance['links'], pixel_gate='original strict full-window comparison',
            fixed_mask_qualification_used=False, existing_outline_entity=provenance['outline']['entity'])
        self.save()

    def call(self, label, code='', expression='probe.snapshot()'):
        # Reuse the original finite sequence without ever sending its create
        # statement. The owned entity was created by the preserved failed run.
        if label == 'outline_prepare':
            if code != 'probe.prepare_outline()':
                raise RuntimeError('Unexpected outline preparation request')
            label, code = 'existing_outline_reused', ''
        return super().call(label, code, expression)

    def run(self):
        state = self.resident('recovery_existing_entity_gate')
        current, reference = state['outline'], self.provenance['outline']
        for key in ('entity', 'requested_position', 'native_position', 'camera', 'projected_bounds'):
            if current.get(key) != reference.get(key):
                raise RuntimeError('Existing outline or departed camera changed before recovery: '+key)
        super().run()

    def outline_check(self, label, before, active, after):
        raw = [report['state']['outline'] for report in (before, active, after)]
        resolved = [resolved_snapshot(snapshot) for snapshot in raw]
        snapshots = original.outline_verify.compare_snapshots(*resolved)
        images = []
        for report in (before, active, after):
            with Image.open(report['capture_file']) as image:
                images.append(image.convert('RGB'))
        pixels = original.outline_verify.compare_outline(*images, self.roi,
                                                       bounds=raw[1]['projected_bounds'])
        self.extra['outline'].append({'label': label,
            'captures': [row['label'] for row in (before, active, after)],
            'raw_snapshots': raw, 'resolved_snapshots': resolved,
            'snapshots': snapshots, 'pixels': pixels, 'strict_full_window_gate': True,
            'fixed_masks_used': False, 'static_backdrop_receipt': self.provenance['links']['static_backdrop_receipt']})
        self.save()
        if not snapshots['pass'] or not pixels['pass']:
            raise RuntimeError('Strict native outline recovery gate failed at '+label)
        if pixels['fixture_window'][3] > original.OUTPUT_Y:
            raise RuntimeError('Native outline observation window overlaps the diagnostic output')
        return self.extra['outline'][-1]


def _sources():
    return {**original._sources(), 'weather_stencil_integrated_probe/compat_recovery.py':
            original._sha(Path(__file__).read_bytes())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path, required=True)
    parser.add_argument('--failed-evidence', type=Path, required=True)
    parser.add_argument('--backdrop-receipt', type=Path, required=True)
    args = parser.parse_args()
    for key in ('project','evidence','previous_evidence','failed_evidence','backdrop_receipt'):
        setattr(args, key, getattr(args, key).resolve())
    for source in (args.previous_evidence, args.failed_evidence):
        if args.evidence == source or source in args.evidence.parents or args.evidence in source.parents:
            raise ValueError('Recovery requires a fresh evidence directory outside preserved evidence')
    args.evidence.mkdir(parents=True, exist_ok=False)
    previous, provenance, experiment, failure, trace = None, None, None, None, None
    sources_before = _sources()
    try:
        previous = original.validate_previous(args.previous_evidence)
        provenance = validate_recovery_inputs(previous, args.failed_evidence, args.backdrop_receipt)
        shutil.copyfile(args.previous_evidence/'launch.json', args.evidence/'launch.json')
        experiment = Recovery(args, previous, provenance)
        experiment.run()
    except Exception as error:
        failure, trace = repr(error), traceback.format_exc()
    finally:
        if experiment is not None:
            experiment.save()
        previous_unchanged = original._tree(args.previous_evidence) == previous['frozen_tree'] if previous else None
        failure_unchanged = original._tree(args.failed_evidence) == provenance['failed_tree'] if provenance else None
        backdrop_unchanged = args.backdrop_receipt.read_bytes() == provenance['backdrop_bytes'] if provenance else None
        sources_after = _sources()
        if (previous_unchanged is False or failure_unchanged is False or backdrop_unchanged is False
                or sources_before != sources_after):
            failure = failure or 'Preserved evidence, static backdrop receipt or recovery sources changed'
        stages = experiment.extra['completed_stages'] if experiment else []
        status = {'schema':'integrated_native_compatibility_recovery_v1', 'failure':failure,
            'failure_traceback':trace, 'ui_passed':'ui' in stages, 'outline_passed':'outline' in stages,
            'joint_passed':'joint' in stages, 'completed_stages':stages,
            'links':{**(previous['links'] if previous else {}), **(provenance['links'] if provenance else {})},
            'previous_evidence_unchanged':previous_unchanged,
            'original_failed_evidence_unchanged':failure_unchanged, 'static_backdrop_receipt_unchanged':backdrop_unchanged,
            'source_hashes_before':sources_before, 'source_hashes_after':sources_after,
            'sources_unchanged':sources_before==sources_after,
            'frozen_reference_identity':previous['reference']['identity'] if previous else None,
            'frozen_reference_active_pages':previous['reference']['active_pages'] if previous else None,
            'frozen_reference_state':previous['reference'] if previous else None,
            'last_state':experiment.state if experiment else None, 'reports':len(experiment.reports) if experiment else 0,
            'rain_reversion_required':experiment.weather_is_raining if experiment else None,
            'existing_outline_reused':True, 'strict_full_window_pixel_gate':True, 'fixed_masks_used':False,
            'owned_game_left_for_parent_direction':True, 'launch_or_stop_performed':False}
        (args.evidence/'compat-status.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
        print(json.dumps({'failure':failure,'completed_stages':stages}),flush=True)
    return 1 if failure else 0


if __name__ == '__main__':
    raise SystemExit(main())
