"""Offline candidate-install regressions using miniature installed asset fixtures."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
ROLES = ('base', 'bit64', 'bit128', 'reference', 'reference_opaque')
PREFIX = 'pmanim_particle_candidate_'
FROZEN = ('behavior_pack/stencil_large/runtime.py',
          'behavior_pack/stencil_large/integrated_runtime.py',
          'resource_pack/materials/terrain.material',
          'resource_pack/materials/postprocess.material',
          'resource_pack/shaders/glsl/stencil_integrated_restore.fragment')


def _builder():
    spec = importlib.util.spec_from_file_location(
        'particle_candidate_builder_under_test', HERE / 'build_candidate.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (dict, list)):
        path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    else:
        path.write_bytes(value)


def _tree(path):
    return {file.relative_to(path).as_posix(): file.read_bytes()
            for file in path.rglob('*') if file.is_file()}


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _installed(root):
    """Mimic the relevant 467018 paths without using the actual game install."""
    game = root / 'fake_client/Minecraft.Windows.exe'
    _write(game, b'offline executable placeholder\n')
    resource = game.parent / 'data/resource_packs/vanilla_netease'
    sfx = {'materials': {'version': '1.0.0',
        'billboard_base': {'vertexShader': 'shaders/sfx.vertex'},
        'sequence:billboard_base': {'fragmentShader': 'shaders/sfx.fragment'},
        'sequence_add:sequence': {'blendSrc': 'SourceAlpha', 'blendDst': 'One'},
        'point_sequence:sequence': {'samplerStates': [
            {'samplerIndex': 0, 'textureFilter': 'Point'}]},
        'point_sequence_add:point_sequence': {'blendSrc': 'SourceAlpha', 'blendDst': 'One'},
        'unrelated_native_sfx:billboard_base': {'defines': ['KEEP_THIS_NATIVE_SFX']}}}
    particle = {'materials': {'version': '1.0.0',
        'common_particle': {
            'vertexShader': 'shaders/common_particle.vertex',
            'fragmentShader': 'shaders/common_particle.fragment',
            'vertexFields': [{'field': name} for name in ('Position', 'Color', 'UV0')],
            'states': ['Blending', 'DisableCulling', 'DisableDepthWrite'],
            'samplerStates': [{'samplerIndex': 0, 'textureWrap': 'Clamp',
                               'textureFilter': 'Bilinear'}],
            'msaaSupport': 'Both'},
        'common_particle_add:common_particle': {'blendSrc': 'SourceAlpha', 'blendDst': 'One'},
        'common_particle_blend:common_particle': {},
        'point_common_particle:common_particle': {'samplerStates': [
            {'samplerIndex': 0, 'textureFilter': 'Point'}]},
        'unrelated_native_particle:common_particle': {'defines': ['KEEP_NATIVE_PARTICLE']}}}
    effect = {'particleeffect': {
        'direction': {'max': '0.0 0.0 0.0', 'min': '0.0 0.0 0.0', 'value': 'Direction'},
        'velocity': {'max': '0.0', 'min': '0.0'},
        'emissionrate': {'max': '10.0', 'min': '10.0'},
        'numparticles': {'value': '1'},
        'particlesize': {'max': '0.5 0.5', 'min': '0.5 0.5'},
        'timetolive': {'max': '999.0', 'min': '999.0'},
        'emittersize': {'value': '0.0 0.0 0.0'},
        'emittertype': {'value': 'Box'},
        'texture': {'name': 'textures/particle/sun'},
        'colorfade': [{'color': '1.0 1.0 1.0 1.0', 'time': '0.0%'}],
        'enabletexture': {'enable': True}, 'pointFiltering': True, 'layer': 1}}
    _write(resource / 'materials/sfx.material', sfx)
    _write(resource / 'materials/particles_netease.material', particle)
    _write(resource / 'effects/emote/xy_s2blackhole_emote_1.json', effect)
    return game, particle


def _project(root, include_package=True):
    project = root / 'project'
    _write(project / '.pmanim_stencil_large_probe.json',
           {'kind': 'weather_stencil_large_v1', 'version': 1})
    _write(project / 'probe_resources.json', {
        'kind': 'weather_stencil_integrated_v1', 'version': 1,
        'runtime': {'package': 'stencil_large', 'entrypoint': 'stencil_large.modMain',
                    'system_namespace': 'pmanim_stencil_integrated', 'system_name': 'probe'},
        'native_compatibility': {'variant': 'carrier'},
        'frozen_bulk_runtime_sha256': _sha(b'# original bulk runtime\n'),
        'sentinel_receipt_metadata': {'preserve': True}})
    _write(project / 'resource_pack/materials/sfx.material',
           {'materials': {'version': '1.0.0',
                          'sequence:billboard_base': {'defines': ['FROZEN_SHARED_OVERRIDE']}}})
    _write(project / 'resource_pack/materials/terrain.material',
           {'materials': {'version': '1.0.0', 'frozen_transport_geometry': {'stencilRef': 64}}})
    _write(project / 'resource_pack/materials/postprocess.material',
           {'frozen_restore': {'fragmentShader': 'shaders/glsl/stencil_integrated_restore.fragment'}})
    _write(project / 'resource_pack/materials/common.json', [
        {'path': 'materials/sfx.material'}, {'path': 'materials/particles_netease.material'}])
    _write(project / 'resource_pack/shaders/glsl/stencil_integrated_restore.fragment',
           b'// unchanged original restore shader\n')
    _write(project / 'resource_pack/textures/stencil_large/white.png',
           bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
                         '0000000b49444154789c63f80f040009fb03fd2a86e38a0000000049454e44ae426082'))
    if include_package:
        _write(project / 'behavior_pack/stencil_large/runtime.py', b'# original bulk runtime\n')
        _write(project / 'behavior_pack/stencil_large/integrated_runtime.py',
               b'# original integrated runtime\n')
        _write(project / 'behavior_pack/stencil_large/modMain.py', b'# original mod registration\n')
        _write(project / 'behavior_pack/stencil_large/known_fixture.py',
               b'# original FrameAni known fixture\n')
    for folder in ('resource_pack', 'behavior_pack'):
        _write(project / folder / 'manifest.json', {'format_version': 1,
            'header': {'name': 'fake integrated ' + folder, 'uuid': folder, 'version': [0, 1, 0]},
            'modules': [{'type': 'resources' if folder == 'resource_pack' else 'data',
                         'uuid': folder + '_module', 'version': [0, 1, 0]}]})
    return project


class ParticleCandidateBuilderTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='particle_candidate_test_', dir=str(runtime))
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.game, self.native_particles = _installed(self.root)
        self.project = _project(self.root)
        self.builder = _builder()

    def test_private_materials_preserve_every_native_entry_and_frozen_file(self):
        sources_before = _tree(self.game.parent)
        frozen_before = {name: (self.project / name).read_bytes() for name in FROZEN}
        registration_before = (self.project / 'behavior_pack/stencil_large/modMain.py').read_bytes()

        self.builder.install(self.project, self.game)

        self.assertEqual(_tree(self.game.parent), sources_before)
        for name, original in frozen_before.items():
            with self.subTest(frozen=name):
                self.assertEqual((self.project / name).read_bytes(), original)
        self.assertNotEqual((self.project / 'behavior_pack/stencil_large/modMain.py').read_bytes(),
                            registration_before)
        self.assertFalse((self.project / 'resource_pack/materials/sfx.material').exists())
        generated = json.loads((self.project / 'resource_pack/materials/particles_netease.material').read_text(
            encoding='utf-8'))['materials']
        for name, definition in self.native_particles['materials'].items():
            with self.subTest(native_material=name):
                self.assertEqual(generated[name], definition)
        additions = set(generated) - set(self.native_particles['materials'])
        self.assertEqual({name.split(':', 1)[0] for name in additions},
                         {PREFIX + role for role in ROLES})
        self.assertEqual(len(additions), len(ROLES))

    def test_effects_select_unique_private_materials_and_use_stable_single_particles(self):
        self.builder.install(self.project, self.game)
        effects = {}
        for path in (self.project / 'resource_pack/effects').rglob('*.json'):
            particle = json.loads(path.read_text(encoding='utf-8')).get('particleeffect', {})
            selected = particle.get('materialname', {}).get('value', '')
            if selected.startswith(PREFIX):
                self.assertNotIn(selected, effects, 'Each private role requires its own effect resource')
                effects[selected] = particle
        self.assertEqual(set(effects), {PREFIX + role for role in ROLES})
        for name, particle in effects.items():
            with self.subTest(role=name):
                self.assertEqual(int(particle['numparticles']['value']), 1)
                self.assertEqual(float(particle['velocity']['min']), 0)
                self.assertEqual(float(particle['velocity']['max']), 0)
                self.assertEqual(particle['particlesize']['min'], particle['particlesize']['max'])
                self.assertGreater(min(map(float, particle['particlesize']['min'].split())), 0)
                self.assertGreaterEqual(float(particle['timetolive']['min']), 999)
                self.assertNotIn('ani', particle['texture'])

    def test_receipt_and_probe_metadata_are_written_without_erasing_prior_metadata(self):
        self.builder.install(self.project, self.game)
        receipt_path = self.project / 'particle_candidate_receipt.json'
        self.assertTrue(receipt_path.is_file())
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        self.assertIn('particle', receipt['schema'])
        self.assertIn('candidate', receipt['schema'])
        self.assertEqual(receipt['viewport'], [720, 1080])
        self.assertEqual(receipt['roi'], [8, 128, 512, 512])
        self.assertEqual(receipt['logical_bytes'], 65536)
        self.assertEqual(set(receipt['roles']), set(ROLES))
        self.assertTrue(receipt['sfx_overlay_omitted'])
        self.assertTrue(receipt['native_particle_entries_preserved'])
        self.assertFalse(receipt['native_verified'])
        self.assertFalse(receipt['after_weather_order_verified'])
        self.assertFalse(receipt['native_shadow_fix_included'])
        self.assertFalse(receipt['runtime_file_writes'])
        for relative, digest in receipt['hashes'].items():
            with self.subTest(generated_hash=relative):
                self.assertEqual(_sha((self.project / relative).read_bytes()), digest)
        for relative, digest in receipt['frozen_runtime_hashes'].items():
            with self.subTest(frozen_hash=relative):
                self.assertEqual(_sha((self.project / relative).read_bytes()), digest)
        self.assertEqual(set(receipt['frozen_runtime_hashes']), set(FROZEN[:2]))
        for name, source in receipt['source_files'].items():
            with self.subTest(source_hash=name):
                self.assertEqual(_sha(Path(source['path']).read_bytes()), source['sha256'])
        metadata = json.loads((self.project / 'probe_resources.json').read_text(encoding='utf-8'))
        self.assertEqual(metadata['sentinel_receipt_metadata'], {'preserve': True})
        self.assertEqual(metadata['particle_candidate'], receipt)
        self.assertEqual(metadata['runtime']['class'], 'stencil_large.particle_candidate_runtime.ProbeSystem')

    def test_nondefault_valid_layout_is_compiled_into_each_private_fragment(self):
        viewport, roi = (800, 1000), (12, 160, 256, 128)
        receipt = self.builder.install(self.project, self.game, viewport=viewport, roi=roi)
        self.assertEqual(receipt['viewport'], list(viewport))
        self.assertEqual(receipt['roi'], list(roi))
        self.assertEqual(receipt['logical_bytes'], 8192)
        config = (self.project / 'behavior_pack/stencil_large/particle_candidate_config.py').read_text(
            encoding='utf-8')
        self.assertIn('VIEWPORT = ' + repr(viewport), config)
        self.assertIn('ROI = ' + repr(roi), config)
        fragments = self.project / 'resource_pack/shaders/glsl'
        for role in ROLES:
            with self.subTest(role=role):
                shader = (fragments / (PREFIX + role + '.fragment')).read_text(encoding='utf-8')
                self.assertIn('const vec2 VIEWPORT = vec2(800.0, 1000.0);', shader)
                self.assertIn('const vec2 ORIGIN = vec2(12.0, 160.0);', shader)
                self.assertIn('const vec2 EXTENT = vec2(256.0, 128.0);', shader)
                self.assertNotIn('EXTRA_VECTOR', shader)

    def test_invalid_static_layout_is_rejected_before_project_mutation(self):
        invalid = (((0, 1080), (8, 128, 512, 512)),
                   ((720, 1080), (-1, 128, 512, 512)),
                   ((720, 1080), (8, 128, 713, 512)),
                   ((720, 1080), (8, 128, 512, 953)),
                   ((720, 1080), (8, 128, 3, 512)),
                   ((720, 1080), (8, 128, 512, 0)))
        before = _tree(self.project)
        for viewport, roi in invalid:
            with self.subTest(viewport=viewport, roi=roi):
                with self.assertRaises((ValueError, RuntimeError)):
                    self.builder.install(self.project, self.game, viewport=viewport, roi=roi)
                self.assertEqual(_tree(self.project), before)

    def test_second_install_is_rejected_without_changing_the_first_result(self):
        self.builder.install(self.project, self.game)
        installed = _tree(self.project)
        with self.assertRaises((ValueError, RuntimeError)):
            self.builder.install(self.project, self.game)
        self.assertEqual(_tree(self.project), installed)

    def test_missing_integrated_runtime_is_rejected_before_mutation(self):
        (self.project / 'behavior_pack/stencil_large/integrated_runtime.py').unlink()
        before = _tree(self.project)
        with self.assertRaises((ValueError, RuntimeError)):
            self.builder.install(self.project, self.game)
        self.assertEqual(_tree(self.project), before)

    def test_project_outside_repository_runtime_is_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory(prefix='particle_candidate_external_') as outside:
            project = _project(Path(outside))
            before = _tree(project)
            with self.assertRaises((ValueError, RuntimeError)):
                self.builder.install(project, self.game)
            self.assertEqual(_tree(project), before)


if __name__ == '__main__':
    unittest.main()
