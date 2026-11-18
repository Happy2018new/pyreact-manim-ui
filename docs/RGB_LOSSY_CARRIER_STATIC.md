# 不写文件的 RGB 有损载体：静态推导

后续已完成受控原生全码域及 512 KiB 隔离静态验证，见[实机研究与兼容限制](SCENE_CODEC_512K_RESEARCH.md)。本页是早期推导，不能代替雨天与原生后处理的实际验证。

同日后续已执行原生实验：3 KiB／64 KiB 的 k=1／2 载荷和 alpha 恢复通过，k=2／64 KiB 的首次 RGB 失败及后续稳定样本分别保留。实际场景分布、容量和静态性能统一见[大容量与组合压缩研究](LARGE_ALPHA_AND_SCENE_CODEC_RESEARCH.md)。下文“未实测”描述的是静态推导阶段，不能替代后续结果；后续实验也尚未证明原生全部效果兼容。

2026-11-18。用户明确网易模组运行时不允许写文件，动态 PNG 路线排除；允许研究可控 RGB 有损压缩，并与“alpha 大量重复”的条件结合。完全不借用场景 RGBA 的私有通路仍优先。本文只做源码／文档分析与 CPU 整数穷举，未启动或操作 MC，未运行 GPU，没有新帧率测量。

## 结论

RGB 允许丢失部分精度后，新增了一条比“事后压缩已经被覆盖的 alpha”更具体的候选：**让几何 writer 的固定功能颜色混合同时压缩原 destination RGB 并注入 payload。** 在理想线性 UNORM8 下，单次混合可把颜色映射到小区间、数据存到高位；三次特定混合则可把每通道 1 bit 数据直接放进原 RGB 的最低位，全程保留 destination alpha，不需要先读取或备份原 RGB。

数学模型可验证，不等于引擎实现已经成立。目标格式、色彩空间、逐 draw 量化、覆盖和排序仍是硬门槛；三次混合在当前 block geometry carrier 上没有已证严格顺序契约。原生后处理还可能直接读取未处理的 TEXTURE_1，单次高位载荷不能仅靠最前面的恢复 pass 保证兼容。

## 两个用户假设分别如何使用

- **alpha 大量相同：** 可减少保存原 alpha 的空间，但分布和精度未测。任意 alpha 没有必然无损压缩空间。此前覆盖前捕获与写入工作 RT 的限制仍适用。
- **RGB 可有损：** 可以用固定精度量化获得确定容量，不必依赖画面是否容易压缩。容量可以按载荷大小计算；能接受多大视觉误差仍需实际图像和后处理验证。

第一个后处理的输入是场景渲染结果，并不保证就是显示器最终收到的 8 位 RGB。它可能继续经过 bloom、色彩调整、曝光或色调映射。中间目标是否 UNORM8、是否 sRGB、是否 HDR／浮点均未确认；“场景通道误差 1/255”不能直接换算为最终显示误差 1/255。

## 候选 A：一次标准混合，载荷放高位

设原通道整数 x∈[0,255]，每个 RGB 通道要传 k bit，1≤k≤7，b∈[0,2^k−1]，n=2^(8−k)。下表与本次脚本仅验证 k=1..4。在同一线性 UNORM8 码域中设：

```text
source alpha = (256−n)/255
source RGB   = n*b/(256−n)
blendSrc     = SourceAlpha
blendDst     = OneMinusSrcAlpha
state        = DisableAlphaWrite
```

由标准 blend 公式，输出 byte 为：

```text
y = round((n−1)*x/255) + n*b
```

取 `b=floor(y/n)` 得到载荷，取 `q=y mod n`，原颜色近似恢复为 `round(q*255/(n−1))`。码区间互不重叠，且 source RGB／alpha 均在 [0,1] 内。DisableAlphaWrite 只禁止目标 alpha 写入，不妨碍 RGB 混合使用 source alpha。

以 k=1 为例，source RGB 是一个 0 或 1 的数据 bit，source alpha 为 128/255，输出是 `round(127*x/255)+128*b`。原颜色映射到 0..127，数据决定其处于下半或上半区间。直接用 0.5 的混合会在 byte 128 产生不同 b 的碰撞，不能直接替代这个系数。

| 每 RGB 通道载荷 | 理想恢复后的原通道最大误差 | 全 720×1080 单像素槽的理论容量 | 64 KiB 所需单像素记录 |
| --- | ---: | ---: | ---: |
| 1 bit | 1／255 | 291,600 B／284.77 KiB | 174,763 |
| 2 bit | 2／255 | 583,200 B／569.53 KiB | 87,382 |
| 3 bit | 4／255 | 874,800 B／854.30 KiB | 58,255 |
| 4 bit | 8／255 | 1,166,400 B／1,139.06 KiB | 43,691 |

表中无头部、边距、坏点或覆盖冗余，假设整个画面都可用于 1px 槽。2×2 像素复制一个数据符号时，容量约降为四分之一。3/4 bit 超过现有 compact8 每记录单 byte 的能力，不能称为直接复用当前编码器。

**兼容性问题：** 原生 `daul_blur_up_sample.fragment` legacy 分支和 `depth_sample.fragment` 会直接读 TEXTURE_1.rgb。首个自定义 post 恢复自己的输出，只会修复后继 TEXTURE_0；原 TEXTURE_1 仍可能是高位乱色。需要核对每个原始颜色引用与恢复点，不能仅靠插在 render_order 第 0 位宣称视觉兼容。

## 候选 B：三次混合，数据仅替换最低位

k=1 可在理想线性 UNORM8 中构造更有利于保留原画面的版本。对每个原 RGB byte x 和数据 bit b∈{0,1}，按顺序绘制三次，全部 DisableAlphaWrite：

| 阶段 | source RGB／alpha | RGB blend 因子 | 阶段输出 byte |
| --- | --- | --- | --- |
| 1. 降低精度 | RGB=0，A=128/255 | SourceAlpha／OneMinusSrcAlpha | q=round(127*x/255)=floor(x/2) |
| 2. 乘二 | RGB=1 | DestColor／SourceColor | 2q |
| 3. 加数据 bit | RGB=b/255 | One／One | y=2q+b |

所以最终 `y mod 2=b`，且 `|y−x|≤1`。这里连尚未解码的场景颜色也只改变一个最低位，TEXTURE_1 的后续引用不再看到高位载荷。每个 RGB 像素可传 3 bit，理论容量同上表 k=1。

这仍不是最终画面误差保证：bloom 中的 step 阈值可能被 1 个色阶推过，从而产生大于 1 色阶、覆盖更大区域的差异。后续世界绘制或后处理也可能改变数据最低位；必须先从未污染源提取数据至私有 RT，之后供 consumer 完整索引。

**三次绘制尚缺当前 carrier 的顺序依据。** 已知骨骼模型的 SetModelMultiPassMaterial／多材质配置承诺按数组顺序渲染，但现 carrier 是 CombineBlockPaletteToGeometry + AddActorBlockGeometry，不是该骨骼模型。不能给 anchor 设置多材质就假设附属 geometry 也执行三遍；现有 AddActorBlockGeometry 和 RenderBlockGeometryModel 参数没有对应 pass 列表。三个不同附件的提交顺序也不能当成 GPU 排序保证。严格顺序与同一覆盖必须另外证明。

## 自动选择损失与容量

固定精度方案可直接按 resident 载荷 L、头部 H、可用独立像素槽 P 计算。H 以 bit 计：

```text
所需 bits        = 8L + H
统一每通道 k_min = ceil((8L+H)/(3P))
使用槽数        = ceil((8L+H)/(3k))
```

若 k_min 超过质量上限，不能悄悄继续劣化：应拒绝该容量、减少 resident 数据，或使用别的私有路径。也可以只占用需要数量的槽，其余位置保持原样。最后一槽最多浪费 3k−1 bit；“恰好装下”无需复杂图像压缩搜索。

更复杂的空间／色度有损压缩可利用画面冗余，但码长与质量不再只依赖一个简单公式，还会引入 block 分析、变长定位和更多读取／pass；目前优先固定精度模型。k 随容量变化时应避免每帧抖动，不把上传预算误当 resident 大小。

**64 KiB resident + 每帧 3 KiB 更新，容量仍按 64 KiB 计算。** 限速影响调色板／几何更新工作，不能降低每帧需要保留的完整数组空间。全部活跃 geometry 仍需绘制，未更新页不等于没有渲染成本。

## 接现有内存入口与数组语义

现 geometry 入口在游戏内从 bytearray 构建 palette dict，经 DeserializeBlockPalette → CombineBlockPaletteToGeometry → AddActorBlockGeometry，载荷传入不依赖游戏写文件。开发构建预置模型和 shader 仍由宿主完成。

以候选 A 的 k=2 为例，将每 6 个 payload bit 合成 `Q=bR+4*bG+16*bB`，Q∈[0,63]，可由 compact8 编码；fragment 再拆为 RGB 三个 2-bit 值。64 KiB 为 87,382 个记录，相比旧单 byte／quad 的 65,536 个记录更多。若整块套旧 stride 倍增，palette 声明 volume 还会由 256²×16 跳到 512²×16，不能只按 quad 数估成本。

可按 3,072 个逻辑 byte 分页：每页恰有 4,096 个 6-bit 记录，保持 stride64／height16 的小块。k=1 则每 quad 只传 3 bit，3,072 B 需要 8,192 个记录；64 KiB 总计 174,763 个记录。三 draw 版还需额外两阶段绘制；若共用同一载荷几何，则这些记录要画三遍。前两阶段只是统一颜色运算，若排序与覆盖能力允许，也可考虑用少量矩形覆盖连续区域。两种实现都未验证，不承诺保持旧帧率。

提取 pass 可将三通道符号重组成私有数据纹理，再提供 byteAt(index) 和依赖查询。按固定 bit 地址跨符号取数；每符号携带 3 bit 时，一个 byte 最多涉及 4 个符号，不按画面颜色猜数据。逻辑 byte 数、几何记录数、屏幕像素数、palette volume 和每帧实际重建量须分开记录。小页的发布版本、跨页查询与背压仍需设计；当前 scheduler 的整表重建不能冒充 dirty 更新。

## 硬门槛与下一验证

1. **确认码域与格式。** 实际目标是否逐 draw UNORM8 量化，是否存在 sRGB 转换、HDR、dither、MSAA resolve。旧 alpha 成功不证明 RGB 满足这些条件。
2. **确认混合与覆盖。** 同像素同阶段恰好写一次，无后续世界 draw 污染，source shader 不被额外 fog／lighting／premultiply 改值；最低位版还需严格三阶段顺序。抗锯齿边缘不能混合不同符号。
3. **只做很小原生数值 PoC 后再谈大容量。** 对背景 0..255 与不同 payload 组合验证数据和颜色误差；故意重叠、改变绘制顺序／AA 作为负对照。先确认单次混合模型，三阶段单独验证。本文没有执行这些实验。
4. **提取与兼容。** 全量及依赖索引必须与输入独立对照；原 alpha 保留、透明物／粒子、bloom／DOF 原始颜色引用、窗口变化分别验证。数值误差上界不是肉眼无差异或最终屏幕误差上界。

私有 U5–U16 研究保持优先。运行时 PNG 不再安排实验；不通过写其他目录、RawPath 或缓存文件规避用户明确的无文件约束。

## 静态验证与来源

`tools/geometry_atlas_probe/verify_rgb_blend_math.py` 只用整数 CPU 运算穷举。单次混合 k=1..4 共 7,680 对原值／payload，最低位三 draw 版 512 对；另用 50/50 混合作碰撞负对照。它不导入 SDK、不访问 MC、不证明硬件混合精度。结果见 [static-arithmetic.json](evidence/rgb-blend/static-arithmetic.json)。

- 官方 `NeteaseGuide/mcguide/16-美术/7-材质与着色器/3-材质配置说明.md`，Blend 小节：公式、SourceAlpha／OneMinusSrcAlpha／DestColor／SourceColor／One 与 DisableAlphaWrite；多材质骨骼模型按顺序渲染。
- 本机 `data/resource_packs/vanilla/materials/entity.material` 625–631：beacon_beam_transparent 同时使用标准 RGB 混合和 DisableAlphaWrite。
- 本机 `data/shaders/glsl/daul_blur_up_sample.fragment` 56、62，`depth_sample.fragment` 96：原始 TEXTURE_1 RGB 引用；`threshold.fragment` 18–27：bloom 阈值。
- 本项目 `tools/geometry_atlas_probe/build_probe.py`、`runtime.py`、`scatter.vertex`、`scatter.fragment`，及 `tools/geometry_packet_probe/codec.py`：现有内存入口、材质、compact8。
- 本地可读 wrapper `NeteaseVanillaMCP/mod/client/component/modelCompClient.py` 1474–1500：SetModelMultiPassMaterial；`actorRenderCompClient.py` 1385–1409：AddActorBlockGeometry。它们不替代原生实现和实际排序验证。
