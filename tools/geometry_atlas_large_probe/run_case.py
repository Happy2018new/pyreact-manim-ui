"""Run one cumulative resident prefix at64KiB,1MiB,1.5MiB,2MiB, without mutation retries."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image
from verify_capture import expected_bytes, verify_files, verify_image

HERE = Path(__file__).resolve().parent
SYSTEM = 'pmanim_geometry_atlas_large_probe'


class Case:
    def __init__(self, project, evidence):
        self.project, self.evidence = project.resolve(), evidence.resolve()
        self.commands = self.evidence / 'large_commands'
        self.commands.mkdir(exist_ok=False)
        self.state = {}
        self.events = []
        self.results = []
        self.serial = 0
        self.frozen = None
        self.started = time.monotonic()

    def call(self, label, code=''):
        self.serial += 1
        full = '%03d_%s' % (self.serial, label)
        path = self.commands / (full + '.py')
        path.write_text("probe=api.GetSystem(%r,'probe')\n" % SYSTEM + code +
            '\n_result=json.dumps(probe.snapshot())\n', encoding='utf-8')
        self.host('call', full, path)
        self.state = json.loads((self.evidence / (full + '.state.json')).read_text(encoding='utf-8'))
        if self.state.get('error'):
            raise RuntimeError(self.state['error'])
        return full

    def host(self, action, label, path=None):
        command = [sys.executable, '-B', '-X', 'utf8', str(HERE / 'host.py'), action,
            '--project', str(self.project), '--evidence', str(self.evidence), '--label', label, '--timeout', '120']
        if path:
            command += ['--code', str(path)]
        event = {'action': action, 'label': label, 'started_seconds': time.monotonic()-self.started}
        self.events.append(event)
        with (self.evidence / (label + '.' + action + '.log')).open('x', encoding='utf-8') as log:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                timeout=140.)
        event['returncode'] = result.returncode
        event['finished_seconds'] = time.monotonic()-self.started
        if result.returncode:
            raise RuntimeError('Host action failed; mutation not replayed: ' + label)

    def wait_ready(self):
        deadline = time.monotonic()+30.
        while not self.state.get('ready'):
            if time.monotonic() > deadline:
                raise TimeoutError('Page uniforms did not become ready')
            time.sleep(.2)
            self.call('readiness')

    def capture(self, label, expect_pass=True):
        time.sleep(.25)
        state_label = self.call(label+'_settled')
        if self.identity() != self.frozen:
            raise ValueError('A query changed seed, generation, page identities, hashes or upload serials')
        capture = self.evidence / (label + '.png')
        if capture.exists():
            raise ValueError('Capture already exists')
        self.host('capture', label)
        verification = self.evidence / (label + '.verify.json')
        receipt = self.evidence / (state_label + '.state.json')
        report = verify_files(receipt, capture, verification)
        entry = {'label': label, 'expected_pass': expect_pass, 'receipt': str(receipt),
            'capture': str(capture), 'verification': str(verification), 'passed': report['passed'],
            'checked': report['logical_queries_checked'], 'failed': report['failed_queries'],
            'border_failures': report['border_failures']}
        self.results.append(entry)
        print(json.dumps(entry), flush=True)
        if report['passed'] != expect_pass or report['border_failures']:
            raise ValueError('Unexpected full pixel verification result: ' + label)
        if expect_pass:
            previous = dict(self.state, generation=self.state['generation']+1)
            with Image.open(capture) as image:
                rejection = verify_image(previous, image)
            rejection['control'] = 'different_generation_oracle_same_native_image'
            (self.evidence / (label + '.wrong-generation.verify.json')).write_text(json.dumps(rejection, indent=2), encoding='utf-8')
            if rejection['passed']:
                raise ValueError('Wrong generation oracle unexpectedly passed')

    def grow(self, n):
        self.resources('before_%d' % n)
        self.frozen = None
        self.call('grow_%d' % n, 'probe.grow(%d)' % n)
        self.wait_ready()
        for index, page in enumerate(self.state['pages']):
            if page['loaded']:
                continue
            self.call('upload_page_%03d' % index, 'probe.upload_page(%d)' % index)
            loaded = self.state['pages'][index]
            values = expected_bytes(self.state['seed'], self.state['generation'],
                range(loaded['base'], loaded['base']+loaded['count']))
            host_oracle = {'seed': self.state['seed'], 'generation': self.state['generation'],
                'base': loaded['base'], 'count': loaded['count'],
                'sha256': hashlib.sha256(values.tobytes()).hexdigest(),
                'sum_u8_mod2^32': int(values.astype('uint64').sum()) & 0xffffffff,
                'runtime_fingerprint': loaded['payload_fingerprint']}
            if host_oracle['sum_u8_mod2^32'] != loaded['payload_fingerprint']['value']:
                raise ValueError('Host and runtime page byte sums disagree')
            (self.evidence / ('page_%03d.host-oracle.json' % index)).write_text(json.dumps(host_oracle,indent=2),encoding='utf-8')
            print(json.dumps({'resident_target': n, 'page': index,
                'loaded_bytes': self.state['loaded_bytes'], 'cumulative_timings': self.state['cumulative_timings']}), flush=True)
        self.frozen = self.identity()

    def resources(self, label):
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length',ctypes.c_ulong),('load_percent',ctypes.c_ulong)] + [
                (name,ctypes.c_ulonglong) for name in ('total_physical','available_physical',
                'commit_limit','available_commit','total_virtual','available_virtual','extended_virtual')]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.WinDLL('kernel32',use_last_error=True).GlobalMemoryStatusEx(ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())
        report = {name:int(getattr(status,name)) for name,_ in status._fields_}
        report['minimum_available_commit_bytes'] = 4*1024**3
        (self.evidence / ('resources_'+label+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
        if report['available_commit'] < report['minimum_available_commit_bytes']:
            raise RuntimeError('Available system commit below4GiB; do not increase resident capacity')

    def identity(self):
        return {'seed': self.state['seed'], 'generation': self.state['generation'],
            'slot_count': self.state['slot_count'], 'geometry_build_serial': self.state['geometry_build_serial'],
            'native_attempt_serial': self.state['native_attempt_serial'],
            'pages': [{key: page[key] for key in ('base', 'count', 'name', 'seed', 'generation',
                'payload_fingerprint', 'upload_serial')} for page in self.state['pages']]}

    def run(self, resume_resident64k=False):
        resize = json.loads((self.evidence / 'resize_2560x1440.json').read_text(encoding='utf-8'))
        native = resize.get('result',resize)
        if native.get('ok') is not True or native.get('actualClient') != [2560,1440]:
            raise ValueError('Require a successful owned native-size resize receipt before any upload')
        if resume_resident64k:
            self.call('resume_snapshot')
            if self.state['slot_count'] != 65536 or self.state['loaded_bytes'] != 65536 or not self.state['pipeline_ready']:
                raise ValueError('Explicit resume accepts only the existing fully loaded64KiB prefix')
            self.frozen = self.identity()
            self.call('resume_query','probe.query(0)')
        else:
            self.grow(65536)
            self.call('install', 'probe.install_pipeline()')
            time.sleep(.2)
            self.call('connect', 'probe.finish_pipeline()')
        self.capture('calibration_64k_identity')
        self.call('hide_writer', 'probe.set_writer_visible(False)')
        self.capture('calibration_64k_hidden', False)
        self.call('show_writer', 'probe.set_writer_visible(True)')
        self.capture('calibration_64k_restored')
        for n in (1048576, 1572864, 2097152):
            self.grow(n)
            self.call('identity_%d' % n, 'probe.query(0)')
            self.capture('resident_%d_identity' % n)
            self.call('dependent_%d' % n, 'probe.query(2,salt=37,salt2=91)')
            self.capture('resident_%d_dependent' % n)
            self.resources('after_%d' % n)
            (self.evidence / ('resident_%d.summary.json' % n)).write_text(json.dumps({
                'bytes': n, 'binary_mib': n/1048576., 'page_count': len(self.state['pages']),
                'cumulative_timings': self.state['cumulative_timings'], 'state': self.state,
                'capacity_claim': 'verified_at_least_this_size_not_an_absolute_limit'}, indent=2), encoding='utf-8')
        self.call('quiesce', 'probe.set_writer_visible(False)\nprobe.set_geometry_visible(False)\nprobe.set_pipeline_enabled(False)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--resume-resident64k',action='store_true',help='Explicitly reuse an already verified resident prefix; never replay its upload')
    args = parser.parse_args()
    case = Case(args.project, args.evidence)
    outcome = {'status': 'running', 'runtime_file_writes': False, 'formal_fps_measured': False}
    try:
        case.run(args.resume_resident64k)
        outcome['status'] = 'passed'
    except (OSError, RuntimeError, ValueError, KeyError, TimeoutError, subprocess.SubprocessError) as error:
        outcome.update(status='failed', error='%s: %s' % (type(error).__name__, error),
            mutation_replayed=False)
        raise
    finally:
        outcome.update(results=case.results, events=case.events, final_state=case.state,
            elapsed_host_seconds=time.monotonic()-case.started)
        (case.evidence / 'large_case.summary.json').write_text(json.dumps(outcome, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
