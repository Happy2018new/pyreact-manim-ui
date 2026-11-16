"""Capacity, exact layout and ownership checks without Minecraft or native SDK."""
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools/runtime_packet_probe"
COUNTS = (8, 32, 64, 256, 1024, 4096)
LOGICAL = (563, 327)
PHYSICAL = (2251, 1305)


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROBE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = load_module("packet_scale_builder", "build_probe.py")
VERIFY = load_module("packet_scale_verifier", "verify_capture.py")


class Control:
    def __init__(self):
        self.visible = None
        self.position = None
        self.size = None
        self.color = None
        self.rendered = None

    def asImage(self):
        return self

    def asNeteasePaperDoll(self):
        return self

    def SetVisible(self, visible, force_update):
        self.visible = visible

    def SetPosition(self, position):
        self.position = position

    def SetSize(self, size):
        self.size = size

    def SetSpriteColor(self, color):
        self.color = color

    def RenderEntity(self, settings):
        self.rendered = settings
        return True


class ScreenBase:
    def __init__(self, *args):
        self.nodes = {}
        self.lookups = []
        self.updates = []
        for index in range(4096):
            path = "/slot_%03d" % index
            for suffix in ("", "/carrier", "/canvas"):
                self.nodes[path + suffix] = Control()

    def GetBaseUIControl(self, path):
        self.lookups.append(path)
        return self.nodes.get(path)

    def UpdateScreen(self, force_update):
        self.updates.append(force_update)


class Actor:
    def __init__(self):
        self.uniforms = {}

    def SetEntityUIExtraUniforms(self, identifier, number, value):
        self.uniforms[(identifier, number)] = value
        return True


class RuntimePacketScaleTests(unittest.TestCase):
    def setUp(self):
        actor = Actor()
        api = types.ModuleType("mod.client.extraClientApi")
        api.GetScreenNodeCls = lambda: ScreenBase
        api.GetClientSystemCls = lambda: object
        api.GetLevelId = lambda: "fake_level"
        api.GetEngineCompFactory = lambda: types.SimpleNamespace(
            CreateActorRender=lambda entity: actor,
            CreateGame=lambda level: types.SimpleNamespace(GetScreenSize=lambda: LOGICAL))
        mod = types.ModuleType("mod")
        mod.__path__ = []
        client = types.ModuleType("mod.client")
        client.__path__ = []
        mod.client = client
        client.extraClientApi = api
        module_patch = patch.dict(sys.modules, {
            "mod": mod, "mod.client": client, "mod.client.extraClientApi": api})
        module_patch.start()
        self.addCleanup(module_patch.stop)
        self.runtime = load_module("packet_scale_runtime", "runtime.py")
        self.runtime.time = types.SimpleNamespace(clock=time.perf_counter)
        self.actor = actor

    def test_all_stage_rectangles_fit_and_every_byte_supports_three_by_three(self):
        image = Image.new("RGBA", PHYSICAL)
        sx, sy = PHYSICAL[0] / LOGICAL[0], PHYSICAL[1] / LOGICAL[1]
        for count in COUNTS:
            with self.subTest(count=count):
                rects = self.runtime.packet_rectangles(count, LOGICAL)
                self.assertEqual(count, len(rects))
                previous_right = {}
                for x, y, w, h in rects:
                    self.assertGreaterEqual(x, 0)
                    self.assertGreaterEqual(y, 0)
                    self.assertGreater(w, 0)
                    self.assertGreater(h, 0)
                    self.assertLessEqual(x + w, LOGICAL[0])
                    self.assertLessEqual(y + h, LOGICAL[1])
                    self.assertGreaterEqual(w * sx / 9., 4.)
                    self.assertGreaterEqual(h * sy, 4.)
                    self.assertGreaterEqual(x, previous_right.get(y, 0.))
                    previous_right[y] = x + w
                    physical = (x * sx, y * sy, w * sx, h * sy)
                    for byte in range(9):
                        _, _, sample_width = VERIFY._sample(image, physical, byte, 9, False)
                        self.assertEqual(3, sample_width)

    def test_dense_boundary_has_integer_scissors_and_no_negative_small_screen(self):
        rects = self.runtime.packet_rectangles(4096, LOGICAL)
        self.assertEqual((16., 32., 18., 2.), rects[0])
        self.assertTrue(all(value == math.floor(value) for rect in rects for value in rect))
        self.assertEqual((16., 32., 527., 23.),
                         self.runtime.packet_rectangles(8, LOGICAL)[0])
        self.assertEqual([], self.runtime.packet_rectangles(0, LOGICAL))
        for size in ((0, 100), (100, -1), (float("nan"), 100), (100, float("inf")), (8, 8)):
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.runtime.packet_rectangles(4096, size)

    def test_configure_uses_identical_scissor_uniform_and_receipt_and_cached_controls(self):
        self.runtime.LIMIT = 4096
        screen = self.runtime.PacketScreen("test", "test", {})
        screen.Create()
        self.assertEqual(4096, len(screen.controls))
        self.assertTrue(all(not parent.visible for parent, image, canvas in screen.controls))
        self.assertEqual(4096 * 3, len(screen.lookups))
        for count in COUNTS:
            with self.subTest(count=count):
                screen.values = []
                snapshot = screen.configure(count, seed=12345, carriers=False)
                self.assertEqual(count, snapshot["count"])
                self.assertEqual(count, len(snapshot["records"]))
                self.assertEqual(4096 * 3, len(screen.lookups))
                for index, controls in enumerate(screen.controls):
                    parent, image, canvas = controls
                    self.assertEqual(index < count, parent.visible)
                    if index >= count:
                        continue
                    record = snapshot["records"][index]
                    x, y, w, h = record["rect"]
                    self.assertEqual((x, y), parent.position)
                    self.assertEqual((w, h), parent.size)
                    self.assertEqual((0., 0.), canvas.position)
                    self.assertEqual((w, h), canvas.size)
                    self.assertFalse(image.visible)
                    identifier = "pmanim_packet:slot_%03d" % index
                    self.assertEqual(identifier, canvas.rendered["entity_identifier"])
                    self.assertEqual((2*x/563-1, 1-2*y/327, 2*w/563, 2*h/327),
                                     self.actor.uniforms[(identifier, 3)])
                    self.assertEqual(tuple(value / 16777216. for value in record["values"]),
                                     image.color)
        self.assertIn("/slot_1000/carrier", screen.nodes)
        self.assertIn(("pmanim_packet:slot_4095", 3), self.actor.uniforms)

    def test_maximum_builder_has_unique_four_digit_resources_and_preserves_layers(self):
        with tempfile.TemporaryDirectory() as directory:
            output = BUILD.build(Path(directory) / "probe", slots=4096)
            receipt = json.loads((output / "probe_resources.json").read_text(encoding="utf-8"))
            ui = json.loads((output / "resource_pack/ui/pmanim_packet_probe.json").read_text(encoding="utf-8"))
            self.assertEqual(4096, receipt["runtime"]["slot_count"])
            self.assertEqual({"block_fallback": False, "initial_panel_offset": [0, 0]}, receipt["options"])
            self.assertIsNone(receipt["block_probe"])
            self.assertEqual(4096, len(receipt["slots"]))
            self.assertEqual(4096, len(set(row["identifier"] for row in receipt["slots"])))
            self.assertEqual(1000, ui["main"]["layer"])
            slots = {key: value for item in ui["main"]["controls"]
                     for key, value in item.items() if key.startswith("slot_")}
            for index in range(4096):
                panel = slots["slot_%03d" % index]
                self.assertFalse(panel["visible"])
                self.assertEqual([0, 0], panel["offset"])
                children = {key: value for item in panel["controls"] for key, value in item.items()}
                self.assertEqual({"carrier", "canvas"}, set(children))
                self.assertEqual(10 + 2 * index, children["carrier"]["layer"])
                self.assertEqual(11 + 2 * index, children["canvas"]["layer"])
                self.assertTrue(children["canvas"]["enable_scissor_test"])
            for index in (999, 1000, 4095):
                name = "slot_%03d" % index
                self.assertTrue((output / ("resource_pack/entity/pmanim_packet_" + name + ".entity.json")).is_file())
                self.assertTrue((output / ("behavior_pack/entities/pmanim_packet_" + name + ".json")).is_file())
                self.assertEqual("/" + name + "/carrier", receipt["slots"][index]["carrier_path"])
            runtime = (output / "behavior_pack/packet_probe/runtime.py").read_text(encoding="utf-8")
            self.assertIn("LIMIT = 4096\n", runtime)
            self.assertIn("LIMIT = 8\n", (PROBE / "runtime.py").read_text(encoding="utf-8"))
            self.assertFalse((output / "resource_pack/graphics_settings/post_process.json").exists())
            for relative in ("resource_pack/materials/terrain.material", "resource_pack/blocks.json",
                             "resource_pack/models/netease_block/pmanim_packet_quad.json",
                             "behavior_pack/netease_blocks/pmanim_packet_quad.json",
                             "resource_pack/shaders/glsl/packet_block.vertex",
                             "resource_pack/shaders/glsl/packet_block.fragment"):
                self.assertFalse((output / relative).exists(), relative)
            self.assertTrue(all("block_canvas_path" not in row for row in receipt["slots"]))

    def test_optional_block_fallback_and_rebuild_options_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            output = BUILD.build(Path(directory) / "blocks", slots=2, block_fallback=True)
            receipt = json.loads((output / "probe_resources.json").read_text(encoding="utf-8"))
            marker = json.loads((output / BUILD.MARKER).read_text(encoding="utf-8"))
            self.assertEqual({"block_fallback": True, "initial_panel_offset": [0, 0]}, marker["options"])
            self.assertEqual(marker["options"], receipt["options"])
            self.assertEqual("pmanim_packet:block_quad", receipt["block_probe"]["identifier"])
            self.assertEqual("/slot_001/block_canvas", receipt["slots"][1]["block_canvas_path"])
            ui_path = output / "resource_pack/ui/pmanim_packet_probe.json"
            original = ui_path.read_bytes()
            ui = json.loads(original)
            slots = [next(iter(item.values())) for item in ui["main"]["controls"]
                     if next(iter(item)).startswith("slot_")]
            for index, panel in enumerate(slots):
                children = {key: value for item in panel["controls"] for key, value in item.items()}
                self.assertEqual({"carrier", "canvas", "block_canvas"}, set(children))
                self.assertFalse(children["block_canvas"]["visible"])
                self.assertEqual(11 + 2 * index, children["block_canvas"]["layer"])
                self.assertEqual([0, 0], panel["offset"])
            for relative in ("resource_pack/materials/terrain.material", "resource_pack/blocks.json",
                             "resource_pack/models/netease_block/pmanim_packet_quad.json",
                             "behavior_pack/netease_blocks/pmanim_packet_quad.json",
                             "resource_pack/shaders/glsl/packet_block.vertex",
                             "resource_pack/shaders/glsl/packet_block.fragment"):
                self.assertTrue((output / relative).is_file(), relative)
            BUILD.build(output, slots=2, block_fallback=True)
            self.assertEqual(original, ui_path.read_bytes())
            with self.assertRaisesRegex(ValueError, "different probe configuration"):
                BUILD.build(output, slots=2)
            self.assertEqual(original, ui_path.read_bytes())
            default_output = BUILD.build(Path(directory) / "entity", slots=2)
            with self.assertRaisesRegex(ValueError, "different probe configuration"):
                BUILD.build(default_output, slots=2, block_fallback=True)
            # Old owned outputs contain implicit fallback assets and must stay
            # untouched rather than silently carrying those files into a test.
            legacy = Path(directory) / "legacy"
            BUILD.write_json(legacy / BUILD.MARKER,
                             {"kind": "pmanim_runtime_packet_probe", "slots": 2, "version": 1})
            with self.assertRaisesRegex(ValueError, "different probe configuration"):
                BUILD.build(legacy, slots=2)

    def test_output_protection_and_slot_limits_fail_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for invalid in (0, 4097):
                with self.subTest(slots=invalid), self.assertRaisesRegex(ValueError, "4096"):
                    BUILD.build(folder / "invalid", invalid)
            unrelated = folder / "unrelated"
            unrelated.mkdir()
            sentinel = unrelated / "keep.txt"
            sentinel.write_bytes(b"untouched")
            with self.assertRaisesRegex(ValueError, "ownership marker"):
                BUILD.build(unrelated, 4096)
            self.assertEqual(b"untouched", sentinel.read_bytes())
            owned = folder / "owned"
            owned.mkdir()
            BUILD.write_json(owned / BUILD.MARKER,
                             {"kind": "pmanim_runtime_packet_probe", "slots": 4096,
                              "options": {"block_fallback": False, "initial_panel_offset": [0, 0]}})
            global_post = owned / "resource_pack/graphics_settings/post_process.json"
            global_post.parent.mkdir(parents=True)
            global_post.write_bytes(b"preserve global override evidence")
            with self.assertRaisesRegex(ValueError, "global postprocess override"):
                BUILD.build(owned, 4096)
            self.assertEqual(b"preserve global override evidence", global_post.read_bytes())
            with self.assertRaisesRegex(ValueError, "different probe configuration"):
                BUILD.build(owned, 1024)
        for production in (ROOT, ROOT / "behavior_pack", ROOT / "resource_pack", PROBE):
            with self.subTest(output=production), self.assertRaisesRegex(ValueError, "isolated"):
                BUILD.build(production, 4096)


if __name__ == "__main__":
    unittest.main()
