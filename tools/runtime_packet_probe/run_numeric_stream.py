"""Verify a large game-generated float32 stream in capacity-bounded GPU chunks.

This is a correctness experiment. WGC and RPC wait between chunks, so wall time
is NOT an upload throughput measurement. A chunk replaces the previous atlas;
the complete stream is never simultaneously resident on the GPU.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import struct
import sys
import time

from PIL import Image
from verify_capture import verify_image


HERE = Path(__file__).resolve().parent
MAGIC = 0x504d4e31


def expected_payload(start, count, generation):
    values = [((index * 73) % 2001 - 1000) / 37.0
              for index in range(start, start + count)]
    data = struct.pack('<%df' % count, *values) if count else b''
    return struct.pack('<4I', MAGIC, count, count * 4, generation) + data


def observed_bytes(verification):
    """Use actual sampled pixels, requiring exact grayscale, not receipt words."""
    if not verification.get('exact_equal'):
        raise ValueError('GPU byte comparison was not exact')
    result = bytearray()
    for row in verification['results']:
        for rgb in row['observed']:
            if len(rgb) != 3 or rgb[0] != rgb[1] or rgb[1] != rgb[2]:
                raise ValueError('GPU output is not a grayscale byte')
            result.append(rgb[0])
    return bytes(result)


def verify_chunk(verification, start, count, generation, capacity):
    observed = observed_bytes(verification)
    expected = expected_payload(start, count, generation)
    if len(expected) > capacity:
        raise ValueError('Chunk exceeds capacity')
    expected += b'\x00' * (capacity - len(expected))
    if observed != expected:
        raise ValueError('GPU bytes differ from independent float32 formula/header/padding')
    return observed[16:16 + count * 4]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--total', type=int, default=100000)
    args = parser.parse_args()
    if not 1 <= args.total <= 1000000:
        parser.error('total must be between 1 and 1000000')
    project, evidence = args.project.resolve(), args.evidence.resolve()
    summary_path = evidence / 'numeric_stream.summary.json'
    if summary_path.exists() or (evidence / 'numeric_stream_0000.state.json').exists():
        raise ValueError('Preserve previous evidence; use a fresh evidence directory')
    commands = evidence / 'commands'
    commands.mkdir(parents=True, exist_ok=True)

    def host(action, label, code=None):
        command = [sys.executable, '-B', '-X', 'utf8', str(HERE / 'host.py'),
                   action, '--project', str(project), '--evidence', str(evidence),
                   '--label', label]
        if code is not None:
            path = commands / (label + '.py')
            path.write_text(code, encoding='utf-8')
            command += ['--code', str(path)]
        with (evidence / (label + '.' + action + '.log')).open('w', encoding='utf-8') as output:
            subprocess.run(command, check=True, stdout=output, stderr=subprocess.STDOUT)
        if action == 'call':
            return json.loads((evidence / (label + '.state.json')).read_text(encoding='utf-8'))

    initial = host('call', 'numeric_stream_initial', '_result=json.dumps(probe.aggregation.snapshot())\n')
    if not initial['ready'] or initial['enabled'] is not True:
        raise RuntimeError('Finish aggregate setup first')
    pages = initial['aggregate']['pages']
    capacity = pages * 24
    chunk_count = (capacity - 16) // 4
    rows, digest = [], hashlib.sha256()
    started = time.monotonic()
    for index, start in enumerate(range(0, args.total, chunk_count)):
        count = min(chunk_count, args.total - start)
        generation = index + 100
        label = 'numeric_stream_%04d' % index
        code = ('from packet_probe.numeric_runtime import write_numbers\n'
                'values=[((i*73)%%2001-1000)/37. for i in range(%d,%d)]\n'
                '_result=json.dumps(write_numbers(probe.aggregation,values,%d))\n'
                % (start, start + count, generation))
        receipt = host('call', label, code)
        host('capture', label)
        with Image.open(evidence / (label + '.png')) as image:
            verification = verify_image(receipt, image)
        for kind, suffix in (('receipt', '.state.json'), ('capture', '.png')):
            verification[kind + '_sha256'] = hashlib.sha256(
                (evidence / (label + suffix)).read_bytes()).hexdigest()
        (evidence / (label + '.verify.json')).write_text(
            json.dumps(verification, separators=(',', ':')), encoding='utf-8')
        data = verify_chunk(verification, start, count, generation, capacity)
        digest.update(data)
        row = {'index': index, 'start': start, 'count': count, 'generation': generation,
               'checked_bytes': capacity, 'exact_equal': True,
               'data_sha256': hashlib.sha256(data).hexdigest(),
               'receipt_sha256': verification['receipt_sha256'],
               'capture_sha256': verification['capture_sha256'],
               'numeric_header': receipt['numeric_header']}
        rows.append(row)
        print(json.dumps({'chunk': index + 1, 'verified_scalars': start + count,
                          'total': args.total, 'exact_equal': True}), flush=True)
    expected_digest = hashlib.sha256(expected_payload(0, args.total, 0)[16:]).hexdigest()
    if digest.hexdigest() != expected_digest:
        raise ValueError('Reassembled observed stream digest differs from independent formula')
    report = {'passed': True, 'total_scalars': args.total, 'payload_bytes': args.total * 4,
              'chunks': len(rows), 'capacity_bytes': capacity,
              'max_resident_float32_count': chunk_count, 'checked_bytes': len(rows) * capacity,
              'sha256': digest.hexdigest(), 'expected_sha256': expected_digest,
              'whole_stream_simultaneously_resident': False,
              'verification_scope': 'one_frozen_payload_per_chunk',
              'all_render_frames_verified': False, 'throughput_measured': False,
              'wall_seconds_including_rpc_and_wgc': time.monotonic() - started,
              'results': rows}
    summary_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'results'}))


if __name__ == '__main__':
    main()
