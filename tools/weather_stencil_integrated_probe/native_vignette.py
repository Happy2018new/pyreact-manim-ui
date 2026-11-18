"""Run a bounded, owner-bound check with the shipped vignette process."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

import numpy as np
from PIL import Image

from runner import Experiment, HERE, verify_module


CORE = ('stencil_integrated_copy', 'stencil_integrated_restore', 'stencil_integrated_consumer')
LATE = 'stencil_integrated_after_vignette'


def definition(name, material, size, viewport, roi, output_y):
    params = [('control', [float(viewport[0]), float(viewport[1]), 0., float(size)]),
              ('roi', [float(value) for value in roi]),
              ('output', [0., float(output_y), float(viewport[0]), 0.])]
    return {'name': name, 'enable': True, 'paras': [
        {'name': parameter, 'value': value, 'range': [0., 2097152.]}
        for parameter, value in params], 'pass_array': [
            {'render_target': {'width': 1., 'height': 1.}, 'material': material, 'depth_enable': False}]}


def capture(experiment, label, reports):
    experiment.invoke([sys.executable, '-B', '-X', 'utf8', str(HERE/'host.py'), 'capture',
                       '--project', str(experiment.args.project.resolve()),
                       '--evidence', str(experiment.evidence), '--label', label], label+'_capture')
    path = experiment.evidence/(label+'.png')
    receipt = json.loads((experiment.evidence/(label+'.json')).read_text(encoding='utf-8'))
    if (not receipt['ok'] or receipt['backend'] != 'Windows.Graphics.Capture'
            or [receipt['width'], receipt['height']] != experiment.viewport
            or receipt['frame_qpc_100ns'] < receipt['request_qpc_100ns']
            or receipt.get('agent_activation_allowed') is not False
            or not all(receipt.get(key, {}).get('window_noactivate')
                       for key in ('background_before', 'background_after'))):
        raise RuntimeError('Fresh passive capture rejected')
    row = {'label': label, 'capture_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    reports.append(row)
    with Image.open(path) as image:
        return image.convert('RGB'), row


def pixels_in_known_scene(image, viewport, roi, vignette, tolerance=0):
    x, y, width, height = roi
    field = np.asarray(image)[y:y+height, x:x+width].reshape((-1, 3))
    iy, ix = np.divmod(np.arange(width*height), width)
    distance = np.hypot((x+ix+.5)/viewport[0]-.5, (y+iy+.5)/viewport[1]-.5)
    rgb = verify_module.fixture_rgba(roi)[:, :3]
    edge, center = distance > .47, distance < .38
    if not np.any(edge) or not np.any(center):
        raise RuntimeError('Known ROI must contain both native vignette reference regions')
    expected_edge = [255, 0, 255] if vignette else rgb[edge]
    return {'outer_examples': int(np.count_nonzero(edge)),
            'outer_errors': int(np.count_nonzero(np.any(field[edge] != expected_edge, axis=1))),
            'center_examples': int(np.count_nonzero(center)),
            'center_errors': int(np.count_nonzero(np.any(np.abs(field[center].astype(np.int16) - rgb[center].astype(np.int16)) > tolerance, axis=1)))}


def setup(experiment, receipt):
    calls = """probe.configure('off')
probe.inspect(0, enabled=True)
probe.configure_known_fixture(True,False)
accepted=[probe.post.SetVignetteRGB((255,0,255)),probe.post.SetVignetteCenter((0.5,0.5)),probe.post.SetVignetteRadius(0.45),probe.post.SetVignetteSmoothness(0.05),probe.post.SetEnableVignette(True)]
"""
    receipt['setters'] = experiment.call('enable_vignette', calls,
        "{'setters':accepted,'order':probe.post.GetPostProcessOrder(),'enabled':probe.post.CheckVignetteEnabled()}")
    if not all(receipt['setters']['setters']):
        raise RuntimeError('A native vignette setter rejected its value')
    time.sleep(.65)
    definitions = [definition(name, name, len(experiment.payload), experiment.viewport,
                              experiment.roi, experiment.output_y) for name in CORE]
    consumer = definition(LATE, CORE[-1], len(experiment.payload), experiment.viewport,
                          experiment.roi, experiment.output_y)
    code = """order=list(probe.post.GetPostProcessOrder() or [])
missing=[(i,item) for i,item in enumerate(%r) if item['name'] not in order]
accepted=[(item['name'],probe.post.AddPostProcess(item,i)) for i,item in missing]
late_accepted=probe.post.AddPostProcess(%r)
""" % (definitions, consumer)
    receipt['registration'] = experiment.call('register_after_vignette', code,
        "{'readded':accepted,'late_added':late_accepted,'order':probe.post.GetPostProcessOrder()}")
    if (not receipt['registration']['late_added']
            or not all(added for _, added in receipt['registration']['readded'])):
        raise RuntimeError('Restore or the post-vignette reader could not be registered')
    time.sleep(.65)
    links = [(CORE[0], 0, CORE[1], 0, 3), (CORE[0], 0, CORE[2], 0, 3),
             (CORE[1], 0, CORE[2], 0, 4), (CORE[0], 0, LATE, 0, 3), (CORE[1], 0, LATE, 0, 4)]
    code = """links=[(link,probe.post.PostPassResultToOtherPass(*link)) for link in %r]
order=list(probe.post.GetPostProcessOrder() or [])
flags=[(name,probe.post.CheckEnabledByName(name)) for name in order]
""" % links
    receipt['connections'] = experiment.call('link_after_vignette', code,
        "{'links':links,'order':order,'flags':flags,'enabled':probe.post.CheckVignetteEnabled()}")
    bridge = receipt['connections']
    expected = [*CORE, 'vignette', LATE]
    ordered = [name for name in bridge['order'] if name in expected]
    enabled = [name for name, value in bridge['flags'] if value]
    if (ordered != expected or enabled != expected or not bridge['enabled']
            or not all(connected for _, connected in bridge['links'])):
        raise RuntimeError('Native vignette activation, full order or texture links fail')


def run(args, receipt):
    previous = Path(args.previous_evidence).resolve()
    prior_path = previous/'results.json'
    receipt['prior_results_sha256'] = hashlib.sha256(prior_path.read_bytes()).hexdigest()
    prior = json.loads(prior_path.read_text(encoding='utf-8'))
    info = prior['loads'][-1]
    reference = info['state_after_load']
    initial_size = info['logical_bytes']
    payload_file = next((parent/('n%d_actual_input.bin'%initial_size)
                         for parent in (previous,*previous.parents[:3])
                         if (parent/('n%d_actual_input.bin'%initial_size)).is_file()), None)
    if payload_file is None:
        raise RuntimeError('Resident payload file unavailable')
    shutil.copyfile(previous/'launch.json', args.evidence/'launch.json')
    experiment = Experiment(args)
    experiment.payload = payload_file.read_bytes()
    experiment.viewport, experiment.roi = info['viewport'], info['roi']
    experiment.output_y = 650 if initial_size == 65536 else 128
    state = experiment.call('same_instance_initial')
    if any(state[key] != reference[key] for key in ('identity','active_pages','logical_bytes','viewport','source_roi')):
        raise RuntimeError('Payload, pages or screen differ from the validated native probe')
    if hashlib.sha256(experiment.payload).hexdigest() != state['identity']['host_sha256']:
        raise RuntimeError('Host payload identity differs from the frozen game input')
    experiment.call('known_fixture_visible', "probe.configure('off')\nprobe.inspect(0,enabled=True)\nprobe.configure_known_fixture(True,False)")
    time.sleep(.6)
    image, row = capture(experiment, 'native_vignette_off', receipt['captures'])
    row.update(pixels_in_known_scene(image, experiment.viewport, experiment.roi, False))
    if row['outer_errors'] or row['center_errors']:
        raise RuntimeError('Known scene must already be visible with vignette disabled')
    setup(experiment, receipt)
    time.sleep(.6)
    image, row = capture(experiment, 'native_vignette_on', receipt['captures'])
    row.update(pixels_in_known_scene(image, experiment.viewport, experiment.roi, True))
    if row['outer_errors'] or row['center_errors']:
        raise RuntimeError('Native vignette did not match the fixed inner and outer truth regions')
    experiment.call('vignette_with_carrier', "probe.configure('all')\nprobe.inspect(0,enabled=True)")
    time.sleep(.6)
    image, row = capture(experiment, 'native_vignette_with_carrier', receipt['captures'])
    row.update(pixels_in_known_scene(image, experiment.viewport, experiment.roi, True, tolerance=2))
    if row['outer_errors'] or row['center_errors']:
        raise RuntimeError('Active carrier disturbed the inner or outer native vignette reference')
    for mode in (1, 2):
        controls = [float(v) for v in (*experiment.viewport, mode, initial_size)]
        code = "probe.configure('all')\nprobe.inspect(0,enabled=True)\naccepted=probe.post.SetParameter(%r,'control',%r)" % (LATE,controls)
        state = experiment.call('after_vignette_mode_%d'%mode,code,"{'accepted':accepted,'state':probe.snapshot()}")
        if not state['accepted'] or not dict(state['state']['native_post_flags'])['vignette']:
            raise RuntimeError('Active native vignette and late reader are required')
        time.sleep(.6)
        image, row = capture(experiment,'after_vignette_mode_%d'%mode, receipt['captures'])
        row.update(verify_module.verify(image,mode,experiment.payload,experiment.viewport,
                                        experiment.roi,output_y=experiment.output_y))
        if not row['exact']:
            raise RuntimeError('Full-array check after native vignette failed')
    experiment.call('native_compat_finished', "probe.configure('off')\nprobe.configure_known_fixture(False)\n"
                    "removed=probe.post.SetEnableVignette(False)", "{'vignette_disabled':removed}")
    receipt['verified'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--previous-evidence', type=Path, required=True)
    args = parser.parse_args()
    args.evidence = args.evidence.resolve()
    args.evidence.mkdir(exist_ok=False)
    receipt = {'verified': False, 'captures': [], 'failure': None}
    try:
        run(args, receipt)
    except Exception as error:
        receipt['failure'] = repr(error)
        raise
    finally:
        (args.evidence/'vignette-status.json').write_text(
            json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))


if __name__ == '__main__':
    main()
