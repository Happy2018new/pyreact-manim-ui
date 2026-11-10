# 原生 LaTeX 公式变换

`--input-kind latex` 实际创建固定 **ManimGL 1.7.2 的 `Tex`**。执行链为
LaTeX → DVI → dvisvgm SVG → 上游 SVG 字形 → `Transform.begin/interpolate`。
分数线、上下标、根号及数学间距来自 TeX，未用普通 `Text` 或字体字符伪造公式。
导出的曲线继续走现有 schema 2 编译器和游戏播放器。

## 环境和命令

宿主需已安装 `latex` 和 `dvisvgm`，并将其放在 PATH。工具不会下载或安装 TeX
发行版，也不会自动安装缺失的宏包。当前固定使用上游 `basic` 模板，依赖
`standalone`、`preview`、`babel`、`amsmath`、`amssymb`、`xcolor`。
缺工具或宏包时返回明确错误；LaTeX 每次子进程限时 90 秒，Windows 不弹控制台。
游戏运行不需要 TeX、dvisvgm 或宿主 Python。

本机实际使用 MiKTeX-pdfTeX 4.27（MiKTeX 26.5）及 dvisvgm 3.6。
每份导出报告记录工具版本、可执行文件 SHA-256、模板和命令兼容调整。

```powershell
& '.venv-reference/Scripts/python.exe' -B -X utf8 tools/reference/export_text_transform.py `
  --input-kind latex --source '\frac{a}{b}' --target '\frac{b}{a}' `
  --name manimgl_fraction_swap --glyph-height 3 --geometry curve_slots `
  --allow-marker-approximation --output .runtime/reference/latex_fraction_swap --render-reference

& '.venv-reference/Scripts/python.exe' -B -X utf8 tools/reference/export_text_transform.py `
  --input-kind latex --source 'x^2' --target '\sqrt{x}' `
  --name manimgl_power_to_root --glyph-height 3 --geometry curve_slots `
  --allow-marker-approximation --output .runtime/reference/latex_power_to_root --render-reference
```

PowerShell 单引号中的反斜杠保持原样；Python 调用时可使用 `r'\frac{a}{b}'`。
`ExportSettings(input_kind='latex', tex_template='basic', ...)` 与 CLI 等价。
此分支不使用 `font`/`font_file`，数学字体由 TeX 模板决定；中文文本使用
`Text` 加所选中文字体。当前未宣称支持中文 TeX、任意宏包或任意 Manim 脚本。

## Windows 兼容调整

ManimGL 1.7.2 的上游命令给 `latex` 传入 `-no-pdf`，但 MiKTeX 的 `latex`
不接受该参数；它本来就输出 DVI。适配器仅对 MiKTeX 移除这个参数，并添加
`-disable-installer`、`-disable-write18`。TeX Live 保留 `-no-pdf`，显式关闭
shell escape。临时输入以文件名传入，并把子进程工作目录设为临时目录，避免
Windows `HAPPY2~1` 这样的 8.3 路径被 TeX 把 `~` 解释为命令。

作用域仅替换 `manimlib.utils.tex_file_writing` 的 subprocess 引用，并在成功或
失败后恢复。没有修改安装的 ManimGL 文件，也没有全局替换 `subprocess.run`。
`Tex`、字形对齐、`Transform` 和原生 `Camera` 均维持上游实现；这些命令调整
仍作为兼容差异明确记录，不把运行环境描述成完全未经调整。

## 输出与本次验证

除场景、原始控制点和报告外，每份公式还保留 `source.tex`、`target.tex`、
`source.svg`、`target.svg` 及 SHA-256。TeX 文件保存上游实际使用的 labelled
内容；SVG 是该 `Tex` 实际加载的转换结果。

2026-11-10 已完成以下离线验证，均采用 61 帧、0.003 场景单位弦误差容差，
并实际输出 1280×720 原生 Camera 的五张参考图：

| 示例 | 对齐后的路径数 | 采样顶点总数 | 状态 |
| --- | ---: | ---: | --- |
| `\frac{a}{b}` → `\frac{b}{a}` | 3 | 337 | 满足当前 2048 顶点预算 |
| `x^2` → `\sqrt{x}` | 3 | 649 | 满足当前 2048 顶点预算 |
| `x^2+y^2=z^2` → `z=\sqrt{x^2+y^2}` | 9 | 1767 | 可导出且满足 2048 预算；本轮未纳入默认实机验收 |

单元/集成测试另用独立原生 `Tex` 和 `Transform` 执行，逐帧核对控制点及法线，
同时检查编译器预算、真实公式来源和作用域适配器恢复。所有导出保留原生
`get_unit_normal`，schema 2 写入其二维符号 `fill_orientation`。

这些样例已证明实际 LaTeX 排版和原生几何转换可用。`allow_marker_approximation`
仍表示允许采样帧之间极窄的浮点 skip 差异；曲线采样、时间采样和跨引擎光栅化
也不等于逐像素 1:1。实机验收由主项目统一执行并单独记录。

## 数学字体来源

本机 `dvitype` 对实际 DVI 的核验结果：分数用 CMMI10；`x^2` 用 CMMI10、CMR7；
`\sqrt{x}` 用 CMMI10、CMSY10。字体是 MiKTeX 所带 `amsfonts/cm` 的
Computer Modern Type 1。对应 PFB 头声明：Copyright (c) 1997, 2009
American Mathematical Society，SIL Open Font License 1.1；保留字体名分别
为 CMMI10、CMR7、CMSY10。游戏只打包已编译的几何，仓库不复制这些 PFB。

本次实际文件的 SHA-256（位于 MiKTeX `fonts/type1/public/amsfonts/cm/`）：

| 文件 | SHA-256 |
| --- | --- |
| `cmmi10.pfb` | `e3661061e8aa474d6de5ffa916edceb0e3d8b998862018c147f0357fce00bcd7` |
| `cmr7.pfb` | `b37e8671820b0753c6e233eaa3230c6ab9cff04e6c4baee312d60ae261e5aba1` |
| `cmsy10.pfb` | `62ee8cef552017551cd3e026a483e700730103eceaad959c87b7730017f59cff` |

其他系统安装或模板可产生不同字体，因此不能把以上样例的清单当作任意公式的
字体清单。分发声明与许可全文由项目第三方声明统一收录。
