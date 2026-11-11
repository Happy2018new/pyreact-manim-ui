# 实现架构

## 数据流与边界

```text
examples/text_transforms.py → 固定 ManimGL Text/Tex/Transform → 参考与文字 IR
examples/basic_2d.py        → 本项目 Scene/Shape/Animation → 二维 IR
                                      ↓
                     验证 → 数据纹理 + shader + manifest
                                      ↓
                  behavior_pack + resource_pack 部署
                                      ↓
                    Python 2 播放器 → MC 后处理画布
                                      ↓
                     实机采样与原生参考帧分别验收
```

“静态 Python 转 shader”指宿主执行已支持的场景定义并输出几何、时间数据与绘制程序，不是任意 Python 源码自动转成 GLSL。Python 文件 IO、任意第三方库和运行时副作用不会自动成为 GPU 能力。场景确定后，游戏只需更新时间和少量视口参数，无需 GPU → Python 读回。

以上是保留的静态链路。0.3.0 将播放状态抽到 `PlaybackController`，分别适配后处理与实体 UI 画布；增加固定容量的实时参数图元。任意新字形／公式的数据上传仍未交付。实测结论见 [运行时验收](RUNTIME_ACCEPTANCE.md)。

## 模块职责

| 路径 | 职责 |
| --- | --- |
| `examples/text_transforms.py` | 四组西文、两组宋体中文、两组真实 LaTeX；显式标注近似预览 |
| `examples/basic_2d.py` | 二维图形与坐标轴曲线的静态 Python 场景 |
| `src/pyreact_manim/reference/` | 固定 ManimGL 执行、轮廓导出、原生参考、来源及误差报告 |
| `src/pyreact_manim/{geometry,animation,scene}.py` | 二维对象、动画求值、顺序/并行时间轴与导出 |
| `src/pyreact_manim/compiler/` | IR 校验、量化纹理、shader、manifest 与离线预览 |
| `behavior_pack/manim_ui/` | Python 2 时间轴、后处理控制、Pyreact 播放面板与生命周期 |
| `tools/build_demo.py`、`tools/deploy_demo.py` | 统一构建；校验资源和路径后部署 |
| `tools/start_dev.py` | 60 FPS 配置与受管测试实例启动 |

宿主依赖不能导入游戏 Python。PyreactMC 已随行为包集成，具体基准和本地修改来源见 [第三方记录](../THIRD_PARTY_NOTICES.md)。

## 两种 IR

**Schema 1：固定拓扑闭合多边形。** 保存按时刻采样的路径、轮廓、颜色和描边。适用于首批轮廓稳定的文字及二维场景。GPU 在相邻帧之间插值，使用非零环绕填充；二次曲线转折线与时间采样都有误差，不能自动认定为原版连续曲线的逐像素还原。

**Schema 2：有向曲线扇形数据（directed curve fans）。** 保留固定曲线槽位、有效标记及有方向的曲线采样，用于轮廓分隔变化的文字路径；多个扇形按字形累积填充，避免把内部辅助边当作真实字形边。当前 8 → 1、UI → UX 需要显式开启 marker 近似，导出报告必须保留这项限制。该路径已实现并不意味着原生填充语义或像素一致性已验收。

两种格式都经过版本、时间顺序、路径顺序、拓扑、有限数值和资源预算校验。当前上限为每帧 32 路径、2048 顶点、每场景 256 帧；纹理边长上限 2048。超限明确失败，不能静默裁掉几何。静态数据编码为 RG16 UNORM 纹理，使用 Point 采样，manifest 记录坐标范围、误差界限和资源哈希。

0.2.0 的全部文字和公式示例使用 Schema 2。每个子像素先累积有符号透明度，再叠加原生字形细边、平均和恢复负透明度，修正旧版先平均再加边的差异。折线采样、纹理量化、时间插值与浮点 marker 时间窗仍有近似；按用户要求，本轮不继续追逐逐像素差异。

编译器 shader 生成版本2会在全部关键帧上独立识别不变几何／样式，使用单帧图集读取，并为完整曲线扇形生成含量化、边线和子像素余量的保守边界。两部影片的字幕编译器另生成整组字形边界，参数曲线采用保守分组剔除与时间不变量复用。图集和运行时接口兼容；设计依据、重建范围及帧率结论边界见 [性能说明](PERFORMANCE.md)。

## 字体与公式的构建边界

文字由宿主 ManimPango 使用指定字体排版。支持显式字体文件，以及按构建电脑已安装的字体名称解析字体；校验实际字体家族、字符覆盖并记录来源。默认中文演示使用从 Noto Serif SC 提取并改名的开源宋体小子集；系统 SimSun/宋体仅在本机验证，不把系统字体复制进仓库或游戏包。

目标机器播放的是已经生成的轮廓和 shader，因此不必重复安装构建字体。游戏运行时查询系统字体、临时输入新文字和即时生成字形，尚不是当前播放器的能力。字体存在也不自动代表涵盖输入字符或满足本场景资源预算。

公式使用真正的 `manimlib.Tex`，经过本机 LaTeX → DVI → dvisvgm → SVG → VMobject，再执行原生 `Transform`。MiKTeX 命令兼容仅限定在该构建调用中，不修改全局安装配置，也不自动安装缺失宏包。公式源码与实际生成 SVG 的哈希进入参考记录；播放器不携带 TeX 引擎。

## 二维场景与动画

`Scene.add` 在时间轴开始前声明对象；一次 `play` 中的不同对象并行动画，多次 `play` 顺序执行，`wait` 保持状态。同一次 `play` 写入同一对象会报错。动画在宿主求值，不会把用户 Python 函数传入游戏。

基础动画提供平移、旋转、缩放、淡入、淡出、多边形转换，另有线条逐段显现 `Create` 和路径运动 `MoveAlong`。`Create` 当前面向 Line/Plot/Polyline；轮廓拆分、合并不属于二维多边形 Transform 的支持范围。

多边形 Transform 将两端较少的顶点按等弧长提升，支持矩形与圆双向转换。导出时提升历史帧中不足的轮廓，保持整场景固定拓扑；已经密集的轮廓与 Create 数据不重复采样。这是多边形近似，不能代替文字原生参考导出。后续动画从前一动画的实际缓动终点继续，允许终值回到起点的缓动函数。

## 游戏播放器与画布

Python 2 播放器安装编译后的后处理，按渲染帧上传播放时间与画布参数；暂停或参数未变化时跳过重复上传。Pyreact 面板负责播放、进度、前后切例和页面清理。Esc 退出时暂停并关闭效果；回到 HUD 后 F8 释放事件重开，保留场景与暂停位置。事件使用公开 `OnKeyPressInGame`，页面 key 防止重复入栈。

首版计时针对 Windows：初始化通过公开 `GetPlatform()` 判断平台，Python 2 使用标准库 `time.clock()` 的 Windows QPC 实现；宿主 Python 3 使用 `perf_counter()`。不使用可被系统校时调整的 `time.time()`，也不把 Unix Python 2 的 CPU 时间误当播放时间。非 Windows Python 2 暂未支持。

保留的后处理载体为控件留出画布区域。用 `GetScreenSize()` 的逻辑高度计算顶部 55、底部 115 像素预留；极小屏按比例缩小预留与控件，画布至少占 35% 高度。`GetScreenViewInfo()` 提供物理屏幕尺寸，换算物理画布高度，保证宽高比和抗锯齿使用实际像素。

| 参数 | 内容 |
| --- | --- |
| `EXTRA_VECTOR1` | 时间、物理画布宽高比、物理画布像素高度、不透明度 |
| `EXTRA_VECTOR2` | Y 翻转、画布顶部比例、画布高度比例、保留项；高度不大于 0 表示整屏 |

0.3.0 另有 `CanvasRenderer` + `ManimCanvas`：使用原生实体 UI 绘制调用，顶点 shader 将 UV 映射到真实控件矩形，保留 UI 排序与矩形裁剪。每个场景两个独立 identifier，挂载租用槽位，第三个明确报错；卸载归还槽位。通过 `tools/build_canvas.py` 把既有两种 schema 的填充／描边转换为逐层透明合成，复用同一份数据纹理。

`runtime_shapes` 的同一 shader 通过 uniform 接收形变、描绘进度、描边、缩放、RGB 和旋转；时间轴控制轻微周期位移。它没有字体解析器或 TeX 引擎。`EXTRA_ACTOR_UNIFORM1` 是时间／宽高比／像素高／透明度，U2 是图元参数或静态播放选项，U3 是屏幕矩形，U4 是颜色／旋转。API 与已知限制见 [UI 画布 API](CANVAS_API.md)。

暂停时相同参数跳过上传；布局后下一渲染帧测量控件和逻辑／物理视口，避免尺寸事件早于物理窗口更新。不在每帧读取屏幕信息。`dispose` 停止时间轴、隐藏并清理订阅／实例槽位；原生注册资源是否释放不作承诺。

## 普通图片组件

`behavior_pack/manim_ui/images/` 提供独立的 `ImageController`、`ImageRenderer` 和 `ShaderImage` primitive。模型负责原子参数校验及波纹时钟，渲染器负责四个图片槽位、材质参数缓存和原生显隐，primitive 复用已有局部画布模板与布局测量。图片槽位与两个 ManimCanvas 槽位分别管理。`images/demo.py` 与 `images/panel.py` 提供主播放器“图片变形”入口的原图对照与交互参数。

`tools/build_shader_images.py` 将预置普通 PNG 打包成一个有间隔的 RGBA 图集，生成对应图片元数据和四个实体 identifier；所有图片共用小型 shader。U3 保存屏幕矩形，U1 保存波纹时间／画布比例／透明度／效果类型，U2 保存带镜像符号的显示宽高／旋转／效果强度，U4 保存最终裁剪后的图集矩形。采样颜色先预乘 alpha，再做手动双线性插值，材质使用预乘混合。详情、重建方式及限制见 [ShaderImage](SHADER_IMAGE.md)。

## 可复建与证据

字体、上游版本及许可见 [第三方记录](../THIRD_PARTY_NOTICES.md) 与 `tools/reference/upstream.json`。构建输出记录实际源码/字体哈希、采样配置、资源哈希和近似开关；`.runtime/` 保存参考、编译产物、截图与完整日志，小型验收摘要进入 `docs/evidence/`。CPU 结果、桌面参考与 MC 实机证据不能相互替代。
