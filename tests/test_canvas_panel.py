"""The production two-canvas page uses the same business actions as SDK tests."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


RUNTIME = Path(__file__).resolve().parents[1] / "behavior_pack/manim_ui"
PACKAGE = "_manim_canvas_panel_test"
SCENES = [{"name": "first", "title": "First", "duration": 2},
          {"name": "second", "title": "Second", "duration": 4},
          {"name": "runtime_shapes", "title": "Shapes", "duration": 4}]


class Renderer:
    def __init__(self):
        self.releases = 0
        self.shape = {"morph": 0, "progress": 1, "rotation": 0,
                      "color": (1, 1, 1), "scale": 1, "stroke_width": 0.04}

    def install_scene(self, scene):
        return True, False

    def set_scene_visible(self, scene, enabled):
        return True

    def render_scene(self, scene, position):
        return True

    def set_shape(self, **changes):
        self.shape.update(changes)
        return True

    def shape_snapshot(self):
        return dict(self.shape)

    def release_scenes(self):
        self.releases += 1


class CanvasPanelTests(unittest.TestCase):
    def setUp(self):
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(RUNTIME)]
        canvas = types.ModuleType(PACKAGE + ".canvas")
        canvas.RUNTIME_SCENE = "runtime_shapes"
        primitive = types.ModuleType(PACKAGE + ".canvas_primitive")
        primitive.ManimCanvas = lambda **props: dict(kind="canvas", **props)
        ui = types.ModuleType(PACKAGE + ".pyreact")
        ui.Component = lambda function: function
        self.effects = []
        self.updates = []
        ui.use_state = lambda state: (state, self.updates.append)
        ui.use_effect = lambda effect, deps: self.effects.append(effect)
        ui.Style = lambda **props: props
        ui.Color = lambda *values: values
        for name in ("Panel", "Image", "Label", "Button", "Slider"):
            setattr(ui, name, lambda **props: props)
        for name, fields in {"FlexDirection": ("row",), "JustifyContent": ("space_between",),
                             "AlignItems": ("center",), "Position": ("absolute",),
                             "TextAlignment": ("center",)}.items():
            setattr(ui, name, types.SimpleNamespace(**dict((field, field) for field in fields)))
        patcher = patch.dict(sys.modules, {PACKAGE: package, PACKAGE + ".canvas": canvas,
                            PACKAGE + ".canvas_primitive": primitive, PACKAGE + ".pyreact": ui})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.now = 0.0
        playback = self.load("playback")
        def factory():
            return playback.PlaybackController(SCENES, Renderer(), lambda: self.now)
        canvas.create_canvas_player = factory
        self.module = self.load("canvas_panel")
        self.demo = self.module.CanvasDemo()

    def load(self, name):
        spec = importlib.util.spec_from_file_location(PACKAGE + "." + name, RUNTIME / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def ready(self):
        self.demo.left.load("first")
        self.demo.right.load("runtime_shapes")
        self.demo.on_ready("left", self.demo.left)
        self.demo.on_ready("right", self.demo.right)

    def test_switching_and_seeking_the_left_player_does_not_change_right(self):
        self.assertFalse(self.demo.select_left(1))
        self.ready()
        self.assertEqual(self.demo.names, ("first", "second"))
        before = self.demo.right.snapshot()
        shape = self.demo.right.renderer.shape_snapshot()
        self.assertTrue(self.demo.select_left(-1))
        self.assertEqual(self.demo.left.snapshot()["scene"], "second")
        self.demo.seek_left(0.5)
        self.assertEqual(self.demo.left.snapshot()["position"], 2)
        self.demo.toggle_left()
        self.now = 0.5
        self.demo.left.frame()
        self.assertEqual(self.demo.left.snapshot()["position"], 2.5)
        self.assertFalse(self.demo.load_left("runtime_shapes"))
        self.assertEqual(self.demo.right.snapshot(), before)
        self.assertEqual(self.demo.right.renderer.shape_snapshot(), shape)

    def test_shape_sliders_and_presets_notify_without_touching_left(self):
        self.ready()
        self.demo.left.seek(0.75)
        before = self.demo.left.snapshot()
        received = []
        unsubscribe = self.demo.subscribe(received.append)
        self.demo.set_parameter("morph", 0.6)
        self.demo.set_parameter("progress", 0.3)
        self.demo.set_parameter("rotation", 0.25)
        self.demo.set_color((1, 0.4, 0.75))
        shape = received[-1]["shape"]
        self.assertEqual(shape["morph"], 0.6)
        self.assertEqual(shape["progress"], 0.3)
        self.assertAlmostEqual(shape["rotation"], self.module.math.pi / 2)
        self.assertEqual(shape["color"], (1, 0.4, 0.75))
        self.assertEqual(self.demo.left.snapshot(), before)
        self.demo.preset("square")
        self.assertEqual(self.demo.snapshot()["shape"]["morph"], 1)
        self.demo.preset("partial")
        self.assertEqual(self.demo.snapshot()["shape"]["progress"], 0.55)
        unsubscribe()
        unsubscribe()
        count = len(received)
        self.demo.set_shape(morph=0.2)
        self.assertEqual(len(received), count)

    def test_real_component_callbacks_and_cleanup_own_two_players(self):
        element = self.module.CanvasPanel(demo=self.demo, onBack=lambda: True)
        disconnect = self.effects[-1]()
        canvases = []
        def visit(node):
            if not isinstance(node, dict):
                return
            if node.get("kind") == "canvas":
                canvases.append(node)
            children = node.get("children", [])
            for child in children if isinstance(children, list) else [children]:
                visit(child)
        visit(element)
        self.assertEqual(len(canvases), 2)
        self.assertEqual([item["scene"] for item in canvases], ["first", "runtime_shapes"])
        self.assertTrue(all(not item["autoPlay"] for item in canvases))
        for item in canvases:
            item["player"].load(item["scene"])
            item["onReady"](item["player"])
        self.assertEqual(self.demo.snapshot()["ready"], {"left": True, "right": True})
        disconnect()
        self.demo.dispose()
        self.assertTrue(self.demo.snapshot()["disposed"])
        self.assertEqual(self.demo.left.renderer.releases, 1)
        self.assertEqual(self.demo.right.renderer.releases, 1)
        self.assertEqual(self.demo.left._subscribers, [])
        self.assertEqual(self.demo.right._subscribers, [])
        self.assertFalse(self.demo.set_shape(morph=0.5))


if __name__ == "__main__":
    unittest.main()
