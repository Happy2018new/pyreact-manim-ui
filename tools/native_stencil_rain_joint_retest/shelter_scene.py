"""Predeclared native roof/backdrop; no shaders or acceptance masks change."""
import hashlib
import json
import math
import time

import numpy as np


PROTECTED_RECT = [220, 74, 500, 540]
EXPOSED_RECT = [16, 280, 144, 160]


def block_plan():
    blocks = {(x, -50, z): 'minecraft:glass'
              for x in range(-5, 3) for z in range(-5, 5)}
    blocks.update({(x, y, 4): 'minecraft:stone'
                   for x in range(-5, 2) for y in range(-59, -49)})
    return [(position, blocks[position]) for position in sorted(blocks)]


def ray_endpoint(ray):
    origin, direction = ray['origin'], ray['direction']
    if direction[2] <= 0:
        raise ValueError('Sheltered view rays must point toward the declared backdrop')
    wall_t = (4. - origin[2]) / direction[2]
    floor_t = (-59. - origin[1]) / direction[1] if direction[1] < 0 else float('inf')
    distance = min(wall_t, floor_t)
    if distance <= 0:
        raise ValueError('Shelter ray endpoint must lie in front of the camera')
    endpoint = [origin[i] + direction[i] * distance for i in range(3)]
    if not (-4.75 <= endpoint[0] <= 2.75 and -4.75 <= endpoint[2] <= 4.75):
        raise ValueError('Protected view segment leaves the roof footprint margin')
    if max(origin[1], endpoint[1]) > -52.:
        raise ValueError('Protected rays need at least two blocks of roof clearance')
    if wall_t <= floor_t and not (-5. <= endpoint[0] <= 2. and -59. <= endpoint[1] <= -49.):
        raise ValueError('Protected background ray misses the declared opaque backdrop')
    return {'endpoint': endpoint, 'surface': 'backdrop' if wall_t <= floor_t else 'floor',
            'roof_vertical_clearance': -50. - max(origin[1], endpoint[1])}


class ShelterScene:
    def __init__(self, experiment, joint):
        self.experiment, self.joint = experiment, joint
        self.backup = None
        self.receipt = {'schema': 'predeclared_sheltered_native_rain_scene_v1',
                        'protected_screen_rectangle': PROTECTED_RECT,
                        'exposed_source_rectangle': EXPOSED_RECT,
                        'minimum_exposed_alpha_non255': 24,
                        'original_masks_and_oracles_unchanged': True,
                        'shader_changes': False, 'runtime_file_writes': False,
                        'installed': False, 'cleanup_failure': None}

    def install(self):
        if self.backup is not None:
            raise RuntimeError('Shelter must be installed once in a fresh owned session')
        exp = self.experiment
        x, y, width, height = PROTECTED_RECT
        points = [(px, py) for px in (x, x + width * .5, x + width)
                  for py in (y, y + height * .5, y + height)]
        rays = exp.call('rain_shelter_protected_rays', expression=
            '[probe.camera.GetWorldRayFromScreenPoint(*point) for point in %r]' % points)
        endpoints = [ray_endpoint(ray) for ray in rays]
        # Bound the original geometry window before any shelter capture exists.
        bounds = exp.state['outline']['projected_bounds']
        margin = max(12, int(math.ceil(max(bounds[2] - bounds[0], bounds[3] - bounds[1]) * .25)))
        outline = [max(0, math.floor(bounds[0]) - margin), max(0, math.floor(bounds[1]) - margin),
                   min(720, math.ceil(bounds[2]) + margin), min(1080, math.ceil(bounds[3]) + margin)]
        if not (x <= outline[0] and y <= outline[1] and outline[2] <= x + width and outline[3] <= y + height):
            raise RuntimeError('Original outline window is outside the protected predeclared rectangle')
        foot = exp.state['outline']['requested_position']
        px, _, pz = foot
        receiver = [(px - 1.25, -59., pz - 1.25), (px + 1.25, -59., pz - 1.25),
                    (px + 1.25, -59., pz + 1.25), (px - 1.25, -59., pz + 1.25)]
        control = [(px - .35, -59., pz + 1.7), (px + .35, -59., pz + 1.7),
                   (px + .35, -59., pz + 2.2), (px - .35, -59., pz + 2.2)]
        projected = self.joint.hover._polygon(exp, 'rain_shelter_original_regions', receiver + control)
        shadow_plan = self.joint.hover.verify.make_plan(exp.viewport, exp.roi, projected[:4], bounds, projected[4:])
        receiver_mask, body_mask, control_mask, _, _ = self.joint.hover.verify._masks(shadow_plan)
        target = exp.call('rain_shelter_current_target', expression=
            "{'eye':probe.camera.GetPosition(),'pick':probe.camera.PickFacing()}")
        if target['pick'].get('type') != 'Block':
            raise RuntimeError('Shelter coverage requires the unchanged real target selection')
        position = tuple(target['pick'][key] for key in ('x', 'y', 'z'))
        ui_receipt = json.loads((exp.args.project / 'ui_clip_fixture_receipt.json').read_text(encoding='utf-8'))
        target_plan = self.joint.target_plan(exp, position, target['eye'], ui_receipt)
        masks = {'shadow': receiver_mask | body_mask | control_mask,
                 'outline': self.joint.outline_verify._ORIGINAL._rectangle((1080, 720), outline),
                 'highlight': self.joint.target_mask(target_plan)}
        protected = np.zeros((1080, 720), dtype=bool)
        protected[y:y + height, x:x + width] = True
        coverage = {name: {'pixels': int(mask.sum()), 'outside_protected': int((mask & ~protected).sum())}
                    for name, mask in masks.items()}
        if any(row['outside_protected'] for row in coverage.values()):
            raise RuntimeError('An original role acceptance pixel lies outside the shelter view rectangle')
        ex, ey, ew, eh = EXPOSED_RECT
        if any(mask[ey:ey + eh, ex:ex + ew].any() for mask in masks.values()):
            raise RuntimeError('Exposed weather strip must not overlap any original role acceptance region')
        open_points = [(px, py) for px in (ex, ex + ew) for py in (ey, ey + eh)]
        open_rays = exp.call('rain_shelter_exposed_rays', expression=
            '[probe.camera.GetWorldRayFromScreenPoint(*point) for point in %r]' % open_points)
        openings = []
        for ray in open_rays:
            origin, direction = ray['origin'], ray['direction']
            distance = (4. - origin[2]) / direction[2]
            point = [origin[i] + direction[i] * distance for i in range(3)]
            if point[0] <= 2.1:
                raise RuntimeError('Declared exposed strip is not outside the backdrop opening')
            openings.append(point)
        plan = block_plan()
        self.receipt.update(block_count=len(plan), blocks=plan, ray_samples=points,
                            ray_endpoints=endpoints, outline_window=outline,
                            exposed_backdrop_intersections=openings, original_region_coverage=coverage,
                            independently_recreated_shadow_plan_sha256=shadow_plan['plan_sha256'])
        encoded = json.dumps(self.receipt, sort_keys=True, separators=(',', ':')).encode('ascii')
        self.receipt['pre_capture_plan_sha256'] = hashlib.sha256(encoded).hexdigest()
        self.backup = self.joint.attached._backup(exp, 'rain_shelter_backup', [pos for pos, name in plan])
        exp.server('rain_shelter_place',
            "blocks=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\n"
            "accepted=[blocks.SetBlockNew(tuple(pos),{'name':name,'aux':0},0,0,True,False) for pos,name in %r]\n"
            "_result=json.dumps({'accepted':accepted,'count':len(accepted)})" % plan)
        time.sleep(1.)
        readback = exp.server('rain_shelter_readback',
            "blocks=api.GetEngineCompFactory().CreateBlockInfo(api.GetLevelId())\n"
            "rows=[{'pos':pos,'expected':name,'after':blocks.GetBlockNew(tuple(pos),0)} for pos,name in %r]\n"
            "_result=json.dumps({'rows':rows,'all_exact':all(row['after'] is not None and row['after'].get('name')==row['expected'] and row['after'].get('aux',0)==0 for row in rows)})" % plan)
        self.receipt['placement_readback'] = readback
        if not readback['all_exact']:
            raise RuntimeError('Native shelter block readback must be exact')
        self.receipt['installed'] = True

    def cleanup(self):
        if self.backup is None:
            return self.receipt
        try:
            restored = self.joint.restore_blocks(self.experiment, 'rain_shelter_restore', self.backup)
            self.receipt['restoration'] = restored
            if not restored['all_exact']:
                raise RuntimeError('Shelter original blocks did not all restore exactly')
        except Exception as error:
            self.receipt['cleanup_failure'] = repr(error)
        return self.receipt
