# -*- coding: utf-8 -*-
"""Client soundtrack transport for the two bundled presentations.

The public audio API has no pause or seek. Each five-second segment therefore
has four additional files starting at seconds 1..4. Resume chooses the preceding
whole-second start, keeping the soundtrack offset below one second. No native
global volume or other projects' music is changed.
"""

PRESENTATION_SCENES = ("client_showcase", "story_showcase")
PRESENTATION_TITLES = {"client_showcase": "万象变换", "story_showcase": "风之童话"}
SEGMENT_SECONDS = 5.0


class PresentationAudioController(object):
    def __init__(self, component, clock):
        self.component = component
        self._clock = clock
        self._name = ""
        self._music_id = ""
        self._segment = None
        self._ends_at = 0.0
        self._failed_segment = None
        self._pending_stops = {}
        self._retry_at = 0.0
        self._syncing = False
        self._deferred_state = None
        self._generation = 0
        self.error = ""
        self.last_failure = None
        self.disposed = False

    def _fail(self, operation, name, result):
        failure = {"operation": operation, "name": name, "result": result}
        if failure != self.last_failure:
            print("[manim-ui] Soundtrack %s failed: %s (%s)" % (operation, name, result))
        self.last_failure = failure
        self.error = "配乐播放失败" if operation == "play" else "配乐停止失败"

    def _drain_stops(self, now):
        if not self._pending_stops or now < self._retry_at:
            return
        self._retry_at = now + 0.1
        for name, ends_at in tuple(self._pending_stops.items()):
            # Even a rejected stop cannot leave a non-looping short clip alive
            # beyond its natural end. Do not keep retrying an expired resource.
            if now >= ends_at or self.component.StopCustomMusic(name, 0):
                self._pending_stops.pop(name, None)
        if not self._pending_stops and self.error == "配乐停止失败":
            self.error = ""

    def stop(self):
        """Stop only a resource this controller successfully started."""
        self._generation += 1
        now = self._clock()
        name, ends_at = self._name, self._ends_at
        self._name = ""
        self._music_id = ""
        self._segment = None
        self._failed_segment = None
        if name and now < ends_at:
            result = self.component.StopCustomMusic(name, 0)
            if not result:
                self._pending_stops[name] = ends_at
                self._retry_at = now + 0.1
                self._fail("stop", name, result)
        self._drain_stops(now)
        return not self._pending_stops

    def sync(self, state):
        """Follow the sampled visual clock; return whether diagnostics changed."""
        if self._syncing:
            self._deferred_state = state
            return False
        before = self.snapshot()
        self._syncing = True
        self._deferred_state = None
        try:
            self._sync_state(state)
            deferred = self._deferred_state
            self._deferred_state = None
            if deferred is not None:
                self._sync_state(deferred)
        finally:
            self._syncing = False
        return before != self.snapshot()

    def _sync_state(self, state):
        now = self._clock()
        self._drain_stops(now)
        scene = state["scene"]
        position = state["position"]
        active = (not self.disposed and scene in PRESENTATION_SCENES
                  and state["playing"] and state["visible"]
                  and position < state["duration"])
        if not active:
            self.stop()
            return
        segment = (scene, int(position / SEGMENT_SECONDS))
        if segment == self._segment or segment == self._failed_segment:
            return
        self.stop()
        if self._pending_stops:
            return
        self._failed_segment = segment
        offset = min(4, int(position - segment[1] * SEGMENT_SECONDS))
        suffix = "_o%02d" % offset if offset else ""
        name = "pmanim.presentation.%s.s%02d%s" % (scene, segment[1], suffix)
        if self.component is None:
            self._fail("play", name, "CreateCustomAudio unavailable")
            return
        generation = self._generation
        music_id = self.component.PlayCustomUIMusic(name, 1.0, 1.0, False)
        if not music_id or str(music_id) in ("-1", "-2", "-3"):
            self._fail("play", name, music_id)
            return
        self._name = name
        self._music_id = music_id
        self._segment = segment
        self._failed_segment = None
        self._ends_at = now + SEGMENT_SECONDS - offset
        self.error = ""
        # Native playback can dispatch PlaySoundClientEvent before returning.
        # A reentrant pause/dispose must also stop the just-returned sound.
        if self.disposed or generation != self._generation:
            self.stop()

    def snapshot(self):
        return {"name": self._name, "music_id": self._music_id,
                "error": self.error,
                "last_failure": dict(self.last_failure) if self.last_failure is not None else None,
                "stopping": bool(self._pending_stops), "disposed": self.disposed}

    def dispose(self):
        if self.disposed:
            return False
        self.disposed = True
        self.stop()
        return True
