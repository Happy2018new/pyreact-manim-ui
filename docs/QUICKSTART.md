# 快速入门

## 先看游戏内演示

在已加载本项目 `behavior_pack` 和 `resource_pack` 的 Windows 网易测试世界中，播放器会在 UI 初始化后打开。首版是一个独立演示，玩家端无需安装 Python、Manim 或 LaTeX。

1. 点击“播放”，观看当前示例；再次点击暂停。
2. 拖动进度条检查中间形状。拖动和“起点 / 中间态 / 终点”按钮都会暂停在选定位置。
3. 用“上一例 / 下一例”浏览四组西文、两组 LaTeX、两组宋体中文、二维图形和坐标轴曲线，共十例。切换后从新示例起点开始。
4. 按 Esc 关闭播放器并暂停效果；回到正常游戏画面后按 F8 重开。场景和暂停位置会保留。

默认文字和公式示例均显式允许轮廓 marker 近似。已保留测得有效的画面修正；按用户要求不再为微小像素差异延迟交付，但也不称为严格 1:1。

画面上下为标题和按钮留空，中间保持场景宽高比。当前仍由全屏后处理绘制，并非可以随意拖入其他页面的独立 UI 控件。

## 在本机启动演示

开发者先按 [调试环境说明](../.agents/skills/pyreact-debugging/references/setup.md) 配置网易开发客户端和本机 `.mcdev.json`，再按 [后台测试约定](BACKGROUND_TESTING.md) 配置带保护的 MCDK 和 `background-tools.local.json`。代理测试必须后台静默，不使用激活游戏的鼠标键盘操作。在仓库根目录运行：

```powershell
python -B -X utf8 tools/start_dev.py --owner manim-demo
```

启动器要求 Python 3.12+、Windows x64，默认有界等待 120 秒。后续调试使用回执中的 session 和相同 owner，不操作其他会话的游戏。

测试上限固定 **60 FPS**。启动器检查真正生效的 Windows roaming `options.txt`，修改前备份到 `.runtime/options-backups/`；配置已为 60 时不改写。需要修改但仍有 MC 进程时会停止并说明原因，不关闭它们。启动回执和 stderr 位于 `.runtime/latest-launch.private.json`、`.runtime/latest-launch.stderr.private.log`，这些文件不应提交或公开。

如果已进入世界但没有面板，先回到正常游戏画面再按 F8；仍失败时检查启动状态和游戏日志。重新生成 shader 后需重新加载资源；不能因为旧页面仍在就认定新 shader 已生效。

## 修改静态 Python 并重新构建

以下步骤运行在开发电脑，不在游戏 Python 2 中执行。固定 ManimGL 参考环境已使用 Python 3.13；字体和依赖版本见 [第三方记录](../THIRD_PARTY_NOTICES.md)。

第一次创建独立参考环境：

```powershell
.\tools\reference\setup_reference.ps1 -Python python
```

其中 `python` 应指向用于构建的 Python 3.13；也可通过 `-Python` 传入实际解释器路径。脚本将环境放在 `.venv-reference/`，下载缓存和安装报告放在 `.runtime/reference/`，不修改全局 Python 包。

默认示例另需本机 LaTeX 与 dvisvgm，见 [LaTeX 构建说明](../tools/reference/LATEX.md)。宋体小子集已经随构建工具提供；扩充中文内容和选择系统字体见 [字体说明](../tools/reference/FONTS.md)。

全部十例构建、原生文字参考帧生成与本仓库部署：

```powershell
.\.venv-reference\Scripts\python.exe -B -X utf8 tools/build_demo.py --render-reference
```

文字输入在 [examples/text_transforms.py](../examples/text_transforms.py)。每条记录声明 `name`、`source`、`target`、`duration` 等导出参数。默认演示使用 `geometry_mode="curve_slots"` 与 `allow_marker_approximation=True`，导出报告保留近似说明。公式使用 `input_kind="latex"`；源码建议使用 Python 原始字符串，例如 `r"\frac{a}{b}"`。

中文可选已安装的宋体等字体，或传入 `font_file` 与匹配的 `font` 名称。构建端检查实际字形覆盖，不存在的字体、缺字或超出每帧 2048 顶点预算会明确报错。默认开源宋体小子集只涵盖示例字符；增加文字前按字体说明扩充子集或改用完整系统字体。目标机器只播放轮廓，不需要安装相同字体；当前没有游戏内动态排版接口。

二维内容在 [examples/basic_2d.py](../examples/basic_2d.py)。`build_scenes()` 返回要构建的场景，默认包括图形与坐标轴两例。简单的编排方式：

```python
from pyreact_manim.animation import FadeIn, Rotate, Shift
from pyreact_manim.geometry import Circle
from pyreact_manim.scene import Scene

scene = Scene("my_circle")
scene.add("circle", Circle())
scene.play(FadeIn("circle"), duration=0.5)
scene.play(Shift("circle", 2, 0), duration=1.0)
scene.play(Rotate("circle", 1.57), duration=1.0)
scene.wait(0.5)
```

把场景加入该文件的 `build_scenes()` 返回列表后，重新执行统一构建命令。一次 `play` 中可以给不同对象并行动画；同一对象不能在同一次 `play` 中被两条动画同时改写。该 API 是本项目的小型二维场景接口，不是任意 Manim 脚本兼容层。

只构建文字时使用 `--skip-2d`；`--examples <路径>` 可替换文字定义文件。注意：部署后的播放列表只包含本次构建的场景，因此 `--skip-2d` 会从当前播放列表移除二维例子。重新执行默认构建可恢复完整列表。

## 生成物与验证

| 位置 | 内容 |
| --- | --- |
| `.runtime/reference/<文字场景>/` | 导出 IR、原始参考、来源/误差报告及可选原生参考帧 |
| `.runtime/compiled/<场景>/` | 数据纹理、shader、带哈希的 `scene.json` manifest |
| `behavior_pack/manim_ui/generated_scenes.py` | 生成的游戏播放列表，不手工修改 |
| `resource_pack/materials/`、`textures/manim/`、`shaders/glsl/` | 部署后的游戏资源 |
| `docs/evidence/` | 可复核的验收摘要；完整本机证据在忽略目录 |

在依赖已安装的宿主环境运行离线回归：

```powershell
.\.venv-reference\Scripts\python.exe -B -X utf8 -m unittest discover -s tests
```

构建成功和测试通过后，还需在 MC 中检查实际画面、控制操作和布局。0.1.0 历史记录见 [初版验收](INITIAL_ACCEPTANCE.md)，当前十例见 [中文与公式验收](TEXT_FORMULA_ACCEPTANCE.md)。严格字形 1:1、语义字符/公式片段匹配和独立 UI 多实例尚未完成。示例输入改变后需重新验证。

## 打包本地预览

在完整构建成功后运行：

```powershell
python -B -X utf8 tools/package_demo.py
```

输出为 `dist/pyreact-manim-ui-0.2.0-preview.mcaddon`，仅包含游戏行为包、资源包和随包许可。宿主环境、参考工具、私有会话信息和截图不进入预览包。该包面向网易 Windows ModSDK 开发环境；国际基岩版不提供这里使用的 Python ModSDK，不能将此包描述为国际版通用 addon。
