# pyreact-manim-ui

在网易版 Minecraft 中播放 Manim 风格的文字转换与二维数学动画。宿主 Python 离线生成几何、时间数据和 shader，游戏 Python 2 负责播放、暂停与进度控制；玩家端无需安装 Manim、LaTeX 或额外计算服务。

当前优先交付**可操作、可修改的初版演示**。整体不追求完整 Manim 功能；文字转换仍以固定 ManimGL 参考的 1:1 为目标，**尚未通过严格 1:1 验收**。真实上游导出、离线测试通过与 MC 画面一致是不同的验证结果。

## 初版内容

| 示例 | 可观察的内容 | 边界 |
| --- | --- | --- |
| O → B | 字形轮廓、孔洞与中间态 | 固定参考样例，严格一致性待验证 |
| C → S | 开口字形的连续转换 | 固定参考样例，严格一致性待验证 |
| 8 → 1 | 多轮廓变化 | 明确启用 marker 近似的预览，不是 1:1 通过项 |
| UI → UX | 多字符转换 | 明确启用 marker 近似的预览，不代表语义字符匹配已完成 |
| `basic_geometry` | 圆变矩形、旋转、缩放、平移与淡入淡出 | 二维多边形近似 |
| `axes_sine` | 坐标轴、正弦曲线逐段绘制、点沿曲线移动 | 静态 Python 生成的确定性场景 |

Pyreact 播放器已集成，支持播放/暂停、拖动进度、起点/中间态/终点、上一例/下一例、Esc 关闭及回到游戏画面后 F8 重开。关闭后保留当前场景和暂停位置。

当前画布仍由**全屏后处理**绘制，上下为控制面板预留空间；这不等于已实现可嵌入任意页面、独立裁剪的 UI 组件。首版运行环境为 Windows 网易开发客户端，手机计时与输入尚未适配。

六例已完成后台实机复验：18 个定点画面、播放状态、关闭重开路径及 640×360 小窗口布局。96 项离线测试通过，60 FPS 上限下四次采样约为 60.08 FPS。证据和边界见 [初版验收记录](docs/INITIAL_ACCEPTANCE.md)；这些测量不扩张为其他设备的性能保证。

## 开始使用

先阅读 [快速入门](docs/QUICKSTART.md)：前半部分介绍游戏内演示操作，后半部分介绍修改静态 Python 和重新构建。

已配置开发环境时，构建全部六例并部署到本仓库行为包、资源包：

```powershell
.\.venv-reference\Scripts\python.exe -B -X utf8 tools/build_demo.py --render-reference
```

启动受管测试实例，固定 60 FPS，并强制后台不激活：

```powershell
python -B -X utf8 tools/start_dev.py --owner manim-demo
```

启动前需按 [调试环境说明](.agents/skills/pyreact-debugging/references/setup.md) 配置本机 `.mcdev.json`，并按 [后台测试约定](docs/BACKGROUND_TESTING.md) 设置 `background-tools.local.json`。启动器默认等待 120 秒，记录独立 session/owner；不接管其他对话的 MC 实例。后台 guard 缺失时停止，不退回普通前台启动。

## 开发与文档

- [开发路线](docs/DEVELOPMENT_PLAN.md)：初版范围、后续文字一致性和 UI 里程碑。
- [实现架构](docs/ARCHITECTURE.md)：宿主/游戏边界、两种数据格式、shader 与时间轴。
- [验收标准](docs/ACCEPTANCE.md)：如何区分实现、离线验证、实机验证与 1:1。
- [迁移记录](docs/MIGRATION.md)：skills、agent 约定、调试脚本与共享 MCP。
- [开发约定](AGENTS.md) 与 [第三方来源](THIRD_PARTY_NOTICES.md)：字体、ManimGL、PyreactMC 的版本和许可。

通用宿主包要求 Python 3.10+；固定参考环境已使用 Python 3.13，受管 MC 调试脚本要求 Python 3.12+、Windows x64。大型环境、世界、日志和截图保存在忽略目录，不随源码复制。
