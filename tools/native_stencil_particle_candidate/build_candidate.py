"""Offline, composable installation of independently named particle materials."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAMESPACE = uuid.UUID('823171f9-4ce2-4d1c-bb24-ab8a96ddfd24')
ROLES = ('base', 'bit64', 'bit128', 'reference', 'reference_opaque')
PREFIX = 'pmanim_particle_candidate_'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')


def validate_layout(viewport, roi):
    if (len(viewport) != 2 or len(roi) != 4
            or any(type(value) is not int for value in tuple(viewport)+tuple(roi))
            or min(viewport) < 1 or max(viewport) > 4095 or min(roi) < 0):
        raise ValueError('Expected integer viewport and ROI within 12-bit dimensions')
    x, y, width, height = roi
    if width < 4 or width % 4 or height < 1 or x+width > viewport[0] or y+height > viewport[1]:
        raise ValueError('Static source ROI must fit the viewport and contain horizontal four-pixel lanes')
    if width*height//4 > 524288:
        raise ValueError('Static candidate remains bounded to the frozen 512 KiB upload limit')


def material(role):
    reference = role.startswith('reference')
    value = {'vertexShader': 'shaders/glsl/'+PREFIX+'quad.vertex',
             'fragmentShader': 'shaders/glsl/'+PREFIX+role+'.fragment',
             'vertexFields': [{'field': 'Position'}, {'field': 'Color'}, {'field': 'UV0'}],
             'states': ['Blending', 'DisableCulling', 'DisableDepthTest', 'DisableDepthWrite'],
             'blendSrc': 'One' if reference or role != 'base' else 'SourceAlpha',
             'blendDst': 'Zero' if reference else ('OneMinusSrcAlpha' if role == 'base' else 'One'),
             'alphaSrc': 'One' if reference else 'Zero',
             'alphaDst': 'Zero' if reference else 'One', 'msaaSupport': 'Both'}
    if not reference:
        value['states'].append('DisableAlphaWrite')
    if role in ('bit64', 'bit128'):
        mask = 64 if role == 'bit64' else 128
        face = {'stencilFunc': 'Equal', 'stencilFailOp': 'Keep',
                'stencilDepthFailOp': 'Keep', 'stencilPassOp': 'Keep'}
        value.update(frontFace=dict(face), backFace=dict(face), stencilRef=mask,
                     stencilReadMask=mask, stencilWriteMask=0)
        value['states'].append('EnableStencilTest')
    return value


def fragment(role, viewport, roi):
    declarations = ('const vec2 VIEWPORT = vec2(%s);\nconst vec2 ORIGIN = vec2(%s);\n'
                    'const vec2 EXTENT = vec2(%s);\n' %
                    (', '.join(str(float(n)) for n in viewport),
                     ', '.join(str(float(n)) for n in roi[:2]),
                     ', '.join(str(float(n)) for n in roi[2:])))
    if role.startswith('reference'):
        alpha = 'mod(11.0*pos.x + 31.0*pos.y + 211.0, 256.0)' if role == 'reference' else '255.0'
        output = ('vec3 rgb = mod(vec3(33.0,73.0,151.0)*pos.x + vec3(17.0,19.0,47.0)*pos.y'
                  ' + vec3(13.0,41.0,97.0),256.0);\n'
                  '    gl_FragColor = vec4(rgb, '+alpha+')/255.0;')
    else:
        output = 'gl_FragColor = '+{'base': 'vec4(0.0,0.0,0.0,192.0/255.0)',
                  'bit64': 'vec4(64.0/255.0,0.0,0.0,1.0)',
                  'bit128': 'vec4(128.0/255.0,0.0,0.0,1.0)'}[role]+';'
    return ('// __multiversion__\nprecision highp float;\n#include "fragmentVersionCentroid.h"\n'+declarations+
            'void main() {\n    vec2 pos = floor(vec2(gl_FragCoord.x, VIEWPORT.y-gl_FragCoord.y))-ORIGIN;\n'
            '    if (min(pos.x,pos.y)<0.0 || pos.x>=EXTENT.x || pos.y>=EXTENT.y) discard;\n    '+output+'\n}\n')


def effect(template, role):
    value = copy.deepcopy(template)
    particle = value['particleeffect']
    particle.update(materialname={'value': PREFIX+role}, activetime={'value': '0.0'},
        colorfade=[{'color': '1.0 1.0 1.0 1.0', 'time': '0.0%'},
                   {'color': '1.0 1.0 1.0 1.0', 'time': '100.0%'}],
        direction={'min': '0.0 0.0 0.0', 'max': '0.0 0.0 0.0', 'value': 'Direction'},
        velocity={'min': '0.0', 'max': '0.0'}, constantforce={'value': '0.0 0.0 0.0'},
        emissionrate={'min': '20.0', 'max': '20.0'}, numparticles={'value': '1'},
        emittersize={'value': '0.0 0.0 0.0'}, emittertype={'value': 'Box'},
        particlesize={'min': '4.0 4.0', 'max': '4.0 4.0'},
        timetolive={'min': '999.0', 'max': '999.0'}, sizedelta=[],
        enabletexture={'enable': True}, texture={'name': 'textures/stencil_large/white'},
        layer=12 if role.startswith('reference') else 13+('base','bit64','bit128').index(role))
    return value


def install(project, game_exe, viewport=(720, 1080), roi=(8, 128, 512, 512)):
    """Modify only a fresh generated project, never frozen source or installed resources."""
    project, game_exe = Path(project).resolve(), Path(game_exe).resolve()
    validate_layout(viewport, roi)
    if (ROOT/'.runtime').resolve() not in project.parents:
        raise ValueError('Candidate output must be a generated project below this repository .runtime')
    resource, package = project/'resource_pack', project/'behavior_pack/stencil_large'
    receipt_path = project/'particle_candidate_receipt.json'
    if receipt_path.exists() or (package/'particle_candidate_runtime.py').exists():
        raise ValueError('Particle candidate must be installed exactly once in a fresh generated project')
    frozen = [package/'runtime.py', package/'integrated_runtime.py']
    if not all(path.is_file() for path in frozen) or not (resource/'textures/stencil_large/white.png').is_file():
        raise ValueError('Build the existing integrated carrier before installing the candidate')
    native = game_exe.parent/'data/resource_packs/vanilla_netease'
    inputs = {'sfx': native/'materials/sfx.material',
              'particles': native/'materials/particles_netease.material',
              'template': native/'effects/emote/xy_s2blackhole_emote_1.json'}
    raw = {name: path.read_bytes() for name, path in inputs.items()}
    particles = json.loads(raw['particles'].decode('utf-8-sig'))
    template = json.loads(raw['template'].decode('utf-8-sig'))
    if 'common_particle' not in particles['materials'] or 'particleeffect' not in template:
        raise ValueError('Installed China-particle source contract is missing')
    if any(PREFIX+role in particles['materials'] for role in ROLES):
        raise ValueError('Installed source already contains a candidate material name')
    probe_path = project/'probe_resources.json'
    probe = json.loads(probe_path.read_text(encoding='utf-8'))
    frozen_hashes = {path.relative_to(project).as_posix(): sha(path.read_bytes()) for path in frozen}
    material_path = resource/'materials/particles_netease.material'
    if material_path.exists():
        raise ValueError('A previous particle overlay exists; compose before another particle customization')
    old_sfx = resource/'materials/sfx.material'
    old_sfx_hash = sha(old_sfx.read_bytes()) if old_sfx.exists() else None
    generated = []
    for role in ROLES:
        particles['materials'][PREFIX+role] = material(role)
        path = resource/('effects/pmanim_particle_candidate/'+role+'.json')
        write_json(path, effect(template, role))
        generated.append(path)
        path = resource/('shaders/glsl/'+PREFIX+role+'.fragment')
        path.write_text(fragment(role, viewport, roi), encoding='utf-8')
        generated.append(path)
    write_json(material_path, particles)
    generated.append(material_path)
    copies = {resource/('shaders/glsl/'+PREFIX+'quad.vertex'): HERE/'particle.vertex',
              package/'particle_candidate_runtime.py': HERE/'runtime.py',
              package/'modMain.py': HERE/'modMain.py'}
    for target, source in copies.items():
        target.write_bytes(source.read_bytes())
        generated.append(target)
    config = package/'particle_candidate_config.py'
    config.write_text('# -*- coding: utf-8 -*-\nVIEWPORT = %r\nROI = %r\n' % (tuple(viewport), tuple(roi)), encoding='utf-8')
    generated.append(config)
    if old_sfx.exists():
        old_sfx.unlink()
    for folder in ('behavior_pack', 'resource_pack'):
        path = project/folder/'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        identity = repr((tuple(viewport), tuple(roi)))+'/'+folder
        manifest['header'].update(name='Independent particle carrier '+folder,
            uuid=str(uuid.uuid5(NAMESPACE, identity+'/header')), version=[0, 1, 0])
        for index, item in enumerate(manifest['modules']):
            item.update(uuid=str(uuid.uuid5(NAMESPACE, identity+'/'+str(index))), version=[0, 1, 0])
        write_json(path, manifest)
        generated.append(path)
    receipt = {'schema': 'static_independent_particle_candidate_v1', 'viewport': list(viewport),
        'roi': list(roi), 'logical_bytes': roi[2]*roi[3]//4, 'roles': list(ROLES),
        'sfx_overlay_omitted': True, 'removed_sfx_overlay_sha256': old_sfx_hash,
        'native_sfx_sha256': sha(raw['sfx']), 'native_particle_entries_preserved': True,
        'source_files': {name: {'path': str(inputs[name]), 'sha256': sha(data)} for name, data in raw.items()},
        'frozen_runtime_hashes': frozen_hashes,
        'runtime_file_writes': False, 'private_texture_upload': False, 'continuous_update': False,
        'static_layout_only': True, 'maximum_simultaneous_particles': 4,
        'native_verified': False, 'after_weather_order_verified': False,
        'native_shadow_fix_included': False,
        'source_hashes': {path.name: sha(path.read_bytes()) for path in (HERE/'build_candidate.py', HERE/'runtime.py', HERE/'modMain.py', HERE/'particle.vertex')},
        'hashes': {path.relative_to(project).as_posix(): sha(path.read_bytes()) for path in generated}}
    for relative, digest in frozen_hashes.items():
        if sha((project/relative).read_bytes()) != digest:
            raise RuntimeError('Candidate changed frozen runtime: '+relative)
    probe['particle_candidate'] = receipt
    probe['runtime']['class'] = 'stencil_large.particle_candidate_runtime.ProbeSystem'
    # Prior build receipts remain historical; this receipt describes the final composition.
    probe['changed_sfx_materials'] = []
    probe['known_fixture'] = {'material': PREFIX+'reference', 'layer': 12,
                              'independent_particle': True, 'varying_alpha_optional': True}
    write_json(probe_path, probe)
    write_json(receipt_path, receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--game-exe', type=Path, required=True)
    parser.add_argument('--viewport', type=int, nargs=2, default=(720, 1080))
    parser.add_argument('--roi', type=int, nargs=4, default=(8, 128, 512, 512))
    args = parser.parse_args()
    print(json.dumps(install(args.project, args.game_exe, args.viewport, args.roi), indent=2))
