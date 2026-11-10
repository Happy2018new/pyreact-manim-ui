# 中文、宋体与已安装字体

中文演示默认使用 **Pyreact Manim Song**。它是从官方 Noto Serif SC 生成的宋体风格静态 400 字重子集，文件为 `fonts/PyreactManimSong-Regular.ttf`，大小 **35,068 字节**。这是可再分发的开源字体子集；Windows 自带的 **宋体 / SimSun** 则通过本机字体调用，不复制进仓库。

字体只在宿主 Python 离线构建时使用。进入游戏的是已经生成的几何与动画数据，玩家电脑无需安装对应字体，也不在 Minecraft Python 中运行 Pango、fontTools 或 LaTeX。

## 直接使用安装在电脑上的字体

在仓库根目录运行：

```powershell
.\.venv-reference\Scripts\python.exe -B -X utf8 tools/reference/export_text_transform.py --output .runtime/reference/my_song --source "中文" --target "变换" --name my_song --font "宋体" --geometry curve_slots --glyph-height 3 --allow-marker-approximation --render-reference
```

`--font "SimSun"` 与 `--font "宋体"` 指向同一系统字体。省略 `--font-file` 时，宿主会从 Windows 当前用户和系统字体目录、字体注册表中寻找真实匹配的家族名，并优先选择常规字重。英文和本地化家族名均匹配字体自身的 `name` 表，不根据文件名猜测。当前字体名自动查询支持 Windows；其他平台传入明确的字体文件。

也可以明确指定字体文件：

```powershell
.\.venv-reference\Scripts\python.exe -B -X utf8 tools/reference/export_text_transform.py --output .runtime/reference/my_font --source "中文" --target "变换" --name my_font --font "SimSun" --font-file C:/Windows/Fonts/simsun.ttc --geometry curve_slots --glyph-height 3 --allow-marker-approximation
```

支持 TTF、OTF 和 TTC/OTC 字体集合。集合通过家族名选择对应 face；例如本机 `simsun.ttc` 的 `SimSun / 宋体` 是 face 0，`NSimSun` 是另一 face。集合包含多个 face 时不能省略家族名。报告记录真实文件 SHA-256、face 索引、请求名称、实际绘制家族以及已验证的 Unicode 码点。

Pango 对部分中文别名的支持与 Windows 不同。直接把 `宋体` 交给它可能回退成无衬线字；导出器现在先从选定 face 读取规范英文家族名 `SimSun`，确认 Pango 能识别该家族，再进行实际绘制。本地化名称只作为明确的字体选择入口。实际回归已确认 `宋体` 和 `SimSun` 的 5 帧原生控制点完全相同，并且与误回退后的 Sans 几何不同。

## 使用仓库默认宋体子集

```python
from pathlib import Path
from pyreact_manim.reference import ExportSettings, export_text_transform

settings = ExportSettings(
    source="中文", target="变换", name="chinese_change",
    font="Pyreact Manim Song",
    font_file=Path("tools/reference/fonts/PyreactManimSong-Regular.ttf"),
    glyph_height=3.0, geometry_mode="curve_slots",
    allow_marker_approximation=True, render_reference=True,
)
export_text_transform(".runtime/reference/chinese_change", settings)
```

默认子集包含演示用简体、少量繁体及 ASCII，并不是完整中文字体。导出前检查所选 face 的 Unicode cmap；缺字会明确列出码点并停止，不使用方框或其他字体替代。

增加字符或者重建默认子集：

```powershell
.\.venv-reference\Scripts\python.exe -B -X utf8 tools/reference/setup_cjk.py
.\.venv-reference\Scripts\python.exe -B -X utf8 tools/reference/setup_cjk.py --text "山川星海"
.\.venv-reference\Scripts\python.exe -B -X utf8 tools/reference/setup_cjk.py --text-file examples/my_chinese.txt
```

要求 `fontTools==4.62.1`。工具校验固定源文件及许可，先取子集再实例化 400 字重，重命名字体家族与 PostScript 名称，固定源时间戳。`--text` 和 `--text-file` 都保留原来的演示字符与 ASCII；`--output` 可指定其他输出位置；`--offline` 只使用已有校验通过的缓存。默认输出的重复构建 SHA-256 相同。

`--style sans` 可按需生成 Noto Sans SC 派生子集，仓库不同时附带第二套字体。完整字体仅缓存在 `.runtime/cjk-font-source/`，不会放进 Git 或玩家包。也可直接指定本机完整字体，并使用它自己的家族名。

## 来源和许可

- 宋体来源：Google Fonts 官方 `notoserifsc`，固定 commit `8b0a1d0f5983c89bc2b93f1b5fb55f9e252744b5`。
- 完整源字体：`NotoSerifSC[wght].ttf`，25,125,512 字节；SHA-256 `050080d9255a86808f2945bffac582b31ef32bc36411ce29563b4961670c66f9`。
- 默认子集 SHA-256：`230390ac718f0bddccce9666a1aeb71611cb86bdd77851f9af0d4b8287de6585`。
- 许可为 **SIL Open Font License 1.1**，完整原文见 [LICENSE_NOTO_SERIF_SC.txt](fonts/LICENSE_NOTO_SERIF_SC.txt)。字体保留版权与许可条目，派生版本使用独立名称。
- 全部覆盖字符、源地址、工具版本及哈希见 [PyreactManimSong-Regular.source.json](fonts/PyreactManimSong-Regular.source.json)。

Windows 自带字体及用户自行安装字体的许可由各自权利人规定；本仓库不再分发这些字体文件。

## 当前验证范围

真实 ManimGL 1.7.2 文字构造与变换已通过：默认宋体 `中文 → 变换`（1,544 个采样顶点）和 `数学 → 中文`（1,704 个采样顶点）。系统 SimSun 的 `中文 → 变换` 已完成实际原生参考导出（1,071 个采样顶点）。缺字、错误家族、TTC face 选择、中文别名和已安装字体查找均有检查。

字体覆盖通过不代表任意长文本均可编译，也不代表严格逐像素相等。中文笔画数量会受到当前场景顶点预算限制；部分变换会触发原生填充法线不受支持的检查，例如该宋体的 `数学 → 动画`。这些情况仍会明确拒绝。示例使用显式的 `allow_marker_approximation` 预览模式，窄小原生浮点标记窗口的全时间轴一致性尚未关闭。
