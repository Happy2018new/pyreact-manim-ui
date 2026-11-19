"""Bounded native shadow branch; run only through the sole lifecycle owner's Experiment."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import time

from PIL import Image


HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location('native_shadow_frozen_visual_oracle',
    HERE.parent / 'integrated_shadow_fixture/verify.py')
verify = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verify)


def _images(reports):
    frames = []
    for report in reports:
        with Image.open(report['capture_file']) as image:
            frames.append(image.convert('RGB'))
    return frames


def _project(experiment, label, points):
    return experiment.call(label, expression=
        "[probe.camera.WorldToScreenPoint(*point) for point in %r]" % (points,))


def _polygon(experiment, label, points):
    projected = _project(experiment, label, points)
    if any(not point or point.get('depth', 0) <= 0 for point in projected):
        raise RuntimeError('Known floor points must project in front of the fixed camera')
    return [[point['screenX'], point['screenY']] for point in projected]


def _body(experiment, entity, kind):
    foot = experiment.call('shadow_' + kind + '_native_foot', expression=
        'probe.factory.CreatePos(%r).GetFootPos()' % entity)
    half, height = (.5, 1.) if kind == 'cube' else (.85, 1.15)
    points = [(foot[0] + dx, foot[1] + dy, foot[2] + dz)
              for dx in (-half, half) for dy in (0., height) for dz in (-half, half)]
    projected = _project(experiment, 'shadow_' + kind + '_body_bounds', points)
    return [min(point['screenX'] for point in projected), min(point['screenY'] for point in projected),
            max(point['screenX'] for point in projected), max(point['screenY'] for point in projected)]


def _floor(experiment, foot):
    cx, cz = int(math.floor(foot[0])), int(math.floor(foot[2]))
    positions = [(x, -60, z) for x in range(cx - 2, cx + 4) for z in range(cz - 2, cz + 4)]
    before = experiment.server('shadow_floor_backup',
        "blocks=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\n"
        "rows=[{'pos':pos,'before':blocks.GetBlockNew(pos,0)} for pos in %r]\n"
        "if any(row['before'] is None for row in rows): raise RuntimeError('Shadow floor needs loaded terrain')\n"
        "_result=json.dumps(rows)" % (positions,))
    return before


def _place_floor(experiment, backup):
    return experiment.server('shadow_floor_stone',
        "factory=api.GetEngineCompFactory()\nblocks=factory.CreateBlockInfo(api.GetLevelId())\n"
        "rules=factory.CreateGame(api.GetLevelId()).SetGameRulesInfoServer({'cheat_info':{'daylight_cycle':False,'weather_cycle':False,'mob_spawn':False,'random_tick_speed':0}})\n"
        "time_ok=factory.CreateTime(api.GetLevelId()).SetTimeOfDay(6000)\nrows=[]\n"
        "for pos in %r:\n"
        "    blocks.SetBlockNew(tuple(pos),{'name':'minecraft:stone','aux':0},0,0,True,False)\n"
        "    rows.append({'pos':pos,'after':blocks.GetBlockNew(tuple(pos),0)})\n"
        "_result=json.dumps({'rules_ok':rules,'time_ok':time_ok,'rows':rows})" % ([row['pos'] for row in backup],))


def _restore_floor(experiment, backup):
    return experiment.server('shadow_floor_restore',
        "blocks=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\nrows=[]\n"
        "for row in %r:\n"
        "    pos=tuple(row['pos']); block=row['before']\n"
        "    blocks.SetBlockNew(pos,block,0,0,False,False)\n"
        "    after=blocks.GetBlockNew(pos,0)\n"
        "    rows.append({'pos':pos,'exact':after is not None and after.get('name')==block.get('name') and after.get('aux',0)==block.get('aux',0)})\n"
        "_result=json.dumps({'all_exact':all(row['exact'] for row in rows),'rows':rows})" % (backup,))


def _pig(experiment, foot):
    return experiment.server('shadow_pig_create',
        "system=api.GetServerSystemCls()('pmanim_native_shadow_fixture','temporary')\n"
        "entity=system.CreateEngineEntityByTypeStr('minecraft:pig',%r,(0.,0.),0,True,False)\n"
        "if entity is None: raise RuntimeError('Native stock pig creation rejected')\n"
        "factory=api.GetEngineCompFactory()\ncontrol=factory.CreateControlAi(entity)\n"
        "accepted=control.SetBlockControlAi(False,True)\n"
        "_result=json.dumps({'entity':entity,'freeze_accepted':accepted,'ai_enabled':control.GetBlockControlAi(),"
        "'position':factory.CreatePos(entity).GetFootPos(),'rotation':factory.CreateRot(entity).GetRot()})" % (tuple(foot),))


def _snapshot(experiment, label, entity, enabled, revision, kind):
    receipt = experiment.call(label,
        'probe.factory.CreateModel(%r).SetEntityShadowShow(%r)' % (entity, enabled),
        expression="{'entity':%r,'shadow_requested':%r,'native_position':probe.factory.CreatePos(%r).GetFootPos(),"
        "'rotation':probe.factory.CreateRot(%r).GetRot(),'camera':{'position':probe.camera.GetPosition(),"
        "'forward':probe.camera.GetForward()}}" % (entity, enabled, entity, entity))
    receipt.update(receiver_revision=revision, static_entity=kind == 'cube', animation_frozen=kind == 'pig')
    if kind == 'pig':
        frozen = experiment.server(label + '_freeze_receipt',
            "factory=api.GetEngineCompFactory()\n_result=json.dumps({'ai_enabled':factory.CreateControlAi(%r).GetBlockControlAi(),"
            "'position':factory.CreatePos(%r).GetFootPos(),'rotation':factory.CreateRot(%r).GetRot()})" % (entity, entity, entity))
        receipt['native_frozen_receipt'] = frozen
        receipt['animation_frozen'] = frozen['ai_enabled'] is False
    return receipt


def _triplet(experiment, prefix, configuration, entity, revision, kind):
    reports, states = [], []
    for suffix, enabled in (('off_before', False), ('on', True), ('off_after', False)):
        label = prefix + '_' + suffix
        states.append(_snapshot(experiment, label + '_toggle', entity, enabled, revision, kind))
        reports.append(experiment.raw_capture(label, configuration=configuration))
    return reports, states


def run(experiment):
    """No starts/stops/input/asset edits. Preserve unsuccessful cube before stock pig fallback."""
    path = experiment.evidence / 'shadow-status.json'
    if path.exists():
        raise RuntimeError('Use a fresh shadow evidence directory')
    status = {'schema':'bounded_native_shadow_compat_v1','variant':experiment.variant,
              'attempts':[],'failure':None,'cleanup':{},'game_lifecycle_operations':False}
    backup, cube, pig = None, None, None

    def save():
        path.write_text(json.dumps(status,indent=2),encoding='utf-8')
        experiment.save()

    try:
        ray = experiment.call('shadow_fixed_roi_ray', expression=
            "{'ray':probe.camera.GetWorldRayFromScreenPoint(520.,550.),'camera':{'position':probe.camera.GetPosition(),'forward':probe.camera.GetForward()}}")
        origin, direction = ray['ray']['origin'], ray['ray']['direction']
        distance = (-59. - origin[1]) / direction[1]
        if distance <= 1. or distance > 16.:
            raise RuntimeError('Fixed camera shadow ray must intersect floor within1..16blocks')
        foot = [origin[index] + direction[index] * distance for index in range(3)]
        foot[1] = -59.
        status.update(camera=ray['camera'], foot=foot)
        backup = _floor(experiment, foot)
        status['floor_backup'] = backup
        save()
        floor = _place_floor(experiment, backup)
        status['floor_placed'] = floor
        if not floor['rules_ok'] or not floor['time_ok'] or any(
                row['after'].get('name') != 'minecraft:stone' for row in floor['rows']):
            raise RuntimeError('Native floor/rules setup failed')
        revision = hashlib.sha256(json.dumps(floor,sort_keys=True).encode('ascii')).hexdigest()
        for kind in ('cube','pig'):
            if kind == 'cube':
                experiment.call('shadow_cube_prepare', 'probe.prepare_outline(position=%r)\nprobe.configure_outline(False)' % (tuple(foot),))
                cube = experiment.state['outline']['entity']
                entity = cube
            else:
                experiment.call('shadow_cube_destroy_before_pig', 'probe.outline.destroy()')
                cube = None
                pig_receipt = _pig(experiment, foot)
                status['pig_receipt'] = pig_receipt
                pig = pig_receipt['entity']
                if not pig_receipt['freeze_accepted'] or pig_receipt['ai_enabled'] is not False:
                    raise RuntimeError('Native pig AI/animation freeze failed')
                entity = pig
            time.sleep(.7)
            body = _body(experiment, entity, kind)
            px, _, pz = foot
            receiver_world = [(px-1.25,-59.,pz-1.25),(px+1.25,-59.,pz-1.25),
                              (px+1.25,-59.,pz+1.25),(px-1.25,-59.,pz+1.25)]
            control_world = [(px+1.6,-59.,pz-.3),(px+2.2,-59.,pz-.3),
                             (px+2.2,-59.,pz+.3),(px+1.6,-59.,pz+.3)]
            plan = verify.make_plan(experiment.viewport,experiment.roi,
                _polygon(experiment,'shadow_'+kind+'_receiver_projection',receiver_world),body,
                _polygon(experiment,'shadow_'+kind+'_control_projection',control_world))
            item = {'kind':kind,'entity':entity,'plan':plan,'receiver_world':receiver_world,
                    'control_world':control_world,'body_bounds':body,'receiver_revision':revision}
            status['attempts'].append(item)
            save()  # Freeze and persist geometry before the first acceptance capture.
            baseline, states = _triplet(experiment,'shadow_'+kind+'_native','off',entity,revision,kind)
            item['native_snapshots'] = states
            item['native_state_gate'] = verify.compare_snapshots(states)
            item['native_visual'] = verify.compare_shadow(*_images(baseline),plan)
            item['native_captures'] = [report['capture_file'] for report in baseline]
            save()
            if not item['native_state_gate']['pass'] or not item['native_visual']['pass']:
                if kind == 'cube':
                    continue
                raise RuntimeError('Stock pig native shadow positive control failed; preserve evidence')
            if experiment.variant == 'carrier':
                active, active_states = _triplet(experiment,'shadow_'+kind+'_active','all',entity,revision,kind)
                item['active_snapshots'] = active_states
                item['active_state_gate'] = verify.compare_snapshots(active_states)
                _snapshot(experiment,'shadow_'+kind+'_payload_on',entity,True,revision,kind)
                data = experiment.data_checks('shadow_'+kind+'_payload')
                item['coexistence'] = verify.compare_coexistence(_images(baseline),_images(active),plan,data,experiment.payload)
                item['payload_captures'] = [report['capture_file'] for report in data]
                save()
                if not item['active_state_gate']['pass'] or not item['coexistence']['pass']:
                    raise RuntimeError('Native shadow/64KiB coexistence failed; preserve actual conflict')
            status['pass'] = True
            break
        if not status.get('pass'):
            raise RuntimeError('No actual native shadow positive control was established')
    except Exception as error:
        status['failure'] = repr(error)
        raise
    finally:
        if pig is not None:
            status['cleanup']['pig'] = experiment.server('shadow_pig_destroy',
                "system=api.GetServerSystemCls()('pmanim_native_shadow_fixture','cleanup')\n"
                "accepted=system.DestroyEntity(%r)\n_result=json.dumps({'destroy_requested':%r,'accepted':accepted})" % (pig,pig))
        if cube is not None:
            status['cleanup']['cube'] = experiment.call('shadow_cube_destroy','probe.outline.destroy()')
        if backup is not None:
            status['cleanup']['floor'] = _restore_floor(experiment,backup)
            if not status['cleanup']['floor']['all_exact']:
                status['failure'] = status['failure'] or 'Shadow floor restoration failed'
        save()
    return status
