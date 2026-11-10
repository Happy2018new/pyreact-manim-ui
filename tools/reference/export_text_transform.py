"""Export real upstream ManimGL Text-to-Text Transform without launching Minecraft."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pyreact_manim.reference import ExportSettings, export_text_transform


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--output", type=Path, required=True,
                        help="Output directory for scene, raw controls and report")
    parser.add_argument("--source", default="O", help="Starting visible text")
    parser.add_argument("--target", default="B", help="Ending visible text")
    parser.add_argument("--name", default="manimgl_o_to_b",
                        help="Scene ID matching [a-z][a-z0-9_]{0,47}")
    parser.add_argument("--font", default="DejaVu Serif", help="Pango family matching --font-file")
    parser.add_argument("--font-file", type=Path, default=ExportSettings.font_file,
                        help="Font file temporarily registered with upstream ManimPango")
    parser.add_argument("--frames", type=int, default=61, help="Number of sampled frames, 2..256")
    parser.add_argument("--duration", type=float, default=2.0, help="Animation duration in seconds")
    parser.add_argument("--tolerance", type=float, default=0.003,
                        help="Maximum quadratic chord error at exported frames, in scene units")
    parser.add_argument("--glyph-height", type=float, default=4.0,
                        help="Independently normalize source and target text to this scene height")
    parser.add_argument("--render-reference", action="store_true",
                        help="Use the actual upstream Camera's standalone OpenGL renderer")
    parser.add_argument("--geometry", choices=("contours", "curve_slots"), default="contours",
                        help="Schema 1 fixed closed contours or schema 2 native directed curve fans")
    parser.add_argument("--allow-marker-approximation", action="store_true",
                        help="Explicitly permit schema 2 previews with reported narrow native float32 skip-window differences")
    args = parser.parse_args()
    settings = ExportSettings(source=args.source, target=args.target, name=args.name,
                              font=args.font, font_file=args.font_file,
                              frame_count=args.frames, duration=args.duration,
                              glyph_height=args.glyph_height, tolerance=args.tolerance,
                              render_reference=args.render_reference, geometry_mode=args.geometry,
                              allow_marker_approximation=args.allow_marker_approximation)
    result = export_text_transform(args.output, settings)
    print(result["scene"])
    print(result["report"])
    print("Vertices per path:", result["data"]["sampling"]["vertices_per_path"])


if __name__ == "__main__":
    main()
