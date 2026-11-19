"""Host-only stage controls and observational RGB summaries; never game file IO."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image


STAGES = ('off', 'base', 'bit64', 'bit128', 'all', 'writers_only', 'readers_only')
MODES = (1, 3, 7)
LINKS = (('stencil_integrated_copy', 0, 'stencil_integrated_restore', 0, 3),
         ('stencil_integrated_copy', 0, 'stencil_integrated_consumer', 0, 3),
         ('stencil_integrated_restore', 0, 'stencil_integrated_consumer', 0, 4))


def stage_spec(stage):
    if stage not in STAGES:
        raise ValueError('Unknown bounded diagnostic stage')
    return {'clear': stage != 'off',
        'writers': ['bit64', 'bit128'] if stage in ('all', 'writers_only') else
                   [stage] if stage in ('bit64', 'bit128') else [],
        'readers': [0, 1, 2] if stage in ('all', 'readers_only') else
                   [0, 1] if stage == 'bit64' else [0, 2] if stage == 'bit128' else
                   [0] if stage == 'base' else []}


def stage_source(stage, mode):
    spec = stage_spec(stage)
    if mode not in MODES or isinstance(mode, bool):
        raise ValueError('Stage consumers are mode 1, 3 or 7')
    return """stage_spec=%r
if len(probe.controls)!=3 or len(probe.active_pages)!=2: raise RuntimeError('Stage requires exactly three readers and two cached bit pages')
if any(sum(('_'+kind+'_') in page['name'] for page in probe.active_pages)!=1 for kind in ('bit64','bit128')): raise RuntimeError('Stage bit-page identities are ambiguous')
probe.configure('all')
stage_receipts=[]
accepted=probe.clear_actor['render'].SetActorBlockGeometryVisible(probe.clear_page,stage_spec['clear'])
stage_receipts.append({'operation':'clear_visibility','accepted':accepted,'enabled':stage_spec['clear']})
if accepted is not True: raise RuntimeError('Stage clear visibility rejected')
for page in probe.active_pages:
    enabled=any(('_'+kind+'_') in page['name'] for kind in stage_spec['writers'])
    accepted=page['actor']['render'].SetActorBlockGeometryVisible(page['name'],enabled)
    stage_receipts.append({'operation':'writer_visibility','page':page['name'],'accepted':accepted,'enabled':enabled})
    if accepted is not True: raise RuntimeError('Stage writer visibility rejected')
for index,control in enumerate(probe.controls):
    enabled=index in stage_spec['readers']
    accepted=control.Play() if enabled else control.Stop()
    stage_receipts.append({'operation':'late_reader_play' if enabled else 'late_reader_stop','reader':index,'accepted':accepted})
    if accepted is not True: raise RuntimeError('Stage late-reader control rejected')
probe.inspect(%d,shape_enabled=False,enabled=True,restore_enabled=False)
""" % (spec, mode) + ("if not probe.post.SetParameter('stencil_integrated_consumer','output',[0.,650.,float(probe.viewport[0]),0.]): raise RuntimeError('Raw export Y650 rejected')\n" if mode == 7 else '')


def predicted_payload(stage, payload):
    if stage in ('base', 'readers_only'):
        return bytes(len(payload))
    if stage in ('bit64', 'bit128'):
        mask = 0x55 if stage == 'bit64' else 0xAA
        return bytes(value & mask for value in payload)
    return bytes(payload) if stage == 'all' else None


def summarize(image, mode, payload, viewport, roi, verify, output_y=128):
    rgb = np.asarray(image.convert('RGB'))
    width, height = viewport
    if rgb.shape != (height, width, 3) or mode not in MODES:
        raise ValueError('Expected full native stage image and reviewed consumer')
    count = len(payload)*(1 if mode == 1 else 4)
    output = rgb[output_y:].reshape(-1, 3)
    data, guard = output[:count], output[count:]
    if len(data) != count:
        raise ValueError('Stage output cannot contain full source')
    colors, frequencies = np.unique(data, axis=0, return_counts=True)
    ordered = np.argsort(-frequencies)[:16]
    result = {'mode': mode, 'output_origin': [0, output_y], 'data_pixels': count, 'guard_pixels': len(guard),
        'guard_error_pixels': int(np.any(guard != [17, 53, 97], axis=1).sum()),
        'data_sha256': hashlib.sha256(data.tobytes()).hexdigest(),
        'data_unique_rgb': len(colors), 'channel_min': data.min(axis=0).tolist(),
        'channel_max': data.max(axis=0).tolist(), 'exact_asserted': False,
        'top_rgb': [{'rgb': colors[index].tolist(), 'pixels': int(frequencies[index])} for index in ordered],
        'data_first_16': data[:16].tolist()}
    if mode in (1, 3):
        result['full_payload_comparison'] = verify(image.convert('RGB'), mode, payload,
                                                 viewport, roi, output_y=output_y, fixture=False)
    if mode == 1:
        wide = data[:, 0].astype(np.uint16)
        valid = (data[:, 1] == (71*wide+43) % 256) & (data[:, 2] == (131*wide+17) % 256)
        result.update(valid_byte_markers=int(valid.sum()), zero_byte_markers=int(np.all(data == [0, 43, 17], axis=1).sum()))
    else:
        codes, counts = np.unique(data[:, 0]//64, return_counts=True)
        result['red_quotient64_histogram'] = {str(int(k)): int(v) for k, v in zip(codes, counts)}
        if mode == 3:
            codes, counts = np.unique(data[:, 1], return_counts=True)
            result.update(alpha_histogram={str(int(k)): int(v) for k, v in zip(codes, counts)},
                          range_flag_nonzero_pixels=int((data[:, 2] != 0).sum()))
        else:
            result['raw_green_or_blue_above63_pixels'] = int(np.any(data[:, 1:] > 63, axis=1).sum())
            result['analytic_fixture_reference_asserted'] = False
            x, y, roi_width, roi_height = roi
            source = rgb[y:y+roi_height, x:x+roi_width].reshape(-1, 3)
            delta = np.abs(source.astype(np.int16)-data.astype(np.int16))
            result['same_frame_screen_roi'] = {'roi': list(roi), 'pixels': len(source),
                'data_sha256': hashlib.sha256(source.tobytes()).hexdigest(),
                'data_unique_rgb': len(np.unique(source, axis=0)),
                'max_rgb_error_vs_t3': delta.max(axis=0).tolist(),
                'different_pixels_vs_t3': int(np.any(delta != 0, axis=1).sum()),
                'data_first_16': source[:16].tolist(), 'separate_frame_comparison': False}
    return result


def capture(experiment, label, mode, original, positive):
    experiment.invoke([sys.executable, '-B', '-X', 'utf8', str(positive.COMPAT/'host.py'), 'capture',
        '--project', str(experiment.args.project), '--evidence', str(experiment.evidence), '--label', label], label+'_capture')
    receipt = json.loads((experiment.evidence/(label+'.json')).read_text(encoding='utf-8'))
    if (receipt.get('ok') is not True or receipt.get('backend') != 'Windows.Graphics.Capture' or
            [receipt.get('width'), receipt.get('height')] != experiment.viewport or
            receipt.get('frame_qpc_100ns', 0) < receipt.get('request_qpc_100ns', 1) or
            receipt.get('agent_activation_allowed') is not False or
            not all(receipt.get(key, {}).get('window_noactivate') for key in ('background_before', 'background_after'))):
        raise RuntimeError('Stage observation requires fresh passive owned noactivation WGC')
    path = experiment.evidence/(label+'.png')
    with Image.open(path) as frame:
        stats = summarize(frame, mode, experiment.payload, experiment.viewport, experiment.roi,
                          original.integrated.verify_module.verify, output_y=650 if mode == 7 else 128)
    row = {'label': label, 'capture_file': str(path), 'capture_receipt': receipt,
           'state': experiment.state, 'intentional_stage_observation': True, **stats}
    experiment.reports.append(row)
    experiment.save()
    return row


def effects_source():
    return """probe.configure('off')
manual_receipts=[]
manual_old_effects=list(probe.effects)
for effect in list(probe.effects):
    accepted=probe.DestroyEntity(effect)
    manual_receipts.append({'operation':'DestroyEntity(effect)','entity':effect,'accepted':accepted})
    if accepted is not True: raise RuntimeError('Manual effect destruction rejected')
probe.effects,probe.controls=[],[]
probe._effects_ready()
manual_result={'old_effects':manual_old_effects,'effects':list(probe.effects),'receipts':manual_receipts,'frame':probe.render_event}
"""


def holders_source():
    return """manual_before={'identity':dict(probe.identity),'generation':probe.generation,'pages':list(probe.pages),'native_attempts':len(probe.attempts)}
manual_specs=[dict((key,actor[key]) for key in ('kind','index','count','stride','offset','pages')) for actor in probe.actors]
probe.configure('off')
manual_receipts=[]
for actor in list(probe.actors):
    probe.DestroyClientEntity(actor['entity'])
    manual_receipts.append({'operation':'DestroyClientEntity','entity':actor['entity'],'void_return_documented':True})
position,forward=probe.camera.GetPosition(),probe.camera.GetForward()
probe.anchor=tuple(position[i]+3.*forward[i] for i in range(3))
probe.actors,probe.writer_actors,probe.active_pages=[],[],[]
probe.clear_actor=None
probe.payload_visible,probe.clear_visible=False,False
for spec in manual_specs:
    actor=probe._new_actor(spec['kind'],spec['index'])
    for key in ('count','stride','offset'): actor[key]=spec[key]
    actor['ready']=probe._actor_uniforms(actor)
    if spec['kind']=='clear': probe.clear_actor=actor
    else: probe.writer_actors.append(actor)
    for name in spec['pages']:
        accepted=actor['render'].AddActorBlockGeometry(name,(0.,0.,0.),(0.,0.,0.))
        manual_receipts.append({'operation':'AddActorBlockGeometry','geometry':name,'entity':actor['entity'],'accepted':accepted})
        if accepted is not True: raise RuntimeError('Manual cached-page reattachment rejected')
        actor['pages'].append(name)
        if not actor['render'].SetActorBlockGeometryVisible(name,False): raise RuntimeError('Manual initial hide rejected')
        if spec['kind']!='clear': probe.active_pages.append({'name':name,'actor':actor})
manual_result={'before':manual_before,'specs':manual_specs,'receipts':manual_receipts,'frame':probe.render_event,
    'actor_ids':[actor['entity'] for actor in probe.actors],'effects':list(probe.effects),'runtime_file_writes':False}
"""


def relink_source():
    return """manual_links=[]
for link in %r:
    accepted=probe.post.PostPassResultToOtherPass(*link)
    manual_links.append({'link':list(link),'accepted':accepted})
    if accepted is not True: raise RuntimeError('Manual postprocess relink rejected')
probe.pipeline_link_attempts+=1
probe.pipeline_links=list(%r)
probe.pipeline_ready=True
probe.configure('all')
probe.inspect(1,shape_enabled=False,enabled=True,restore_enabled=True)
manual_link_result={'receipts':manual_links,'frame':probe.render_event,'probe':probe.snapshot()}
""" % (LINKS, LINKS)


def fixture_comparison(image, stage, payload, viewport, roi, verify_module, output_y=650):
    """Existing layer-12 analytic reference, separate from natural scene runs."""
    frame = np.asarray(image.convert('RGB'))
    rgb = frame[output_y:].reshape(-1, 3)[:len(payload)*4]
    expected = verify_module.fixture_rgba(roi)[:, :3].copy()
    if stage != 'off':
        expected = np.rint(expected.astype(np.float64)*(63./255.)).astype(np.uint8)
        if stage == 'all':
            values = np.frombuffer(bytes(payload), dtype=np.uint8)
            symbols = ((values[:, None] >> np.arange(0, 8, 2, dtype=np.uint8)) & 3).reshape(-1)
            expected[:, 0] += symbols*64
    x, y, width, height = roi
    source = frame[y:y+height, x:x+width].reshape(-1, 3)
    def compared(actual):
        difference = np.abs(actual.astype(np.int16)-expected.astype(np.int16))
        return {'data_pixels': len(actual), 'data_error_pixels': int(np.any(difference > (0 if stage == 'off' else 1), axis=1).sum()),
                'max_rgb_error': difference.max(axis=0).tolist()}
    return {'analytic_fixture': True, 'per_channel_tolerance': 0 if stage == 'off' else 1,
        'prediction': 'fixture RGB' if stage == 'off' else 'fixture RGB*63/255 plus encoded red symbols' if stage == 'all' else 'fixture RGB*63/255',
        'screen_roi': compared(source), 'exported_t3': compared(rgb),
        'same_frame_different_pixels': int(np.any(source != rgb, axis=1).sum()),
        'export_output_y': output_y, 'exact_asserted': False}
