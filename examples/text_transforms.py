"""Static Python scene definitions consumed by tools/build_demo.py.

The host executes ManimGL's actual Transform. The game receives only compiled
geometry and shader resources, never this Python-3 program or the Manim runtime.
"""
from pathlib import Path

SONG_FONT = Path(__file__).resolve().parents[1] / "tools/reference/fonts/PyreactManimSong-Regular.ttf"

SCENES = (
    {"name": "manimgl_o_to_b", "source": "O", "target": "B", "duration": 2.0,
     "geometry_mode": "curve_slots", "allow_marker_approximation": True},
    {"name": "manimgl_c_to_s", "source": "C", "target": "S", "duration": 2.0,
     "geometry_mode": "curve_slots", "allow_marker_approximation": True},
    {"name": "manimgl_8_to_1", "source": "8", "target": "1", "duration": 2.0,
     "geometry_mode": "curve_slots", "allow_marker_approximation": True},
    {"name": "manimgl_ui_to_ux", "source": "UI", "target": "UX", "duration": 2.0,
     "glyph_height": 3.0, "geometry_mode": "curve_slots", "allow_marker_approximation": True},
    {"name": "manimgl_fraction_swap", "source": r"\frac{a}{b}", "target": r"\frac{b}{a}",
     "input_kind": "latex", "duration": 2.0, "glyph_height": 3.0,
     "geometry_mode": "curve_slots", "allow_marker_approximation": True},
    {"name": "manimgl_power_to_root", "source": "x^2", "target": r"\sqrt{x}",
     "input_kind": "latex", "duration": 2.0, "glyph_height": 3.0,
     "geometry_mode": "curve_slots", "allow_marker_approximation": True},
    {"name": "manimgl_chinese_change", "source": "中文", "target": "变换", "duration": 2.0,
     "font": "Pyreact Manim Song", "font_file": SONG_FONT, "glyph_height": 3.0,
     "geometry_mode": "curve_slots", "allow_marker_approximation": True},
    {"name": "manimgl_chinese_math", "source": "数学", "target": "中文", "duration": 2.0,
     "font": "Pyreact Manim Song", "font_file": SONG_FONT, "glyph_height": 3.0,
     "geometry_mode": "curve_slots", "allow_marker_approximation": True},
)
