"""Host-only fixed-target face highlight witness; no Minecraft calls on import."""
import importlib.util
from pathlib import Path

import numpy as np


_SPEC = importlib.util.spec_from_file_location('highlight_shared_full_payload_verifier', Path(__file__).with_name('verify.py'))
shared = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(shared)


def _erode(mask, radius=3):
    """Exclude at least three screen pixels around every original face edge."""
    height,width=mask.shape
    padded=np.pad(mask,radius,mode='constant',constant_values=False)
    result=mask.copy()
    for dy in range(2*radius+1):
        for dx in range(2*radius+1):
            result &= padded[dy:dy+height,dx:dx+width]
    return result


def _masks(plan):
    width, height = plan['viewport']
    polygon = np.asarray(plan['face_polygon'], dtype=float)
    center = polygon.mean(axis=0)
    # Exclude wireframe and raster edges geometrically before observing pixels.
    inset = (center + (polygon - center) * .84).tolist()
    face = shared._polygon((height, width), inset) & _erode(shared._polygon((height,width),polygon.tolist()))
    control = shared._polygon((height, width), plan['control_polygon']) & ~face
    face[plan['output_y']:] = False
    control[plan['output_y']:] = False
    inside = np.zeros_like(face)
    x,y,w,h = plan['roi']
    inside[y:y+h,x:x+w] = True
    boundary = np.zeros_like(face)
    boundary[y:y+h,max(0,x-2):x+3] = True
    boundary[y:y+h,x+w-2:min(width,x+w+3)] = True
    boundary[max(0,y-2):y+3,x:x+w] = True
    boundary[y+h-2:min(height,y+h+3),x:x+w] = True
    return face,control,inside,boundary


def make_plan(viewport,roi,face_polygon,control_polygon,target,output_y=650):
    """Record projected known block face and separate guard before any capture."""
    if target.get('type') != 'Block' or any(key not in target for key in ('x','y','z','face')):
        raise ValueError('Need authenticated native PickFacing Block xyz/face target')
    plan = {'schema':'native_target_highlight_face_plan_v1','viewport':list(viewport),'roi':list(roi),
            'face_polygon':face_polygon,'control_polygon':control_polygon,'target':dict(target),
            'output_y':output_y,'pixel_derived_masks':False,'alignment_search':False,
            'face_inset_fraction':.08,'minimum_pixels_each_side':24,'pixel_tolerance':2}
    plan['minimum_face_edge_exclusion_pixels']=3
    face,control,inside,_ = _masks(plan)
    counts = {'face':int(face.sum()),'guard':int(control.sum()),
              'face_inside_roi':int((face&inside).sum()),'face_outside_roi':int((face&~inside).sum())}
    if min(counts.values()) < 64:
        raise ValueError('Predeclared face interior must cross source ROI with a separate guard')
    plan['mask_pixels'] = counts
    plan['plan_sha256'] = shared._sha(plan)
    return plan


def compare_snapshots(states,plan):
    shared._validate_plan(plan)
    if len(states) != 3:
        raise ValueError('Need target highlighter off/on/off receipts')
    errors = []
    if [state.get('highlight_requested') for state in states] != [False,True,False]:
        errors.append('native highlight requested sequence must be off/on/off')
    target_keys = ('type','x','y','z','face')
    for state in states:
        pick = state.get('pick',{})
        if any(pick.get(key) != plan['target'].get(key) for key in target_keys):
            errors.append('native target block/face changed or is not Block')
    for key in ('camera','block_readback'):
        if states[0].get(key) is None or any(state.get(key) != states[0].get(key) for state in states[1:]):
            errors.append('native '+key+' missing or changed')
    return {'pass':not errors,'errors':errors,'setter_return_value_is_proof':False,
            'material_variant_inferred_from_toggle':False}


def compare_visible(off_before,on,off_after,plan):
    shared._validate_plan(plan)
    before,active,after = [shared._rgb(frame,plan) for frame in (off_before,on,off_after)]
    face,control,inside,boundary = _masks(plan)
    delta = np.minimum(np.max(np.abs(active-before),axis=2),np.max(np.abs(active-after),axis=2))
    positive = face & (delta >= 8)
    counts = {'inside_roi':int((positive&inside).sum()),'outside_roi':int((positive&~inside).sum()),
              'at_roi_boundary':int((positive&boundary).sum()),'total':int(positive.sum())}
    stability = {'face_off_replay':shared._change(before,after,face,4),
                 'guard_off_replay':shared._change(before,after,control,4),
                 'guard_on':shared._change(before,active,control,4)}
    errors = [key+' changed beyond native target witness' for key,row in stability.items()
              if row['changed_fraction'] > .01]
    if min(counts['inside_roi'],counts['outside_roi']) < 24 or counts['at_roi_boundary'] < 2:
        errors.append('visible native face-interior highlight must cross source ROI')
    return {'schema':'native_target_highlight_visible_v1','pass':not errors,'errors':errors,
            'plan_sha256':plan['plan_sha256'],'face_changed_pixels':counts,'stability':stability,
            'wireframe_excluded':True,'native_material_variant_proven':False}


def compare_coexistence(native_triplet,active_triplet,plan,payload_reports,actual_payload):
    native = compare_visible(*native_triplet,plan)
    active = compare_visible(*active_triplet,plan)
    face,control,_,_ = _masks(plan)
    region = face|control
    visual = [shared._change(shared._rgb(first,plan),shared._rgb(second,plan),region,2)
              for first,second in zip(native_triplet,active_triplet)]
    payload = shared._payload_gate(payload_reports,plan['roi'])
    simultaneous = shared._diagnostic_visuals(native_triplet[1],payload_reports,plan,region,actual_payload)
    errors = []
    if not native['pass'] or not active['pass']:
        errors.append('native and carrier-active face highlight positive controls must pass')
    if any(row['changed_pixels'] for row in visual):
        errors.append('native face highlight/guard changed beyond2channel restoration tolerance')
    if not payload['pass']:
        errors.extend(payload['errors'])
    if len(simultaneous)<2 or any(not row['pass'] for row in simultaneous):
        errors.append('complete payload decoding and native highlight must pass in same diagnostic PNGs')
    return {'schema':'native_target_highlight_64kib_coexistence_v1','pass':not errors,'errors':errors,
            'native':native,'active':active,'whole_regions':visual,'payload':payload,
            'same_frame_highlight_and_payload_screenshots':simultaneous,
            'visual_channel_tolerance':2,'pixel_derived_masks':False}
