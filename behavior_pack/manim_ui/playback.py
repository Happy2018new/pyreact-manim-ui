# -*- coding: utf-8 -*-
"""Scene-name playback API, independent of ModSDK and the demo panel.

The injected renderer implements install_scene(scene) -> (ok, reused),
set_scene_visible(scene, enabled), render_scene(scene, position), and
release_scenes(). It owns native resources; this controller owns their lifetime.
All methods run on the caller's client thread.
"""
import traceback
from .timeline import Timeline, finite_number


class PlaybackController(object):
    def __init__(self, scenes, renderer, clock):
        self.scenes = tuple(dict(scene) for scene in scenes)
        self._scene_indices = {}
        for index, scene in enumerate(self.scenes):
            name = scene["name"]
            if not name or name in self._scene_indices:
                raise ValueError("Scene names must be nonempty and unique")
            Timeline(scene["duration"])
            self._scene_indices[name] = index
        self.renderer = renderer
        self._clock = clock
        self.scene_index = 0
        self.timeline = None
        self.visible = False
        self.error = ""
        self.disposed = False
        self._subscribers = []
        self._load_timings = []
        self._last_notify = 0.0

    def scene_names(self):
        return tuple(scene["name"] for scene in self.scenes)

    def _scene(self):
        return self.scenes[self.scene_index]

    def _set_error(self, message):
        self.error = message
        print("[manim-ui] " + message)

    def load(self, name):
        """Select a scene by name, show its first frame, and remain paused."""
        if self.disposed:
            return False
        index = self._scene_indices.get(name)
        if index is None:
            self._set_error("Unknown compiled scene: " + str(name))
            self.notify()
            return False
        started = self._clock()
        previous = self._scene()["name"] if self.timeline is not None else ""
        self._hide()
        scene = self.scenes[index]
        install_started = self._clock()
        installed, reused = self.renderer.install_scene(scene)
        install_seconds = max(0.0, self._clock() - install_started)
        if installed:
            self.scene_index = index
            self.timeline = Timeline(scene["duration"])
            success = self._show()
        else:
            self._set_error("Unable to install shader: " + name)
            success = False
        operation = "reuse" if reused else ("switch_install" if previous else "first_install")
        self._load_timings.append({
            "scene": name, "previous_scene": previous, "operation": operation,
            "reused": reused, "success": success,
            "install_seconds": install_seconds,
            "total_seconds": max(0.0, self._clock() - started),
        })
        del self._load_timings[:-32]
        self.notify()
        return success

    def load_timings(self):
        """Recent synchronous API costs; these are not GPU/frame-ready timings."""
        return [dict(record) for record in self._load_timings]

    def _show(self):
        if self.disposed or self.timeline is None:
            return False
        self.visible = bool(self.renderer.set_scene_visible(self._scene(), True))
        if not self.visible:
            self.timeline.pause(self._clock())
            self._set_error("Unable to enable shader: " + self._scene()["name"])
            return False
        self.error = ""
        return self._update_frame(self._clock())

    def show(self):
        success = self._show()
        self.notify()
        return success

    def _hide(self):
        if self.timeline is not None:
            self.timeline.pause(self._clock())
            self.renderer.set_scene_visible(self._scene(), False)
        self.visible = False

    def hide(self):
        if self.disposed:
            return False
        self._hide()
        self.notify()
        return True

    def _ensure_selected(self, name):
        if self.disposed:
            return False
        if name is not None and (self.timeline is None or self._scene()["name"] != name):
            return self.load(name)
        if self.timeline is not None:
            return True
        return bool(self.scenes) and self.load(self.scenes[0]["name"])

    def play(self, name=None):
        """Resume the selected scene, or load a named scene and play it."""
        if not self._ensure_selected(name):
            return False
        if self.visible and self.timeline.playing:
            return True
        if not self._show():
            self.notify()
            return False
        self.timeline.play(self._clock())
        self.notify()
        return True

    def pause(self):
        if self.disposed or self.timeline is None:
            return False
        now = self._clock()
        self.timeline.pause(now)
        success = self._update_frame(now)
        self.notify()
        return success

    def seek(self, seconds):
        """Pause and seek; seek on a hidden player does not reopen its canvas."""
        if self.disposed or self.timeline is None:
            return False
        seconds = finite_number(seconds, "position")
        now = self._clock()
        self.timeline.pause(now)
        self.timeline.seek(seconds, now)
        success = self._update_frame(now)
        self.notify()
        return success

    def replay(self, name=None):
        if not self._ensure_selected(name):
            return False
        now = self._clock()
        self.timeline.pause(now)
        self.timeline.seek(0.0, now)
        return self.play()

    def stop(self):
        """Pause, hide and reset to zero; compiled native resources stay reusable."""
        if self.disposed or self.timeline is None:
            return False
        self._hide()
        self.timeline.seek(0.0, self._clock())
        self.notify()
        return True

    def _update_frame(self, now):
        if not self.visible or self.timeline is None:
            return True
        position = self.timeline.sample(now)
        if not self.renderer.render_scene(self._scene(), position):
            self._set_error("Shader parameter update failed")
            self._hide()
            return False
        return True

    def fail_render(self, message):
        """Stop and expose a renderer failure raised outside frame(), e.g. resize."""
        if self.disposed:
            return False
        self._set_error(message)
        self._hide()
        self.notify()
        return False

    def frame(self):
        if self.disposed or not self.visible:
            return
        now = self._clock()
        success = self._update_frame(now)
        if not success or now - self._last_notify >= 0.1:
            self._last_notify = now
            self.notify()

    def snapshot(self):
        scene = self._scene() if self.scenes else {}
        return {
            "scene": scene.get("name", ""), "title": scene.get("title", ""),
            "position": self.timeline.position if self.timeline else 0.0,
            "duration": self.timeline.duration if self.timeline else 1.0,
            "playing": bool(self.timeline and self.timeline.playing),
            "visible": self.visible, "error": self.error, "disposed": self.disposed,
            "last_load": dict(self._load_timings[-1]) if self._load_timings else None,
        }

    def subscribe(self, callback):
        """Subscribe to state changes; unsubscribe and teardown are idempotent."""
        if not callable(callback):
            raise TypeError("subscriber must be callable")
        # Each registration owns a token, even if the same callback subscribes twice.
        entry = [callback]
        if not self.disposed:
            self._subscribers.append(entry)
        def unsubscribe():
            for index, item in enumerate(self._subscribers):
                if item is entry:
                    del self._subscribers[index]
                    break
        return unsubscribe

    def notify(self):
        if self.disposed:
            return
        for entry in tuple(self._subscribers):
            if self.disposed:
                break
            # Observer failures cannot prevent other components receiving state.
            try:
                entry[0](self.snapshot())
            except Exception:
                traceback.print_exc()

    def dispose(self):
        if self.disposed:
            return False
        self._hide()
        self.disposed = True
        self._subscribers = []
        self.renderer.release_scenes()
        return True
