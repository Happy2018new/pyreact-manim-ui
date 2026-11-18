"""Run the finite64KiB default/transparent/default rain matrix on an owned game."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from verify_capture import verify

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCRIPTS = ROOT/'.agents/skills/pyreact-debugging/scripts'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resource_gate():
    class Status(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('percent', ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in ('total_physical', 'available_physical',
                'commit_limit', 'available_commit', 'total_virtual', 'available_virtual', 'extended_virtual')]
    status = Status()
    status.length = ctypes.sizeof(status)
    if not ctypes.WinDLL('kernel32', use_last_error=True).GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError(ctypes.get_last_error())
    result = {name: int(getattr(status, name)) for name, _ in status._fields_}
    if result['available_commit'] < 4*1024**3:
        raise RuntimeError('Available system commit below4GiB; no new native upload')
    return result


def identity(state):
    return {key: state[key] for key in ('entity', 'geometry_name', 'geometry_build_serial',
        'native_attempt_serial', 'generation', 'logical_payload_bytes', 'allocated_payload_bytes',
        'payload_salt', 'codec_roi', 'source_bundle_sha256')}


class Experiment:
    def __init__(self, args):
        self.args = args
        self.evidence = args.evidence.resolve()
        self.commands = self.evidence/'commands'
        self.commands.mkdir(exist_ok=False)
        self.session = json.loads((self.evidence/'launch.json').read_text(encoding='utf-8'))['session_file']
        self.events, self.reports, self.state, self.frozen = [], [], {}, None
        self.serial = 0

    def invoke(self, command, label):
        event = {'label': label, 'command': command, 'automatic_mutation_replay': False}
        self.events.append(event)
        with (self.evidence/(label+'.log')).open('x', encoding='utf-8') as output:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                timeout=140., creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        event['returncode'] = result.returncode
        if result.returncode:
            raise RuntimeError('Call failed; read state before another mutation: '+label)
        return event

    def call(self, label, code=''):
        self.serial += 1
        label = '%03d_%s' % (self.serial, label)
        path = self.commands/(label+'.py')
        path.write_text(code+'\n_result=json.dumps(probe.snapshot())\n', encoding='utf-8')
        event = self.invoke([sys.executable, '-B', '-X', 'utf8', str(HERE/'host.py'), 'call',
            '--project', str(self.args.project.resolve()), '--evidence', str(self.evidence),
            '--label', label, '--timeout', '120', '--code', str(path)], label)
        event['source_sha256'] = digest(path)
        self.state = json.loads((self.evidence/(label+'.state.json')).read_text(encoding='utf-8'))
        if self.state.get('error'):
            raise RuntimeError(self.state['error'])
        if self.state['native_reported_enabled']:
            raise ValueError('Native effects reported enabled; isolated test stopped')
        if self.frozen is not None and identity(self.state) != self.frozen:
            raise ValueError('Resident payload identity changed')
        return label

    def server(self, label, code):
        path = self.commands/(label+'.server.py')
        path.write_text('import json\nimport mod.server.extraServerApi as api\n'+code, encoding='utf-8')
        event = self.invoke([sys.executable, '-B', '-X', 'utf8', str(SCRIPTS/'instances.py'), 'exec',
            '--session', self.session, '--owner', 'manim-rain-geometry', '--', 'mcdk.py',
            'exec', str(path), '--server'], label)
        event['source_sha256'] = digest(path)
        raw = json.loads((self.evidence/(label+'.log')).read_text(encoding='utf-8-sig'))
        result = json.loads(raw) if isinstance(raw, str) else raw
        (self.evidence/(label+'.server.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result

    def capture(self, label, kind=None, count=None, controls=''):
        if controls:
            self.call(label+'_controls', controls)
        time.sleep(.35)
        state_label = self.call(label+'_settled')
        self.invoke([sys.executable, '-B', '-X', 'utf8', str(HERE/'host.py'), 'capture',
            '--project', str(self.args.project.resolve()), '--evidence', str(self.evidence), '--label', label], label+'_capture')
        receipt = json.loads((self.evidence/(label+'.json')).read_text(encoding='utf-8'))
        if (not receipt.get('ok') or receipt.get('backend') != 'Windows.Graphics.Capture' or
                receipt.get('agent_activation_allowed') is not False or
                receipt['frame_qpc_100ns'] < receipt['request_qpc_100ns']):
            raise ValueError('Capture lacks a fresh passive native WGC receipt')
        image = self.evidence/(label+'.png')
        report = verify(image, kind, count) if kind else {'kind': 'scene_visible', 'pixel_oracle': False}
        report.update(label=label, capture=str(image), state=str(self.evidence/(state_label+'.state.json')),
                      capture_sha256=digest(image), geometry_identity=identity(self.state),
                      transparent_requested=self.state['transparent_requested'],
                      transparent_amount_requested=self.state['transparent_amount_requested'],
                      native_order=self.state['native_post_order'],
                      actual_post_states=self.state['actual_post_states'])
        self.reports.append(report)
        (self.evidence/(label+'.verify.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k in ('label','kind','passed','query_errors',
            'guard_errors','bad_q','alpha_not255','bad_q_alpha_not255','max_block_exceptions',
            'overflow_source_pixels','alpha_restore_error_pixels')}), flush=True)
        if report.get('guard_errors', 0) or report.get('query_alpha_not255', 0):
            raise ValueError('Diagnostic guard or output alpha failed: '+label)
        return report

    def set_weather(self, label, raining):
        receipt = self.server(label, "weather=api.GetEngineCompFactory().CreateWeather(api.GetLevelId())\n"
            "before=weather.GetDimensionLocalWeatherInfo(0)\n"
            "accepted=weather.SetDimensionLocalRain(0,%r,12000000)\n"
            "_result=json.dumps({'accepted':accepted,'before':before,'after':weather.GetDimensionLocalWeatherInfo(0),"
            "'local':weather.GetDimensionUseLocalWeather(0),'requested_rain':%r})" %
            (1.0 if raining else 0.0, raining))
        if not receipt['accepted'] or not receipt['local']:
            raise ValueError('Local weather setter rejected')
        time.sleep(3.)

    def domain_controls(self):
        (self.evidence/'before_domain.resources.json').write_text(json.dumps(resource_gate(), indent=2), encoding='utf-8')
        self.call('domain_load', 'probe.load_payload(12288,bits=2,code_domain=True,background_first=True)')
        for phase, transparent in (('domain_default', False), ('domain_transparent', True), ('domain_return_default', False)):
            self.call(phase+'_api', 'probe.set_transparent(%r)' % transparent)
            self.capture(phase+'_original', 'domain_original', 16384,
                'probe.set_native_writer_visible(False)\nprobe.rain_inspect(11,16384)')
            self.capture(phase+'_encoded', 'domain_encoded', 16384,
                'probe.set_native_writer_visible(True)\nprobe.rain_inspect(11,16384)')
            self.capture(phase+'_restored', 'domain_restored', 16384, 'probe.rain_inspect(12,16384)')
            self.capture(phase+'_alpha_error', 'alpha_error', 16384, 'probe.rain_inspect(20,16384)')

    def payload_phase(self, phase, transparent, loops):
        self.call(phase+'_api', 'probe.set_transparent(%r,%r)\nprobe.set_native_writer_visible(True)' %
                  (transparent,self.args.amount))
        for frame in range(loops):
            prefix = '%s_frame%02d' % (phase, frame)
            for kind, controls, count in (
                    ('q_alpha', 'probe.rain_inspect(25,87424)', 87424),
                    ('block_alpha', 'probe.rain_inspect(24,87424)', 87424),
                    ('identity', 'probe.query(0,65536,3)', 65536),
                    ('dependent', 'probe.query(0,65536,5)', 65536)):
                self.capture(prefix+'_'+kind, kind, count, controls)

    def run(self):
        self.call('initial_native_state')
        self.call('open', 'api.HideCrossHairGUI(True)\nprobe.open()')
        deadline = time.monotonic()+20
        while not self.state['ready']:
            if time.monotonic() > deadline:
                raise TimeoutError('Actor uniforms not ready')
            time.sleep(.3)
            self.call('ready')
        self.call('camera', "camera=probe.factory.CreateCamera(probe.level)\n"
            "position=camera.GetPosition()\nprobe.rain_origin=(int(position[0]),int(position[1])-1,int(position[2]))\n"
            "camera.DepartCamera()\n"
            "if not camera.SetCameraPos((probe.rain_origin[0],probe.rain_origin[1]+1.,probe.rain_origin[2])) or not camera.SetCameraRotation((8.,180.,0.)):\n"
            "    raise RuntimeError('Camera control rejected')")
        pos = self.state['rain_camera_origin']
        if len(pos) != 3:
            raise RuntimeError('Missing fixed camera origin')
        self.server('prepare_clear_scene', "from geometry_atlas_probe import rain_scene_server as scene\n"
            "_result=json.dumps(scene.prepare(api,api.GetLevelId(),%r,'solid'))" % (tuple(pos),))
        self.call('install', 'probe.install_pipeline()')
        time.sleep(.5)
        self.call('finish', 'probe.finish_pipeline()')
        if not self.args.skip_domain:
            self.domain_controls()
        (self.evidence/'before_payload.resources.json').write_text(json.dumps(resource_gate(), indent=2), encoding='utf-8')
        self.call('payload_load', "probe.load_payload(65536,bits=2,salt=29)\n"
            "probe.layout[2:]=[296,192]\nprobe.codec_roi=[296,192,128,683]\nprobe._writer_controls()\nprobe.configure_codec()")
        self.frozen = identity(self.state)
        self.payload_phase('clear_default', False, 1)
        self.payload_phase('clear_transparent', True, 1)
        clear = [r for r in self.reports if r['label'].startswith('clear_')]
        self.clear_gate_passed = all(r['passed'] for r in clear)
        if not self.clear_gate_passed:
            return
        self.set_weather('rain_enabled', True)
        self.capture('rain_visible_writer_off', controls="probe.set_native_writer_visible(False)\n"
            "for name in probe.codec_processes:\n    probe.post.SetEnableByName(name,name=='scene_codec_raw')")
        self.call('rain_restore_pipeline', 'probe.set_native_writer_visible(True)\nprobe.configure_codec()')
        self.payload_phase('rain_default', False, self.args.rain_loops)
        self.payload_phase('rain_transparent', True, self.args.rain_loops)
        self.payload_phase('rain_return_default', False, self.args.rain_loops)
        self.call('restore_amount_one_and_disable',
                  'probe.set_transparent(True,1.0)\nprobe.set_transparent(False)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--amount', type=float, choices=(.5,1.), default=1.)
    parser.add_argument('--rain-loops', type=int, choices=(3,5), default=5)
    parser.add_argument('--skip-domain', action='store_true')
    args = parser.parse_args()
    task = Experiment(args)
    result = {'schema': 'rain_geometry_experiment_v1', 'status': 'running',
              'runtime_file_writes': False, 'continuous_updates': False, 'formal_fps_measured': False,
              'candidate_amount': args.amount, 'rain_loops': args.rain_loops,
              'requested_transparency_amount': args.amount,
              'domain_controls_run': not args.skip_domain,
              'known_color_domain_skipped': args.skip_domain, 'known_color_domain_valid': False}
    try:
        task.run()
        controls = [r for r in task.reports if r.get('kind') != 'scene_visible']
        transparent = [r for r in controls if r['transparent_requested']]
        result.update(status='matrix_completed', transparent_candidate_passed=all(r['passed'] for r in transparent),
                      expansion_allowed=all(r['passed'] for r in transparent))
        task.call('quiesce', 'probe.quiesce()')
        result['status'] = 'completed'
    except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.SubprocessError) as error:
        result.update(status='failed', error='%s: %s' % (type(error).__name__, error))
        raise
    finally:
        result.update(reports=task.reports, events=task.events, final_state=task.state,
                      clear_gate_passed=getattr(task,'clear_gate_passed',None))
        with (task.evidence/'rain_geometry.results.json').open('x', encoding='utf-8') as output:
            json.dump(result, output, indent=2)


if __name__ == '__main__':
    main()
