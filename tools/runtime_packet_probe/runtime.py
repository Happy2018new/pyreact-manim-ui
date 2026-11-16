# -*- coding: utf-8 -*-
"""Isolated client probe. No production hooks or filesystem uploads."""
import math
import time
import traceback
import mod.client.extraClientApi as api

ScreenNode = api.GetScreenNodeCls()
ClientSystem = api.GetClientSystemCls()
NAMESPACE = "pmanim_packet_probe"
UI_KEY = "probe"
LIMIT = 8
MASK = 16777215


def packet_rectangles(count, screen):
    """One source of truth for the native scissor, shader and capture receipt."""
    width, height = screen
    if (width <= 0 or height <= 0 or math.isnan(width) or math.isnan(height) or
            math.isinf(width) or math.isinf(height)):
        raise ValueError("Screen dimensions must be finite and positive")
    if count == 0:
        return []
    if count <= 64:
        # Keep the already verified eight-slot layout and readable small cases.
        columns = 1 if count <= 8 else (2 if count <= 32 else 4)
        rows = int(math.ceil(float(count) / columns))
        left, top = min(16., width / 16.), min(32., height / 8.)
        pitch_x = (width - 2. * left) / columns
        pitch_y = min(26., (height - 2. * top) / rows)
        w = pitch_x - min(4., pitch_x / 8.)
        h = pitch_y - min(3., pitch_y / 8.)
    else:
        # Nine horizontal byte cells make a slot nine times wider than tall.
        # Integer logical rectangles keep dense native scissors deterministic.
        # Leave the top marker clear and spend the bottom reserve on rows.
        left, top = min(16., width / 16.), min(32., height / 8.)
        available_width = width - 2. * left
        available_height = height - top - min(4., height / 16.)
        columns = max(1, int(round(math.sqrt(
            count * available_width / (9. * available_height)))))
        columns = min(count, columns)
        rows = int(math.ceil(float(count) / columns))
        w = math.floor(available_width / columns)
        h = min(26., math.floor(available_height / rows))
        if w <= 0 or h <= 0:
            raise ValueError("Screen is too small for the requested packet grid")
        pitch_x, pitch_y = w, h
    return [(left + (index % columns) * pitch_x,
             top + (index // columns) * pitch_y, w, h)
            for index in range(count)]


def dataset(seed, count):
    """New values are generated in game Python, not supplied by the host."""
    state = int(seed) & MASK
    result = []
    for index in range(count):
        row = []
        for channel in range(3):
            state = (state * 1664525 + 1013904223) & MASK
            row.append(state)
        result.append(tuple(row))
    return result


def stats(values):
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {"count": len(values), "mean": sum(values) / len(values),
            "p50": ordered[int((len(ordered) - 1) * .50)],
            "p95": ordered[int((len(ordered) - 1) * .95)],
            "max": ordered[-1], "min": ordered[0]}


class PacketScreen(ScreenNode):
    def __init__(self, namespace, name, param):
        ScreenNode.__init__(self, namespace, name, param)
        factory = api.GetEngineCompFactory()
        self.actor = factory.CreateActorRender(None)
        self.game = factory.CreateGame(api.GetLevelId())
        self.controls = []
        self.rects = []
        self.values = []
        self.count = 0
        self.mode = 0
        self.ready = False
        self.setup_ms = 0.
        self.screen = (0, 0)

    def Create(self):
        for index in range(LIMIT):
            path = "/slot_%03d" % index
            parent = self.GetBaseUIControl(path)
            if parent is None:
                break
            carrier = self.GetBaseUIControl(path + "/carrier")
            canvas = self.GetBaseUIControl(path + "/canvas")
            self.controls.append((parent, carrier.asImage(), canvas))
            parent.SetVisible(False, False)
        self.ready = True

    def configure(self, count, mode=0, seed=12345, carriers=True):
        if not self.ready or not 0 <= count <= len(self.controls) or mode not in (0, 1):
            raise ValueError("Invalid or unready packet screen")
        started = time.clock()
        screen = tuple(self.game.GetScreenSize())
        rects = packet_rectangles(count, screen)
        self.count, self.mode = int(count), int(mode)
        self.screen = screen
        width, height = screen
        self.rects = rects
        for index, controls in enumerate(self.controls):
            parent, image, canvas = controls
            visible = index < count
            parent.SetVisible(visible, False)
            if not visible:
                continue
            x, y, w, h = rects[index]
            parent.SetPosition((x, y))
            parent.SetSize((w, h))
            canvas.SetPosition((0., 0.))
            canvas.SetSize((w, h))
            image.SetVisible(carriers, False)
            identifier = "pmanim_packet:slot_%03d" % index
            rectangle = (2*x/width-1, 1-2*y/height, 2*w/width, 2*h/height)
            if not self.actor.SetEntityUIExtraUniforms(identifier, 3, rectangle):
                raise RuntimeError("Rectangle uniform rejected")
            if not canvas.asNeteasePaperDoll().RenderEntity({
                    "entity_identifier": identifier, "scale": 1., "render_depth": -15,
                    "init_rot_x": 0., "init_rot_y": 0., "init_rot_z": 0.}):
                raise RuntimeError("RenderEntity rejected")
        self.UpdateScreen(True)
        self.write(seed)
        self.setup_ms = (time.clock() - started) * 1000.
        return self.snapshot()

    def write(self, seed, provided=None):
        t0 = time.clock()
        values = dataset(seed, self.count) if provided is None else provided
        if len(values) != self.count:
            raise ValueError("Payload length mismatch")
        colors = [tuple(value / 16777216. for value in row) for row in values]
        t1 = time.clock()
        for index, color in enumerate(colors):
            if self.mode == 0:
                self.controls[index][1].SetSpriteColor(color)
            else:
                if not self.actor.SetEntityUIExtraUniforms(
                        "pmanim_packet:slot_%03d" % index, 1, color + (1.,)):
                    raise RuntimeError("Control uniform rejected")
        # Explicitly select CURRENT_COLOR in carrier mode; once at configuration
        # and cached thereafter, not counted as packet writes each frame.
        if self.mode == 0 and not self.values:
            for index in range(self.count):
                if not self.actor.SetEntityUIExtraUniforms(
                        "pmanim_packet:slot_%03d" % index, 1, (0., 0., 0., 0.)):
                    raise RuntimeError("Mode uniform rejected")
        t2 = time.clock()
        self.values = values
        return ((t1-t0)*1000., (t2-t1)*1000.)

    def snapshot(self):
        return {"ready": self.ready, "count": self.count, "mode": self.mode,
                "screen": self.screen, "setup_ms": self.setup_ms,
                "records": [{"index": index, "values": self.values[index], "rect": rect}
                            for index, rect in enumerate(self.rects)]}


class ProbeSystem(ClientSystem):
    def __init__(self, namespace, system_name):
        ClientSystem.__init__(self, namespace, system_name)
        self.screen = None
        self.run = None
        self.last_run = None
        self.aggregation = None
        self.post = api.GetEngineCompFactory().CreatePostProcess(api.GetLevelId())
        self.game = api.GetEngineCompFactory().CreateGame(api.GetLevelId())
        self.registered = False
        self.ListenForEvent(api.GetEngineNamespace(), api.GetEngineSystemName(),
                            "GameRenderTickEvent", self, self.on_frame)

    def open(self):
        if self.run is not None:
            raise RuntimeError('Finish active benchmark before opening UI')
        self._disable_aggregate()
        if self.screen is not None:
            return self.screen.snapshot()
        if not self.registered:
            if not api.RegisterUI(NAMESPACE, UI_KEY, "packet_probe.runtime.PacketScreen",
                                  "pmanim_packet_probe.main"):
                raise RuntimeError("RegisterUI rejected")
            self.registered = True
        self.screen = api.CreateUI(NAMESPACE, UI_KEY, {"isHud": 1})
        if self.screen is None:
            raise RuntimeError("CreateUI failed")
        return self.screen.snapshot()

    def configure(self, count, mode=0, seed=12345, carriers=True):
        if self.run is not None:
            raise RuntimeError("Finish active benchmark first")
        self._disable_aggregate()
        if self.screen is None:
            raise RuntimeError('Open packet UI before configuring it')
        self.screen.values = []
        return self.screen.configure(count, mode, seed, carriers)

    def start(self, count, mode, seconds=8., dynamic=True, seed=12345):
        self.configure(count, mode, seed)
        return self._start_run(count, mode, seconds, dynamic, seed, 'ui')

    def setup_aggregate(self, config, seed=12345):
        from .aggregate_runtime import AggregateProbe
        if self.run is not None:
            raise RuntimeError('Finish active benchmark before aggregate setup')
        self._disable_aggregate()
        if self.screen is not None:
            self.screen.SetRemove()
            self.screen = None
        try:
            self.aggregation = AggregateProbe(self.post, config, seed)
        except Exception as error:
            # Constructor rollback can itself fail. Keep its complete name list
            # reachable so close() can retry cleanup and snapshot() exposes it.
            self.aggregation = getattr(error, 'aggregate_probe', None)
            raise
        return self.aggregation.snapshot()

    def _disable_aggregate(self):
        if self.aggregation is not None and self.aggregation.enabled is not False:
            self.aggregation.set_enabled(False)

    def start_aggregate(self, seconds=8., dynamic=True, seed=12345):
        if (self.aggregation is None or not self.aggregation.ready or
                self.aggregation.enabled is not True or self.aggregation.error is not None):
            raise RuntimeError('Finish and enable aggregate setup before benchmarking')
        if self.screen is not None:
            raise RuntimeError('Close packet UI before aggregate benchmarking')
        return self._start_run(self.aggregation.config['pages'], -1,
                               seconds, dynamic, seed, 'aggregate')

    def _start_run(self, count, mode, seconds, dynamic, seed, kind):
        if self.run is not None:
            raise RuntimeError('Benchmark already running')
        seconds = float(seconds)
        if math.isnan(seconds) or math.isinf(seconds) or seconds <= 1.:
            raise ValueError('Benchmark seconds must be finite and exceed the one-second warmup')
        now = time.clock()
        self.last_run = None
        self.run = {"start": now, "until": now+seconds, "previous": None,
                    "warm_until": now+1., "dynamic": bool(dynamic), "seed": seed,
                    "frames": 0, "count": count, "mode": mode, "kind": kind, "generation_ms": [],
                    "upload_ms": [], "interval_ms": [], "fps": [],
                    "status": "running", "error": None, "success": False}
        return {"started": True, "seconds": seconds, "count": count, "mode": mode}

    def _finish_run(self, status, error=None, now=None):
        run = self.run
        if run is None:
            return
        if now is None:
            now = time.clock()
        if status == 'completed' and (not run['upload_ms'] or not run['interval_ms']):
            status = 'failed'
            error = 'Benchmark ended without measured frames and intervals'
        result = {key: value for key, value in run.items()
                  if key not in ('generation_ms', 'upload_ms', 'interval_ms', 'fps')}
        for key in ('generation_ms', 'upload_ms', 'interval_ms', 'fps'):
            result[key] = stats(run[key])
        result.update(status=status, error=error, success=status == 'completed',
                      elapsed=now-run['start'], measured_frames=len(run['upload_ms']),
                      gpu_verified=False)
        self.last_run = result
        self.run = None

    def on_frame(self, args):
        run = self.run
        if run is None:
            return
        now = time.clock()
        # Include the interval arriving at/after the deadline. Dropping it would
        # hide precisely the long final frame that delayed completion.
        if now >= run['warm_until'] and run['previous'] is not None:
            run['interval_ms'].append((now-run['previous'])*1000.)
        run['previous'] = now
        if now >= run["until"]:
            self._finish_run('completed', now=now)
            return
        run["frames"] += 1
        try:
            writer = self.aggregation if run['kind'] == 'aggregate' else self.screen
            if writer is None:
                raise RuntimeError('Benchmark writer was removed')
            if run['kind'] == 'aggregate' and (
                    not writer.ready or writer.enabled is not True or writer.error is not None):
                raise RuntimeError('Aggregate became unavailable during benchmark')
            if run["dynamic"]:
                generation, upload = writer.write(run["seed"]+run["frames"]*97)
            else:
                generation, upload = 0., 0.
            if now >= run["warm_until"]:
                run["generation_ms"].append(generation)
                run["upload_ms"].append(upload)
                if run["frames"] % 15 == 0:
                    run["fps"].append(self.game.GetFps())
        except Exception as error:
            # SDK failures are exceptional, never discarded timing samples.
            traceback.print_exc()
            self._finish_run('failed', '%s: %s' % (type(error).__name__, error))

    def snapshot(self):
        return {"screen": self.screen.snapshot() if self.screen is not None else None,
                "running": self.run is not None, "last_run": self.last_run,
                "aggregation": self.aggregation.snapshot() if self.aggregation is not None else None}

    def close(self):
        self._finish_run('aborted', 'Probe closed before benchmark completion')
        try:
            self._disable_aggregate()
        finally:
            if self.screen is not None:
                self.screen.SetRemove()
                self.screen = None

    def Destroy(self):
        try:
            self.close()
        finally:
            self.UnListenForEvent(api.GetEngineNamespace(), api.GetEngineSystemName(),
                                  "GameRenderTickEvent", self, self.on_frame)
