"""Fixed-coordinate temporal oracle for native inventory-item enchant glint."""
import hashlib
import json

import numpy as np
from PIL import Image


def _array(image,physical):
    if not isinstance(image,Image.Image):
        with Image.open(image) as source:
            image=source.convert('RGB')
    if list(image.size)!=list(physical):
        raise ValueError('Native glint oracle requires exact physical viewport')
    return np.asarray(image.convert('RGB'))


def _crop(image,rect):
    x,y,width,height=rect
    return image[y:y+height,x:x+width,:]


def _difference(first,second):
    delta=np.abs(first.astype(np.int16)-second.astype(np.int16))
    return {'changed_pixels':int(np.any(delta,axis=2).sum()),'max_channel_change':int(delta.max()),
        'channel_abs_sum':int(delta.sum())}


def _native_screen(state):
    if 'screen' in state:
        return state['screen']
    return state


def verify(normal_before,normal_after,mixed_before,mixed_after,receipt,states=None):
    """Require stable normal widgets, dynamic glint, and exact empty controls.

    Inputs are four fresh WGC frames without pixel translation/search. Caller
    captures normal_all twice, then mixed twice, separated by e.g. >=0.5 s.
    The data/composite state must stay fixed throughout each four-frame group.
    Getter/request state is additional evidence; visible differences are required.
    """
    names=('normal_before','normal_after','mixed_before','mixed_after')
    images={name:_array(value,receipt['physical']) for name,value in zip(names,
        (normal_before,normal_after,mixed_before,mixed_after))}
    mode_expected=('normal_all','normal_all','mixed','mixed')
    state_checks=[]
    if states is not None:
        if len(states)!=4:
            raise ValueError('Expected four native fixture states')
        for name,state,mode in zip(names,states,mode_expected):
            screen=_native_screen(state)
            valid=screen is not None and screen.get('mode')==mode and screen.get('actual_visible') is True
            expected_slots={slot['id']:slot for slot in receipt['slots']}
            actual_ids=[slot.get('id') for slot in screen.get('slots',[])] if screen else []
            valid=valid and len(actual_ids)==len(expected_slots) and set(actual_ids)==set(expected_slots)
            for slot in screen.get('slots',[]) if screen else []:
                definition=expected_slots.get(slot.get('id'),{})
                expected=mode=='mixed' and slot['role']=='enchanted'
                actual=slot.get('item_getter',{})
                valid=valid and slot.get('accepted') is True and bool(actual.get('isEnchanted'))==expected
                valid=valid and actual.get('itemName')==definition.get('item') and actual.get('auxValue')==definition.get('aux')
                valid=valid and slot.get('item_visible')==definition.get('item_visible') and slot.get('role')==definition.get('role')
            valid=valid and len(screen.get('slots',[]))==len(receipt['slots']) if screen else False
            state_checks.append({'frame':name,'mode_expected':mode,'exact':bool(valid)})
    results=[]
    empty_pixels=0
    empty_errors=0
    border_errors=0
    for slot in receipt['slots']:
        rect=slot['renderer_rect']
        crops={name:_crop(image,rect) for name,image in images.items()}
        normal_time=_difference(crops['normal_before'],crops['normal_after'])
        mixed_time=_difference(crops['mixed_before'],crops['mixed_after'])
        spatial0=_difference(crops['normal_before'],crops['mixed_before'])
        spatial1=_difference(crops['normal_before'],crops['mixed_after'])
        color_counts={name:int(np.any(crop!=0,axis=2).sum()) for name,crop in crops.items()}
        border_bad=sum(int(np.any(_crop(image,slot['border_patch'])!=0,axis=2).sum()) for image in images.values())
        border_errors+=border_bad
        if slot['role']=='empty':
            full_crops={name:_crop(image,slot['rect']) for name,image in images.items()}
            bad=sum(int(np.any(crop!=0,axis=2).sum()) for crop in full_crops.values())
            empty_pixels+=sum(crop.shape[0]*crop.shape[1] for crop in full_crops.values())
            empty_errors+=bad
            exact=bad==0 and border_bad==0
        elif slot['role']=='normal':
            exact=(normal_time['changed_pixels']==0 and mixed_time['changed_pixels']==0 and
                spatial0['changed_pixels']==0 and spatial1['changed_pixels']==0 and
                min(color_counts.values())>0 and border_bad==0)
        else:
            exact=(normal_time['changed_pixels']==0 and mixed_time['changed_pixels']>0 and
                spatial0['changed_pixels']>0 and spatial1['changed_pixels']>0 and
                min(color_counts.values())>0 and border_bad==0)
        results.append({'slot':slot['id'],'role':slot['role'],'source_membership':slot['source_membership'],
            'renderer_rect':rect,'normal_time':normal_time,'mixed_time':mixed_time,
            'normal_vs_mixed_before':spatial0,'normal_vs_mixed_after':spatial1,
            'nonblack_pixels':color_counts,'border_errors':border_bad,'exact':bool(exact),
            'frame_sha256':{name:hashlib.sha256(crop.tobytes()).hexdigest() for name,crop in crops.items()}})
    return {'schema':'native_inventory_item_glint_temporal_v1','all_visual_gates_passed':all(row['exact'] for row in results),
        'native_states_supplied':states is not None,'all_state_gates_passed':all(row['exact'] for row in state_checks) if states is not None else None,
        'all_passed':all(row['exact'] for row in results) and states is not None and all(row['exact'] for row in state_checks),
        'empty_control_pixels':empty_pixels,'empty_control_wrong_pixels':empty_errors,'border_wrong_pixels':border_errors,
        'slots':results,'state_checks':state_checks,'pixel_tolerance_for_stable_controls':0,
        'alignment_search':False,'route':receipt['route'],'stock_inventory_screen':False,
        'frame_gap_must_be_recorded_by_caller':True,'fresh_native_capture_receipts_required':True,
        'limits':['Temporal differences establish visible animated enchant rendering on the tested widgets',
            'Does not independently identify every glint draw material or establish arbitrary native-screen compatibility',
            '64KiB data-read correctness requires the separate exhaustive owner oracle']}


def compare_normals(first,second,receipt,mode='mixed'):
    """Exact pipeline off/on control for normal_all or mixed normal slots."""
    if mode not in ('normal_all','mixed'):
        raise ValueError('Stable off/on comparison requires normal_all or mixed')
    a,b=_array(first,receipt['physical']),_array(second,receipt['physical'])
    slots=[]
    for slot in receipt['slots']:
        if slot['role']=='enchanted' and mode!='normal_all':
            continue
        result=_difference(_crop(a,slot['rect']),_crop(b,slot['rect']))
        slots.append(dict(result,slot=slot['id'],exact=result['changed_pixels']==0))
    return {'all_exact':all(slot['exact'] for slot in slots),'slots':slots,
        'glint_phase_equal_not_assumed':True,'alignment_search':False}
