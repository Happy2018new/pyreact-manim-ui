# -*- coding: utf-8 -*-
"""Client-only validation for resources already installed by the host builder.

No native effects are cloned, no native parameters are rewritten, and no native
texture slot is rebound. Call after scene-codec custom processes are inserted.
"""


def install(post, restored_source, physical=(720, 1080)):
    from geometry_atlas_probe.compat_config import CONFIG
    if list(physical) != CONFIG['physical_size']:
        raise ValueError('Compatibility shader physical size differs from runtime')
    if not isinstance(restored_source, (tuple, list)) or len(restored_source) != 2:
        raise ValueError('Expected restored_source=(process_name, final_pass_index)')
    source_name, source_pass = restored_source
    if not isinstance(source_pass, int) or source_pass < 0:
        raise ValueError('Restored source pass must be a nonnegative integer')
    order = post.GetPostProcessOrder()
    if not order or source_name not in order:
        raise RuntimeError('Restored source is absent from the post-process order')
    for effect in ('bloom', 'depthoffield'):
        if effect not in order or order.index(source_name) >= order.index(effect):
            raise RuntimeError('Restored source must precede native effect: ' + effect)
    return {'kind': 'native_compat_chain_receipt_v1', 'order': list(order),
            'restored_source': [source_name, source_pass], 'config': dict(CONFIG),
            'native_effect_parameters_modified': False, 'new_passes_added': 0,
            'chain_order_validated': True,
            'remaining_game_checks': ['source pass is the final enabled restored output before native effects',
                                      'raw T1 is encoded only in the fixed writer ROI',
                                      'native effect state, images, alpha and full payload remain correct']}


def install_alpha_math_fixture(post, restored_source):
    from geometry_atlas_probe.compat_config import ALPHA_PROCESS
    order = post.GetPostProcessOrder()
    if not order or restored_source[0] not in order or 'bloom' not in order:
        raise RuntimeError('Install restored chain before the bloom alpha fixture')
    name = ALPHA_PROCESS['name']
    if name in order:
        raise RuntimeError('Alpha fixture is already installed')
    index = order.index('bloom')
    if order.index(restored_source[0]) >= index:
        raise RuntimeError('Restored source must precede bloom')
    if not post.AddPostProcess(ALPHA_PROCESS, index):
        raise RuntimeError('Alpha math fixture insertion rejected')
    return {'fixture': name, 'enabled': False, 'next_step': 'Wait one render turn, then connect_alpha_math_fixture'}


def connect_alpha_math_fixture(post, restored_source, alpha_byte=-1):
    name = 'pmanim_scene_compat_alpha_math'
    if not post.PostPassResultToOtherPass(restored_source[0], restored_source[1], name, 0, 3):
        raise RuntimeError('Alpha math fixture restored-source connection rejected')
    return set_alpha_math_fixture(post, alpha_byte)


def set_alpha_math_fixture(post, alpha_byte=-1, enabled=True):
    if int(alpha_byte) != alpha_byte or alpha_byte < -1 or alpha_byte > 255:
        raise ValueError('Use -1 identity or an alpha byte 0..255')
    name = 'pmanim_scene_compat_alpha_math'
    if not post.SetParameter(name, 'alpha', [float(alpha_byte), 0., 0., 0.]):
        raise RuntimeError('Alpha math fixture parameter rejected')
    if not post.SetEnableByName(name, bool(enabled)):
        raise RuntimeError('Alpha math fixture enable rejected')
    return {'fixture': name, 'alpha_byte': alpha_byte, 'enabled': bool(enabled),
            'classification': 'synthetic bloom math; not real-world alpha evidence'}


def spawn_translucent_particle(client_api, position):
    particles = client_api.GetEngineCompFactory().CreateParticleSystem(None)
    particle_id = particles.Create('pmanim_scene_compat:translucent', tuple(position), (0., 0., 0.))
    if not particle_id:
        raise RuntimeError('Native translucent particle creation failed')
    return {'particle_id': particle_id, 'position': list(position),
            'resource': 'pmanim_scene_compat:translucent', 'material': 'particles_blend',
            'tint_alpha': .35, 'same_frame_reference_required': True}


def remove_translucent_particle(client_api, particle_id):
    return client_api.GetEngineCompFactory().CreateParticleSystem(None).Remove(particle_id)
