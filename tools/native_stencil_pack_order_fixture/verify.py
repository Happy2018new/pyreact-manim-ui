"""Exact interior oracle for the extra pack's independent JSON UI canary."""
import numpy as np


COLORS = ((239, 43, 67), (23, 211, 101), (37, 83, 241), (251, 197, 29))


def verify(image, position=(632, 160)):
    rgb = np.asarray(image.convert('RGB') if hasattr(image, 'convert') else image)
    x, y = (int(value) for value in position)
    if rgb.ndim != 3 or rgb.shape[2] < 3 or x < 0 or y < 0 or x+64 > rgb.shape[1] or y+32 > rgb.shape[0]:
        raise ValueError('Canary must be fully inside the captured native-size image')
    checked = errors = 0
    patches = []
    for index, color in enumerate(COLORS):
        patch = rgb[y+2:y+30, x+16*index+2:x+16*index+14, :3]
        bad = np.any(patch != np.asarray(color), axis=2)
        count = int(np.count_nonzero(bad))
        checked += int(bad.size)
        errors += count
        patches.append({'index': index, 'expected_rgb': list(color), 'error_pixels': count,
                        'rect': [x+16*index+2, y+2, 12, 28]})
    return {'schema': 'pack_order_canary_pixel_gate_v1', 'position': [x, y],
            'checked_pixels': checked, 'error_pixels': errors, 'exact': errors == 0,
            'patches': patches, 'ordinary_frameani_compatibility_inferred': False}
