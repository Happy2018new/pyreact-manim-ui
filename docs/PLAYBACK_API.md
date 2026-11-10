# 播放 API

本 API 控制已经编译、部署到资源包的场景：按名称选择，播放、暂停、定位、重播和停止，并向业务界面提供状态订阅。游戏运行时使用 Python 2，所有调用和回调都应在客户端线程执行。

本文的客户端系统入口是后处理画布，共用一个播放实例。0.3.0 另提供使用同一播放控制器的独立双实例 UI，创建方式见 [画布 API](CANVAS_API.md)。两者均不包含运行时字体排版、任意新文字或 LaTeX 编译能力。能力范围见 [架构](ARCHITECTURE.md)。

## 业务接入

在模组客户端系统已注册、游戏 UI 初始化完成后取得播放器。业务代码使用稳定的场景名称，不依赖演示列表下标。

```python
# -*- coding: utf-8 -*-
import mod.client.extraClientApi as clientApi

player = clientApi.GetSystem("pyreact_manim_ui", "player")
if player is not None:
    names = player.scene_names()
    if "manimgl_o_to_b" in names:
        if not player.play("manimgl_o_to_b"):
            print("Animation failed: " + player.snapshot()["error"])
```

`scene_names()` 返回已部署场景名称组成的元组；调用不会安装 shader。场景配置来自 `behavior_pack/manim_ui/generated_scenes.py`，应通过现有构建、部署工具更新。中文、公式名称同样可以选择，例如 `manimgl_chinese_change` 和 `manimgl_fraction_swap`，不需要在运行时重新提供文字或公式源文件。

```python
player.load("manimgl_chinese_change")  # 切到首帧、显示、保持暂停
player.seek(0.8)                       # 暂停并定位到 0.8 秒
player.play()                          # 从当前位置继续
player.pause()                         # 停在当前画面
player.replay()                        # 回到 0 秒并播放
player.hide()                          # 暂停并隐藏，保留位置
player.show()                          # 显示保留的画面
player.stop()                          # 暂停、隐藏并回到 0 秒
```

这些操作共用当前场景、播放位置和可见性。多个业务页面需要由上层协调控制权，不能把它们当成彼此独立的播放器。现有演示页仍会在挂载时调用 `show()`，卸载时调用 `hide()`。

## 方法与状态

| 方法 | 行为和返回值 |
| --- | --- |
| `scene_names()` | 返回场景名称元组，不触发安装。 |
| `load(name)` | 安装或复用场景，显示首帧并暂停；即使名称与当前相同也会归零。成功返回 `True`。 |
| `play(name=None)` | 未传名称时继续当前场景；没有已选场景时选择第一项。传入不同名称时先加载；传入当前名称时继续当前位置。已经播放时重复调用不重置计时。到达终点后再次播放从零开始。 |
| `pause()` | 暂停并更新到当前时刻，保留可见性。 |
| `seek(seconds)` | 暂停并定位，时间夹到 `[0, duration]`。隐藏状态下不会自动显示。 |
| `replay(name=None)` | 选择指定场景或使用当前场景，回到零点并播放。 |
| `stop()` | 暂停、隐藏、位置归零，保留已安装资源便于重播。 |
| `show()` | 显示当前场景并更新画面；不主动从暂停状态开始播放。 |
| `hide()` | 暂停并隐藏，保留位置。 |
| `snapshot()` | 返回最近状态的独立字典；不会主动推进时间轴或查询引擎画面。 |
| `subscribe(callback)` | 订阅后续状态变化，返回取消函数；不会立即回调。 |
| `load_timings()` | 返回最近最多 32 次加载记录的副本。 |
| `dispose()` | 终止此客户端播放器并清理其监听；首次返回 `True`，重复调用返回 `False`。 |

播放控制方法通常返回布尔成功值。尚未选择场景时，`pause/seek/stop/show` 返回 `False`；`play/replay` 可选择第一项，空列表则返回 `False`。销毁后所有播放控制均返回 `False`，不会重新安装资源。`seek` 的 NaN、无穷值会抛出 `ValueError`；不可转换为数字的输入也会报错，不会静默接受。无效参数应在业务输入层处理。

`snapshot()` 字段如下：

| 字段 | 含义 |
| --- | --- |
| `scene`、`title` | 当前场景名称和标题；尚未加载时可能是列表第一项的元数据，不能仅凭它们认定加载成功。 |
| `position`、`duration` | 最近采样的播放位置与时长，单位秒。 |
| `playing`、`visible` | 时间轴是否播放、播放器是否处于显示状态；不是 GPU 像素验收结果。 |
| `error` | 最近记录的错误文本；成功显示场景时清空。 |
| `disposed` | 是否已经终止。 |
| `last_load` | 最近一次有效名称加载的计时记录；尚无记录时为 `None`。 |
| `flip_y`、`ui_scale` | 客户端适配层提供的画面方向与演示控件缩放信息。独立控制器的快照不包含这两项。 |

普通业务不要直接修改 `timeline`、`scene_index`、`visible` 等内部状态。索引接口 `select_scene(index)` 和 `toggle_play()` 继续保留，供原有演示面板与诊断脚本兼容使用。

## 订阅与页面清理

先读取一次快照，再订阅后续变化。渲染帧驱动的状态通知约每 0.1 秒一次；播放操作等状态变化还会立即通知，因此它不是固定频率定时器。

```python
def on_state_changed(state):
    # 更新本页控件；避免在这里做耗时工作或不断触发播放操作。
    update_progress(state["position"], state["duration"])
    update_play_button(state["playing"])

on_state_changed(player.snapshot())
unsubscribe = player.subscribe(on_state_changed)

# 页面退出时：
unsubscribe()
player.hide()
```

上例的 `update_progress`、`update_play_button` 是业务自己的界面更新函数。Pyreact 组件可在 `use_effect` 中订阅，并在 effect 返回的清理函数中执行取消与隐藏；当前演示实现见 `behavior_pack/manim_ui/panel.py`。

取消函数可以重复调用，播放器销毁后迟到的页面清理也安全。同一回调订阅两次会形成两份独立订阅，需要分别取消。某个订阅抛出异常时会输出完整 traceback，其他订阅仍能接收通知。销毁会直接清空订阅，不保证发送一条最终 `disposed=True` 回调；需要查看终止状态时显式读取快照。

## 失败与恢复

| 失败情况 | 已选场景与恢复方式 |
| --- | --- |
| 名称不存在 | 返回 `False`，记录错误，保持原场景及播放状态；不新增加载计时。调用正确名称重试。 |
| 安装失败 | 原场景暂停并隐藏，保留其时间轴和位置，不把失败场景的时长套到旧 shader。可 `play()` 恢复原场景，或重试目标名称。首次安装失败时仍没有时间轴。 |
| 安装成功、启用失败 | 目标场景已选中，停在首帧且不播放，加载返回 `False`。修复原因后可 `show()` 或 `play()` 重试。 |
| 参数上传失败 | 暂停并请求关闭效果，记录错误；发生在加载期间时加载返回 `False`。修复原因后可重新显示或播放。 |
| 播放器已经销毁 | 控制方法返回 `False`，不会重新打开页面或恢复播放；应由系统生命周期重新创建实例。 |

这些失败语义覆盖适配层识别的 SDK 返回值；它们不是对设备丢失、进程崩溃或所有 SDK 异常的恢复保证。`True` 表示同步操作获得预期返回值，仍需实机画面确认 shader 实际输出。错误日志以 `[manim-ui]` 为前缀。

## 加载计时的含义

播放器复用播放时间轴的单调时钟。Windows Python 2 使用 `time.clock()` 的 QPC 实现；宿主 Python 3 使用 `perf_counter()`。记录不采用可受系统校时影响的墙上时间。

```python
if player.load("manimgl_chinese_change"):
    record = player.snapshot()["last_load"]
    print(record["operation"], record["install_seconds"], record["total_seconds"])

records = player.load_timings()
```

| 字段 | 含义 |
| --- | --- |
| `scene`、`previous_scene` | 目标场景名称和操作前已选名称；此前未选时后者为空字符串。 |
| `operation` | `first_install`：此前未选场景且没有复用；`switch_install`：此前已有场景且没有复用；`reuse`：后处理名称已在引擎列表中。失败尝试也按此规则分类，必须同时查看 `success`。 |
| `reused` | 是否从引擎后处理列表发现既有名称并跳过 `AddPostProcess`；不表示 GPU 仍保有编译缓存。 |
| `success` | 本次选择、启用及初次参数上传的同步结果是否成功。 |
| `install_seconds` | `install_scene` 同步调用时间，包括查询后处理列表，以及必要时添加并关闭默认启动的效果。 |
| `total_seconds` | 本次有效名称加载从暂停旧场景到新场景启用、初次参数更新或失败结束的同步耗时；不含随后分发订阅回调的时间。 |

只保存最近 32 条，返回数据为副本。恢复播放、暂停和定位不会各自新增加载记录。当前没有预热所有 shader；第一次选择某场景时才尝试安装。

这些数字不能被写作 GPU 编译时间、首帧时间或帧率。驱动可能在后续渲染帧继续编译或准备资源，首次可见画面延迟必须另用实机证据测量。尤其是中文复杂轮廓场景，同步接口返回不等于冷加载已经结束。

## `dispose` 的边界

业务页面的普通退出应取消订阅并调用 `hide()` 或 `stop()`。`dispose()` 用于整个播放器的最终结束，会暂停播放、关闭本播放器触及的后处理、清空订阅，并注销该客户端系统注册的游戏事件；随后 F8 等事件不能让它重新打开。

当前公开文档未找到完整移除后处理对象的接口。因此此处的资源清理是关闭效果并清理 Python 侧订阅及游戏事件监听，已经注册的后处理、材质和纹理仍由引擎管理。不能把 `dispose()` 当成 shader/GPU 显存卸载，也不保证返还所有原生内存。

## 两支全屏作品与配乐

`player.open_showcase()` 继续打开《万象变换》，`player.open_showcase("story_showcase")` 打开《风借来的一颗星》。页面挂载完成后开始播放。`switch_showcase()` 在两片间切换并重播，`replay_showcase()` 重播当前片，`close_showcase()` 返回先前场景的暂停位置。右下角按钮提供相同操作及暂停／继续。

`snapshot()` 新增 `showcase_scene`、`audio_error` 和 `audio`，后者记录当前资源名、音乐ID、最近失败返回值及等待停止状态。配乐使用本项目命名的 `PlayCustomUIMusic` 资源，不调用全局停音或修改全局音量。两个120秒音轨各按5秒分段，分段另有1／2／3／4秒起点尾段。恢复／seek 后选择向下取整的起点，音画时间偏差理论小于1秒，并在下一5秒边界重新对齐；游戏帧调度和解码还可能产生额外延迟。这是公开SDK没有样本偏移参数时的接入限制，不声明样本级同步。

新增声音文件需要重新启动整个客户端；只热重载 Python 不会发现新的 OGG。完整构建与资源路径见 [双片说明](DUAL_PRESENTATIONS.md)。

它不会替业务弹出导航页面，也不销毁共享 Pyreact 框架。结束整个播放器前，业务应按自己的页面生命周期卸载界面；无需终止整个系统时不要调用它。

## 控制器与渲染适配层

`behavior_pack/manim_ui/playback.py` 的 `PlaybackController` 不导入 ModSDK，接收场景列表、渲染器和单调时钟。当前 `ManimClient` 提供后处理适配。渲染器约定为：

| 方法 | 约定 |
| --- | --- |
| `install_scene(scene)` | 返回 `(ok, reused)`，准备可显示的场景资源。 |
| `set_scene_visible(scene, enabled)` | 设置资源显示状态，返回布尔结果。 |
| `render_scene(scene, position)` | 按时间提交画面参数，返回布尔结果。 |
| `release_scenes()` | 清理此渲染器管理的效果；具体释放程度由适配层能力决定。 |

控制器管理时间轴和订阅，适配层管理原生资源及事件。这个接口可以支持后续渲染接入，但只有当前后处理适配已在本文件描述；不能据此声称独立 UI 画布或任意运行时场景已完成。

## 验证范围

`tests/test_playback_api.py` 覆盖名称选择、操作语义、失败恢复、单调时钟计时、复用、重复订阅和终止状态；`tests/test_player_lifecycle.py` 覆盖实际客户端适配代码与模拟 SDK 边界，保留 resize、视口和页面生命周期回归；`tests/test_timeline.py` 验证时间轴。

宿主测试证明控制流与状态行为，不替代 Minecraft 图像验收。`tools/verify_player.py` 保留既有十个示例的实机检查入口；实机操作仍必须使用项目约定的受管、后台、60 FPS 测试实例。
