"""Fixed-coordinate ordinary FrameAni witnesses; never locate sprites from pixels."""
import numpy as np


def _rgb(frame):
    array = np.asarray(frame)
    if array.dtype!=np.uint8 or array.ndim!=3 or array.shape[2]<3:
        raise ValueError('Expected uint8 native RGB or RGBA captures')
    return array[:,:,:3].astype(np.int16)


def compare_snapshots(off_before,on,off_after):
    snapshots = (off_before,on,off_after)
    errors = []
    if [row.get('visible') for row in snapshots]!=[False,True,False]:
        errors.append('ordinary effect must be off/on/off')
    for key in ('effects','route','tint','layer','location','position','scale','expected_bounds',
                'predeclared_patches','expected_plane_world_corners','projected_plane_corners','camera'):
        if any(row.get(key)!=snapshots[0].get(key) for row in snapshots[1:]):
            errors.append('frozen parameter changed: '+key)
    if any(not row.get('camera_matches_initial') for row in snapshots):
        errors.append('camera changed from fixture creation')
    if len(on.get('effects',{}))!=4 or on.get('route') not in on.get('effects',{}):
        errors.append('four created native routes and one selected route required')
    return {'pass':not errors,'errors':errors,'native_quad_extent_claimed':False}


def compare_visible(off_before,on,off_after,fixture,tolerance=3,minimum_pixels=24):
    before,active,after = map(_rgb,(off_before,on,off_after))
    if before.shape!=active.shape or before.shape!=after.shape:
        raise ValueError('Use identical native viewport dimensions')
    tint = np.asarray(fixture['tint'],dtype=np.float64)
    additive = fixture['route'].endswith('_add')
    rows,errors = [],[]
    for patch in fixture['predeclared_patches']:
        x,y,width,height = patch['rect']
        if x<0 or y<0 or x+width>active.shape[1] or y+height>active.shape[0]:
            raise ValueError('Predeclared native patch is outside capture')
        baseline,actual,replay = (value[y:y+height,x:x+width] for value in (before,active,after))
        source = np.asarray(patch['rgba'],dtype=np.float64)
        alpha = source[3]/255.*tint[3]
        wanted = np.clip(np.floor(source[:3]*tint[:3]*alpha+
            baseline*(1. if additive else 1.-alpha)+.5),0,255).astype(np.int16)
        bad = np.max(np.abs(actual-wanted),axis=2)>tolerance
        drift = np.max(np.abs(baseline-replay),axis=2)>tolerance
        changed = np.max(np.abs(actual-baseline),axis=2)>12
        transparent = source[3]==0
        count = int(np.count_nonzero(changed))
        row = {'name':patch['name'],'rect':patch['rect'],'pixels':width*height,
            'wrong_pixels':int(np.count_nonzero(bad)),'off_replay_changed_pixels':int(np.count_nonzero(drift)),
            'new_visible_pixels':count,'transparent_negative':bool(transparent)}
        rows.append(row)
        if np.any(bad) or np.any(drift):
            errors.append('fixed expected pixels or off replay failed: '+patch['name'])
        if not transparent and count<minimum_pixels:
            errors.append('ordinary native positive missing: '+patch['name'])
        if transparent and count:
            errors.append('transparent texture quadrant changed the scene')
    return {'kind':'ordinary_native_frameani_pixels_v1','pass':not errors,'errors':errors,
        'patches':rows,'compared_pixels':sum(row['pixels'] for row in rows),
        'tolerance':tolerance,'alignment_search':False,'color_search':False,
        'native_scale_convention_requires_positive_gate':True}


def compare_to_native(native_on,carrier_on,fixture,tolerance=2):
    native,carrier = map(_rgb,(native_on,carrier_on))
    if native.shape!=carrier.shape:
        raise ValueError('Native and carrier packs require identical viewports')
    rows = []
    for patch in fixture['predeclared_patches']:
        x,y,width,height = patch['rect']
        bad = np.max(np.abs(native[y:y+height,x:x+width]-carrier[y:y+height,x:x+width]),axis=2)>tolerance
        rows.append({'name':patch['name'],'pixels':width*height,'wrong_pixels':int(np.count_nonzero(bad))})
    return {'pass':not any(row['wrong_pixels'] for row in rows),'patches':rows,
        'compared_pixels':sum(row['pixels'] for row in rows),'tolerance':tolerance,
        'requires_successful_stock_native_positive_control':True,'separate_frame_background_must_match':True}
