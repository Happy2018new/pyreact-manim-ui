"""Small host-only SFX routing comparison on unchanged effect IDs and metadata."""
import time

from PIL import Image


def ids_expression():
    return "{'fixture':probe.known_fixture.effect,'late':list(probe.effects)}"


def guard_source(ids):
    values = [ids.get('fixture')]+ids.get('late', [])
    if len(values) != 4 or any(value is None for value in values) or len(set(values)) != 4:
        raise ValueError('Routing requires four distinct existing effect IDs')
    return ("if probe.known_fixture.effect!=%r or list(probe.effects)!=%r: raise RuntimeError('Routing effect identities changed')\n"
            % (ids['fixture'], ids['late']))+"if probe.known_fixture.control is None or len(probe.controls)!=3: raise RuntimeError('Routing controls are unavailable')\n"


def destroy_fixture_source():
    return """routing_destroy=[]
if probe.known_fixture.control is not None:
    accepted=probe.known_fixture.control.Stop()
    routing_destroy.append({'operation':'Stop','accepted':accepted})
    if accepted is not True: raise RuntimeError('Overworld fixture Stop rejected')
if probe.known_fixture.effect is not None:
    entity=probe.known_fixture.effect
    accepted=probe.DestroyEntity(entity)
    routing_destroy.append({'operation':'DestroyEntity','entity':entity,'accepted':accepted})
    if accepted is not True: raise RuntimeError('Overworld fixture destruction rejected')
probe.known_fixture.effect,probe.known_fixture.control=None,None
probe.known_fixture.visible=False
probe.known_fixture.varying_alpha,probe.known_fixture.roi=None,None
"""


def fixture_source():
    # Reuse metadata already set on this fixture. Only visibility/playback and
    # diagnostic post controls change between the identical compared views.
    return """probe.configure('off')
if not probe.known_fixture.control.Play(): raise RuntimeError('Routing fixture Play rejected')
probe.known_fixture.visible=True
probe.inspect(7,shape_enabled=False,enabled=True,restore_enabled=False)
if not probe.post.SetParameter('stencil_integrated_consumer','output',[0.,650.,float(probe.viewport[0]),0.]): raise RuntimeError('Routing raw export Y650 rejected')
"""


def all_source(mode):
    if mode not in (1, 3):
        raise ValueError('Routing payload views use modes 1 and 3')
    return """if not probe.known_fixture.control.Stop(): raise RuntimeError('Routing fixture Stop rejected')
probe.known_fixture.visible=False
probe.configure('all')
probe.inspect(%d,shape_enabled=False,enabled=True,restore_enabled=True)
""" % mode


def global_source(ids):
    return guard_source(ids)+"""routing_receipts=[]
for entity,control in [(probe.known_fixture.effect,probe.known_fixture.control)]+list(zip(probe.effects,probe.controls)):
    accepted=control.SetGlobal(True)
    routing_receipts.append({'operation':'SetGlobal','entity':entity,'value':True,'accepted':accepted})
    if accepted is not True: raise RuntimeError('Routing SetGlobal rejected')
routing_result={'receipts':routing_receipts,'frame':probe.render_event,'ids':{'fixture':probe.known_fixture.effect,'late':list(probe.effects)}}
"""


def metadata_source(ids):
    return guard_source(ids)+"""routing_receipts=[]
pairs=(probe.viewport,probe.roi[:2],probe.roi[2:])
packed=tuple((first*4096+second)/16777216. for first,second in pairs)
controls=[(probe.known_fixture.effect,probe.known_fixture.control,12,packed+(.25,))]
controls.extend((entity,control,13+index,packed+((index+1)/4.,)) for index,(entity,control) in enumerate(zip(probe.effects,probe.controls)))
for entity,control,layer,mix in controls:
    values=(('SetFaceCamera',True),('SetLoop',True),('SetLayer',layer),('SetMixColor',mix),('Play',None))
    for operation,value in values:
        if operation=='SetFaceCamera': accepted=control.SetFaceCamera(value)
        elif operation=='SetLoop': accepted=control.SetLoop(value)
        elif operation=='SetLayer': accepted=control.SetLayer(value)
        elif operation=='SetMixColor': accepted=control.SetMixColor(value)
        else: accepted=control.Play()
        routing_receipts.append({'operation':operation,'entity':entity,'value':value,'accepted':accepted})
        if accepted is not True: raise RuntimeError('Routing metadata/playback reapply rejected: '+operation)
probe.known_fixture.visible=True
routing_result={'receipts':routing_receipts,'frame':probe.render_event,'ids':{'fixture':probe.known_fixture.effect,'late':list(probe.effects)}}
"""


def position_source(ids):
    return guard_source(ids)+"""import math
head=probe.factory.CreatePos(api.GetLocalPlayerId()).GetPos()
forward=probe.camera.GetForward()
if head is None or forward is None or any(math.isnan(value) or math.isinf(value) for value in tuple(head)+tuple(forward)): raise RuntimeError('Routing player position or forward unavailable')
target=tuple(head[index]+4.*forward[index] for index in range(3))
routing_receipts=[]
for entity in [probe.known_fixture.effect]+list(probe.effects):
    accepted=probe.factory.CreateFrameAniTrans(entity).SetPos(target)
    routing_receipts.append({'operation':'FrameAniTrans.SetPos','entity':entity,'position':target,'accepted':accepted})
    if accepted is not True: raise RuntimeError('Routing SFX position rejected')
routing_result={'receipts':routing_receipts,'frame':probe.render_event,'player_position':head,'forward':forward,'target':target,
    'ids':{'fixture':probe.known_fixture.effect,'late':list(probe.effects)}}
"""


def moved_gate(experiment, positive, reference, ids, target):
    frozen = positive.static_identity(reference['probe'])
    recovery = reference['probe']['dimension_recovery']
    def gate(label):
        value = positive.current(experiment, label)
        positive.candidate.gate(value['probe'], frozen['identity'], frozen['native_page_names'],
                                recovery['serial'], recovery['pair'])
        if (value['dimension'] != reference['dimension'] or positive.static_identity(value['probe']) != frozen or
                not positive.pose.vector(value['camera']) or not positive.pose.vector(value['anchor']) or
                any(abs(value[key][index]-reference[key][index]) > .01 for key in ('camera', 'anchor') for index in range(3))):
            raise RuntimeError('Moved SFX routing changed camera, geometry, dimension or static identity')
        positions = experiment.call(label+'_sfx_positions', guard_source(ids), expression=
            "[probe.factory.CreateFrameAniTrans(entity).GetPos() for entity in [probe.known_fixture.effect]+list(probe.effects)]")
        value['routing_effect_positions'] = positions
        if (len(positions) != 4 or any(not positive.pose.vector(position) or
                any(abs(position[index]-target[index]) > .02 for index in range(3)) for position in positions)):
            raise RuntimeError('Moved routing SFX positions differ from the recorded player-relative target')
        return value
    return gate


def fixture_view(experiment, original, positive, observations, label, ids, gate):
    row = {'kind': 'fixture_only', 'mode': 7}
    row['controls'] = experiment.call(label+'_controls', guard_source(ids)+fixture_source())
    time.sleep(.6)
    row['state'] = gate(label+'_settled')
    row['readback'] = observations.capture(experiment, label, 7, original, positive)
    with Image.open(row['readback']['capture_file']) as frame:
        row['fixture_comparison'] = observations.fixture_comparison(frame, 'off', experiment.payload,
            experiment.viewport, experiment.roi, original.integrated.verify_module)
    check = row['fixture_comparison']
    row['pixel_verified'] = (check['screen_roi']['data_error_pixels'] == 0 and
        check['exported_t3']['data_error_pixels'] == 0 and row['readback']['guard_error_pixels'] == 0)
    return row


def preflight(experiment, original, positive, observations, frozen, record):
    """Overworld analytic positive, then destroy/reset before authentic transit."""
    record.update(attempted=True, pixel_verified=False)
    try:
        record['create'] = experiment.call('routing_overworld_fixture_create', 'probe.configure_known_fixture(True,False)')
        ids = experiment.call('routing_overworld_ids', expression=ids_expression())
        record['ids'] = ids
        def gate(label):
            value = positive.current(experiment, label)
            positive.gate(value, frozen)
            if value['dimension'] != 0 or value['probe']['dimension_recovery'].get('serial') != 0:
                raise RuntimeError('Routing preflight requires initial Overworld serial zero')
            return value
        record['observation'] = fixture_view(experiment, original, positive, observations,
                                            'routing_overworld_fixture_m7', ids, gate)
        record['pixel_verified'] = record['observation']['pixel_verified']
        if not record['pixel_verified']:
            raise RuntimeError('Overworld routing fixture was not an analytic positive')
    finally:
        record['destroy_reset'] = experiment.call('routing_overworld_fixture_destroy_reset',
            destroy_fixture_source(),
            expression="{'receipts':routing_destroy,'fixture':probe.known_fixture.snapshot(),'control_reset':probe.known_fixture.control is None}")
        if (record['destroy_reset']['fixture']['entity'] is not None or
                record['destroy_reset']['fixture']['visible'] or record['destroy_reset']['control_reset'] is not True):
            raise RuntimeError('Overworld fixture was not destroyed and reset before transit')


def views(experiment, original, positive, observations, label, ids, gate, record):
    record['camera_ray_observation'] = experiment.call(label+'_center_ray', expression=
        "{'camera':probe.camera.GetPosition(),'forward':probe.camera.GetForward(),"
        "'player_position':probe.factory.CreatePos(api.GetLocalPlayerId()).GetPos(),"
        "'center_ray':probe.camera.GetWorldRayFromScreenPoint(probe.viewport[0]*.5,probe.viewport[1]*.5)}")
    record['fixture'] = fixture_view(experiment, original, positive, observations, label+'_fixture_m7', ids, gate)
    record['payload'] = []
    for mode in (1, 3):
        row = {'mode': mode}
        record['payload'].append(row)
        row['controls'] = experiment.call(label+'_all_m%d_controls'%mode, guard_source(ids)+all_source(mode))
        time.sleep(.6)
        row['state'] = gate(label+'_all_m%d_settled'%mode)
        row['readback'] = observations.capture(experiment, label+'_all_m%d'%mode, mode, original, positive)
    record['ids_after'] = experiment.call(label+'_ids_after', expression=ids_expression())
    if record['ids_after'] != ids:
        raise RuntimeError('Routing comparison changed effect identities')
    record['pixel_verified'] = (record['fixture']['pixel_verified'] and all(
        row['readback']['full_payload_comparison']['exact'] is True for row in record['payload']))


def run(experiment, original, positive, observations, gate, record):
    record.update(attempted=True, checkpoints=[], completed=False, pixel_verified=False, recovered_at=None)
    record['create'] = experiment.call('routing_target_fixture_create', 'probe.configure_known_fixture(True,False)')
    ids = experiment.call('routing_target_ids', expression=ids_expression())
    if ids['fixture'] is None or len(ids['late']) != 3:
        raise RuntimeError('Routing requires one existing fixture and three late effects')
    record['ids'] = ids
    baseline = {'name': 'baseline', 'intervention': None}
    record['checkpoints'].append(baseline)
    views(experiment, original, positive, observations, 'routing_baseline', ids, gate, baseline)
    if baseline['pixel_verified']:
        record.update(pixel_verified=True, recovered_at='baseline')
    changed = {'name': 'global_only'}
    record['checkpoints'].append(changed)
    changed['intervention'] = experiment.call('routing_set_global_only', global_source(ids), expression='routing_result')
    views(experiment, original, positive, observations, 'routing_global', ids, gate, changed)
    if changed['pixel_verified']:
        record.update(completed=True, pixel_verified=True,
                      recovered_at='baseline' if baseline['pixel_verified'] else 'global_only')
        return record
    later = {'name': 'global_then_metadata_playback'}
    record['checkpoints'].append(later)
    frame = changed['intervention']['frame']
    for attempt in range(8):
        time.sleep(.25)
        later['later_state'] = gate('routing_metadata_wait_%d'%attempt)
        if later['later_state']['probe']['render_event'] > frame:
            break
    else:
        raise RuntimeError('Routing metadata checkpoint requires a later render frame')
    later['intervention'] = experiment.call('routing_metadata_playback_reapply', metadata_source(ids), expression='routing_result')
    views(experiment, original, positive, observations, 'routing_metadata', ids, gate, later)
    if later['pixel_verified']:
        record.update(completed=True, pixel_verified=True,
                      recovered_at=record['recovered_at'] or 'global_then_metadata_playback')
        return record
    moved = {'name': 'global_metadata_then_player_position'}
    record['checkpoints'].append(moved)
    reference = gate('routing_before_position_only')
    moved['intervention'] = experiment.call('routing_player_relative_position_only', position_source(ids), expression='routing_result')
    views(experiment, original, positive, observations, 'routing_position', ids,
          moved_gate(experiment, positive, reference, ids, moved['intervention']['target']), moved)
    record.update(completed=True, pixel_verified=record['pixel_verified'] or moved['pixel_verified'],
                  recovered_at=record['recovered_at'] or ('global_metadata_then_player_position' if moved['pixel_verified'] else None))
    return record
