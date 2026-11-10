"""2D timeline and geometry regressions independent of Minecraft and Manim."""
import math
from pathlib import Path
import runpy
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pyreact_manim.animation import Animation, Create, FadeIn, FadeOut, Rotate, Shift, Transform
from pyreact_manim.geometry import Circle, Dot, Plot, Rectangle
from pyreact_manim.scene import Scene


class SceneTests(unittest.TestCase):
    def test_parallel_tracks_have_common_start_and_sequential_tracks_keep_end_state(self):
        scene = Scene("test").add("a", Dot()).add("b", Dot())
        scene.play(Shift("a", 2, 0), Shift("b", 0, 4), duration=2)
        scene.play(Shift("a", 0, 2), duration=1)
        center = lambda shape: tuple(sum(p[i] for p in shape.contours[0]) / len(shape.contours[0]) for i in (0, 1))
        self.assertAlmostEqual(center(scene.at(1)["a"])[0], 1)
        self.assertAlmostEqual(center(scene.at(1)["b"])[1], 2)
        self.assertAlmostEqual(center(scene.at(2.5)["a"])[0], 2)
        self.assertAlmostEqual(center(scene.at(2.5)["a"])[1], 1)
        self.assertAlmostEqual(center(scene.at(2.5)["b"])[1], 4)

    def test_rotation_follows_arc_and_does_not_collapse_through_center(self):
        scene = Scene("rotate").add("point", Dot((2, 0)))
        scene.play(Rotate("point", math.pi), duration=1)
        points = scene.at(0.5)["point"].contours[0]
        self.assertAlmostEqual(sum(p[0] for p in points) / len(points), 0)
        self.assertAlmostEqual(sum(p[1] for p in points) / len(points), 2)

    def test_next_animation_starts_from_the_actual_eased_endpoint(self):
        scene = Scene("return").add("point", Dot())
        scene.play(Shift("point", 2, 0, easing=lambda t: 4 * t * (1 - t)), duration=1)
        scene.play(Shift("point", 0, 2), duration=1)
        middle = scene.at(0.5)["point"].contours[0]
        after = scene.at(1.5)["point"].contours[0]
        self.assertAlmostEqual(sum(p[0] for p in middle) / len(middle), 2)
        self.assertAlmostEqual(sum(p[0] for p in after) / len(after), 0)
        self.assertAlmostEqual(sum(p[1] for p in after) / len(after), 1)
        scene.export()

    def test_create_keeps_topology_and_reveals_by_arc_length(self):
        curve = Plot(lambda x: x, (0, 2), samples=8)
        scene = Scene("create").add("curve", curve).play(Create("curve"), duration=1)
        initial = scene.at(0)["curve"].contours[0]
        self.assertEqual(set(initial), {(0.0, 0.0)})
        for time in (0, 0.01, 0.25, 0.5, 0.99, 1):
            self.assertEqual(len(scene.at(time)["curve"].contours[0]), 16)
        midpoint = scene.at(0.5)["curve"].contours[0]
        self.assertLess(max(p[0] for p in midpoint), 1.05)
        self.assertEqual(scene.at(1)["curve"].contours, curve.contours)

    def test_fade_in_hides_until_its_start_and_can_restore_after_fade_out(self):
        scene = Scene("fade").add("circle", Circle(fill=(1, 1, 1, 0.5)))
        scene.wait(1).play(FadeIn("circle"), duration=1)
        self.assertEqual(scene.at(0.5)["circle"].fill[3], 0)
        self.assertAlmostEqual(scene.at(1.5)["circle"].fill[3], 0.25)
        scene.play(FadeOut("circle"), duration=1).play(FadeIn("circle"), duration=1)
        self.assertEqual(scene.at(3)["circle"].fill[3], 0)
        self.assertEqual(scene.at(4)["circle"].fill[3], 0.5)

    def test_polygon_morph_resamples_target_without_changing_vertex_count(self):
        scene = Scene("morph").add("shape", Circle(samples=64))
        scene.play(Transform("shape", Rectangle()), duration=1)
        result = scene.export()
        self.assertEqual(len(result["frames"][-1]["paths"][0]["contours"][0]), 64)
        for x, y in result["frames"][-1]["paths"][0]["contours"][0]:
            self.assertTrue(abs(abs(x) - 1) < 1e-10 or abs(abs(y) - 1) < 1e-10)

    def test_sparse_rectangle_morphs_to_a_full_circle_and_promotes_prior_frames(self):
        circle = Circle(samples=64)
        scene = Scene("reverse_morph").add("shape", Rectangle())
        scene.wait(0.5).play(Transform("shape", circle), duration=1)
        # Authoring state stays sparse until the transform; compile-time promotion
        # also covers the static hold before it starts.
        self.assertEqual(len(scene.at(0)["shape"].contours[0]), 4)
        result = scene.export()
        for frame in result["frames"]:
            self.assertEqual(len(frame["paths"][0]["contours"][0]), 64)
        start = result["frames"][0]["paths"][0]["contours"][0]
        for x, y in start:
            self.assertTrue(abs(abs(x) - 1) < 1e-10 or abs(abs(y) - 1) < 1e-10)
        end = result["frames"][-1]["paths"][0]["contours"][0]
        for (x, y), (expected_x, expected_y) in zip(end, circle.contours[0]):
            self.assertAlmostEqual(math.hypot(x, y), 1)
            self.assertAlmostEqual(x, expected_x)
            self.assertAlmostEqual(y, expected_y)

    def test_invalid_easing_endpoint_does_not_mutate_the_timeline(self):
        scene = Scene("invalid_easing").add("point", Dot())
        with self.assertRaises(ValueError):
            scene.play(Shift("point", 1, 0, easing=lambda t: float("nan")))
        self.assertEqual(scene.cursor, 0)
        self.assertEqual(scene._clips, [])

    def test_intermediate_contour_split_is_rejected_before_compilation(self):
        from dataclasses import replace
        scene = Scene("split").add("point", Dot())
        def split(shape, alpha):
            return replace(shape, contours=shape.contours * (2 if 0 < alpha < 1 else 1))
        scene.play(Animation("point", split), duration=1)
        with self.assertRaisesRegex(ValueError, "contour count"):
            scene.export()

    def test_conflicting_parallel_tracks_fail_without_mutating_timeline(self):
        scene = Scene("conflict").add("point", Dot())
        with self.assertRaises(ValueError):
            scene.play(Shift("point", 1, 0), Shift("point", 2, 0))
        self.assertEqual(scene.cursor, 0)
        self.assertEqual(scene._clips, [])

    def test_all_bundled_2d_examples_fit_compiler_budgets(self):
        examples = runpy.run_path(str(ROOT / "examples/basic_2d.py"))["build_scenes"]()
        self.assertEqual(len(examples), 2)
        for example in examples:
            data = example.export()
            self.assertEqual(data["frames"][0]["time"], 0)
            self.assertEqual(data["frames"][-1]["time"], data["duration"])


if __name__ == "__main__":
    unittest.main()
