"""Matched static-scene wrapper for the unchanged native DOF retest.

Owner invoked only; no operations on import. No shader, kernel, old receipt or
pack mutation. Fresh disposable developer worlds and --initialize are required.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
RETEST = HERE.parent / 'native_stencil_post_retest'
STATUS = 'dof-guard-status.json'
POLICY = 'native-dof-guard-v1-local-and-existing-world-actors-hidden'


def inventory_code():
    """Current client world actors, excluding exact owned fixture IDs."""
    return """guard_loaded=api.GetEngineActor()
guard_owned=set(str(actor['entity']) for actor in probe.actors)
guard_owned.update(str(entity) for entity in probe.effects)
guard_fixture=getattr(probe,'known_fixture',None)
if guard_fixture is not None and guard_fixture.effect is not None:
    guard_owned.add(str(guard_fixture.effect))
guard_ordinary=dict((entity,info) for entity,info in guard_loaded.items() if str(entity) not in guard_owned)
"""


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def base_modules():
    if str(RETEST) not in sys.path:
        sys.path.insert(0, str(RETEST))
    base = module('owned_matched_dof_base_runner', RETEST / 'runner.py')
    return base, base.dof


def verify_matched_identity(status, dof):
    status = Path(status).resolve()
    fixture = read(status.parent / STATUS)
    if (fixture.get('schema') != 'native_dof_guard_v1' or fixture.get('policy') != POLICY
            or fixture.get('wrapper_sha256') != sha(__file__)
            or fixture.get('case') != 'dof-identity' or fixture.get('failure') is not None
            or fixture.get('cleanup_failure') is not None or fixture.get('complete') is not True
            or fixture.get('identity_status_sha256') != sha(status)):
        raise ValueError('An accepted matching static-scene identity fixture is required')
    if fixture.get('local_player_hidden', {}).get('accepted') is not True:
        raise ValueError('Matching identity lacks the local-player hide receipt')
    if fixture.get('world_rule', {}).get('after') is not False:
        raise ValueError('Matching identity did not disable natural spawning')
    if fixture.get('world_actor_check', {}).get('all_hidden') is not True:
        raise ValueError('Matching identity ordinary world actors were not hidden')
    return dof.verify_identity_gate(status, dof.native_module().verify_module.payload_bytes(65536))


class SceneGuard:
    def __init__(self, experiment, case):
        self.experiment = experiment
        self.case = case
        self.rule_changed = False
        self.local_changed = False
        self.hidden = []
        self.actor_touched = False
        self.cleaned = False
        self.receipt = {'schema': 'native_dof_guard_v1', 'policy': POLICY, 'case': case,
                        'wrapper_sha256': sha(__file__),
                        'failure': None, 'cleanup_failure': None, 'complete': False,
                        'prepared': False, 'runtime_file_writes': False,
                        'shader_or_kernel_modified': False,
                        'scope': 'Session local player and preexisting current-dimension nonplayer render flags; world mob_spawn only.'}

    def before_prepare(self):
        if self.rule_changed:
            raise RuntimeError('Static scene requires one fresh prepare only')
        # Server GetEngineActor explicitly excludes players. Enumeration occurs
        # before original prepare creates any client SFX fixture or carrier.
        prior = self.experiment.server('dof_guard_read_world_rule',
            "game=api.GetEngineCompFactory().CreateGame(api.GetLevelId())\n"
            "_result=json.dumps({'before':game.GetGameRulesInfoServer()['cheat_info']['mob_spawn']})")
        self.receipt['world_rule'] = prior
        if type(prior.get('before')) is not bool:
            raise RuntimeError('World natural-spawn rule lacks a Boolean readback')
        self.rule_changed = True  # Prior is durable even after a transport failure.
        code = """game=api.GetEngineCompFactory().CreateGame(api.GetLevelId())
accepted=game.SetGameRulesInfoServer({'cheat_info':{'mob_spawn':False}})
after=game.GetGameRulesInfoServer()['cheat_info']['mob_spawn']
actors=api.GetEngineActor()
players=api.GetPlayerList()
_result=json.dumps({'accepted':accepted,'after':after,'actors':actors,'players':players})
"""
        row = self.experiment.server('dof_guard_world_rule', code)
        row['before'] = prior['before']
        self.receipt['world_rule'] = row
        self.rule_changed = True  # Cleanup even if a subsequent readback fails.
        if type(row.get('before')) is not bool or row.get('accepted') is not True or row.get('after') is not False:
            raise RuntimeError('World natural-spawn preparation was rejected')
        actors = row['actors']
        if not isinstance(actors, dict) or len(actors) > 128 or set(actors) & set(row['players']):
            raise RuntimeError('Unexpected disposable-world actor enumeration')
        ids = sorted(key for key, value in actors.items() if value['dimensionId'] == 0)
        self.receipt['world_actor_ids'] = ids
        code = """probe._dof_guard_expected=%r
probe._dof_guard_saved=[]
guard_initial_loaded=api.GetEngineActor()
for entity in %r:
    if entity not in guard_initial_loaded: continue
    if (guard_initial_loaded[entity].get('dimensionId')!=0 or
            guard_initial_loaded[entity].get('identifier')!=probe._dof_guard_expected[entity].get('identifier')):
        raise RuntimeError('Initial world actor identity changed')
    render=api.GetEngineCompFactory().CreateActorRender(entity)
    prior=render.GetNotRenderAtAll()
    if type(prior) is not bool: raise RuntimeError('World actor lacks render-state readback')
    probe._dof_guard_saved.append((entity,prior))
    if render.SetNotRenderAtAll(True) is not True: raise RuntimeError('World actor hide rejected')
""" % ({key: actors[key] for key in ids}, ids)
        # Keep partial state in the client context for independent cleanup.
        self.actor_touched = True
        try:
            result = self.experiment.call('dof_guard_hide_world', code,
                "{'saved':probe._dof_guard_saved,'frame':probe.render_event}")
            self.hidden = result['saved']
            self.receipt['world_actors_hidden'] = result
        finally:
            # Retrieve even a prefix if one actor failed after earlier changes.
            result = self.experiment.call('dof_guard_saved_world', expression=
                "{'saved':getattr(probe,'_dof_guard_saved',[])}")
            self.hidden = result['saved']
        self.check_world()

    def check_world(self):
        row = self.experiment.call('dof_guard_check_world', inventory_code(), expression=
            "{'flags':[(entity,api.GetEngineCompFactory().CreateActorRender(entity).GetNotRenderAtAll()) for entity,prior in probe._dof_guard_saved if entity in guard_ordinary],"
            "'absent':[entity for entity,prior in probe._dof_guard_saved if entity not in guard_loaded],"
            "'owned_replacements':[entity for entity,prior in probe._dof_guard_saved if entity in guard_loaded and str(entity) in guard_owned],"
            "'unexpected':[entity for entity in guard_ordinary if entity not in dict(probe._dof_guard_saved)],"
            "'identity_mismatch':[entity for entity in guard_ordinary if entity in probe._dof_guard_expected and "
            "(guard_ordinary[entity].get('dimensionId')!=0 or guard_ordinary[entity].get('identifier')!=probe._dof_guard_expected[entity].get('identifier'))],"
            "'inventory':guard_loaded,'owned_fixture_ids':list(guard_owned),'frame':probe.render_event}")
        if row.get('unexpected') or row.get('identity_mismatch'):
            raise RuntimeError('A new or changed ordinary world actor became loaded')
        if any(flag is not True for _, flag in row['flags']):
            raise RuntimeError('Ordinary world actor render flag was not hidden')
        row['all_hidden'] = True
        self.receipt['world_actor_check'] = row
        return row

    def after_prepare(self):
        self.local_changed = True  # Restore even after a rejected/transport-failed setter.
        row = self.experiment.call('dof_guard_hide_local_player',
            'guard_game=api.GetEngineCompFactory().CreateGame(api.GetLevelId())\n'
            'accepted=guard_game.SetRenderLocalPlayer(False)',
            "{'accepted':accepted,'local_player':api.GetLocalPlayerId(),'frame':probe.render_event,"
            "'camera':{'position':probe.camera.GetPosition(),'forward':probe.camera.GetForward()}}")
        self.receipt['local_player_hidden'] = row
        if row['accepted'] is not True:
            raise RuntimeError('Explicit local-player render hide was rejected')
        self.check_world()
        self.receipt['prepared'] = True

    def cleanup(self):
        if self.cleaned:
            return
        errors = []
        if self.local_changed:
            try:
                row = self.experiment.call('dof_guard_restore_local_player',
                    'accepted=api.GetEngineCompFactory().CreateGame(api.GetLevelId()).SetRenderLocalPlayer(True)',
                    "{'accepted':accepted}")
                self.receipt['local_player_restore'] = row
                if row['accepted'] is not True:
                    raise RuntimeError('Local player render restore rejected')
            except Exception as error:
                errors.append('local: ' + repr(error))
        if self.actor_touched or self.hidden:
            try:
                row = self.experiment.call('dof_guard_restore_world',
                    inventory_code() +
                    "guard_restore_original=getattr(probe,'_dof_guard_saved',%r)\n" % self.hidden +
                    "guard_restore_expected=getattr(probe,'_dof_guard_expected',{})\n"
                    "guard_restore_saved=[(entity,prior) for entity,prior in guard_restore_original if entity in guard_ordinary and "
                    "guard_ordinary[entity].get('dimensionId')==0 and "
                    "(entity not in guard_restore_expected or guard_ordinary[entity].get('identifier')==guard_restore_expected[entity].get('identifier'))]\n" +
                    'restored=[(entity,prior,api.GetEngineCompFactory().CreateActorRender(entity).SetNotRenderAtAll(prior)) for entity,prior in guard_restore_saved]',
                    "{'restored':restored,'readbacks':[(entity,api.GetEngineCompFactory().CreateActorRender(entity).GetNotRenderAtAll()) for entity,prior in guard_restore_saved],"
                    "'absent_or_replaced':[entity for entity,prior in guard_restore_original if entity not in dict(guard_restore_saved)],"
                    "'inventory':guard_loaded,'owned_fixture_ids':list(guard_owned)}")
                self.receipt['world_actor_restore'] = row
                if (any(ok is not True for _, _, ok in row['restored'])
                        or [(entity, flag) for entity, flag in row['readbacks']] !=
                           [(entity, prior) for entity, prior, _ in row['restored']]
                        or not set((entity, prior) for entity, prior in self.hidden).issubset(
                            [(entity, prior) for entity, prior, _ in row['restored']] +
                            [(entity, prior) for entity, prior in self.hidden if entity in row.get('absent_or_replaced', [])])):
                    raise RuntimeError('World actor render restore rejected')
            except Exception as error:
                errors.append('actors: ' + repr(error))
        if self.rule_changed:
            try:
                prior = self.receipt['world_rule']['before']
                row = self.experiment.server('dof_guard_restore_world_rule',
                    "game=api.GetEngineCompFactory().CreateGame(api.GetLevelId())\n"
                    "accepted=game.SetGameRulesInfoServer({'cheat_info':{'mob_spawn':%r}})\n" % prior +
                    "_result=json.dumps({'accepted':accepted,'after':game.GetGameRulesInfoServer()['cheat_info']['mob_spawn']})")
                self.receipt['world_rule_restore'] = row
                if row['accepted'] is not True or row['after'] is not prior:
                    raise RuntimeError('World mob_spawn restore rejected')
            except Exception as error:
                errors.append('rule: ' + repr(error))
        if errors:
            self.receipt['cleanup_failure'] = '; '.join(errors)
        self.cleaned = True

    def save(self, result=None):
        if result is not None:
            self.receipt['dof_status'] = result.get('status')
            self.receipt['dof_failure'] = result.get('failure')
            self.receipt['dof_cleanup_failure'] = result.get('cleanup_failure')
            if self.case == 'dof-identity':
                self.receipt['identity_status_sha256'] = sha(self.experiment.evidence / 'dof-identity-status.json')
            self.receipt['complete'] = (self.receipt['prepared'] is True
                and self.receipt['failure'] is None and self.receipt['cleanup_failure'] is None
                and result.get('failure') is None and result.get('cleanup_failure') is None
                and (result.get('gate', {}).get('accepted') is True if self.case == 'dof-identity'
                     else result.get('compatibility_verified') is True))
        (self.experiment.evidence / STATUS).write_text(json.dumps(self.receipt, indent=2)+'\n', encoding='utf-8')


def main():
    args = sys.argv[1:]
    if '--help' in args or '-h' in args:
        base, _ = base_modules()
        return base.main()
    if '--initialize' not in args:
        raise ValueError('Matched fixture requires a fresh owner launch and --initialize')
    case = args[args.index('--case')+1] if '--case' in args else None
    if case not in ('dof-identity', 'dof-active'):
        raise ValueError('Matched wrapper supports identity and active only')
    base, dof = base_modules()
    if case == 'dof-active':
        if '--identity-gate' not in args:
            raise ValueError('Matched active requires --identity-gate')
        verify_matched_identity(args[args.index('--identity-gate')+1], dof)
    original_native = dof.native_module
    original_run = dof.run
    guards = {}

    def guarded_native():
        native = original_native()
        original_prepare = native.prepare_camera
        def prepare(experiment, effect):
            guard = SceneGuard(experiment, case)
            guards['active'] = guard
            try:
                guard.before_prepare()
                result = original_prepare(experiment, effect)
                guard.after_prepare()
                return result
            except Exception as error:
                guard.receipt['failure'] = repr(error)
                guard.cleanup()
                guard.save()
                raise
        native.prepare_camera = prepare
        return native

    def guarded_run(experiment, selected, identity_gate=None):
        guard = guards.get('active')
        if guard is None or guard.receipt['prepared'] is not True:
            raise RuntimeError('Matched scene was not prepared')
        result = None
        try:
            guard.check_world()
            result = original_run(experiment, selected, identity_gate)
            guard.check_world()
            return result
        except Exception as error:
            guard.receipt['failure'] = repr(error)
            raise
        finally:
            guard.cleanup()
            guard.save(result)
            if guard.receipt['cleanup_failure'] is not None:
                raise RuntimeError('Matched scene restore failed: ' + guard.receipt['cleanup_failure'])

    dof.native_module, dof.run = guarded_native, guarded_run
    try:
        base.main()
    finally:
        guard = guards.get('active')
        if guard is not None and not guard.cleaned:
            guard.receipt['failure'] = guard.receipt['failure'] or 'DOF initialization ended before the guarded run'
            guard.cleanup()
            guard.save()
        dof.native_module, dof.run = original_native, original_run


if __name__ == '__main__':
    main()
