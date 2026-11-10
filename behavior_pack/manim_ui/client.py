# -*- coding: utf-8 -*-
# pylint: disable=unexpected-keyword-arg,E1123
"""Client-only transport and playback; glyph geometry stays on the GPU."""
import mod.client.extraClientApi as clientApi
from .generated_scenes import SCENES
from .timeline import get_playback_clock
from .playback import PlaybackController
from . import pyreact

ClientSystem = clientApi.GetClientSystemCls()
PLAYER_PAGE_KEY = "manim_player"
CANVAS_PAGE_KEY = "manim_canvas_demo"


class ManimClient(ClientSystem):
    def __init__(self, namespace, system_name):
        ClientSystem.__init__(self, namespace, system_name)
        factory = clientApi.GetEngineCompFactory()
        self.post = factory.CreatePostProcess(clientApi.GetLevelId())
        self.game = factory.CreateGame(clientApi.GetLevelId())
        # NetEase 3.10 postprocess UV origin is bottom-left, unlike atlas rows.
        self.flip_y = True
        self.viewport = (1280.0, 720.0)
        self._viewport_dirty = False
        self.canvas = (0.0, 1.0)
        self.ui_scale = 1.0
        self._last_parameters = None
        self._touched_post_names = set()
        self._clock = get_playback_clock(platform=clientApi.GetPlatform())
        self.playback = PlaybackController(SCENES, self, self._clock)
        self.scenes = self.playback.scenes
        self.canvas_demo = None
        self._reopen_key = str(clientApi.GetMinecraftEnum().KeyBoardType.KEY_F8)
        self._listeners = [
            ("UiInitFinished", self.on_ui_ready),
            ("GameRenderTickEvent", self.on_frame),
            ("ScreenSizeChangedClientEvent", self.on_resize),
            ("OnKeyPressInGame", self.on_key),
        ]
        pyreact.runtime_init(self, debug=True)
        for event, callback in self._listeners:
            self.ListenForEvent(clientApi.GetEngineNamespace(), clientApi.GetEngineSystemName(), event, self, callback)

    # Compatibility for the demo panel and existing diagnostics. New callers
    # select names through load/play rather than relying on generated indices.
    scene_index = property(lambda self: self.playback.scene_index)
    timeline = property(lambda self: self.playback.timeline)
    visible = property(lambda self: self.playback.visible)
    _subscribers = property(lambda self: self.playback._subscribers)

    @property
    def error(self):
        return self.playback.error

    @error.setter
    def error(self, value):
        self.playback.error = value

    def on_ui_ready(self, _args=None):
        if self.playback.disposed:
            return
        self.update_viewport()
        if not self.scenes:
            self.error = "No compiled scenes. Run tools/deploy_demo.py."
        elif self.timeline is None:
            self.select_scene(0)
        self.open_panel()

    def open_panel(self):
        if self.playback.disposed:
            return False
        navigator = pyreact.navigator
        if not navigator.is_ready or navigator.is_transitioning:
            return False
        if navigator.contains(PLAYER_PAGE_KEY):
            return True
        from .panel import PlayerPanel
        return navigator.push(PlayerPanel(player=self), key=PLAYER_PAGE_KEY,
                              on_error=self.on_ui_error)

    def on_key(self, args):
        # Public OnKeyPressInGame uses strings for key and isDown. Release
        # avoids keyboard auto-repeat; only the game HUD may reopen our page.
        if (args.get("key") != self._reopen_key or args.get("isDown") != "0"
                or args.get("screenName") != "hud_screen"):
            return
        if clientApi.GetTopUI() != "hud_screen":
            return
        self.open_panel()

    def open_canvas_panel(self):
        navigator = pyreact.navigator
        if self.playback.disposed or not navigator.is_ready or navigator.is_transitioning:
            return False
        if navigator.contains(CANVAS_PAGE_KEY):
            return True
        from .canvas_panel import CanvasDemo, CanvasPanel
        self.canvas_demo = CanvasDemo()
        self.hide()
        accepted = navigator.push(CanvasPanel(demo=self.canvas_demo, onBack=self.close_canvas_panel),
                                  key=CANVAS_PAGE_KEY, on_result=self._canvas_closed,
                                  on_error=self._canvas_error)
        if not accepted and self.canvas_demo is not None:
            self._canvas_closed()
        return accepted

    def close_canvas_panel(self):
        navigator = pyreact.navigator
        if not navigator.contains(CANVAS_PAGE_KEY) or navigator.is_transitioning:
            return False
        return navigator.pop()

    def canvas_snapshot(self):
        return self.canvas_demo.snapshot() if self.canvas_demo is not None else None

    def _canvas_closed(self, _result=None):
        if self.canvas_demo is not None:
            self.canvas_demo.dispose()
            self.canvas_demo = None
        if not self.playback.disposed and pyreact.navigator.contains(PLAYER_PAGE_KEY):
            self.show()

    def _canvas_error(self, error):
        self._canvas_closed()
        self.error = "Canvas UI failed: " + str(error)
        print("[manim-ui] " + self.error)
        self.notify()

    def on_ui_error(self, error):
        self.hide()
        self.error = "Player UI failed: " + str(error)
        print("[manim-ui] " + self.error)

    def on_resize(self, args):
        # The event may precede the engine's physical viewport update. Read
        # the new values on the next render frame, coalescing resize bursts.
        self._viewport_dirty = True

    def update_viewport(self):
        self.viewport = self.game.GetScreenViewInfo()[:2]
        logical_height = float(self.game.GetScreenSize()[1])
        if logical_height > 0:
            # Reserve logical UI pixels above/below the picture. Tiny screens
            # compress both margins proportionally, keeping at least 35% canvas.
            margin_scale = min(1.0, logical_height * 0.65 / 170.0)
            self.ui_scale = margin_scale
            top = 55.0 * margin_scale / logical_height
            height = 1.0 - 170.0 * margin_scale / logical_height
            self.canvas = (top, height)
        else:
            self.canvas = (0.0, 1.0)
            self.ui_scale = 1.0
        self._last_parameters = None

    def install_scene(self, scene):
        name = scene["post_name"]
        self._touched_post_names.add(name)
        if name in (self.post.GetPostProcessOrder() or []):
            return True, True
        definition = {
            "name": name,
            "enable": False,
            "paras": [
                {"name": "playback", "value": [0.0, 1.7777778, 720.0, 1.0]},
                {"name": "options", "value": [0.0, 0.0, 0.0, 0.0]},
            ],
            "pass_array": [{
                "render_target": {"width": 1.0, "height": 1.0},
                "material": scene["material"],
                "depth_enable": False,
                "bindTexture": [{"texture": scene["texture"]}],
            }],
        }
        result = self.post.AddPostProcess(definition)
        disabled = self.post.SetEnableByName(name, False)
        return bool(result and disabled), False

    def scene_names(self):
        return self.playback.scene_names()

    def load(self, name):
        return self.playback.load(name)

    def load_timings(self):
        return self.playback.load_timings()

    def select_scene(self, index):
        if not self.scenes:
            return False
        target_index = int(index) % len(self.scenes)
        return self.load(self.scenes[target_index]["name"])

    def set_scene_visible(self, scene, enabled):
        self._last_parameters = None
        return bool(self.post.SetEnableByName(scene["post_name"], enabled))

    def release_scenes(self):
        # The public SDK has no documented whole-process removal API. Disable
        # only our visited scenes; keep native registrations available for reuse.
        for name in self._touched_post_names:
            self.post.SetEnableByName(name, False)
        self._touched_post_names.clear()
        self._last_parameters = None

    def show(self):
        return self.playback.show()

    def hide(self):
        return self.playback.hide()

    def play(self, name=None):
        return self.playback.play(name)

    def pause(self):
        return self.playback.pause()

    def replay(self, name=None):
        return self.playback.replay(name)

    def stop(self):
        return self.playback.stop()

    def toggle_play(self):
        if self.timeline is None:
            return False
        if self.timeline.playing:
            return self.pause()
        return self.play()

    def seek(self, seconds):
        return self.playback.seek(seconds)

    def on_frame(self, _args=None):
        if self.playback.disposed:
            return
        if self._viewport_dirty:
            self._viewport_dirty = False
            self.update_viewport()
        self._update_frame()

    def _update_frame(self):
        self.playback.frame()

    def render_scene(self, scene, position):
        width, height = self.viewport
        if height <= 0 or width <= 0:
            return True
        top_ratio, height_ratio = self.canvas
        canvas_height = float(height) * height_ratio
        parameters = (position, float(width) / canvas_height, canvas_height, 1.0)
        options = (float(self.flip_y), top_ratio, height_ratio, 0.0)
        cache_key = (parameters, options)
        if cache_key != self._last_parameters:
            name = scene["post_name"]
            ok = self.post.SetParameter(name, "playback", list(parameters))
            ok_options = self.post.SetParameter(name, "options", list(options))
            if not ok or not ok_options:
                return False
            self._last_parameters = cache_key
        return True

    def snapshot(self):
        state = self.playback.snapshot()
        state.update(flip_y=self.flip_y, ui_scale=self.ui_scale)
        return state

    def subscribe(self, callback):
        if not callable(callback):
            raise TypeError("subscriber must be callable")
        return self.playback.subscribe(lambda _state: callback(self.snapshot()))

    def notify(self):
        self.playback.notify()

    def dispose(self):
        return self.Destroy()

    def Destroy(self):
        if self.canvas_demo is not None:
            self.canvas_demo.dispose()
            self.canvas_demo = None
        disposed = self.playback.dispose()
        for event, callback in self._listeners:
            self.UnListenForEvent(clientApi.GetEngineNamespace(), clientApi.GetEngineSystemName(), event, self, callback)
        self._listeners = []
        return disposed
