"""Bounded fixed native block scene around the unchanged guarded DOF camera.

Host wrapper only. Import/preflight never contacts a game. A sole owner supplies
fresh projects/sessions. All old image gates and native kernels remain intact.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

import numpy as np


HERE = Path(__file__).resolve().parent
GUARD = HERE.parent / 'native_stencil_dof_guard_retest/runner.py'
STATUS = 'dof-fixed-world-status.json'
SCHEMA = 'native_dof_fixed_world_v1'
ROOM_BLOCK = 'minecraft:glowstone'
RULE_KEYS = ('daylight_cycle', 'weather_cycle')
TIME = 6000


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def room_plan(camera):
    if (not isinstance(camera, (list, tuple)) or len(camera) != 3
            or any(type(item) not in (float, int) or not math.isfinite(item) for item in camera)):
        raise ValueError('A finite actual camera origin is required')
    x, y, z = [int(math.floor(value)) for value in camera]
    minimum, maximum = [x-8, y-4, z-8], [x+8, y+8, z+8]
    if minimum[1] < -64 or maximum[1] > 319:
        raise ValueError('Fixed room would cross the supported build height')
    rows = []
    for px in range(minimum[0], maximum[0]+1):
        for py in range(minimum[1], maximum[1]+1):
            for pz in range(minimum[2], maximum[2]+1):
                shell = (px in (minimum[0], maximum[0]) or py in (minimum[1], maximum[1])
                         or pz in (minimum[2], maximum[2]))
                rows.append([[px, py, pz], ROOM_BLOCK if shell else 'minecraft:air', 0])
    return {'camera': list(camera), 'minimum': minimum, 'maximum': maximum,
            'rows': rows, 'cell_count': len(rows), 'rows_sha256': digest(rows),
            'shell_block': ROOM_BLOCK, 'interior_block': 'minecraft:air'}


def zero_match(identity, active):
    """Add an exact full exterior prerequisite without reducing the old gate."""
    a, b = np.asarray(identity, dtype=np.int16), np.asarray(active, dtype=np.int16)
    if a.shape != (1080, 720, 3) or b.shape != a.shape:
        raise ValueError('Fixed-world zero baseline requires native 720x1080 RGB')
    delta = np.abs(a-b)
    exterior = np.ones(a.shape[:2], dtype=bool)
    exterior[:120] = False  # The existing debug HUD is outside native scene evidence.
    exterior[128:640, 8:520] = False
    exact_errors = int(np.count_nonzero(exterior & np.any(delta != 0, axis=2)))
    tolerance_errors = int(np.count_nonzero(exterior & np.any(delta > 2, axis=2)))
    source_errors = int(np.count_nonzero(np.any(delta[128:640, 8:520] > 2, axis=2)))
    return {'accepted': exact_errors == 0 and source_errors == 0,
            'exterior_pixels': int(exterior.sum()), 'exterior_exact_error_pixels': exact_errors,
            'exterior_error_gt2_pixels': tolerance_errors,
            'source_error_gt2_pixels': source_errors,
            'exterior_max_channel_error': int(delta[exterior].max()),
            'source_max_channel_error': int(delta[128:640, 8:520].max()),
            'debug_hud_excluded_rows': [0, 120], 'existing_roi_guard_gate_unchanged': True}


class FixedWorld:
    def __init__(self, experiment, case):
        self.experiment, self.case = experiment, case
        self.prior_blocks = []
        self.prior_env = None
        self.blocks_touched = self.env_touched = False
        self.cleaned = False
        self.receipt = {'schema': SCHEMA, 'case': case, 'wrapper_sha256': sha(__file__),
            'guard_wrapper_sha256': sha(GUARD), 'failure': None, 'cleanup_failure': None,
            'prepared': False, 'complete': False, 'native_kernels_unchanged': True,
            'runtime_file_writes': False, 'world_dimension': 0, 'fixed_time': TIME,
            'room_restored_after_test': True}

    def prepare(self, camera):
        plan = room_plan(camera)
        self.receipt['room'] = {key: value for key, value in plan.items() if key != 'rows'}
        row = self.experiment.server('fixed_world_environment_before',
            "game=api.GetEngineCompFactory().CreateGame(api.GetLevelId())\n"
            "clock=api.GetEngineCompFactory().CreateTime(api.GetLevelId())\n"
            "dimension=api.GetEngineCompFactory().CreateDimension(api.GetLevelId())\n"
            "weather=api.GetEngineCompFactory().CreateWeather(api.GetLevelId())\n"
            "local=weather.GetDimensionUseLocalWeather(0)\n"
            "rules=game.GetGameRulesInfoServer()['cheat_info']\n"
            "_result=json.dumps({'time':clock.GetTime(),'local_time':dimension.GetUseLocalTime(0),"
            "'weather_local':local,'weather':weather.GetDimensionLocalWeatherInfo(0) if local else {},"
            "'rules':dict((key,rules[key]) for key in %r)})" % (RULE_KEYS,))
        self.prior_env = row
        self.receipt['environment_before'] = row
        if (type(row.get('time')) is not int or row.get('local_time') is not False
                or type(row.get('weather_local')) is not bool
                or any(type(row['rules'].get(key)) is not bool for key in RULE_KEYS)):
            raise RuntimeError('Fixed-world environment lacks typed readbacks')
        self.env_touched = True
        row = self.experiment.server('fixed_world_environment_set',
            "game=api.GetEngineCompFactory().CreateGame(api.GetLevelId())\n"
            "clock=api.GetEngineCompFactory().CreateTime(api.GetLevelId())\n"
            "weather=api.GetEngineCompFactory().CreateWeather(api.GetLevelId())\n"
            "accepted=[game.SetGameRulesInfoServer({'cheat_info':{'daylight_cycle':False,'weather_cycle':False}}),clock.SetTime(6000)]\n"
            "accepted.extend([weather.SetDimensionUseLocalWeather(0,True),weather.SetDimensionLocalDoWeatherCycle(0,False),"
            "weather.SetDimensionLocalRain(0,0.,12000000),weather.SetDimensionLocalThunder(0,0.,12000000)])\n"
            "rules=game.GetGameRulesInfoServer()['cheat_info']\n"
            "_result=json.dumps({'accepted':accepted,'time':clock.GetTime(),'rules':dict((key,rules[key]) for key in %r)})" % (RULE_KEYS,))
        self.receipt['environment_fixed'] = row
        if not all(value is True for value in row['accepted']) or row['time'] != TIME or any(row['rules'][key] is not False for key in RULE_KEYS):
            raise RuntimeError('Fixed time/daylight/weather rules were rejected')
        # Snapshot every cell before the first block write. The host retains the
        # complete bounded prior so restoration survives server exec namespaces.
        positions = [item[0] for item in plan['rows']]
        before = self.experiment.server('fixed_world_blocks_before',
            "block=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\n"
            "rows=[]\n"
            "for pos in %r:\n" % positions +
            "    item=block.GetBlockNew(tuple(pos),0)\n"
            "    if not item or 'name' not in item or 'aux' not in item: raise RuntimeError('Room cell is not loaded')\n"
            "    rows.append([pos,item['name'],item['aux']])\n"
            "_result=json.dumps({'rows':rows})")
        self.prior_blocks = before['rows']
        if [item[0] for item in self.prior_blocks] != positions:
            raise RuntimeError('Fixed room snapshot lacks exact cells')
        self.receipt['prior_blocks_sha256'] = digest(self.prior_blocks)
        self.blocks_touched = True
        changed = self.experiment.server('fixed_world_blocks_set',
            "block=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\n"
            "changed=0\n"
            "for pos,name,aux in %r:\n" % plan['rows'] +
            "    if block.SetBlockNew(tuple(pos),{'name':name,'aux':aux},0,0,True,True): changed+=1\n"
            "_result=json.dumps({'changed_cells':changed})")
        self.receipt['block_set'] = changed
        self.check(plan['rows'], 'fixed_world_blocks_ready')
        # Additional render fences allow queued chunk geometry/lighting to
        # finish. Their presence is evidence, not a replacement for zero PNGs.
        first = self.experiment.call('fixed_world_render_start', expression="{'frame':probe.render_event}")
        time.sleep(3.)
        last = self.experiment.call('fixed_world_render_ready', expression="{'frame':probe.render_event}")
        self.receipt['render_settle'] = [first, last]
        if last['frame'] <= first['frame']:
            raise RuntimeError('Fixed room did not cross a render turn')
        self.receipt['prepared'] = True

    def check(self, expected=None, label='fixed_world_blocks_check'):
        expected = expected or room_plan(self.receipt['room']['camera'])['rows']
        row = self.experiment.server(label,
            "block=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\n"
            "clock=api.GetEngineCompFactory().CreateTime(api.GetLevelId())\n"
            "game=api.GetEngineCompFactory().CreateGame(api.GetLevelId())\n"
            "weather=api.GetEngineCompFactory().CreateWeather(api.GetLevelId())\n"
            "actual=[]\n"
            "for pos,name,aux in %r:\n" % expected +
            "    item=block.GetBlockNew(tuple(pos),0)\n"
            "    actual.append([pos,item.get('name') if item else None,item.get('aux') if item else None])\n"
            "rules=game.GetGameRulesInfoServer()['cheat_info']\n"
            "_result=json.dumps({'rows':actual,'time':clock.GetTime(),'weather_local':weather.GetDimensionUseLocalWeather(0),"
            "'weather':weather.GetDimensionLocalWeatherInfo(0),'rules':dict((key,rules[key]) for key in %r)})" % (RULE_KEYS,))
        exact = row['rows'] == expected
        self.receipt[label] = {'cells': len(row['rows']), 'rows_sha256': digest(row['rows']),
            'exact': exact, 'time': row['time'], 'rules': row['rules'], 'weather_local': row['weather_local'],
            'weather': row['weather']}
        if (not exact or row['time'] != TIME or any(row['rules'][key] is not False for key in RULE_KEYS)
                or row['weather_local'] is not True or row['weather'].get('isWeatherCycle') is not False
                or row['weather'].get('rainLevel') != 0. or row['weather'].get('thunderLevel') != 0.):
            raise RuntimeError('Fixed room/environment readback differs from the declared scene')

    def cleanup(self):
        if self.cleaned:
            return
        errors = []
        if self.blocks_touched:
            try:
                row = self.experiment.server('fixed_world_blocks_restore',
                    "block=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\n"
                    "expected=%r\n" % self.prior_blocks +
                    "for pos,name,aux in expected:\n"
                    "    block.SetBlockNew(tuple(pos),{'name':name,'aux':aux},0,0,True,True)\n"
                    "mismatches=[]\n"
                    "for pos,name,aux in expected:\n"
                    "    item=block.GetBlockNew(tuple(pos),0)\n"
                    "    if not item or item.get('name')!=name or item.get('aux')!=aux: mismatches.append(pos)\n"
                    "_result=json.dumps({'cells':len(expected),'mismatches':mismatches})")
                self.receipt['block_restore'] = row
                if row['cells'] != len(self.prior_blocks) or row['mismatches']:
                    raise RuntimeError('Fixed world block restoration failed')
            except Exception as error:
                errors.append('blocks: ' + repr(error))
        if self.env_touched:
            try:
                row = self.experiment.server('fixed_world_environment_restore',
                    "game=api.GetEngineCompFactory().CreateGame(api.GetLevelId())\n"
                    "clock=api.GetEngineCompFactory().CreateTime(api.GetLevelId())\n"
                    "weather=api.GetEngineCompFactory().CreateWeather(api.GetLevelId())\n"
                    "weather_before=%r\n" % self.prior_env['weather'] +
                    "weather_accepted=[]\n"
                    "if %r:\n" % self.prior_env['weather_local'] +
                    "    weather_accepted=[weather.SetDimensionLocalDoWeatherCycle(0,weather_before['isWeatherCycle']),"
                    "weather.SetDimensionLocalRain(0,weather_before['rainLevel'],weather_before['rainTime']),"
                    "weather.SetDimensionLocalThunder(0,weather_before['thunderLevel'],weather_before['thunderTime'])]\n"
                    "weather_accepted.append(weather.SetDimensionUseLocalWeather(0,%r))\n" % self.prior_env['weather_local'] +
                    "accepted=[clock.SetTime(%r),game.SetGameRulesInfoServer({'cheat_info':%r})]\n" %
                    (self.prior_env['time'], self.prior_env['rules']) +
                    "rules=game.GetGameRulesInfoServer()['cheat_info']\n"
                    "_result=json.dumps({'accepted':accepted,'weather_accepted':weather_accepted,"
                    "'weather_local':weather.GetDimensionUseLocalWeather(0),'time':clock.GetTime(),"
                    "'rules':dict((key,rules[key]) for key in %r)})" % (RULE_KEYS,))
                self.receipt['environment_restore'] = row
                if (not all(value is True for value in row['accepted']) or row['rules'] != self.prior_env['rules']
                        or not all(value is True for value in row['weather_accepted'])
                        or row['weather_local'] is not self.prior_env['weather_local']
                        or abs(row['time']-self.prior_env['time']) > 2):
                    raise RuntimeError('Fixed world environment restoration failed')
            except Exception as error:
                errors.append('environment: ' + repr(error))
        self.cleaned = True
        if errors:
            self.receipt['cleanup_failure'] = '; '.join(errors)

    def save(self, result=None):
        if result is not None:
            self.receipt['dof_status'] = result.get('status')
            self.receipt['dof_failure'] = result.get('failure')
            self.receipt['dof_cleanup_failure'] = result.get('cleanup_failure')
            self.receipt['complete'] = (self.receipt['prepared'] is True
                and self.receipt['failure'] is None and self.receipt['cleanup_failure'] is None
                and result.get('failure') is None and result.get('cleanup_failure') is None
                and (result.get('gate', {}).get('accepted') is True if self.case == 'dof-identity'
                     else result.get('compatibility_verified') is True))
            if self.case == 'dof-active':
                self.receipt['complete'] = (self.receipt['complete'] and
                    self.receipt.get('zero_exterior_gate', {}).get('accepted') is True)
            if self.case == 'dof-identity':
                self.receipt['identity_status_sha256'] = sha(self.experiment.evidence / 'dof-identity-status.json')
                status = read(self.experiment.evidence / 'dof-identity-status.json')
                if status.get('profiles') and len(status['profiles']) == 5:
                    _, dof = module('fixed_identity_guard_reader', GUARD).base_modules()
                    self.receipt['identity_exterior_return'] = zero_match(
                        dof._open_rgb(status['profiles'][0]), dof._open_rgb(status['profiles'][-1]))
                    self.receipt['complete'] = (self.receipt['complete'] and
                        self.receipt['identity_exterior_return']['accepted'] is True)
        (self.experiment.evidence / STATUS).write_text(json.dumps(self.receipt, indent=2)+'\n', encoding='utf-8')


def verify_fixed_identity(path, guard, dof):
    path = Path(path).resolve()
    receipt = read(path.parent / STATUS)
    if (receipt.get('schema') != SCHEMA or receipt.get('case') != 'dof-identity'
            or receipt.get('wrapper_sha256') != sha(__file__) or receipt.get('guard_wrapper_sha256') != sha(GUARD)
            or receipt.get('failure') is not None or receipt.get('cleanup_failure') is not None
            or receipt.get('complete') is not True or receipt.get('identity_status_sha256') != sha(path)
            or receipt.get('identity_exterior_return', {}).get('accepted') is not True
            or receipt.get('fixed_world_blocks_ready', {}).get('exact') is not True):
        raise ValueError('A clean accepted fixed-world identity is required before active runtime')
    guard.verify_matched_identity(path, dof)
    return receipt


def main():
    if '--preflight' in sys.argv:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--preflight', action='store_true')
        parser.add_argument('--camera', type=float, nargs=3, default=[0., -58., -3.])
        args = parser.parse_args()
        plan = room_plan(args.camera)
        print(json.dumps({key: value for key, value in plan.items() if key != 'rows'}, indent=2))
        return
    guard = module('fixed_world_existing_scene_guard', GUARD)
    base, dof = guard.base_modules()
    args = sys.argv[1:]
    if '--help' in args or '-h' in args:
        return guard.main()
    if '--initialize' not in args or '--case' not in args:
        raise ValueError('Fixed world requires fresh --initialize and --case')
    case = args[args.index('--case')+1]
    if case not in ('dof-identity', 'dof-active'):
        raise ValueError('Fixed world supports identity/active only')
    baseline = None
    if case == 'dof-active':
        if '--identity-gate' not in args:
            raise ValueError('Fixed active requires --identity-gate')
        identity_path = Path(args[args.index('--identity-gate')+1]).resolve()
        baseline = verify_fixed_identity(identity_path, guard, dof)
    original_scene, original_native, original_run = guard.SceneGuard, dof.native_module, dof.run
    worlds = {}

    class RoomGuard(original_scene):
        def after_prepare(self):
            original_scene.after_prepare(self)
            world = FixedWorld(self.experiment, case)
            worlds['active'] = world
            try:
                camera = self.receipt['local_player_hidden']['camera']['position']
                world.prepare(camera)
                if baseline is not None and world.receipt['room'] != baseline['room']:
                    raise RuntimeError('Active fixed room differs from identity geometry/origin')
            except Exception as error:
                world.receipt['failure'] = repr(error)
                world.cleanup()
                world.save()
                raise

        def cleanup(self):
            world = worlds.get('active')
            if world is not None:
                world.cleanup()
            original_scene.cleanup(self)
            if world is not None and world.receipt['cleanup_failure'] is not None:
                self.receipt['cleanup_failure'] = world.receipt['cleanup_failure']

        def save(self, result=None):
            original_scene.save(self, result)
            world = worlds.get('active')
            if world is not None:
                if self.receipt['failure'] is not None:
                    world.receipt['failure'] = self.receipt['failure']
                world.save(result)

    def fixed_native():
        native = original_native()
        original_capture = native._capture
        def capture(*call_args, **kwargs):
            label = call_args[3]
            world = worlds['active']
            if label in ('candidate_dof-identity_zero', 'candidate_dof-active_zero'):
                world.check(label='fixed_world_after_initialization')
            row = original_capture(*call_args, **kwargs)
            if case == 'dof-active' and label == 'candidate_dof-active_zero':
                original = read(identity_path)['profiles'][0]
                comparison = zero_match(dof._open_rgb(original), dof._open_rgb(row))
                world.receipt['zero_exterior_gate'] = comparison
                world.check(label='fixed_world_zero_blocks_check')
                world.save()
                if comparison['accepted'] is not True:
                    raise RuntimeError('Fixed-world zero exterior differs; active nonzero profiles skipped')
            if label.endswith('_late_m6'):
                world.check(label='fixed_world_after_profiles')
            return row
        native._capture = capture
        return native

    def fixed_run(*call_args, **kwargs):
        worlds['active'].check(label='fixed_world_before_profiles')
        return original_run(*call_args, **kwargs)

    guard.SceneGuard, dof.native_module, dof.run = RoomGuard, fixed_native, fixed_run
    try:
        guard.main()
    finally:
        guard.SceneGuard, dof.native_module, dof.run = original_scene, original_native, original_run


if __name__ == '__main__':
    main()
