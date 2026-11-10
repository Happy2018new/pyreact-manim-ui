"""Readable formula holds, semantic transport, and continuous title handoffs."""
from collections import Counter
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from showcase_v2 import build_film as film


def glyph_signature(glyph):
    return (glyph["id"], glyph["role"], tuple(glyph["center"]), tuple(glyph["size"]))


class ShowcaseTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.groups = json.loads((ROOT / "tools/showcase_v2/type_data.json").read_text(
            encoding="utf-8"))["groups"]
        cls.code, cls.events = film.make_type(cls.groups)

    def test_formula_motion_is_short_and_followed_by_readable_holds(self):
        self.assertEqual(len(self.events), 21)
        self.assertEqual(self.events[-1]["end"], 120)
        for event in self.events:
            with self.subTest(chapter=event["chapter"], source=event["source"]):
                duration = event["transition_end"] - event["transition_start"]
                self.assertGreaterEqual(event["transition_start"], event["start"])
                self.assertLessEqual(event["transition_end"], event["end"])
                self.assertGreater(event["hold_until"], event["transition_end"])
                self.assertEqual(event["hold_until"], event["target_hold"]["end"])
                self.assertAlmostEqual(event["hold"]["after"],
                                       event["hold_until"] - event["transition_end"])
                if event["chapter"] == "closing":
                    self.assertAlmostEqual(duration, 1.0)
                elif event["chapter"] in ("opening", "finale"):
                    self.assertGreaterEqual(duration, .7)
                    self.assertLessEqual(duration, .9)
                else:
                    self.assertGreaterEqual(duration, .65)
                    self.assertLessEqual(duration, .9)
                    self.assertGreater(event["target_hold"]["duration"], 2.0)
                    self.assertGreaterEqual(event["arc_strength"], .03)
                    self.assertLessEqual(event["arc_strength"], .10)

    def test_review_regions_fit_their_authored_typography_bands(self):
        for event in self.events:
            x0, y0, x1, y1 = event["review_bounds"]
            with self.subTest(chapter=event["chapter"], target=event["target"]):
                self.assertLess(x0, x1)
                self.assertLess(y0, y1)
                if event["chapter"] in ("complex", "calculus", "harmonics"):
                    self.assertGreaterEqual(y0, 1.5)
                    self.assertLessEqual(y1, 3.5)
                elif event["chapter"] == "algebra":
                    self.assertLessEqual(x1 - x0, 11.5)
                    self.assertLessEqual(y1 - y0, 3.0)

    def test_integrals_and_fractions_preserve_body_scale_and_baseline(self):
        for names in (("calculus0", "calculus1", "calculus2"),
                      ("fourier0", "fourier1", "fourier2", "fourier3")):
            layouts = film.chain_layouts(self.groups, names, (0, 2.5), 1.15, 11,
                                          max_height=1.7)
            body = {}
            compared = 0
            for name in names:
                for glyph in layouts[name]:
                    if glyph["role"] != "body":
                        continue
                    key = glyph["id"]
                    value = (*glyph["size"], glyph["center"][1])
                    if key in body:
                        compared += 1
                        for actual, expected in zip(value, body[key]):
                            self.assertAlmostEqual(actual, expected, places=6)
                    else:
                        body[key] = value
            self.assertGreater(compared, 4)

    def test_authored_modes_count_real_shape_changes_separately_from_transport(self):
        modes = Counter(event["transition_mode"] for event in self.events)
        self.assertEqual(modes, {"shape_morph": 18, "matching_transport": 3})
        for event in self.events:
            with self.subTest(source=event["source"], target=event["target"]):
                self.assertEqual(event["tracks"], sum(event[kind + "_tracks"] for kind in
                                 ("shape_morph", "transport", "stationary", "birth", "death")))
                if event["transition_mode"] == "shape_morph":
                    self.assertGreater(event["shape_morph_tracks"], 0)
                else:
                    self.assertEqual(event["shape_morph_tracks"], 0)

    def test_pairs_respect_authored_mode_and_reproduce_both_endpoints(self):
        for event in self.events:
            source = film.layout(self.groups[event["source"]])
            target = film.layout(self.groups[event["target"]])
            pairs = film.pair_glyphs(source, target, event["transition_mode"])
            with self.subTest(source=event["source"], target=event["target"]):
                for index, expected in ((0, source), (1, target)):
                    actual = [pair[index] for pair in pairs if pair[index]["opacity"] > 0]
                    self.assertEqual(Counter(map(glyph_signature, actual)),
                                     Counter(map(glyph_signature, expected)))
                for a, b in pairs:
                    if a["opacity"] == 0 or b["opacity"] == 0:
                        self.assertEqual(a["id"], b["id"])
                        self.assertEqual(a["center"], b["center"])
                        visible, hidden = (a, b) if a["opacity"] else (b, a)
                        for full, small in zip(visible["size"], hidden["size"]):
                            self.assertAlmostEqual(small, full * .84)
                    elif film.pair_kind(a, b) == "shape_morph":
                        self.assertEqual(event["transition_mode"], "shape_morph")
                        self.assertNotEqual(a["id"], b["id"])
                        self.assertNotEqual(a["tile"], b["tile"])
                        self.assertTrue(film.shape_compatible(a, b))
                    else:
                        self.assertEqual((a["id"], a["role"]), (b["id"], b["role"]))

    def test_repeated_symbols_keep_reading_order_and_different_roles_do_not_pair(self):
        base = film.layout(self.groups["calculus0"])[0]

        def glyph(x, role="body"):
            result = deepcopy(base)
            result.update(center=[x, 0], role=role)
            return result

        pairs = film.pair_glyphs([glyph(3), glyph(-3), glyph(0, "superscript")],
                                 [glyph(2), glyph(4), glyph(-2, "denominator")],
                                 mode="matching_transport")
        matched = [(a["center"][0], b["center"][0]) for a, b in pairs
                   if a["opacity"] and b["opacity"]]
        self.assertEqual(matched, [(-3, 2), (3, 4)])
        self.assertEqual(len(pairs), 4)

    def test_shape_mode_accepts_cross_kind_ink_but_protects_rules_and_scripts(self):
        source = film.layout(self.groups["c_universe"])[0]
        target = deepcopy(source)
        target.update(id="different_outline", kind="latex", role="body",
                      tile=[0, 0, 192, 192])
        pairs = film.pair_glyphs([source], [target], "shape_morph")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(film.pair_kind(*pairs[0]), "shape_morph")
        for protected in (dict(id="tex_rule", role="fraction_rule", size=[1.5, .025]),
                          dict(role="superscript", size=[.3, .3]),
                          dict(id="minus", role="body", size=[1.5, .05])):
            candidate = deepcopy(target)
            candidate.update(protected)
            self.assertFalse(film.shape_compatible(source, candidate))

    def test_an_identical_tile_is_never_reported_as_outline_morph(self):
        source = film.layout(self.groups["c_universe"])[0]
        target = deepcopy(source)
        target["center"][0] += .1
        self.assertEqual(film.pair_kind(source, target), "transport")
        target["id"] = "another_alias_of_the_same_tile"
        self.assertEqual(film.pair_kind(source, target), "transport")

    def test_identical_emitted_geometry_stays_static_during_neighbor_motion(self):
        a = film.layout(self.groups["calculus0"])[0]
        b = deepcopy(a)
        b["center"][0] += 1e-10
        code = film.render_pairs([(a, b)], amount="progress", arc_strength=.08)
        self.assertIn(",0.0,0.000000,WHITE,visibility,aa);", code)
        self.assertNotIn("progress", code)

    def test_review_bounds_enclose_padded_glyphs_with_aa_margin(self):
        glyphs = film.layout(self.groups["quadratic1"])
        x0, y0, x1, y1 = film.review_bounds(glyphs)
        for glyph in glyphs:
            x, y = glyph["center"]
            w, h = glyph["size"]
            self.assertLessEqual(x0, x - w / 2 - .059)
            self.assertLessEqual(y0, y - h / 2 - .059)
            self.assertGreaterEqual(x1, x + w / 2 + .059)
            self.assertGreaterEqual(y1, y + h / 2 + .059)


@unittest.skipUnless(importlib.util.find_spec("moderngl"), "desktop GL extra is not installed")
class ShowcaseHandoffRenderTests(unittest.TestCase):
    def test_opening_and_closing_have_no_visibility_or_geometry_reset(self):
        # Render only the real typography shader, excluding moving backgrounds.
        # The old gates produced an empty frame at 2.4 and a blank-to-full jump
        # at 114; endpoint geometry checks alone cannot detect those regressions.
        sys.path.insert(0, str(ROOT / "tools/showcase"))
        from render_film import FilmRenderer
        groups = json.loads((ROOT / "tools/showcase_v2/type_data.json").read_text(
            encoding="utf-8"))["groups"]
        code, _events = film.make_type(groups)
        prefix = (ROOT / "tools/showcase_v2/film.fragment").read_text(
            encoding="utf-8").split("// __GEOMETRY__")[0]
        main = """
void main() {
    vec2 p=(uv-0.5)*vec2(16.0,9.0);
    vec3 c=vec3(0.0);
    typography(c,p,EXTRA_VECTOR1.x,9.0/EXTRA_VECTOR1.z);
    gl_FragColor=vec4(clamp(c,0.0,1.0),1.0);
}
"""
        with tempfile.TemporaryDirectory() as temporary:
            shader = Path(temporary) / "typography.fragment"
            shader.write_text(prefix + code + main, encoding="utf-8")
            renderer = FilmRenderer(shader, ROOT / "resource_pack/textures/manim/client_showcase.png",
                                    640, 360)
            try:
                for boundary in (2.4, 114.0):
                    with self.subTest(boundary=boundary):
                        frames = [renderer.frame(boundary + delta) for delta in (-.0001, 0, .0001)]
                        energy = sum(frames[1])
                        self.assertGreater(energy, 100000)
                        for frame in (frames[0], frames[2]):
                            difference = sum(abs(a - b) for a, b in zip(frame, frames[1]))
                            self.assertLess(difference / energy, .002)
            finally:
                renderer.close()


if __name__ == "__main__":
    unittest.main()
