# pyreact-manim-ui

在网易版 Minecraft 中播放 Manim 风格的文字转换与二维数学动画。宿主 Python 离线生成几何、时间数据和 shader，游戏 Python 2 负责播放、暂停与进度控制；玩家端无需安装 Manim、LaTeX 或额外计算服务。

当前版本为 **0.3.0 预览版**，优先提供可操作、可修改的文字、中文和公式变换。按用户最新要求，保留已验证的画面修正，停止继续追逐微小像素差异，以快速交付为主。**尚未通过严格 1:1 验收**；本版本不以逐像素一致为交付门槛。

当前提供两支 **120 秒、1080p60** 作品：《万象变换 V6》用同一组曲线、控制点和面积拼块连续演出数学变换；《风借来的一颗星 V2》以原创曲线人物、层叠村落和贯穿全片的风线讲述旅程。两片文字共用闭合轮廓对应点变换，英文由 LaTeX Computer Modern 排版，中文使用宋体；童话字幕从上一句连续变为下一句。两片共享游戏播放器、片内切换、暂停／继续和重播，原创配乐及风声已打包进游戏资源。影片内容、构建命令与音频边界见 [双片说明](docs/DUAL_PRESENTATIONS.md)。当前视频分别位于 `dist/client-showcase-v6/` 和 `dist/storybook-wind-v2/`；按用户要求直接交其观看，没有执行本版逐帧或完整实机验收，旧版视频保留。

## 初版内容

| 示例 | 可观察的内容 | 边界 |
| --- | --- | --- |
| O → B | 字形轮廓、孔洞与中间态 | 固定参考样例，严格一致性待验证 |
| C → S | 开口字形的连续转换 | 固定参考样例，严格一致性待验证 |
| 8 → 1 | 多轮廓变化 | 明确启用 marker 近似的预览，不是 1:1 通过项 |
| UI → UX | 多字符转换 | 明确启用 marker 近似的预览，不代表语义字符匹配已完成 |
| 中文 → 变换 | 宋体中文轮廓连续变换 | 使用可分发的 Noto Serif SC 宋体子集；可改用系统宋体 |
| 数学 → 中文 | 更复杂的中文笔画和孔洞 | 明确检查字体覆盖；不代表所有复杂度的长句均可播放 |
| `\frac{a}{b}` → `\frac{b}{a}` | 真正 LaTeX 分式变换 | 原生 ManimGL Tex 排版；不是把公式源码当作普通文字 |
| `x^2` → `\sqrt{x}` | 上标与根号之间的转换 | 保留原生 Transform；尚未实现语义公式片段匹配 |
| `basic_geometry` | 圆变矩形、旋转、缩放、平移与淡入淡出 | 二维多边形近似 |
| `axes_sine` | 坐标轴、正弦曲线逐段绘制、点沿曲线移动 | 静态 Python 生成的确定性场景 |

Pyreact 播放器已集成，支持播放/暂停、拖动进度、起点/中间态/终点、上一例/下一例、Esc 关闭及回到游戏画面后 F8 重开。关闭后保留当前场景和暂停位置。

0.3.0 新增真正的 **Pyreact 独立 UI 画布**，同屏支持两个独立实例、透明背景、布局缩放与矩形裁剪。主播放器的“独立画布”按钮打开双画布页面：左侧选择十个预置例，右侧实时改变圆形／矩形、描绘进度、旋转和颜色。原后处理播放器保留。首版运行环境为 Windows 网易开发客户端，手机计时与输入尚未适配。

实时图元使用同一 shader 接收游戏中的新参数；文字、中文与复杂公式仍在构建端生成。动态纹理实验的更新依赖全材质重载，尚不适合发布成任意运行时内容引擎；详见 [本版验收与数据入口结论](docs/RUNTIME_ACCEPTANCE.md)。

目前仍有明显冷加载等待：首次载入完整 UI 材质可能持续数分钟，两组中文后处理首装在本次机器上分别约 90 秒和 83 秒。加载后的播放及切例已通过验证，冷加载优化尚未关闭。

0.1.0 的六例、18 帧及小窗口测量作为历史记录保留在 [初版验收记录](docs/INITIAL_ACCEPTANCE.md)。0.2.0 增加的中文、公式与渲染修正另见 [本版验收记录](docs/TEXT_FORMULA_ACCEPTANCE.md)，不把旧版测试数量沿用为新版结果。

## 开始使用

先阅读 [快速入门](docs/QUICKSTART.md)：前半部分介绍游戏内演示操作，后半部分介绍修改静态 Python 和重新构建。

已配置开发环境和 LaTeX 工具链时，构建全部十例并部署到本仓库行为包、资源包：

```powershell
.\.venv-reference\Scripts\python.exe -B -X utf8 tools/build_demo.py --render-reference
```

启动受管测试实例，固定 60 FPS，并强制后台不激活：

```powershell
python -B -X utf8 tools/start_dev.py --owner manim-demo
```

启动前需按 [调试环境说明](.agents/skills/pyreact-debugging/references/setup.md) 配置本机 `.mcdev.json`，并按 [后台测试约定](docs/BACKGROUND_TESTING.md) 设置 `background-tools.local.json`。启动器默认等待 120 秒，记录独立 session/owner；不接管其他对话的 MC 实例。后台 guard 缺失时停止，不退回普通前台启动。

## 开发与文档

- [播放 API](docs/PLAYBACK_API.md) 与 [UI 画布 API](docs/CANVAS_API.md)：业务接入、双实例、实时参数和清理。
- [开发路线](docs/DEVELOPMENT_PLAN.md)：初版范围、后续文字一致性和 UI 里程碑。
- [实现架构](docs/ARCHITECTURE.md)：宿主/游戏边界、两种数据格式、shader 与时间轴。
- [验收标准](docs/ACCEPTANCE.md)：如何区分实现、离线验证、实机验证与 1:1。
- [字体与宋体](tools/reference/FONTS.md)：按系统字体名称选择、显式字体文件和缺字处理。
- [LaTeX 构建](tools/reference/LATEX.md)：本机 TeX 工具链与当前支持范围。
- [迁移记录](docs/MIGRATION.md)：skills、agent 约定、调试脚本与共享 MCP。
- [开发约定](AGENTS.md) 与 [第三方来源](THIRD_PARTY_NOTICES.md)：字体、ManimGL、PyreactMC 的版本和许可。

通用宿主包要求 Python 3.10+；固定参考环境已使用 Python 3.13，受管 MC 调试脚本要求 Python 3.12+、Windows x64。大型环境、世界、日志和截图保存在忽略目录，不随源码复制。
