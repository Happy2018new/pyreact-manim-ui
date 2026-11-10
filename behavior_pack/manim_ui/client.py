# -*- coding: utf-8 -*-
# pylint: disable=unexpected-keyword-arg,E1123
"""Client-only transport and playback; glyph geometry stays on the GPU."""
import mod.client.extraClientApi as clientApi
from .generated_scenes import SCENES
from .timeline import Timeline, get_playback_clock
from . import pyreact

ClientSystem = clientApi.GetClientSystemCls()
PLAYER_PAGE_KEY = "manim_player"


class ManimClient(ClientSystem):
    def __init__(self, namespace, system_name):
        ClientSystem.__init__(self, namespace, system_name)
        factory = clientApi.GetEngineCompFactory()
        self.post = factory.CreatePostProcess(clientApi.GetLevelId())
        self.game = factory.CreateGame(clientApi.GetLevelId())
        self.scenes = SCENES
        self.scene_index = 0
        self.timeline = None
        self.visible = False
        # NetEase 3.10 postprocess UV origin is bottom-left, unlike atlas rows.
        self.flip_y = True
        self.viewport = (1280.0, 720.0)
        self.canvas = (0.0, 1.0)
        self.ui_scale = 1.0
        self.error = ""
        self._subscribers = []
        self._last_notify = 0.0
        self._last_parameters = None
        self._clock = get_playback_clock(platform=clientApi.GetPlatform())
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

    def on_ui_ready(self, _args=None):
        self.update_viewport()
        if not self.scenes:
            self.error = "No compiled scenes. Run tools/deploy_demo.py."
        elif self.timeline is None:
            self.select_scene(0)
        self.open_panel()

    def open_panel(self):
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

    def on_ui_error(self, error):
        self.hide()
        self.error = "Player UI failed: " + str(error)
        print("[manim-ui] " + self.error)

    def on_resize(self, args):
        self.update_viewport()

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

    def _install(self, scene):
        name = scene["post_name"]
        if name in self.post.GetPostProcessOrder():
            return True
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
        self.post.SetEnableByName(name, False)
        return bool(result)

    def select_scene(self, index):
        if not self.scenes:
            return False
        self.hide()
        target_index = int(index) % len(self.scenes)
        scene = self.scenes[target_index]
        if not self._install(scene):
            self.error = "Unable to install shader: " + scene["name"]
            print("[manim-ui] " + self.error)
            self.notify()
            return False
        self.scene_index = target_index
        self.timeline = Timeline(scene["duration"])
        self._last_parameters = None
        self.error = ""
        self.show()
        self.notify()
        return True

    def show(self):
        if self.timeline is None:
            return False
        name = self.scenes[self.scene_index]["post_name"]
        self.visible = bool(self.post.SetEnableByName(name, True))
        if not self.visible:
            self.error = "Unable to enable shader: " + name
            print("[manim-ui] " + self.error)
        self._last_parameters = None
        self.on_frame()
        return self.visible

    def hide(self):
        if self.timeline is not None:
            self.timeline.pause(self._clock())
            self.post.SetEnableByName(self.scenes[self.scene_index]["post_name"], False)
        self.visible = False

    def toggle_play(self):
        if self.timeline is None:
            return
        if self.timeline.playing:
            self.timeline.pause(self._clock())
        else:
            if self.show():
                self.timeline.play(self._clock())
        self.notify()

    def seek(self, seconds):
        if self.timeline is None:
            return
        now = self._clock()
        self.timeline.pause(now)
        self.timeline.seek(seconds, now)
        self.on_frame()
        self.notify()

    def on_frame(self, _args=None):
        if not self.visible or self.timeline is None:
            return
        now = self._clock()
        position = self.timeline.sample(now)
        width, height = self.viewport
        if height <= 0 or width <= 0:
            return
        top_ratio, height_ratio = self.canvas
        canvas_height = float(height) * height_ratio
        parameters = (position, float(width) / canvas_height, canvas_height, 1.0)
        options = (float(self.flip_y), top_ratio, height_ratio, 0.0)
        cache_key = (parameters, options)
        if cache_key != self._last_parameters:
            name = self.scenes[self.scene_index]["post_name"]
            ok = self.post.SetParameter(name, "playback", list(parameters))
            ok_options = self.post.SetParameter(name, "options", list(options))
            if not ok or not ok_options:
                self.error = "Shader parameter update failed"
                self.hide()
                print("[manim-ui] " + self.error)
            self._last_parameters = cache_key
        if now - self._last_notify >= 0.1:
            self._last_notify = now
            self.notify()

    def snapshot(self):
        scene = self.scenes[self.scene_index] if self.scenes else {}
        return {
            "scene": scene.get("name", ""), "title": scene.get("title", ""),
            "position": self.timeline.position if self.timeline else 0.0,
            "duration": self.timeline.duration if self.timeline else 1.0,
            "playing": bool(self.timeline and self.timeline.playing),
            "visible": self.visible, "error": self.error, "flip_y": self.flip_y,
            "ui_scale": self.ui_scale,
        }

    def subscribe(self, callback):
        self._subscribers.append(callback)
        def unsubscribe():
            if callback in self._subscribers:
                self._subscribers.remove(callback)
        return unsubscribe

    def notify(self):
        if not self._subscribers:
            return
        state = self.snapshot()
        for callback in tuple(self._subscribers):
            callback(state)

    def Destroy(self):
        self.hide()
        self._subscribers = []
        for event, callback in self._listeners:
            self.UnListenForEvent(clientApi.GetEngineNamespace(), clientApi.GetEngineSystemName(), event, self, callback)
