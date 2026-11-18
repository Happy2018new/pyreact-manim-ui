"""Host-only native .skinning name resolution; original pixel gates stay strict.

The client may report the resolved skinning variant of the three native material
names. Keep every raw snapshot unchanged and resolve only those six exact names
in copies passed to the original verifier. No general suffix stripping is used.
"""
import importlib.util
from pathlib import Path


_SPEC = importlib.util.spec_from_file_location(
    'integrated_outline_original_strict_verifier', Path(__file__).with_name('verify.py'))
_ORIGINAL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ORIGINAL)
MATERIALS = ('entity_alphatest_netease', 'netease_entity_alphatest_outline_base',
             'netease_entity_alphatest_outline')
CONTROLLERS = ('controller.render.pmanim_integrated_outline.base',
               'controller.render.pmanim_integrated_outline.outline')
EXACT_VARIANTS = {name: name for name in MATERIALS}
EXACT_VARIANTS.update({name + '.skinning': name for name in MATERIALS})


def _resolved_snapshot(raw):
    values = raw.get('registered_material_values')
    canonical = [EXACT_VARIANTS.get(value) for value in values] if isinstance(values, (list, tuple)) else []
    recipe_present = (len(canonical) == len(MATERIALS) and None not in canonical
                      and set(canonical) == set(MATERIALS))
    controllers = raw.get('registered_render_controllers')
    controllers_present = (isinstance(controllers, (list, tuple))
                           and all(value in controllers for value in CONTROLLERS))
    resolved = dict(raw)
    resolved['native_material_recipe_present'] = recipe_present
    resolved['native_render_controllers_present'] = controllers_present
    evidence = {'raw_material_values': values, 'canonical_material_values': canonical,
                'raw_recipe_present_flag': raw.get('native_material_recipe_present'),
                'resolved_recipe_present': recipe_present,
                'resolved_controllers_present': controllers_present}
    return resolved, evidence


def compare_snapshots(off_before, on, off_after):
    """Resolve exact native variants in copies; preserve all other original checks."""
    pairs = [_resolved_snapshot(raw) for raw in (off_before, on, off_after)]
    result = _ORIGINAL.compare_snapshots(*(pair[0] for pair in pairs))
    result.update({'host_resolution': 'exact_known_native_materials_optional_dot_skinning_v1',
                   'raw_snapshots_modified': False,
                   'material_resolution': [pair[1] for pair in pairs]})
    return result


def compare_outline(off_before, on, off_after, roi, bounds=None, minimum_pixels=24):
    """Delegate unchanged original pixel gates, including whole-window <=1% drift."""
    return _ORIGINAL.compare_outline(off_before, on, off_after, roi, bounds, minimum_pixels)
