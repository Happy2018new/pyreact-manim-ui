"""Add the layer-12 RGBA reference to an already generated test project."""
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
MATERIAL = 'sequence_add:sequence'
EFFECT = 'stencil_integrated_known_fixture'
SHADER = EFFECT + '.fragment'


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n',
                    encoding='utf-8', newline='\n')


def add_known_fixture(project):
    """Use the non-point additive route, separate from the three carrier routes."""
    project = Path(project)
    resource = project / 'resource_pack'
    effect_dir = resource / 'effects'
    material_path = resource / 'materials/sfx.material'
    sfx = json.loads(material_path.read_text(encoding='utf-8-sig'))
    material = sfx['materials'][MATERIAL]
    if 'fragmentShader' in material:
        raise ValueError('The native sequence_add route is already overridden')
    material.update({
        'vertexShader': 'shaders/glsl/stencil_large_effect.vertex',
        'fragmentShader': 'shaders/glsl/' + SHADER,
        'vertexFields': [{'field': 'Position'}, {'field': 'UV0'}],
        '+states': ['Blending', 'DisableCulling', 'DisableDepthTest', 'DisableDepthWrite'],
        '-states': ['DisableColorWrite', 'DisableRGBWrite', 'DisableAlphaWrite',
                    'EnableAlphaToCoverage', 'EnableStencilTest', 'StencilWrite'],
        '-defines': ['ALPHA_TEST'],
        'blendSrc': 'One', 'blendDst': 'Zero',
        'alphaSrc': 'One', 'alphaDst': 'Zero',
        'msaaSupport': 'Both',
    })
    _write_json(material_path, sfx)

    config = json.loads((effect_dir / 'stencil_large_base.json').read_text(encoding='utf-8'))
    config['frameeffect'].update(layer=12, point_filtering=False, blend_mode=2)
    _write_json(effect_dir / (EFFECT + '.json'), config)
    project_files = {
        resource / 'shaders/glsl' / SHADER: HERE / 'known_fixture.fragment',
        project / 'behavior_pack/stencil_large/known_fixture.py': HERE / 'known_fixture_runtime.py',
    }
    hashes = {}
    for target, source in project_files.items():
        contents = source.read_bytes()
        target.write_bytes(contents)
        hashes[target.relative_to(project).as_posix()] = hashlib.sha256(contents).hexdigest()
    return {'material': MATERIAL, 'layer': 12, 'prepared_reference': 'controlled native RGBA',
            'varying_alpha_optional': True, 'hashes': hashes}
