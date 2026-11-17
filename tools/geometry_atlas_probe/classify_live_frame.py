"""Classify one live atlas frame against actual submitted payload generations.

Eight dispersed center RGBA samples only eliminate candidates. Every survivor
must also pass verify_image's complete query of exact 3x3 RGBA patches. This
additional live spot check does not replace a benchmark or verify every frame.
"""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path

from PIL import Image

from verify_capture import _receipt, compact_report, expected_lookup, verify_image


IDENTITY = ('seed', 'generation', 'geometry_name', 'geometry_build_serial')


def extract_history(document):
    """Accept an explicit metadata list, terminal updates case, or snapshot."""
    if isinstance(document, list):
        return document
    if not isinstance(document, dict):
        raise ValueError('History must be a list or a terminal updates/snapshot object')
    collected = document.get('submitted_source_history')
    if 'submitted_source_history' in document and not isinstance(collected, list):
        raise ValueError('submitted_source_history must be a list')
    if isinstance(collected, list) and collected:
        return collected
    records, found = [], isinstance(collected, list)
    snapshots = [document]
    if document.get('schema') == 'geometry_atlas_updates_case_v1':
        snapshots.extend(document.get(key) for key in ('initial_snapshot', 'final_snapshot', 'last_snapshot'))
        snapshots.append(document.get('performance'))
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        updates = snapshot.get('last_updates')
        sources = [snapshot]
        if isinstance(updates, dict):
            sources.append(updates)
        for source in sources:
            for key in ('upload_history', 'uploads'):
                if key in source:
                    if not isinstance(source[key], list):
                        raise ValueError('History ' + key + ' must be a list')
                    records.extend(source[key])
                    found = True
    if not found:
        raise ValueError('No submitted upload metadata found in history input')
    return records


def normalize_history(history, receipt):
    if not isinstance(history, list):
        raise ValueError('Submitted history must be a list')
    records = {}
    for ordinal, item in enumerate(history):
        if not isinstance(item, dict):
            raise ValueError('Each submitted history item must be an object')
        item = item.get('upload', item)
        if not isinstance(item, dict):
            raise ValueError('Submitted upload metadata must be an object')
        seed, generation = item.get('seed'), item.get('generation')
        name = item.get('name', item.get('geometry_name'))
        serial = item.get('serial', item.get('geometry_build_serial'))
        if any(type(value) is not int or not 0 <= value <= 0xffffffff for value in (seed, generation)):
            raise ValueError('Submitted seed/generation must be uint32 integers')
        if type(serial) is not int or not 1 <= serial <= 0xffffffff or not isinstance(name, str) or not name:
            raise ValueError('Submitted uploads need an actual nonempty name and positive serial')
        if (type(item.get('slot_count')) is not int or item['slot_count'] != receipt['slot_count'] or
                item.get('encoding') != receipt.get('encoding')):
            raise ValueError('Submitted history must preserve the receipt slot count and encoding')
        key = (seed, generation, name, serial)
        if key not in records:
            records[key] = dict(seed=seed, generation=generation, name=name, serial=serial,
                                history_indices=[])
        records[key]['history_indices'].append(ordinal)
    return list(records.values())


def fingerprint_ordinals(count):
    samples = min(8, count)
    return [0] if samples == 1 else [index * (count - 1) // (samples - 1) for index in range(samples)]


def display_center(local_ordinal, count):
    row, column = divmod(local_ordinal, 64)
    rows = (count + 63) // 64
    left, right = column * 720. / 64, (column + 1) * 720. / 64
    top, bottom = 64. + row * 1000. / rows, 64. + (row + 1) * 1000. / rows
    return math.floor((left + right) / 2), math.floor((top + bottom) / 2)


def classify_frame(receipt, image, history):
    start, count, mode, salt, salt2, _ = _receipt(receipt, image.size)
    image = image.convert('RGBA')
    records = normalize_history(history, receipt)
    groups = {}
    for upload in records:
        groups.setdefault((upload['seed'], upload['generation']), []).append(upload)
    samples = []
    for local in fingerprint_ordinals(count):
        center = display_center(local, count)
        samples.append(dict(local_ordinal=local, query_ordinal=start + local,
                            center=list(center), observed_rgba=list(image.getpixel(center))))
    candidates, matching = [], []
    full_verifications = 0
    for (seed, generation), uploads in groups.items():
        candidate = dict(seed=seed, generation=generation, submitted_candidates=uploads,
                         fingerprint_passed=True, fingerprint_centers_checked=0,
                         full_patch_checked=False, full_patch_passed=False)
        for sample in samples:
            index, value = expected_lookup(seed, generation, receipt['slot_count'],
                                          sample['query_ordinal'], mode, salt, salt2)
            candidate['fingerprint_centers_checked'] += 1
            if sample['observed_rgba'] != [value, value, value, 255]:
                candidate.update(fingerprint_passed=False, first_fingerprint_mismatch=dict(
                    query_ordinal=sample['query_ordinal'], source_index=index,
                    expected_rgba=[value, value, value, 255], observed_rgba=sample['observed_rgba']))
                break
        if candidate['fingerprint_passed']:
            # Resource identity fields satisfy the verifier receipt contract;
            # the seed/generation determine bytes and both dependent addresses.
            representative = uploads[0]
            expected = dict(receipt, seed=seed, generation=generation,
                            geometry_name=representative['name'], geometry_build_serial=representative['serial'])
            verification = verify_image(expected, image)
            full_verifications += 1
            candidate.update(full_patch_checked=True, full_patch_passed=verification['passed'],
                             verification=compact_report(verification))
            if verification['passed']:
                matching.append(candidate)
        candidates.append(candidate)
    classification = 'matched' if len(matching) == 1 else ('ambiguous' if matching else 'unmatched')
    matches = [upload for candidate in matching for upload in candidate['submitted_candidates']]
    return {'schema': 'geometry_atlas_live_frame_classification_v1',
            'classification': classification, 'passed': len(matching) == 1,
            'full_patch_passed': bool(matching), 'unique_submitted_payload_match': len(matching) == 1,
            'matching_payloads': matching, 'matching_candidates': matches,
            'matching_payload_count': len(matching), 'matching_resource_candidates': len(matches),
            'resource_identity_ambiguous': len(matches) > 1, 'resource_identity_verified': False,
            'history_records': len(history), 'distinct_submitted_uploads': len(records),
            'distinct_submitted_names': len({record['name'] for record in records}),
            'distinct_submitted_payloads': len(groups), 'fingerprint_samples': samples,
            'fingerprint_sample_count': len(samples), 'full_query_patch_verifications': full_verifications,
            'candidates': candidates, 'query': list(receipt['query']), 'salt2': salt2,
            'slot_count': receipt['slot_count'], 'capture_size': list(image.size),
            'cpu_receipt_identity': {key: receipt[key] for key in IDENTITY},
            'cpu_receipt_identity_used_as_expected': False,
            'dependent_addresses_recomputed_per_generation': True,
            'fingerprint_alone_can_pass': False, 'full_3x3_patch_required': True,
            'offset_search_used': False, 'all_render_frames_verified': False,
            'every_generation_pixel_verified': False, 'gpu_to_python_readback': False,
            'scope': 'One live capture and its fixed query; extra spot check, not an FPS benchmark.',
            'oracle': 'Shared expected_lookup and verify_image implementation; not an independent second oracle.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--history', type=Path, required=True,
                        help='Actual submitted metadata list, terminal *.updates.json, or snapshot JSON')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('Preserve existing evidence; choose a new output path')
    artifacts = {}
    try:
        raw, source_errors = {}, []
        for key in ('receipt', 'capture', 'history'):
            path = getattr(args, key)
            artifacts[key] = {'path': str(path.resolve())}
            try:
                raw[key] = path.read_bytes()
                artifacts[key]['sha256'] = hashlib.sha256(raw[key]).hexdigest()
            except OSError as error:
                artifacts[key]['error'] = '%s: %s' % (type(error).__name__, error)
                source_errors.append(key + ': ' + artifacts[key]['error'])
        if source_errors:
            raise OSError('Source inputs could not be read: ' + '; '.join(source_errors))
        receipt = json.loads(raw['receipt'].decode('utf-8-sig'))
        history = extract_history(json.loads(raw['history'].decode('utf-8-sig')))
        with Image.open(io.BytesIO(raw['capture'])) as image:
            report = classify_frame(receipt, image, history)
    except (OSError, ValueError, TypeError, KeyError) as error:
        report = {'schema': 'geometry_atlas_live_frame_classification_v1', 'classification': 'error',
                  'passed': False, 'full_patch_passed': False, 'resource_identity_verified': False,
                  'every_generation_pixel_verified': False, 'all_render_frames_verified': False,
                  'error': '%s: %s' % (type(error).__name__, error)}
    report['source_artifacts'] = artifacts
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as output:
        output.write(serialized + '\n')
    print(json.dumps({key: report.get(key) for key in ('classification', 'passed', 'full_patch_passed',
                                                    'matching_payload_count', 'matching_resource_candidates')}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
