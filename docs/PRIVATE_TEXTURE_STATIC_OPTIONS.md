# 私有批量纹理入口与场景 alpha 压缩：静态研究

同日后续用户授权了场景路线实机研究，结果见[大容量 alpha 与组合压缩](LARGE_ALPHA_AND_SCENE_CODEC_RESEARCH.md)：直接 alpha 的 1／1.5／2 MiB 完整读回通过；组合 RGB 输入／alpha 压缩已完成 64 KiB 真实 geometry 验证，保留首次 RGB 异常与兼容边界。下文“未实测”属于此前静态阶段，私有批量入口仍未因此解决，动态 PNG 仍排除。

2026-11-18。本文只做资料、已留存证据与源码分析；本轮没有启动或操作 Minecraft，没有运行 GPU 实验，没有取得新的帧率或 alpha 分布样本。

## 当前结论与优先级

用户最新要求是两条路线并行，**完全不借用场景 RGBA 的私有纹理路线优先**，希望效率接近已有几何 carrier。允许场景 alpha 暂存数据的条件是最终视觉不变，并验证透明物与特效兼容；场景压缩只作为辅助或兜底，不取代私有路线。

**同日后续修正：用户明确网易模组运行时不允许写文件，动态 PNG 路线排除，不再安排 A/B 写入实验。用户另允许研究 RGB 的可控有损压缩；新增[无文件 RGB 混合载体研究](RGB_LOSSY_CARRIER_STATIC.md)，包含同时压缩原 RGB 与注入数据的混合公式、最低位版本及未解决的格式／排序条件。下文 Image 小节保留为历史研究，不能视为现行计划。**

目前没有找到已经证明具备几何路线效率的私有批量入口。现有[私有纹理树](TREE_ATLAS_RESEARCH.md)在 64 KiB 静态驻留时仍约 15.82 FPS，而此前 geometry→场景 alpha 路线的固定 64 KiB 静态样例约 60.05 FPS。两者是各自已有的短时实测，不是本轮重新比较，也不代表 alpha 路线已经通过完整视觉兼容。

| 路线 | 本轮可确定的内容 | 尚未解决的关键条件 | 安排 |
| --- | --- | --- | --- |
| 后处理 U5–U16 → 私有数据 RT | 原生 shader 头声明 U1–U16；可读 Python wrapper 没有总量截断 | 原生 post 参数打包器是否实际上传高编号 bank，是否按 process 独立 | 最先安排极小绑定实验，成功后再评估树 |
| 动态 PNG → 同一 UI Image 的 TEXTURE_0 → 最终 UI | 保留历史资料与首次覆盖读取证据 | 依赖游戏运行时写文件，不满足用户明确约束 | 已排除，不再测试运行时文件刷新 |
| 已证 U1–U3 的节点融合 | 可减少部分 merge pass | 仍有约 1,821 个数据 context；不能保证 64 KiB／60 FPS | 保留为有限优化，不继续扩大相同树 |
| 压缩原场景 alpha 后利用空位 | 有条件无损编码可构造，固定 block 可避免全局 prefix | 真实精度与分布、覆盖前干净源、批量写入目标、恢复时机 | 静态设计并行；未补齐入口前不扩建实现 |
| 几何 RGB 有损混合载体 | 理想 UNORM8 下可同时压缩 destination RGB 并注入 payload；可保留原 alpha | 真实码域／格式、绘制覆盖及次序；最低位版需三阶段 | 新增有条件兜底，见独立研究 |

上述候选都不依赖未经证明的 GPU→Python 回读。公共文档未找到某入口，不等于引擎内部不存在该能力。

## 一、优先私有路线：扩大已上传参数 bank

官方材质教程明确描述：`paras` 支持 float／vec2／vec3／vec4，顺序打包至 `EXTRA_VECTOR1..4`。当前树使用 U1–U3 的 12 个 float，每个 float 放一个 uint24，共 36 B；U4 保留给引擎 ScreenInfo。`SetParameter` 按 process 与参数名设置，没有 pass 下标；多 pass 本身不会提供多份独立参数。

本机原生 `uniformExtraVectorConstants.h` 第 10–25 行声明 U1–U16。`pbr_material_fabric_vip.fragment` 第 101–121 行有 U10–U16 的别名映射，第 750–771 行有实际消费 U11–U16 的源码分支，但对应模型材质启用了命名 uniform reflection；这些都**不能证明自定义 post 收到 U5–U16**。可读 `minecraft/postprocess.py` 第 15–20 行把 tuple 及长度交给原生模块，没有 Python 层总量截断；上传和打包实现在未审阅的原生层。

资料中的 `GetParameter` 返回列表不超过 4，限制的是单个参数向量的长度，不能据此断言所有参数合计只有 4 个标量。反过来，接口标为 `any`、getter 返回成功，也不能证明 GPU 接收了全部 bank。六份已安装原版后处理配置均没有超过四组 vec4 的输入实例。

若 U1–U3 与 U5–U16 均可按 process 独立上传，则可用 15 个 vec4、60 个 float，以已有 uint24 协议提供 **180 B/context**：

| 假设实现 | 64 KiB 数据 context | merge | 加 save／consumer 后 |
| --- | ---: | ---: | ---: |
| 现有 36 B 叶、五叉树，已实现 | 1,821 叶 | 457 | 2,280 pass |
| 180 B 叶，五叉树，绑定待验证 | 365 叶 | 73+15+3+1=92 | 459 pass |
| 所有节点均含 180 B，路由烘焙，重新构造至多五叉树 | 总计 365 个数据节点 | 已含于前列 | 理论 367 pass |

367 是可构造拓扑的理论计数，不是当前逐层 `ceil(n/5)` builder 的现成输出。即使绑定成立，仍有数百个 pass，不能将数量减少比例直接换算为 FPS，更不能承诺接近几何路线。

**下一实验仅验证绑定，不先建大树：** 使用互不相同的 U1–U16 sentinel，按教程顺序保留 U4 对应位置，让 shader 将实际读取值输出为诊断；重复更新 U5、U10、U16，使用两个 process 检查隔离与别名污染，检查 U4 是否仍由引擎覆盖。必须使用原生渲染值判定，getter 或接口 bool 不算通过。高 bank 不可用就停止这条分支，不能把模型路径视为替代证据。

仅在已证三组载荷 uniform 内优化时，可以把自己的数据也放入 merge，烘焙路由元数据。全部节点均含 36 B 时，65,536 B 至少需要 `ceil(65536/36)=1,821` 个数据 context；加 save／consumer 为理论 1,823 pass，相比 2,280 约少 20%。数值编码再节省少量位数，不能消除这一级别的逐帧节点数。

## 二、历史候选：Image 直接消费自己的数据纹理（已排除）

本节记录写文件约束明确前的方案，不再执行以下实验步骤。RawPath 或写其他目录同样不满足当前要求。

候选数据流：

```text
游戏 Python 生成 bytes → 覆盖预置 PNG A/B → Image 切换 texture binding
                                                ↓
                         该 Image 的 shader 读取自身 TEXTURE_0
                                                ↓
                                   array[index] → 最终 Manim UI
```

在该候选中，数据保存在输入 PNG 中，shader 输出最终 UI 颜色，无需将数据写进场景 RGBA，也无需先证明 UI 与 post／actor 共享纹理对象。若完整纹理寻址、字节精确采样及动态刷新验证通过，可在消费该 PNG 的**当前 UI shader 内提供完整数组索引**；不能推广为任意后处理、多个 Image 或模型都能读取同一数组。

原版 `ui.material` 的 `ui_texture_and_color` 使用 `color_texture.fragment`，`ui_textured_and_glcolor` 使用 `texture_ccolor.fragment`；两者都采样 TEXTURE_0。官方资料允许同名材质字段覆盖。但本轮没有找到 per-Image 自定义 shader／material 的公共字段：目前候选依赖既有 UI 材质的全局覆盖，必须先在隔离包确认命中的 variant，并证明受控数据 Image 的识别方式及普通 UI 的行为保持。它不是已经实现的隔离材质 API。

旧探针已同时测试普通 Image、RawPath 与 `force_texture_reload=true`，不可把“加上 force reload”当作新方案。文档仅描述该开关用于在**更改图片路径时**重新加载图像，没有承诺同路径缓存失效或已加载 A/B 内容刷新；旧探针通过固定控件 `SetSprite`，未留下“预置 A/B 已被加载后，游戏覆盖未显示的路径，binding 往返切换，并在同一 Image 自身 shader 里核对新代”的完整记录。原版 UI 的 `#texture`／`#texture_file_system`／`#zip_folder` 动态 binding 提供了下一对照的依据，仍不保证跨缓存刷新。

最小验证按顺序执行，失败不扩大容量：

1. 静态 PNG 在 Image 自身 shader 中完成 identity 与 dependent lookup；检查是否图集打包、色彩转换、UV 偏移及过滤会破坏字节。Point 采样、完整纹理可寻址和受控材质选择都要成立。
2. A/B 启动前均存在，游戏 Python 覆盖当前未显示路径后切换；反复复用已加载路径，保留旧代负对照。不执行全材质重载，不以新路径首次成功代替重复刷新成功。
3. 前两项通过后才扩大至 64 KiB 及以上，并分别计时 PNG 编码、文件写入、切路提交、实际新代可见延迟和长帧。以游戏 Python 构建的数据验收，不用宿主生成替代。

固定 alpha=255、RGB 存 bytes 时，128² 只有 48 KiB；256² 为 192 KiB，512² 为 768 KiB，均需扣除头部。这是纹理容量，**不是已上传量或吞吐**。少量 draw 仅表示有性能潜力：改 3 KiB 逻辑数据后可能仍需整图编码和上传；拆 PNG 页也会引入“单一 shader 如何访问所有页”的 sampler 汇聚问题，不能预先宣布支持高效局部更新。

## 三、用户提出的无损压缩：容量成立的条件

原 alpha 多数相同是待验证假设。无损编码不能保证把任意原图和任意新增数据塞进同样大的空间。对 RGBA8 中的 N 个 alpha byte、允许的原 alpha 状态集合 A、新载荷 L byte，必要条件是：

```text
log2(|A|) + 8L + metadata_bits ≤ 8N
```

若原 alpha 任意，则有 `|A|=256^N`，原信息已占满容量；无论换什么压缩算法，都不能保证 L>0。完整 RGBA 同理。额外私有纹理可增加总容量，但那是增加存储，并非压缩产生了必然空间。

以下**仅假设原生目标为 RGBA8**，共同 alpha 值已知为 255。720×1080 有 777,600 个像素，alpha 总空间为 777,600 B／759.375 KiB。用每像素 1 bit 位图标记例外，另存 k 个例外 byte，头部 h B：

```text
压缩 alpha = 97,200 + k + h byte
可用载荷   = 680,400 − k − h byte
```

若 90% 像素为共同值，k=77,760，h=16，则理论可用 **602,624 B／588.5 KiB**。若只需装 64 KiB，在这个编码下需 `k≤614,848`。这只证明某种输入下空间充足，不含全局偏移表、GPU 编码执行成本，也不代表真实场景已满足。即使 alpha 全常量，777,600 B 也不足以容纳 800 KiB。

真实 RT 可能有其他精度或格式。若 alpha 是浮点，先四舍五入到 byte 就不再是逐值无损。必须明确是 bit-exact 恢复、数值精确恢复还是容差内视觉一致；WGC 合成截图的 alpha 不能证明中间 RT 的格式、原 alpha 或分布。

## 四、可用 fragment gather 构造的固定 block 版本

可以不用全图可变长度压缩，先研究一个条件明确的格式。每 32 个原像素为 block，假设每 block 最多 4 个 alpha 例外，将 32 B 分配为：

| 部分 | 大小 |
| --- | ---: |
| 32 bit 例外位图 | 4 B |
| 顺序排列的最多 4 个例外值 | 4 B |
| payload | 24 B |

编码位图时，每个输出 byte gather 对应 8 个原 alpha；编码第 q 个例外值时，在本 block 内有限扫描。解码读取位图，非例外返回 255，例外通过 block 内 rank 找到原值。GLSL ES 100 可按 byte 使用 floor／mod，不将 32 bit mask 整体放进 float32。

该固定格式不需要全局 prefix sum、SSBO、atomic 或任意地址 scatter。720×1080 刚好有 24,300 个 block；压缩记录占 194,400 B，payload 可用 583,200 B／约 569.53 KiB，尚需扣除全局头部。

但全图例外率低，不能保证每一个 block 都满足最多 4 个例外。任一局部发光或粒子区域都可能溢出。必须在覆盖原信息**之前**判断有效性，并明确不提交、等待或额外私有存储的回退；不能截断例外。有效位、回退目录与其存储也必须计入预算。变长格式可以适应更广分布，但需要码长偏移、更多 pass 或有界搜索，不是免费优化。

这里的“就地”只能指逻辑上重排同样的 alpha 容量。普通 pass 采样 S 的同时将输出写回同一纹理附件会形成反馈；当前公共契约没有提供可依赖的 barrier／输入附件。因此应使用合法的 `S→T→U` 前向输出／ping-pong，不能声称无需额外 RT。

## 五、压缩尚未解决的两个入口问题

**首先，取得未覆盖的原 alpha。** 当前 geometry writer 在世界 draw 中使用 alpha replace 写载荷，后处理 `copy.fragment` 再读取 TEXTURE_1，此时 alpha 已被覆盖。事后压缩这张图无法恢复丢失信息。应保存的是“不启用 writer 时，正常世界渲染最终会产生的 alpha”；只保存 writer 前某一中间值，若之后还有合法 alpha draw，也不等于最终基线。

**其次，把批量数据写进压缩后的空间。** 理想条件数据流如下：

```text
干净场景 S → 压缩原 alpha 到工作 RT T → 批量 writer 仅写 T 的预留槽
                                                ├→ 私有数据 RT → array[index]
                                                └→ 解压原 alpha → 干净场景 U
                                                                         ↓
                                                              正常 bloom 等后处理
```

它要求能够在干净捕获之后把 geometry 定向写入 T，或 payload 已经在另一个可采样纹理里。公开 `RenderBlockGeometryModel`、`RenderEntity`、`RenderSkeletonModel` 没有目标 RT／可导出纹理句柄；`PostPassResultToOtherPass` 连接的是后处理结果，不会把世界 geometry 搬到两个 post pass 之间。`GameRenderTickEvent` 是帧开始事件，也不提供上述渲染阶段调度。

如果全部压缩和写入都在后处理完成，且输入还是 uniform 树，格式可以成立，却仍保留大量输入 context。若输入已是可访问的私有数据纹理，最高优先级的批量输入问题其实已经解决。压缩能节省特定输入的空间，**不会自行创造批量上传接口或正确的渲染阶段**。

因此混合使用是有意义的条件设计：例如保留部分 alpha 备份或数据在私有 RT 中，其余占用已证可恢复的空间。但它仍受相同的捕获、定向写入和生命周期限制，不能现阶段承诺为可靠兜底。

## 六、恢复期限与透明物／特效

本机 `threshold.fragment` 第 18–27 行提供了原 alpha 影响最终 RGB 的具体证据：

```glsl
#ifdef RNGL
    float alpha = step(threshold, luminance(color.rgb) * color.a);
#else
    float alpha = step(threshold, 1.0 - color.a);
#endif
// 随后按该 mask 筛选 bloom RGB
```

因此须在实际 bloom 输入被捕获／读取前恢复原 alpha；等最后输出才恢复无法撤销已经错误生成的 bloom。还需追踪各消费者读取 TEXTURE_0、TEXTURE_1 还是另一个保存结果：恢复主链输出不会自动修复被其他 pass 固定引用的污染源。

已读 terrain base 声明 DisableAlphaWrite，标准水与透明地形继承该路径。普通 SrcAlpha／OneMinusSrcAlpha 的 RGB 混合不依赖 destination alpha，不能断言借用 alpha 一定直接使所有透明物变色。但粒子、天气和部分描边可以写 alpha；若晚于 writer，它们可能破坏载荷。原版 write_alpha_0 材质也明确把 mask 写入 alpha，不能默认原 alpha 恒为 1。

对 30 份可读 material 的搜索未发现 destination-alpha 作为 RGB blend 因子，但编译材质及实际 renderer 选择未完全覆盖。此前仅固定天空区域的 RGB 对照精确相同；原 alpha 未保存，consumer 还强写 alpha=1，不能将该结果称为透明物／泛光兼容通过。

## 后续验证顺序与停止条件

1. **私有 bank 小实验。** 先验证 U5–U16 的实际上传、逐次更新和 process 隔离；失败即停止该分支，不做大树。成功后先测小拓扑的常驻成本，仍不直接推算 64 KiB 帧率。
2. **无文件 RGB 混合静态分支并行。** 按新增研究先确认混合模型的码域与阶段顺序；明确不再开展动态 PNG／RawPath 写文件实验。RGB 方案是借用场景的有损兜底，不标为完全私有路径。
3. **alpha 兜底保持小范围。** 先确认能否取得正确阶段的干净场景和写入目标；没有桥接入口就不扩建压缩器。另用原生 shader 诊断真实 alpha 的值域、量化残差、分布及逐 block 最坏例外数；诊断应在合成前把被测信息编码为可核验输出，不能读 WGC alpha 当原数据。晴天、雨雪、水／玻璃、粒子、附魔、发光、泛光开关与可用 renderer 分支分别记录。当前没有这些新测量。
4. **有可用原型后才验证混合恢复。** 包括容量溢出不提交、多个原 alpha 消费者、透明物和特效、窗口／分辨率变化，以及最终画面逐像素或明确容差对照。当前实验 alpha=1 不是恢复实现。

不重测已明确放弃的大数据全量高频更新。后续最终目标仍是完整随机索引数组驻留、按实际更新工作量限速，而不是累计传输量或诊断画面显示成功。

## 资料与源码依据

资料库路径通过 `minecraft_docs read` 读取；以下保持来源标识，不将资料副本当作原生实现：

- `NeteaseGuide/mcguide/16-美术/7-材质与着色器/4-材质实战.md`，379–390：paras、U1–U4、bindTexture。
- 同目录 `3-材质配置说明.md`，582–585：同名材质合并覆盖；`2-内置材质清单.md`，527–539：UI 材质。
- `NeteaseGuide/mcguide/18-界面与交互/30-UI说明文档.md`，1097–1115：图片路径、来源与 reload。
- `ModAPI/接口/后处理/自定义.md`：AddPostProcess、GetParameter、InsertPassToPostprocess、PostPassResultToOtherPass；没有任意 geometry target 的承诺。
- `GameAssets/resource_packs/vanilla/materials/ui.material`，50–53、193–199，及对应 `color_texture.fragment`／`texture_ccolor.fragment`：UI 自身 TEXTURE_0。
- `GameAssets/resource_packs/vanilla/ui/custom_templates_screen.json`，214–243；`vanilla_netease/ui/player_tips.json`，40–45：动态图片 binding。
- 本机 `D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.448891/data/shaders/glsl/` 下的 `uniformExtraVectorConstants.h`、`pbr_material_fabric_vip.fragment`、`threshold.fragment`、`write_alpha_0.fragment`；同 data 下 `resource_packs/vanilla{,_netease}/materials/`。
- 本机资料副本 `D:/Happy2018newの个人文件/GitHub/NeteaseVanillaMCP/` 的 `mod/client/component/postProcessControlComp.py`、`minecraft/postprocess.py`、`modelCompClient.py`。只证明可读 wrapper 行为。
- 既有实测：[私有 RT 树](TREE_ATLAS_RESEARCH.md)、[动态纹理旧失败与候选](../tools/runtime_packet_probe/BULK_TEXTURE_CANDIDATE.md)、[几何路线](GEOMETRY_ATLAS_RESEARCH.md)、[几何持续更新限制](GEOMETRY_ATLAS_STREAMING_RESEARCH.md)。
