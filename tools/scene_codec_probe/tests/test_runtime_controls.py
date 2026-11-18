"""Exercise in-memory native adapter with fake SDK boundaries, not fake bytes."""
import importlib.util
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).parents[1]


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Base:
    def __init__(self, *unused):
        self.ready = True
        self.pipeline_ready = False
        self.writer_visible = True
        self.native_attempt_serial = self.geometry_build_serial = self.generation = 0
        self.epoch = self.named_records = 0
        self.names, self.name_records, self.dataset_names, self.attached_names = [], {}, set(), set()
        self.budget = True

    def _require_idle_controls(self):
        pass

    def can_upload(self, unused):
        return self.budget

    def begin_dataset(self):
        self.epoch += 1

    def _writer_controls(self, unused=None):
        return True

    def set_writer_visible(self, visible):
        self.writer_visible = bool(visible)

    def snapshot(self):
        return {'slot_count': getattr(self, 'slot_count', 0)}

    def start_measurement(self, seconds):
        self.measurement = {'start': 100., 'warm_until': 101., 'until': 100.+seconds}


class FakeNative:
    def __init__(self):
        self.data = None
        self.uniforms = {}
        self.attached = []
        self.visible = {}

    def GetBlankBlockPalette(self):
        return self

    def DeserializeBlockPalette(self, data):
        self.data = data
        return True

    def CombineBlockPaletteToGeometry(self, palette, name, unused):
        if palette is not self:
            raise ValueError('Wrong palette')
        return name

    def AddActorBlockGeometry(self, name, *unused):
        self.attached.append(name)
        return True

    def SetEntityExtraUniforms(self, index, values):
        self.uniforms[index] = values
        return True

    def SetActorBlockGeometryVisible(self, name, visible):
        self.visible[name] = visible
        return True


class RuntimeAdapterTests(unittest.TestCase):
    def setUp(self):
        base = types.ModuleType('geometry_atlas_probe.base_runtime')
        base.ProbeSystem = Base
        config = types.ModuleType('geometry_atlas_probe.scene_config')
        config.PROCESSES = []
        modules = {'geometry_atlas_probe': types.ModuleType('geometry_atlas_probe'),
                   'geometry_atlas_probe.base_runtime': base,
                   'geometry_atlas_probe.codec': read_module('packet_oracle', HERE.parent/'geometry_packet_probe/codec.py'),
                   'geometry_atlas_probe.scene_codec': read_module('scene_oracle', HERE/'codec.py'),
                   'geometry_atlas_probe.scene_layout': read_module('scene_plan', HERE/'layout.py'),
                   'geometry_atlas_probe.scene_config': config}
        with patch.dict(sys.modules, modules):
            self.runtime = read_module('tested_scene_runtime', HERE/'runtime.py')
        self.native = FakeNative()
        self.probe = self.runtime.ProbeSystem('test', 'probe')
        self.probe.block = self.probe.geometry = self.probe.render = self.native

    def test_64k_geometry_contains_every_record_and_explicit_padding(self):
        for bits in (1, 2):
            with patch.object(time, 'clock', time.perf_counter, create=True):
                state = self.probe.load_payload(65536, bits)
            self.assertEqual(state['logical_payload_bytes'], 65536)
            self.assertGreaterEqual(state['allocated_payload_bytes'], 65536)
            total = sum(len(indices) for indices in self.native.data['common'].values())
            self.assertEqual(total, state['payload_plan']['pixels'])
            self.assertEqual(self.probe.layout[0], total)
            self.assertEqual(self.probe.layout[1], state['codec_roi'][2])
            self.assertEqual(total, state['codec_roi'][2]*state['codec_roi'][3])
            self.assertEqual(self.native.uniforms[4], (1., 0., float(bits), 0.))
            self.assertFalse(state['game_runtime_file_writes'])
            self.assertTrue(all(key[0].startswith('pmanim_geometry_atlas:')
                                for key in self.native.data['common']))

    def test_budget_rejection_precedes_native_allocation(self):
        self.probe.budget = False
        with self.assertRaises(RuntimeError):
            self.probe.load_payload(65536, 2)
        self.assertIsNone(self.native.data)
        self.assertEqual(self.probe.epoch, 0)

    def test_formal_static_window_has_two_warmup_and_25_sample_seconds(self):
        state = self.probe.start_static_measurement(25, 2)
        self.assertEqual(self.probe.measurement['warm_until'], 102.)
        self.assertEqual(self.probe.measurement['until'], 127.)
        self.assertEqual(state['static_measurement_window'],
                         {'warmup_seconds': 2., 'sample_seconds': 25., 'total_seconds': 27.})
        with self.assertRaises(ValueError):
            self.probe.start_static_measurement(8, 2)

    def test_static_baseline_hides_native_attachments_and_restores_only_current(self):
        with patch.object(time, 'clock', time.perf_counter, create=True):
            self.probe.load_payload(3072, 1)
            self.probe.load_payload(3072, 2)
        state = self.probe.set_native_writer_visible(False)
        self.assertEqual(len(state['native_attachment_visibility']), 2)
        self.assertFalse(any(self.native.visible.values()))
        state = self.probe.set_native_writer_visible(True)
        self.assertEqual([name for name, visible in self.native.visible.items() if visible],
                         [self.probe.geometry_name])


if __name__ == '__main__':
    unittest.main()
