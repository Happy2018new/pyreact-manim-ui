"""Static Python scene definitions consumed by tools/build_demo.py.

The host executes ManimGL's actual Transform. The game receives only compiled
geometry and shader resources, never this Python-3 program or the Manim runtime.
"""

SCENES = (
    {"name": "manimgl_o_to_b", "source": "O", "target": "B", "duration": 2.0},
    {"name": "manimgl_c_to_s", "source": "C", "target": "S", "duration": 2.0},
    {"name": "manimgl_8_to_1", "source": "8", "target": "1", "duration": 2.0,
     "geometry_mode": "curve_slots", "allow_marker_approximation": True},
    {"name": "manimgl_ui_to_ux", "source": "UI", "target": "UX", "duration": 2.0,
     "glyph_height": 3.0, "geometry_mode": "curve_slots", "allow_marker_approximation": True},
)
