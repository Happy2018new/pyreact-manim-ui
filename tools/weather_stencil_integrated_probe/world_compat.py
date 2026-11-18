"""Finite host-only world compatibility branch for an already owned 64 KiB run.

Import and call run(experiment) after the core/UI/outline gates. This module
never launches, resizes, activates, or stops Minecraft and installs no assets.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import time

import numpy as np
from PIL import Image


HERE = Path(__file__).resolve().parent
PARTICLE = 'pmanim_scene_compat:translucent'
BACKUP = '_stencil_integrated_world_backup'


def _image(report):
    with Image.open(report['capture_file']) as source:
        return np.asarray(source.convert('RGB')).copy()


def _source_alpha(report, viewport, roi):
    count = roi[2]*roi[3]
    output_y = report['output_origin'][1]
    return _image(report)[output_y:].reshape(-1, 3)[:count, 1].reshape(roi[3], roi[2])


def _rect(points, roi, padding=0):
    projected = [point for point in points if point and 'screenX' in point
                 and 'screenY' in point and 0. <= point.get('depth', .5) <= 1.
                 and math.isfinite(point['screenX']) and math.isfinite(point['screenY'])]
    if not projected:
        raise RuntimeError('World fixture has no finite projection in front of the camera')
    x, y, width, height = roi
    left = max(x, int(math.floor(min(point['screenX'] for point in projected)))-padding)
    top = max(y, int(math.floor(min(point['screenY'] for point in projected)))-padding)
    right = min(x+width, int(math.ceil(max(point['screenX'] for point in projected)))+padding+1)
    bottom = min(y+height, int(math.ceil(max(point['screenY'] for point in projected)))+padding+1)
    if right <= left or bottom <= top:
        raise RuntimeError('World fixture projection does not overlap the full-data source ROI')
    return [left, top, right-left, bottom-top]


def _difference(before, active, after, rect, pink=False):
    x, y, width, height = rect
    regions = [image[y:y+height, x:x+width].astype(np.int16)
               for image in (before, active, after)]
    stable = np.all(regions[0] == regions[2], axis=2)
    changed = np.any(regions[1] != regions[0], axis=2)
    confirmed = stable & changed
    pink_pixels = confirmed & (regions[1][:, :, 0] > regions[1][:, :, 1]+8)
    pink_pixels &= regions[1][:, :, 2] > regions[1][:, :, 1]+4
    result = {'rect': rect, 'pixels': width*height,
              'off_before_after_drift_pixels': int(np.count_nonzero(~stable)),
              'stable_off_changed_on_pixels': int(np.count_nonzero(confirmed)),
              'pink_stable_off_changed_on_pixels': int(np.count_nonzero(pink_pixels)),
              'separate_frame_visibility_observation': True,
              'same_frame_original_rgb_truth': False}
    if result['stable_off_changed_on_pixels'] < 8:
        raise RuntimeError('World fixture visible off/on/off gate failed: '+repr(result))
    if pink and result['pink_stable_off_changed_on_pixels'] < 4:
        raise RuntimeError('Paused translucent particle lacks a localized pink visual positive: '+repr(result))
    return result


def _plans(origin, direction=1):
    if direction not in (-1, 1):
        raise ValueError('World plan direction must be cardinal plus or minus Z')
    spec = importlib.util.spec_from_file_location(
        'integrated_world_scene_plan', HERE.parent/'scene_codec_compat_probe/scene_server.py')
    scene = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scene)
    plans = {}
    for case in ('solid', 'water_glass'):
        # The shipped helper faces +Z; align its pure plan with measured forward.
        plan = {(origin[0]+x, origin[1]+y, origin[2]+direction*z): {'name': 'minecraft:air', 'aux': 0}
                for x in range(-4, 5) for y in range(-1, 4) for z in range(1, 9)}
        for (x, y, z), block in scene.block_plan((0, 0, 0), case):
            plan[(origin[0]+x, origin[1]+y, origin[2]+direction*z)] = block
        plans[case] = sorted(plan.items())
    return plans


def run(experiment):
    """Use the hydrated integrated Experiment; preserve all failure evidence."""
    evidence = Path(experiment.evidence)
    result_path = evidence/'world-compat.json'
    if result_path.exists():
        raise RuntimeError('Use fresh world compatibility evidence; do not overwrite a previous attempt')
    result = {'schema': 'stencil_integrated_world_compat_v1', 'complete': False,
              'receipts': {}, 'captures': [], 'visibility': {}, 'cleanup': {},
              'runtime_file_writes': False, 'game_lifecycle_operations': False,
              'original_natural_rgb_preservation_claimed': False,
              'final_display': 'known/UI/outline fixtures hidden; source restored; visible data consumer',
              'world_controls': 'owned test world remains clear at fixed time6000 with deterministic rules'}

    def save():
        result_path.write_text(json.dumps(result, indent=2), encoding='utf-8')

    def receipt(label, value):
        result['receipts'][label] = value
        save()
        return value

    frozen = None

    def check_state(state):
        if (state['logical_bytes'] != 65536 or state['viewport'] != [720, 1080]
                or state['source_roi'] != [8, 128, 512, 512]
                or not state.get('pipeline_ready') or state.get('measurement') is not None
                or any(enabled for _, enabled in state['native_post_flags'])):
            raise RuntimeError('World compatibility requires idle linked integrated64 with isolated native post')
        names = ['stencil_integrated_copy', 'stencil_integrated_restore', 'stencil_integrated_consumer']
        if [name for name in state['actual_post_order'] if name in names] != names:
            raise RuntimeError('Integrated chain order changed during world compatibility')
        if frozen is not None and any(state[key] != frozen[key]
                                      for key in ('identity', 'active_pages', 'native_attempt_count')):
            raise RuntimeError('World compatibility changed frozen payload or native geometry allocations')

    def capture(label, mode, configuration='all'):
        report = experiment.capture('world_'+label, mode, configuration=configuration,
                                    fixture=False, verify_pixels=mode != 0,
                                    expected=mode != 0, output_y=650 if mode != 4 else 128)
        check_state(report['state'])
        result['captures'].append({'label': report['label'], 'mode': mode,
                                   'capture_file': report['capture_file'],
                                   'exact': report.get('exact'),
                                   'alpha_not255_pixels': report.get('alpha_not255_pixels'),
                                   'encoded_restored_alpha_mismatch_pixels':
                                       report.get('encoded_restored_alpha_mismatch_pixels')})
        save()
        return report

    def prepare(case, plans, origin):
        code = "import stencil_large.scene_fixtures as scene\n"
        code += "planned=%r\n" % (plans[case],)
        code += "blocks=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\n"
        code += "if not hasattr(scene,%r):\n" % BACKUP
        code += "    before=[(tuple(pos),blocks.GetBlockNew(tuple(pos),0)) for pos,desired in planned]\n"
        code += "    if any(value is None for pos,value in before): raise RuntimeError('World fixture requires loaded terrain')\n"
        code += "    setattr(scene,%r,before)\n" % BACKUP
        code += "original_plan=scene.block_plan\ntry:\n"
        code += "    scene.block_plan=lambda origin,case: planned\n"
        code += "    receipt=scene.prepare(api,api.GetLevelId(),%r,%r,dimension=0)\n" % (tuple(origin), case)
        code += "finally:\n    scene.block_plan=original_plan\n"
        code += "receipt['coordinate_transform']=%r\n_result=json.dumps(receipt)" % (
            'local +Z multiplied by%d; fixed camera unchanged' % direction,)
        return receipt('prepare_'+case+'_'+str(len(result['receipts'])), experiment.server('world_prepare_'+case+'_'+str(len(result['receipts'])), code))

    primary_error = None
    branch_started, scene_touched = False, False
    try:
        state = experiment.call('world_initial')
        check_state(state)
        frozen = {key: state[key] for key in ('identity', 'active_pages', 'native_attempt_count')}
        result['frozen'] = frozen
        project = Path(experiment.args.project)
        required = {'scene': project/'behavior_pack/stencil_large/scene_fixtures.py',
                    'particle': project/'resource_pack/particles/pmanim_scene_compat_translucent.particle.json'}
        result['installed_assets'] = {name: {'path': str(path.resolve()),
                                             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                                      for name, path in required.items()}
        particle_asset = json.loads(required['particle'].read_text(encoding='utf-8-sig'))['particle_effect']
        if (particle_asset['description']['identifier'] != PARTICLE
                or particle_asset['description']['basic_render_parameters']['material'] != 'particles_blend'
                or particle_asset['components']['minecraft:particle_appearance_tinting']['color'][3] >= 1):
            raise RuntimeError('Expected copied native translucent particle asset')
        camera = receipt('camera_before', experiment.call('world_camera', expression=
            "{'position':probe.camera.GetPosition(),'forward':probe.camera.GetForward(),"
            "'fov':probe.camera.GetFov(),'origin':probe.origin}"))
        position, forward = camera['position'], camera['forward']
        if abs(forward[2]) < .8 or abs(forward[0]) > .2:
            raise RuntimeError('World helper expects a preserved near-cardinal Z camera; no automatic camera move')
        direction = 1 if forward[2] > 0 else -1
        origin = [int(math.floor(value)) for value in position]
        plans = _plans(origin, direction)
        result['scene_origin'] = origin
        result['plan_direction'] = direction
        result['scene_plan_blocks'] = {case: len(plan) for case, plan in plans.items()}
        save()
        # Independent compatibility fixtures are hidden, with their initial states retained.
        receipt('other_fixture_state', {'known': state.get('known_fixture'),
                                        'ui': state.get('ui_clip'), 'outline': state.get('outline')})
        branch_started = True
        experiment.call('world_other_fixtures_off',
            "probe.configure_known_fixture(False)\n"
            "if probe.ui_clip is not None and probe.ui_clip.screen is not None: probe.configure_ui(False)\n"
            "if probe.outline is not None and probe.outline.entity is not None: probe.configure_outline(False)")
        experiment.weather('world_clear_weather', False)
        scene_touched = True
        prepare('solid', plans, origin)
        time.sleep(1.)
        solid_before = capture('solid_before', 0, 'off')
        prepare('water_glass', plans, origin)
        time.sleep(1.)
        point_groups = {
            'water': [(origin[0]+x, origin[1], origin[2]+direction*z) for x in (-2., 0., 3.) for z in (2., 4., 6.)],
            'glass': [(origin[0]+x, origin[1]+y, origin[2]+direction*4.5) for x in (-2., 0., 3.) for y in (0., 1.5, 3.)]}
        projected = receipt('world_projection', experiment.call('world_projection',
            "groups=%r" % point_groups, expression=
            "dict((name,[probe.camera.WorldToScreenPoint(*point) for point in points]) for name,points in groups.items())"))
        regions = {name: _rect(points, experiment.roi, 4) for name, points in projected.items()}
        result['visibility_rects'] = regions
        water_visible = capture('water_glass_visible', 0, 'off')
        for mode in (1, 2, 3, 5, 4):
            capture('water_glass_m%d' % mode, mode)
        prepare('solid', plans, origin)
        time.sleep(1.)
        solid_after = capture('solid_after', 0, 'off')
        result['visibility']['water_glass'] = {
            name: _difference(_image(solid_before), _image(water_visible), _image(solid_after), rect)
            for name, rect in regions.items()}
        save()

        # Pause preserves real rendered particles, enabling a bounded Hide/Show control.
        emitter = (position[0]+direction*.5, position[1]-1., position[2]+direction*3.5)
        particle_points = [(emitter[0]+x, emitter[1]+y, emitter[2]+z)
                           for x in (-.5, 0., .5) for y in (0., 1.4, 2.8) for z in (-.4, 0., .4)]
        projection = receipt('particle_projection', experiment.call('world_particle_projection',
            "points=%r" % particle_points, expression="[probe.camera.WorldToScreenPoint(*point) for point in points]"))
        particle_rect = _rect(projection, experiment.roi, 8)
        created = receipt('particle_created', experiment.call('world_particle_create',
            "if getattr(probe,'_world_compat_particle',0): raise RuntimeError('Previous world emitter still owned')\n"
            "probe._world_compat_particles=probe.factory.CreateParticleSystem(None)\n"
            "probe._world_compat_particle=probe._world_compat_particles.Create(%r,%r,(0.,0.,0.))\n"
            "if not probe._world_compat_particle: raise RuntimeError('Native translucent particle creation failed')" % (PARTICLE, emitter),
            expression="{'id':probe._world_compat_particle,'position':probe._world_compat_particles.GetPos(probe._world_compat_particle)}"))
        time.sleep(.8)
        paused = receipt('particle_paused_hidden', experiment.call('world_particle_pause_hide',
            "particle=probe._world_compat_particle\nparticles=probe._world_compat_particles\n"
            "if not particles.Pause(particle) or not particles.Hide(particle): raise RuntimeError('Particle pause/hide rejected')",
            expression="{'exists':particles.Exist(particle),'paused':particles.IsPausing(particle),'hidden':particles.IsHiding(particle)}"))
        if not all(paused.values()):
            raise RuntimeError('Native particle pause/hide getters did not confirm the control')
        particle_before = capture('particle_hidden_before', 0)
        alpha_before = capture('particle_hidden_raw_before', 3)
        experiment.call('world_particle_show',
            "if not probe._world_compat_particles.Show(probe._world_compat_particle): raise RuntimeError('Particle show rejected')")
        particle_on = capture('particle_visible', 0)
        particle_raw = None
        for mode in (1, 2, 3, 5, 4):
            report = capture('particle_m%d' % mode, mode)
            if mode == 3:
                particle_raw = report
        experiment.call('world_particle_hide_return',
            "if not probe._world_compat_particles.Hide(probe._world_compat_particle): raise RuntimeError('Particle return hide rejected')")
        particle_after = capture('particle_hidden_after', 0)
        alpha_after = capture('particle_hidden_raw_after', 3)
        result['visibility']['particle'] = _difference(
            _image(particle_before), _image(particle_on), _image(particle_after), particle_rect, pink=True)
        before_a, on_a, after_a = [_source_alpha(report, experiment.viewport, experiment.roi)
                                  for report in (alpha_before, particle_raw, alpha_after)]
        x, y, width, height = particle_rect
        x, y = x-experiment.roi[0], y-experiment.roi[1]
        arrays = [array[y:y+height, x:x+width] for array in (before_a, on_a, after_a)]
        alpha_witness = (arrays[0] == arrays[2]) & (arrays[1] != arrays[0]) & (arrays[1] < 255)
        result['visibility']['particle'].update(
            native_emitter=created, paused_cloud=True, tint_alpha=.35,
            particle_alpha_changed_stable_off_pixels=int(np.count_nonzero(alpha_witness)),
            non255_alpha_on_pixels=int(np.count_nonzero(arrays[1] < 255)))
        save()
        if not np.any(alpha_witness):
            raise RuntimeError('Particle needs localized non255 alpha that changes under frozen Hide/Show control')
        result['complete'] = True
    except Exception as error:
        primary_error = repr(error)
        result['failure'] = primary_error
        raise
    finally:
        # Cleanup is bounded to the emitter and the recorded test-world positions.
        cleanup_errors = []
        try:
            if branch_started:
                result['cleanup']['particle'] = experiment.call('world_particle_cleanup',
                "particle=getattr(probe,'_world_compat_particle',0)\nremoved=True\n"
                "if particle:\n"
                "    removed=probe._world_compat_particles.Remove(particle)\n"
                "    if probe._world_compat_particles.Exist(particle): raise RuntimeError('Owned world particle survived removal')\n"
                "    probe._world_compat_particle=0",
                expression="{'id':particle,'remove_accepted':removed,'remaining':False}")
        except Exception as error:
            cleanup_errors.append('particle: '+repr(error))
        try:
            if scene_touched:
                result['cleanup']['blocks'] = experiment.server('world_restore_blocks',
                "import stencil_large.scene_fixtures as scene\n"
                "before=getattr(scene,%r,[])\n" % BACKUP +
                "blocks=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\n"
                "restored=[]\nfor pos,block in reversed(before):\n"
                "    blocks.SetBlockNew(tuple(pos),block,0,0,False,False)\n"
                "    after=blocks.GetBlockNew(tuple(pos),0)\n"
                "    restored.append({'pos':pos,'matches':after is not None and after.get('name')==block.get('name') and after.get('aux',0)==block.get('aux',0)})\n"
                "if not all(item['matches'] for item in restored): raise RuntimeError('World block restoration did not match backup')\n"
                "if hasattr(scene,%r): delattr(scene,%r)\n" % (BACKUP, BACKUP) +
                "_result=json.dumps({'restored_blocks':len(restored),'all_exact':True})")
        except Exception as error:
            cleanup_errors.append('blocks: '+repr(error))
        try:
            if branch_started:
                end = experiment.call('world_final_state', "probe.configure('all')\nprobe.inspect(4)")
                check_state(end)
                after_camera = experiment.call('world_camera_after', expression=
                    "{'position':probe.camera.GetPosition(),'forward':probe.camera.GetForward()}")
                result['camera_after'] = after_camera
                if 'camera_before' in result['receipts']:
                    before_camera = result['receipts']['camera_before']
                    if any(after_camera[key] != before_camera[key] for key in ('position', 'forward')):
                        raise RuntimeError('Fixed camera changed during world compatibility')
        except Exception as error:
            cleanup_errors.append('final state: '+repr(error))
        result['cleanup']['errors'] = cleanup_errors
        result['complete'] = result['complete'] and not cleanup_errors
        save()
        if cleanup_errors and primary_error is None:
            raise RuntimeError('World compatibility cleanup needs attention: '+repr(cleanup_errors))
    return result
