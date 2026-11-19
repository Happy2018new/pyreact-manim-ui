"""Bounded ordinary-actor render control for a fresh disposable joint world.

Use only public inventory/render/game-rule APIs already exercised by the DOF
scene guard. No actor is deleted, moved, or assigned a different AI state.
"""


class AmbientGuard:
    def __init__(self, experiment):
        self.experiment = experiment
        self.rule_changed = False
        self.actor_touched = False
        self.receipt = {'schema': 'joint_existing_nonplayer_render_guard_v1',
                        'prepared': False, 'cleanup_failure': None,
                        'runtime_file_writes': False}

    def prepare(self):
        exp = self.experiment
        prior = exp.server('joint_ambient_rule_backup',
            "game=api.GetEngineCompFactory().CreateGame(api.GetLevelId())\n"
            "_result=json.dumps({'before':game.GetGameRulesInfoServer()['cheat_info']['mob_spawn']})")
        self.receipt['world_rule'] = prior
        if type(prior.get('before')) is not bool:
            raise RuntimeError('Joint ambient rule requires Boolean original readback')
        self.rule_changed = True
        row = exp.server('joint_ambient_disable_spawning',
            "game=api.GetEngineCompFactory().CreateGame(api.GetLevelId())\n"
            "accepted=game.SetGameRulesInfoServer({'cheat_info':{'mob_spawn':False}})\n"
            "_result=json.dumps({'accepted':accepted,'after':game.GetGameRulesInfoServer()['cheat_info']['mob_spawn'],"
            "'actors':api.GetEngineActor(),'players':api.GetPlayerList()})")
        self.receipt['world_rule'].update(row)
        actors, players = row['actors'], row['players']
        if (row['accepted'] is not True or row['after'] is not False or
                not isinstance(actors, dict) or len(actors) > 128 or set(actors) & set(players)):
            raise RuntimeError('Joint ambient enumeration/spawn control rejected')
        expected = {entity: info for entity, info in actors.items() if info['dimensionId'] == 0}
        self.receipt['enumerated_existing_nonplayers'] = expected
        self.actor_touched = True
        code = """probe._joint_ambient_expected=%r
probe._joint_ambient_players=%r
probe._joint_ambient_saved=[]
joint_loaded=api.GetEngineActor()
for entity in %r:
    if entity not in joint_loaded: continue
    info=joint_loaded[entity]
    if entity in probe._joint_ambient_players or entity==api.GetLocalPlayerId():
        raise RuntimeError('Joint ambient guard must never hide a player')
    if info.get('dimensionId')!=0 or info.get('identifier')!=probe._joint_ambient_expected[entity].get('identifier'):
        raise RuntimeError('Joint ambient actor identity changed')
    render=api.GetEngineCompFactory().CreateActorRender(entity)
    prior=render.GetNotRenderAtAll()
    if type(prior) is not bool: raise RuntimeError('Joint ambient render readback missing')
    probe._joint_ambient_saved.append((entity,prior))
    if render.SetNotRenderAtAll(True) is not True: raise RuntimeError('Joint ambient hide rejected')
""" % (expected, players, sorted(expected))
        self.receipt['hidden'] = exp.call('joint_ambient_hide_existing', code,
            expression="{'saved':probe._joint_ambient_saved,'frame':probe.render_event}")
        self.check()
        self.receipt['prepared'] = True

    @staticmethod
    def inventory_code():
        return """joint_loaded=api.GetEngineActor()
joint_owned=set(str(actor['entity']) for actor in probe.actors)
joint_owned.update(str(entity) for entity in probe.effects)
if probe.outline is not None and probe.outline.entity is not None:
    joint_owned.add(str(probe.outline.entity))
joint_players=set(getattr(probe,'_joint_ambient_players',[]))
joint_players.add(api.GetLocalPlayerId())
joint_ordinary=dict((entity,info) for entity,info in joint_loaded.items()
    if str(entity) not in joint_owned and entity not in joint_players and info.get('dimensionId')==0)
"""

    def check(self):
        row = self.experiment.call('joint_ambient_check_%03d' % self.experiment.serial,
            self.inventory_code(), expression=
            "{'flags':[(entity,api.GetEngineCompFactory().CreateActorRender(entity).GetNotRenderAtAll()) "
            "for entity,prior in probe._joint_ambient_saved if entity in joint_ordinary],"
            "'unexpected':[entity for entity in joint_ordinary if entity not in dict(probe._joint_ambient_saved)],"
            "'identity_mismatch':[entity for entity in joint_ordinary if entity in probe._joint_ambient_expected "
            "and joint_ordinary[entity].get('identifier')!=probe._joint_ambient_expected[entity].get('identifier')],"
            "'frame':probe.render_event}")
        if row['unexpected'] or row['identity_mismatch'] or any(flag is not True for entity, flag in row['flags']):
            raise RuntimeError('Joint ambient actor inventory/render state changed')
        self.receipt.setdefault('checks', []).append(row)
        return row

    def cleanup(self):
        errors = []
        if self.actor_touched:
            try:
                row = self.experiment.call('joint_ambient_restore_existing', self.inventory_code() +
                    "joint_restore=[(entity,prior) for entity,prior in getattr(probe,'_joint_ambient_saved',[]) "
                    "if entity in joint_ordinary and joint_ordinary[entity].get('identifier')==probe._joint_ambient_expected[entity].get('identifier')]\n"
                    "restored=[(entity,prior,api.GetEngineCompFactory().CreateActorRender(entity).SetNotRenderAtAll(prior)) for entity,prior in joint_restore]",
                    expression="{'restored':restored,'readbacks':[(entity,api.GetEngineCompFactory().CreateActorRender(entity).GetNotRenderAtAll()) for entity,prior in joint_restore],"
                    "'absent_or_replaced':[entity for entity,prior in getattr(probe,'_joint_ambient_saved',[]) if entity not in dict(joint_restore)]}")
                self.receipt['actor_restore'] = row
                if (any(ok is not True for entity, prior, ok in row['restored']) or
                        row['readbacks'] != [[entity, prior] for entity, prior, ok in row['restored']]):
                    raise RuntimeError('Joint ambient render restore rejected')
            except Exception as error:
                errors.append('actors: ' + repr(error))
        if self.rule_changed:
            try:
                prior = self.receipt['world_rule']['before']
                row = self.experiment.server('joint_ambient_restore_spawn_rule',
                    "game=api.GetEngineCompFactory().CreateGame(api.GetLevelId())\n"
                    "accepted=game.SetGameRulesInfoServer({'cheat_info':{'mob_spawn':%r}})\n" % prior +
                    "_result=json.dumps({'accepted':accepted,'after':game.GetGameRulesInfoServer()['cheat_info']['mob_spawn']})")
                self.receipt['world_rule_restore'] = row
                if row['accepted'] is not True or row['after'] is not prior:
                    raise RuntimeError('Joint ambient spawning restore rejected')
            except Exception as error:
                errors.append('rule: ' + repr(error))
        self.receipt['cleanup_failure'] = '; '.join(errors) if errors else None
        return self.receipt
