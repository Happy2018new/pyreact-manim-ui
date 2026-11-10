# 第三方来源

本文件记录实际迁入的开发技能、游戏运行时、字体，以及宿主构建依赖的来源与许可。第三方内容分别遵循随附许可；本文件不为新项目原创内容指定许可。

独立演示包通过 [resource_pack/credits/README.md](resource_pack/credits/README.md) 保留简短来源、预览范围及 DejaVu / ManimGL 完整许可副本；PyreactMC 完整许可继续随行为包框架提供。构建字体本体与宿主依赖环境不随游戏包分发。

## mcdk-assistant 技能

- 来源：[GitHub-Zero123/mcdk-assistant](https://github.com/GitHub-Zero123/mcdk-assistant)，来源工程记录基准 `172b3bc8289912e58a096349f568d1b921005d8c`。
- 范围：`.agents/skills/` 下 `ffi-cache`、`hash-key`、`mc-search`、`mod-workflow`、`next-opt`、`py-except`、`py-init`。
- 许可：[BSD 3-Clause 完整文本](docs/vendor/mcdk-assistant.LICENSE.txt)。
- 修改：统一 MCP 入口与新项目工作流适配，详见 [迁移记录](docs/MIGRATION.md)。

## PyreactMC 开发技能与调试脚本

- 来源：[EnderWolf006/PyreactMC](https://github.com/EnderWolf006/PyreactMC)，来源工程记录基准 `9580d0123584ae8b4b4b3a7b0357250e151c54cd`，含来源工程本地修正。
- 范围：`.agents/skills/pyreact-ui-building/` 与 `.agents/skills/pyreact-debugging/` 的上游内容与修改版本。
- 保留 [LICENSE](docs/vendor/PyreactMC.LICENSE.txt) 与 [NOTICE](docs/vendor/PyreactMC.NOTICE.txt) 原文。
- 这一项涵盖开发文档和调试工具；已经随游戏包集成的框架运行时另见下一项。

## 已随包提供的 PyreactMC 运行时与 UI 模板

- 来源：[EnderWolf006/PyreactMC](https://github.com/EnderWolf006/PyreactMC)，上游基准 `9580d0123584ae8b4b4b3a7b0357250e151c54cd`。实际导入同机 `better-building-editor` 中基于该版本的修改集成，包含已有本地修正，不是未经修改的官方发行版。
- 范围：`behavior_pack/manim_ui/pyreact/` 与 `resource_pack/ui/PyreactBase.json`。框架 Python 在本次导入时沿用原集成；UI 模板移除了旧应用的 `ModernProjection.*` 模板引用。
- 具体导入说明：[INTEGRATION.md](behavior_pack/manim_ui/pyreact/INTEGRATION.md)。继承的本地修改与上游基准保留在 [UPSTREAM.md](behavior_pack/manim_ui/pyreact/UPSTREAM.md)，其中旧应用功能说明仅是来源历史。
- 许可：**PyreactMC 自定义许可协议 v1.1**（2026-09-18），不是标准 Apache-2.0。完整 [LICENSE](behavior_pack/manim_ui/pyreact/LICENSE) 与 [NOTICE](behavior_pack/manim_ui/pyreact/NOTICE) 随运行时保留。
- 指定归属陈述：**本项目使用 PyreactMC 客户端 UI 框架**。NOTICE 要求将该文字写在相关网易开发者组件／服务器游戏的作品详情介绍中；保留本文件不能替代该项要求。相关开发者账户下全部付费组件获取量与全部网络游戏获取量之和达到或超过 1,000,000 次时，需要原作者另行书面授权。完整适用范围、文件保留与例外条件以随附 LICENSE 和 NOTICE 为准。

## 已随构建工具提供的 DejaVu Serif 字体

- 来源：[DejaVu Fonts](https://dejavu-fonts.github.io/)。本仓库字体为 Matplotlib 3.10.8 所附未修改的 `DejaVuSerif.ttf` 副本，不依赖用户安装 Times New Roman 等专有字体。
- 范围：[tools/reference/fonts/DejaVuSerif.ttf](tools/reference/fonts/DejaVuSerif.ttf)，379,740 字节；SHA-256 为 `107244956e9962b9e96faccdc551825e0ae0898ae13737133e1b921a2fd35ffa`。它供宿主 ManimPango 构建轮廓使用，游戏播放器消费生成的轮廓／纹理。
- 许可：保留完整 [LICENSE_DEJAVU](tools/reference/fonts/LICENSE_DEJAVU)，包括 Bitstream Vera 字体许可、DejaVu 变更的公有领域声明以及适用的 Arev 归属文本。字体文件未修改、未重命名；不将其误标为 MIT 或 SIL OFL。
- 字体和参考版本的结构化来源记录见 [upstream.json](tools/reference/upstream.json)。

## ManimGL 宿主参考与构建依赖

- 来源：[3b1b/manim](https://github.com/3b1b/manim)，官方 **ManimGL 1.7.2**，tag `v1.7.2` 对应 commit `f427fc67df75513be0cd3f3329e327a9a19401c3`。此处不是 Manim Community Edition。
- 使用范围：离线执行上游 `Text`、`Transform`、`Camera` 来构建轮廓和原生参考画面；源码和二进制安装在忽略的 `.venv-reference/`，不复制进游戏运行时，也没有整份 vendoring 上游源码。
- 许可：MIT，Copyright (c) 2020–2023 3Blue1Brown LLC；完整许可副本见 [LICENSE_MANIMGL.md](tools/reference/LICENSE_MANIMGL.md)。官方 wheel URL、精确 SHA-256 和源码 commit 见 [upstream.json](tools/reference/upstream.json)，实际执行的关键源码哈希记录在每次导出的 `reference_report.json`。
- 安装入口：[setup_reference.ps1](tools/reference/setup_reference.ps1) 和 [requirements.txt](tools/reference/requirements.txt)。宿主环境与下载缓存不进入 Git；下面这些依赖在本次参考运行中使用，各自 wheel 内保留完整许可及其依赖的归属，不因列在此处而改变许可。

| 宿主依赖 | 实跑版本 | 来源 | 主项目许可 |
| --- | --- | --- | --- |
| ManimPango | 0.7.1 | [ManimCommunity/ManimPango](https://github.com/ManimCommunity/ManimPango) | MIT |
| NumPy | 2.3.4 | [numpy/numpy](https://github.com/numpy/numpy) | BSD-3-Clause；wheel 内附第三方归属另依其文本 |
| Pillow | 12.0.0 | [python-pillow/Pillow](https://github.com/python-pillow/Pillow) | MIT-CMU；wheel 内附第三方归属另依其文本 |
| FontTools | 4.62.1 | [fonttools/fonttools](https://github.com/fonttools/fonttools) | MIT |
| SciPy | 1.17.1 | [scipy/scipy](https://github.com/scipy/scipy) | BSD-3-Clause；wheel 内附第三方归属另依其文本 |
| ModernGL | 5.13.0 | [moderngl/moderngl](https://github.com/moderngl/moderngl) | MIT |
| glcontext | 3.1.0 | [moderngl/glcontext](https://github.com/moderngl/glcontext) | MIT |
| setuptools | 80.9.0 | [pypa/setuptools](https://github.com/pypa/setuptools) | MIT |
| audioop-lts | 0.2.2 | [AbstractUmbra/audioop](https://github.com/AbstractUmbra/audioop) | PSF-2.0 |

这是主要固定构建依赖列表，不是整个 Python 环境的完整软件物料清单。ManimGL 的其他传递依赖仍由包管理器安装，保留各包随附许可；来源 URL 和 wheel 哈希可从 `.runtime/reference/install-report.json` 复核，实际关键版本从导出报告复核。若将来分发宿主环境或额外二进制，应随其附带各包完整许可与第三方归属，不能仅使用本表替代。

MCDevTool、网易开发客户端及共享 MCP 可执行文件仍是外部开发工具，没有随仓库复制或打包。
