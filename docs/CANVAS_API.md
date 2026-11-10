# 独立 UI 画布 API

`ManimCanvas` 将预置文字、公式和二维场景放到真正的 JSON UI 控件中。它使用网易纸娃娃的实体材质绘制一个平面，并把平面的顶点精确映射到控件矩形。游戏 Python 只更新播放参数，shader 在 GPU 上绘制透明画面；不会把全屏后处理剪成一个矩形来冒充局部控件。

另外提供 `runtime_shapes`：同一个通用 shader 接受游戏运行时新产生的形状、颜色、角度和进度参数。该能力无需为每组参数预编译动画，但不包含运行时任意字体解析、文字轮廓生成或 LaTeX 排版。

## 最小业务接入

播放器的生命周期应由页面或业务模型持有，不要在每次组件 render 时重新创建。

```python
# 客户端 Python；框架已调用 pyreact.runtime_init。
from manim_ui.canvas import create_canvas_player
from manim_ui.canvas_primitive import ManimCanvas
from manim_ui.pyreact import Component, Style


class AnimationModel(object):
    def __init__(self):
        self.player = create_canvas_player()

    def close(self):
        self.player.dispose()


def on_ready(player):
    # 此时原生控件已有尺寸、场景已加载，可安全发出播放命令。
    player.seek(1.0)


@Component
def AnimationCard(model):
    return ManimCanvas(
        player=model.player,
        scene="manimgl_chinese_change",
        autoPlay=False,
        onReady=on_ready,
        style=Style(width=280, height=160, opacity=0.85, zIndex=3),
    )
```

播放器在挂载前可查询 `scene_names()` 和 `snapshot()`，也可设置实时图元参数。不要提前 `load()` / `play()`：未挂载或布局尺寸为零时加载会明确失败。Primitive 在首个完成布局的渲染帧加载 `scene`，然后触发一次 `onReady(player)`。

`scene` 是声明式选择。变更该 prop 会重新加载对应场景。若界面后续通过 `player.load(name)` 操作，保持 prop 为初始值即可；普通状态重渲染不会强制恢复初始场景。`autoPlay` 默认 False，变更该 prop 才重新控制播放状态；业务随后调用 `play()` / `pause()` 不会被未变化的 prop 覆盖。

## 播放与参数

`create_canvas_player()` 返回与全屏演示相同的 `PlaybackController`：

| 操作 | 行为 |
| --- | --- |
| `scene_names()` | 返回已编译场景名，包括 `runtime_shapes` |
| `load(name)` | 选择场景，显示首帧并暂停；返回成功与否 |
| `play()` / `play(name)` | 继续当前场景，或选择并播放场景 |
| `pause()` | 暂停并保留当前画面 |
| `seek(seconds)` | 暂停并跳到指定时刻；隐藏状态不会因此重新显示 |
| `replay()` | 从零开始播放当前场景 |
| `stop()` | 暂停、隐藏并把时间归零 |
| `show()` / `hide()` | 控制播放内容的显隐；与布局控件自身的可见性分别管理 |
| `subscribe(callback)` | 订阅状态，返回可重复调用的取消订阅函数 |
| `snapshot()` | 获取场景、时间、时长、播放/可见/销毁状态及错误 |
| `load_timings()` | 获取近期同步 API 加载耗时；不代表 GPU 已显示的首帧耗时 |
| `dispose()` | 永久结束播放器、释放资源和槽位；可重复调用 |

实时图元示例：

```python
# 同样在 ManimCanvas 内挂载，scene="runtime_shapes"。
player.renderer.set_shape(
    morph=0.4,
    progress=0.72,
    stroke_width=0.035,
    scale=0.8,
    color=(1.0, 0.4, 0.75),
    rotation=0.785398,
)
parameters = player.renderer.shape_snapshot()
```

| 参数 | 范围与单位 |
| --- | --- |
| `morph` | 0..1，0 是圆形，1 是矩形，中间值连续变化 |
| `progress` | 0..1，从顶部开始顺时针揭示轮廓/形状 |
| `stroke_width` | 非负有限数，以画布高度为归一单位；0 为实心，大于 0 为描边 |
| `scale` | 大于 0 的有限数，缩放形状 |
| `color` | 三个 0..1 的 RGB 分量 |
| `rotation` | 有限数，单位为弧度 |

只传要修改的字段即可。参数先完整验证再更新，错误不会留下部分参数修改。`set_shape()` 返回 uniform 上传是否成功；未选中实时场景时只保存参数，选中后使用。未知字段、非有限数或超出上述范围会抛出 `ValueError`，不默默钳制。

## 两个槽位和清理

当前同屏最多两个独立画布，槽位由挂载自动分配。不是按场景名共享播放时间：每个槽位有自己的实体 identifier、uniform、播放器和缓存。第三个同时挂载会明确抛出 `RuntimeError`，避免两个组件覆盖彼此。

Primitive 卸载时停止播放器、注销框架帧回调、隐藏原生控件并释放槽位。未 `dispose()` 的播放器可以重新挂载；重挂会按该组件的 `scene` 从初始状态加载。页面真正关闭时应取消订阅并 `dispose()` 自己持有的播放器。页面 effect 先 dispose、随后 Primitive 才卸载的顺序也受支持，清理是幂等的。

不要把一个播放器同时交给两个 `ManimCanvas`。需要并排显示时分别创建两个播放器。导航离开时不要只保留隐藏组件占据槽位；应卸载对应组件或销毁页面。

所有操作都在 MC 客户端线程执行，不从服务端或后台工作线程初始化 UI / SDK 组件。这里没有独立注册游戏事件；每帧工作复用 Pyreact 宿主的动画帧生命周期。

## 布局、透明度与裁剪

- 宽高、位置、可见性、`zIndex` 和 `opacity` 使用普通 Pyreact `Style`。有效透明度含祖先继承，必须是 0..1 的有限数；纸娃娃自身的 `SetAlpha` 不承担这项能力，透明度写入 shader。
- 原生布局完成后的下一个渲染帧，使用 Pyreact 已提交的宽高/相对位置，加原生父控件 `GetGlobalPosition()`，根据逻辑屏幕尺寸生成 NDC 矩形，避免 resize 事件早于物理 viewport 更新。网易引擎中隐藏控件的 `GetSize()` 会变成零，因此生产 Primitive 不依赖隐藏目标的原生尺寸。窗口缩放或布局变化时安排一次刷新；普通播放帧只上传变化的参数，不重复获取屏幕信息。仅回调引用变化不触发布局。
- 专用模板开启 `enable_scissor_test`，使用原生 UI 的层级与裁剪。较高层的图片可覆盖画布，透明区域保留下方 UI 和世界画面。
- 预置场景按其作者画幅等比包含在控件内，不会把字形拉伸成控件长宽比。实时图元也按画布比例保持几何一致。
- 原生父控件的 `clips_children` 可裁剪溢出部分。普通 Pyreact `Panel` 暂未暴露 `clips_children` prop，不要编造该 prop；需要越界裁剪的容器应使用已配置的原生模板或现有滚动容器。
- 当前保证矩形画布、常规位置与正向尺寸/缩放。没有承诺任意旋转 UI 控件、负尺寸镜像、圆角蒙版或复杂嵌套滚动的所有组合；按具体业务补实机验收。

## 错误与验证边界

GPU 参数上传或实体渲染 API 返回 False 时，播放器不能报告成功播放。初始矩形与图元参数先上传，非零可见度最后上传；失败时停止并隐藏。`snapshot()["error"]` 保留错误文本。销毁首先隐藏原生控件，避免清理 uniform 失败时留下旧图。

`hide()` 始终同时隐藏原生控件，即使关闭 alpha 的上传失败也不会留下旧画面。恢复显示时重新读取当前 `Style.visible`，不会用隐藏时的旧值覆盖业务后来设置的可见性。每帧只比较已有的 Python 状态，未变化时不重复调用原生显隐接口。

首次挂载尚未绑定实体时保留样式允许的可见性，供引擎完成布局；此时没有实体画面。不能在初始化就强行隐藏再等待原生测量，否则会形成“隐藏 → 零尺寸 → 永远未就绪”的循环。回归用例模拟了这个真实引擎行为，并覆盖隐藏期间改变尺寸后再显示。

布局参数上传失败会记录明确错误并停止播放，已经测得的有效矩形继续保留。接口恢复后，业务调用 `play()` 即可重试，不要求人为再调整一次窗口。初始自动加载失败会保留帧回调但停止重复自动请求；明确调用成功的 `load()` / `play()` 或更改声明式场景后可以恢复，避免“状态显示播放中、宿主却不再推进”的停滞。

已离线验证：两个槽位竞争与复用、未布局拒绝播放、每帧缓存、参数校验与独立性、上传失败、卸载重挂、页面先销毁再卸载、替换播放器的可见性、尺寸与透明度更新。

隔离探针 v2 已由主代理实机确认矩形映射、两个独立进度/颜色、透明底、前景遮挡和父面板裁剪。正式组件随后通过十个预置场景的 30 帧、任意参数图元一帧、两个时钟、三轮重开和隐藏后缩放恢复；见 [本轮集成验收](RUNTIME_ACCEPTANCE.md)。调用与画面验证均在后台完成，实际鼠标／触屏操作由人工复核。
