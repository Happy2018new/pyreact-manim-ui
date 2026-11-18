"""Host-only vectorized integer oracle, native pixels and declared border guard."""
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

SCREEN=(1080,1440)
SENTINEL=np.array([8,16,32,255],dtype=np.uint8)


def expected_bytes(seed,generation,indices):
    index=np.asarray(indices,dtype=np.uint64)
    mask=np.uint64(0xffffffff)
    value=np.uint64(seed^((generation*0x9e3779b9)&0xffffffff))^((index*np.uint64(0x85ebca6b))&mask)
    value^=value>>np.uint64(16)
    value=(value*np.uint64(0x7feb352d))&mask
    value^=value>>np.uint64(15)
    value=(value*np.uint64(0x846ca68b))&mask
    return ((value^(value>>np.uint64(16)))&np.uint64(255)).astype(np.uint8)


def addresses(state,mode):
    n=state['logical_payload_bytes']
    address=np.arange(n,dtype=np.uint64)
    if mode:
        address=(131*address+29)%n
    if mode==2:
        first=expected_bytes(state['seed'],state['generation'],address).astype(np.uint64)
        address=(address+257*first+113)%n
    return address


def payload_identity(state):
    return {key:state[key] for key in ('source_bundle_sha256','seed','generation','dataset_serial',
        'logical_payload_bytes','allocated_payload_bytes_current','allocated_payload_bytes_all_datasets',
        'allocated_records_all_datasets','geometry_build_serial','native_attempt_serial')}|{
        'pages':[{key:p[key] for key in ('dataset','page','record_base','record_count','payload_byte_base',
            'payload_byte_count','name','seed','generation','upload_serial','payload_fingerprint','entity')}
            for p in state['pages']]}


def validate(state,image_size):
    if state.get('schema')!='scene_codec_large_probe_v1' or tuple(image_size)!=SCREEN or state.get('screen_size')!=list(SCREEN):
        raise ValueError('Require a native1080x1440 capture and matching large codec receipt')
    n=state['logical_payload_bytes']
    if n not in (262144,524288) or not state['all_current_pages_loaded'] or not state['pipeline_ready']:
        raise ValueError('Require a complete256/512KiB resident payload and ready pipeline')
    if state['diagnostic_layout']!=[8,128,1024,1] or state['guard_rect_native']!=[0,128,1080,1408]:
        raise ValueError('Unexpected native diagnostic or guard layout')
    plan=state['payload_plan']
    expected_rows=497 if n==262144 else 993
    if plan['roi']!=[8,128,704,expected_rows] or plan['records']!=704*expected_rows:
        raise ValueError('Unexpected controlled block-contiguous source ROI')
    current=[p for p in state['pages'] if p['dataset']==state['dataset_serial']]
    expected_count=(plan['records']+65535)//65536
    if len(current)!=expected_count or sum(p['record_count'] for p in current)!=plan['records']:
        raise ValueError('Missing source geometry page')
    for index,p in enumerate(current):
        if (p['page']!=index or p['record_base']!=index*65536 or p['record_count']%32 or
                p['payload_byte_base']!=p['record_base']*3//4 or
                p['payload_byte_count']!=p['record_count']*3//4 or not p['loaded'] or not p['name'] or
                p['seed']!=state['seed'] or p['generation']!=state['generation']):
            raise ValueError('Page data, global record base, block alignment or identity is invalid')
    return plan


def verify_image(state,image,kind):
    plan=validate(state,image.size)
    if state.get('profile')!=kind:
        raise ValueError('Receipt profile does not match the requested native diagnostic')
    if kind in ('identity','dependent','calibration'):
        expected_mode={'identity':0,'dependent':2,'calibration':3}[kind]
        if state.get('query')!=[0,state['logical_payload_bytes'],expected_mode]:
            raise ValueError('Receipt must declare a complete logical-array query of the requested mode')
    pixels=np.asarray(image.convert('RGBA'),dtype=np.uint8)
    n=state['logical_payload_bytes']
    count=n if kind in ('identity','dependent','calibration') else plan['records']
    ordinal=np.arange(count,dtype=np.uint64)
    x=(ordinal%1024+8).astype(np.intp)
    y=(ordinal//1024+128).astype(np.intp)
    observed=pixels[y,x]
    if kind in ('identity','dependent'):
        index=addresses(state,0 if kind=='identity' else 2)
        expected=expected_bytes(state['seed'],state['generation'],index)
        rgb=np.repeat(expected[:,None],3,axis=1)
    elif kind=='calibration':
        index=ordinal
        rgb=np.repeat((ordinal%256).astype(np.uint8)[:,None],3,axis=1)
    elif kind=='integrity':
        index=ordinal
        rgb=np.zeros((count,3),dtype=np.uint8)
    elif kind=='coordinates':
        index=ordinal
        fx,fy=x.astype(np.uint64),(1439-y).astype(np.uint64)
        rgb=np.stack((fx%256,fy%256,fx//256+8*(fy//256)),axis=1).astype(np.uint8)
    elif kind=='screeninfo':
        index=ordinal
        values=np.array([1080,1440,round(16777216/1080),round(16777216/1440)],dtype=np.uint64)
        codes=values[ordinal%4]
        rgb=np.stack((codes%256,(codes//256)%256,codes//65536),axis=1).astype(np.uint8)
    else:
        raise ValueError('Unknown exact native diagnostic kind')
    errors=np.abs(observed[:,:3].astype(np.int16)-rgb.astype(np.int16))
    failed=np.any(errors!=0,axis=1)|(observed[:,3]!=255)
    invalid_blocks=np.all(observed[:,:3]==[255,0,255],axis=1)
    guard=np.zeros(pixels.shape[:2],dtype=bool)
    guard[128:1408]=True
    guard[y,x]=False
    borders=np.any(pixels[guard]!=SENTINEL,axis=1)
    bad=np.flatnonzero(failed)
    return {'schema':'scene_codec_large_exact_pixels_v1','passed':not failed.any() and not borders.any(),
        'kind':kind,'logical_bytes':n,'checked_native_query_pixels':count,
        'failed_query_pixels':int(failed.sum()),'maximum_rgb_error':int(errors.max()),
        'alpha_failures':int((observed[:,3]!=255).sum()),'magenta_invalid_block_pixels':int(invalid_blocks.sum()),
        'checked_guard_pixels':int(guard.sum()),'failed_guard_pixels':int(borders.sum()),'byte_tolerance':0,
        'source_roi':plan['roi'],'diagnostic_layout':[8,128,1024,1],'guard_rect_native':[0,128,1080,1408],
        'expected_query_sha256':hashlib.sha256(rgb.tobytes()).hexdigest(),
        'observed_query_sha256':hashlib.sha256(observed[:,:3].tobytes()).hexdigest(),
        'failures_first16':[{'ordinal':int(i),'source_address':int(index[i]),'native_pixel':[int(x[i]),int(y[i])],
            'expected_rgb':rgb[i].tolist(),'observed_rgba':observed[i].tolist()} for i in bad[:16]],
        'query_coverage':'all logical ordinals' if count==n else 'all source records including header and padding',
        'distinct_final_addresses':int(np.unique(index).size) if kind=='dependent' else count,
        'initial_indexed_reads_visit_every_logical_byte':kind=='dependent',
        'runtime_file_writes':False}


def verify_files(receipt,capture,kind,output):
    receipt,capture,output=map(Path,(receipt,capture,output))
    if output.exists():
        raise ValueError('Verification output already exists; preserve evidence')
    state=json.loads(receipt.read_text(encoding='utf-8-sig'))
    with Image.open(capture) as image:
        report=verify_image(state,image,kind)
    report.update(receipt_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
        capture_sha256=hashlib.sha256(capture.read_bytes()).hexdigest())
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
