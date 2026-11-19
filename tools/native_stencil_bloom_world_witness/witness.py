"""Offline native-SFX Bloom witness; lifecycle belongs to the caller."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time
import uuid

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PHASES = ('source-control', 'native')
BUILD = 'bloom_world_build.json'
STATUS = 'bloom-world-status.json'
SOURCE = 'resource_pack/shaders/glsl/stencil_integrated_known_fixture.fragment'
VIEWPORT, PATCH, ANALYSIS = [720, 1080], [328, 508, 64, 64], [128, 256, 464, 568]
FRAGMENT = '''// __multiversion__
precision highp float;
#include "fragmentVersionCentroid.h"
#include "uniformExtraVectorConstants.h"
void main() {
    float packedViewport = floor(EXTRA_VECTOR3.r * 16777216.0);
    vec2 viewport = vec2(floor(packedViewport / 4096.0), mod(packedViewport, 4096.0));
    vec2 pixel = floor(vec2(gl_FragCoord.x, viewport.y-gl_FragCoord.y));
    float mode = EXTRA_VECTOR3.a;
    if (mode < 0.125 || mode > 0.875) discard;
    float patchMask = float(pixel.x>=328.0 && pixel.x<392.0 && pixel.y>=508.0 && pixel.y<572.0);
    gl_FragColor = vec4(vec3(patchMask), mix(1.0, mode>0.5 ? 0.0 : 1.0, patchMask));
}
'''


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def base():
    return module('world_bloom_frozen_gate', HERE.parent/'native_stencil_post_candidate/bloom.py')


def inventory(project):
    return {p.relative_to(project).as_posix(): sha(p) for folder in ('behavior_pack', 'resource_pack')
            for p in (project/folder).rglob('*') if p.is_file()}


def build(output, game_exe, phase):
    if phase not in PHASES:
        raise ValueError('Unknown startup phase')
    output, game_exe = Path(output).resolve(), Path(game_exe).resolve()
    if (ROOT/'.runtime').resolve() not in output.parents or output.exists():
        raise ValueError('Use a fresh output under this repository .runtime')
    builder = module('world_bloom_compat_builder', HERE.parent/'native_stencil_compat_probe/build_probe.py')
    builder.build(output, game_exe, 'carrier')
    startup = module('world_bloom_native_startup', HERE.parent/'native_stencil_post_fixture/assets.py')
    native = game_exe.parent/'data/resource_packs/vanilla_netease'
    inputs = {}
    for name in startup.CONFIG_NAMES:
        original = native/'graphics_settings'/name
        config = read(original)
        for process in config['process_array']:
            process['enable'] = phase == 'native' and process['name'] == 'bloom'
        write(output/'resource_pack/graphics_settings'/name, config)
        inputs[str(original)] = sha(original)
    (output/SOURCE).write_text(FRAGMENT, encoding='utf-8')
    for folder in ('behavior_pack', 'resource_pack'):
        path = output/folder/'manifest.json'
        manifest = read(path)
        manifest['header']['uuid'] = str(uuid.uuid5(uuid.NAMESPACE_URL, 'bloom-world/'+phase+'/'+folder))
        for index, item in enumerate(manifest['modules']):
            item['uuid'] = str(uuid.uuid5(uuid.NAMESPACE_URL, 'bloom-world/'+phase+'/'+folder+'/'+str(index)))
        write(path, manifest)
    receipt = {'schema': 'bloom_world_build_v1', 'phase': phase, 'project': str(output),
        'game_executable': str(game_exe), 'builder_sha256': sha(__file__),
        'source_sha256': sha(output/SOURCE), 'native_config_inputs': inputs,
        'native_math_changed': False, 'startup_enable_flags_only': True,
        'viewport': VIEWPORT, 'patch': PATCH, 'analysis_rect': ANALYSIS,
        'files': inventory(output), 'custom_post_source_or_observer': False}
    write(output/BUILD, receipt)
    return receipt


def validate(project, phase):
    project = Path(project).resolve()
    value = read(project/BUILD)
    if value['phase'] != phase or value['project'] != str(project) or value['builder_sha256'] != sha(__file__):
        raise ValueError('World witness build binding differs')
    if value['files'] != inventory(project):
        raise ValueError('World witness pack inventory changed')
    if any(sha(path) != digest for path, digest in value['native_config_inputs'].items()):
        raise ValueError('Installed native config source changed')
    return value


def crop(frame):
    x, y, w, h = ANALYSIS
    value = np.asarray(frame)
    if value.shape != (1080, 720, 3):
        raise ValueError('Expected native 720x1080 RGB')
    return value[y:y+h, x:x+w]


def evaluate_source(frames):
    x, y, w, h = ANALYSIS
    expected = np.zeros((h, w, 3), dtype=np.uint8)
    px, py, pw, ph = PATCH
    expected[py-y:py-y+ph, px-x:px-x+pw] = 255
    errors = [int(np.count_nonzero(np.any(abs(crop(f).astype(np.int16)-expected)>2, axis=2))) for f in frames]
    return {'passed': len(frames)==3 and not any(errors), 'rgb_error_pixels': errors,
            'analysis_pixels_per_image': w*h, 'actual_alpha_sampled': False,
            'alpha_control': 'Declared SFX overwrite shader/mode only; no alpha pixel readback claimed.'}


def evaluate_halo(frames):
    x, y, w, h = ANALYSIS
    px, py, pw, ph = PATCH
    layout = {'viewport': [w, h], 'patch': [px-x, py-y, pw, ph],
              'halo_gap': 3, 'halo_radius': 64, 'guard_gap': 32}
    return base().evaluate_bloom_response([crop(f) for f in frames], layout)


def verify_gate(path, source_sha):
    path = Path(path).resolve()
    value = read(path)
    if (value.get('phase') != 'source-control' or value.get('failure') is not None
            or value.get('source_sha256') != source_sha or value.get('cleanup', {}).get('ok') is not True):
        raise ValueError('Source-control gate binding or cleanup rejected')
    rows = value.get('captures', [])
    if len(rows) != 3 or [r.get('declared_patch_alpha') for r in rows] != [1, 0, 1]:
        raise ValueError('Source-control A/B/A sequence differs')
    frames, last_frame = [], 0
    camera = rows[0]['before']['world_camera']
    for row, varying in zip(rows, (False, True, False)):
        image = Path(row['capture_file'])
        if sha(image) != row['capture_sha256'] or sha(image.with_suffix('.json')) != row['sidecar_sha256']:
            raise ValueError('Source-control evidence hash changed')
        c = read(image.with_suffix('.json'))
        if (c != row['capture_receipt'] or c.get('ok') is not True
                or c.get('backend') != 'Windows.Graphics.Capture' or c.get('native_resolution') is not True
                or [c.get('width'), c.get('height')] != VIEWPORT
                or c.get('pid') != value.get('game_pid') or c.get('agent_activation_allowed') is not False
                or c['frame_qpc_100ns'] <= c['request_qpc_100ns'] or c['request_qpc_100ns'] <= last_frame
                or any(c.get(key, {}).get('window_noactivate') is not True
                       for key in ('background_before', 'background_after'))):
            raise ValueError('Source-control provenance changed')
        last_frame = c['frame_qpc_100ns']
        for key in ('before', 'after'):
            check(row[key], 'source-control', varying, camera)
        with Image.open(image) as im:
            frames.append(np.asarray(im.convert('RGB')))
    result = evaluate_source(frames)
    if not result['passed']:
        raise ValueError('Actual source RGB gate failed')
    return {'file': str(path), 'sha256': sha(path), 'replayed_source': result}


EXPRESSION = ("dict(probe.snapshot(),world_camera={'position':probe.camera.GetPosition(),"
              "'forward':probe.camera.GetForward()})")


def check(state, phase, varying, camera):
    flags = dict(state['native_post_flags'])
    enabled = [name for name, flag in flags.items() if flag]
    if sorted(enabled) != (['bloom'] if phase == 'native' else []):
        raise ValueError('Native startup isolation differs')
    if (state['pipeline_registered'] or state['oracle_installed'] or state['mode'] != 'off'
            or state['payload_visible'] or state['world_camera'] != camera):
        raise ValueError('Carrier/custom pass or camera changed')
    fixture = state['known_fixture']
    if not fixture['visible'] or fixture['varying_alpha'] is not varying:
        raise ValueError('Native SFX source mode differs')


def run(experiment, phase, source_gate=None):
    built = validate(experiment.args.project, phase)
    receipt = {'schema': 'bloom_world_witness_v1', 'phase': phase, 'failure': None,
        'status': 'not_started', 'compatibility': None, 'captures': [],
        'source_sha256': built['source_sha256'], 'native_positive_response_observed': False,
        'actual_alpha_sampled': False, 'carrier_compatibility_tested': False,
        'native_runtime_setters_used': False, 'texture_result_links_used': False,
        'analysis_rect': ANALYSIS, 'patch': PATCH, 'capacity_tested': 0,
        'game_pid': experiment.game_pid, 'project': str(Path(experiment.args.project).resolve())}
    if phase == 'native':
        receipt['source_gate'] = verify_gate(source_gate, built['source_sha256'])
    initial = experiment.call('bloom_world_initial', expression=EXPRESSION)
    frames = []
    try:
        for label, varying in (('a', False), ('b', True), ('a_return', False)):
            name = 'bloom_world_'+phase.replace('-', '_')+'_'+label
            requested = experiment.call(name+'_set', "probe.configure('off')\nprobe.configure_known_fixture(True,%r)" % varying,
                                        expression=EXPRESSION)
            time.sleep(.65)
            before = experiment.call(name+'_before', expression=EXPRESSION)
            check(before, phase, varying, initial['world_camera'])
            if before['render_event'] <= requested['render_event']:
                raise ValueError('Native source did not cross a render turn')
            row, pixels = base()._capture(experiment, name)
            if row['capture_receipt']['frame_qpc_100ns'] <= row['capture_receipt']['request_qpc_100ns']:
                raise ValueError('Strict capture freshness failed')
            after = experiment.call(name+'_after', expression=EXPRESSION)
            check(after, phase, varying, initial['world_camera'])
            row.update(capture_sha256=sha(row['capture_file']), sidecar_sha256=sha(Path(row['capture_file']).with_suffix('.json')),
                       declared_patch_alpha=0 if varying else 1, before=before, after=after)
            receipt['captures'].append(row)
            frames.append(pixels)
        if phase == 'source-control':
            receipt['source_control'] = evaluate_source(frames)
            receipt['status'] = 'source_rgb_observed' if receipt['source_control']['passed'] else 'source_control_unproven'
        else:
            response = evaluate_halo(frames)
            receipt.update(native_response=response, native_positive_response_observed=response['passed'],
                status='native_positive_control_observed' if response['passed'] else 'native_stage_unproven')
    except Exception as error:
        receipt.update(status='helper_failed', failure=repr(error))
    finally:
        try:
            state = experiment.call('bloom_world_cleanup', 'probe.configure_known_fixture(False)', expression=EXPRESSION)
            receipt['cleanup'] = {'ok': not state['known_fixture']['visible'], 'state': state}
        except Exception as error:
            receipt.update(status='helper_failed', cleanup_failure=repr(error))
        receipt['limitation'] = 'Bounded native halo witness only. No alpha pixel proof, carrier compatibility, lossless scene or performance claim.'
        write(Path(experiment.evidence)/STATUS, receipt)
        experiment.save()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    b = sub.add_parser('build')
    b.add_argument('--output', type=Path, required=True)
    b.add_argument('--game-exe', type=Path, required=True)
    r = sub.add_parser('run')
    for key in ('project', 'evidence', 'previous-evidence'):
        r.add_argument('--'+key, type=Path, required=True)
    r.add_argument('--source-gate', type=Path)
    for p in (b, r):
        p.add_argument('--phase', choices=PHASES, required=True)
    args = parser.parse_args()
    if args.action == 'build':
        print(json.dumps(build(args.output, args.game_exe, args.phase)))
        return
    built = validate(args.project, args.phase)
    if args.phase == 'native':
        verify_gate(args.source_gate, built['source_sha256'])
    args.project, args.evidence = args.project.resolve(), args.evidence.resolve()
    args.evidence.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(args.previous_evidence/'launch.json', args.evidence/'launch.json')
    runner = module('world_bloom_owner_experiment', HERE.parent/'native_stencil_compat_probe/runner.py')
    experiment = runner.Experiment(args)
    session = read(experiment.session)
    if (session['owner'] != 'manim-native-stencil-compat' or session['game_pid'] != experiment.game_pid
            or Path(session['project']).resolve() != args.project):
        raise ValueError('Owner/session/project/PID mismatch')
    native = module('world_bloom_camera', HERE.parent/'native_stencil_post_fixture/native_effects.py')
    experiment.invoke([sys.executable, '-B', '-X', 'utf8', str(base().HOST), 'resize',
        '--project', str(args.project), '--evidence', str(args.evidence), '--width', '720', '--height', '1080'], 'bloom_world_resize')
    native.prepare_camera(experiment, 'bloom')
    experiment.weather('bloom_world_clear', False, True)
    experiment.viewport, experiment.roi, experiment.payload = VIEWPORT, [8, 128, 512, 512], b''
    experiment.call('bloom_world_initialized', 'probe.viewport=[720,1080]\nprobe.roi=[8,128,512,512]\nprobe.configure(\'off\')')
    print(json.dumps(run(experiment, args.phase, args.source_gate), ensure_ascii=False))


if __name__ == '__main__':
    main()
