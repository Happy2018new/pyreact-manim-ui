# 随预览包提供的来源与许可

此包为 `pyreact-manim-ui` 的 Windows 网易 ModSDK 初版演示，包含游戏播放器、生成的向量动画数据和 shader。以下来源与完整许可随资源包保留，便于独立分发时核对。

## 字体与生成的字形

文字样例使用未修改的 **DejaVu Serif**，来源为 [DejaVu Fonts](https://dejavu-fonts.github.io/)。构建所用 `DejaVuSerif.ttf` 的 SHA-256 为 `107244956e9962b9e96faccdc551825e0ae0898ae13737133e1b921a2fd35ffa`。

资源包包含从该字体生成的字形轮廓与数值纹理，不包含字体文件本身。完整字体许可及 Bitstream、DejaVu、Arev 归属文本见 [LICENSE_DEJAVU](LICENSE_DEJAVU)。字体许可与本项目原创代码的许可分别适用。

中文示例使用 **Noto Serif SC** 的 weight 400 子集，构建字体改名为 **Pyreact Manim Song**。来源为 google/fonts commit `8b0a1d0f5983c89bc2b93f1b5fb55f9e252744b5`；Copyright 2012 Google Inc.，完整 SIL OFL 1.1 见 [LICENSE_NOTO_SERIF_SC.txt](LICENSE_NOTO_SERIF_SC.txt)。游戏包不包含字体文件，也不包含本机系统宋体文件。

LaTeX 公式使用 AMSFonts 所提供的 **Computer Modern Type 1：CMMI10、CMR7、CMSY10**。Copyright (c) 1997, 2009 American Mathematical Society；许可和保留字体名见 [LICENSE_COMPUTER_MODERN.txt](LICENSE_COMPUTER_MODERN.txt)。游戏包只包含生成的几何，不含 MiKTeX、dvisvgm 或 PFB 字体。

## ManimGL 参考与离线构建

文字变换离线执行官方 [3b1b/manim](https://github.com/3b1b/manim) 的 **ManimGL 1.7.2**，commit `f427fc67df75513be0cd3f3329e327a9a19401c3`。其 `Text`、`Transform` 和 `Camera` 用于产生参考几何、动画数据及核验画面；玩家端不包含或执行桌面 ManimGL 运行时。

ManimGL 的 MIT 许可副本见 [LICENSE_MANIMGL.md](LICENSE_MANIMGL.md)。本项目不是 ManimGL 官方版本，也不提供任意 Manim 脚本兼容。

## PyreactMC

**本项目使用 PyreactMC 客户端 UI 框架。** 框架来源为 [EnderWolf006/PyreactMC](https://github.com/EnderWolf006/PyreactMC)，包含已有集成修改。完整自定义 LICENSE、NOTICE、UPSTREAM 与 INTEGRATION 说明保存在同包的 `behavior_pack/manim_ui/pyreact/`。

其自定义许可要求在相关网易开发者组件／服务器游戏的作品详情介绍中写明上述归属陈述；相关开发者账户下全部付费组件获取量与全部网络游戏获取量之和达到或超过 1,000,000 次时，需要原作者另行书面授权。完整条件以随附 LICENSE 和 NOTICE 为准。

## 预览范围

包内有 O → B、C → S、8 → 1、UI → UX 四组西文，中文 → 变换、数学 → 中文两组宋体中文，分式换位、上标转根号两组真实 LaTeX，以及二维基础图形和坐标轴曲线，共十例。**所有文字仍未通过严格 Manim 1:1 验收。** 默认文字与公式启用了原生曲线分隔标记的近似模式；已修正子像素与填充细边的合成顺序，仍保留曲线采样、浮点和时间插值误差。

当前画布使用全屏后处理，为播放控件预留空间；不等同于支持任意页面内独立裁剪、多实例的 UI 组件。二维基础图形使用本项目的多边形动画接口，未声称完整 Manim API、任意公式和字体、游戏内即时排版或 3D 兼容。
