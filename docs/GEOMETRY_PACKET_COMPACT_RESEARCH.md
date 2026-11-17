# 紧凑几何数据编码与高频更新旧代问题

本轮在[原有几何传输研究](GEOMETRY_PACKET_RESEARCH.md)上完成了 `compact8` 编码，并增加了可判别旧代的高频更新对照。当前最有依据的结论是：**把一个字节拆成整数 Y 的高 4 位和静态模型局部 Y 的低 4 位，可将 palette 的包围体高度从 256 降为 16；12 KiB 的本机有界更新实验显著降低了 Combine 调用耗时。旧编码的双名称连续重建则复现了精确的旧代数据，换成每代新名称或降低更新频率后，最后一代通过。**

这定位了“高频改变内容并重用原生 geometry 名称”这一不可靠条件，尚未确定引擎内部具体的缓存、队列或失效传播机制。更新通过均指停止后对最后一代的完整像素验证，不代表每个更新帧都显示了当代数据，也不代表已经达到 60 FPS。

小型归档入口为[本轮结果摘要](evidence/geometry-packets/compact-update-summary.json)及[v6 更新独立复核](evidence/geometry-packets/independent-updates-v6.json)。原始 case、upload history、命令、状态、原生 PNG、逐窗验证和旧代分类保留在 `.runtime/geometry-packet-study/v6/`、`v7/` 与 `v8/`。v8 冷启动的最终源码又完成了 3 KiB／112 次及 12 KiB／32 次 fresh 更新，最后一代全量像素验证与两 case 的独立复核均通过；12 KiB 运行未达到预热结束时间，没有 FPS 样本。历史失败必须保留；源 payload 失败与证据审计失败是不同状态。

## compact8 如何减少 palette 包围体

载荷长度为 `N`，`S` 为满足 `S*S >= N` 的最小二次幂，最小取 2。每个 slot 仍拥有独立的 X/Z 坐标：

```text
x = i // S
z = i % S
record = x*S + z = i
```

旧 `legacy8` 使用 `y=b` 和一个静态面，palette 体积为 `(S,S,256)`。新 `compact8` 使用 16 个预先生成的静态模型模板，所有模板使用同一材质、同一 shader 和同样的 X/Z 面形：

```text
high = b // 16
low = b % 16
block_y = high
template = low
local_plane_y = (template + 0.5) / 16
palette_volume = (S,S,16)              # 原生顺序为 (z,x,y)
palette_index = high*S*S + i
```

模型文件的 Y 单位为 1/16 方块，因此生成器中模板的 `origin.y` 为 `template+0.5`。半格偏移让每个模板平面处于对应低 4 位区间的中点，到相邻解码边界的距离为 `1/32` 方块。这是编码设计的容差，不是对所有客户端原生顶点精度的保证；实际精度仍由逐档位像素验证判定。

PaperDoll 对 palette 三轴居中，vertex shader 先还原源位置，再解码：

```glsl
source = POSITION.xyz + vec3(S*0.5, palette_height*0.5, S*0.5);
byte = 16.0*floor(source.y) + floor(16.0*fract(source.y));
```

这里低 4 位确实由原生几何面的局部位置携带。`CURRENT_COLOR` 仅传递 query 起点、长度、列数、诊断 mode、stride、Y 偏移和 encoding 标志；它不传 seed、generation 或逐 slot 的期望字节，shader 也不复算 PRNG。

| 指标 | legacy8 | compact8 | 可以据此得出的结论 |
| --- | --- | --- | --- |
| 每个逻辑字节的 primitive 数 | 1 quad | 1 quad | 没有把 quad 数量减少到 1/16 |
| 静态模型模板数 | 1 | 16 | 以有限的静态模板承载低 4 位 |
| palette 高度 | 256 | 16 | 同一个 `S` 下，包围体格数成为原来的 1/16 |
| 12 KiB 的 palette 体积 | `128*128*256` | `128*128*16` | 这是稀疏 palette 包围体的比较 |
| 逻辑载荷 | N 字节 | N 字节 | 没有压缩信息量，也没有减少逻辑 slot 数 |
| 原生顶点／索引／GPU 内存 | 未单独测量 | 未单独测量 | 不能宣称显存或实际内存减少 16 倍 |

本轮更快的 Combine 结果与更小的 palette 包围体一致，但没有引擎内部 profiling，不能把全部耗时差归因于单一内部算法。该编码仍属于“每个 primitive 自带记录”的几何数据通路；单靠它尚不能让任意 shader 按索引读取其他记录。后续几何写入共享纹理与 shader 索引取数的实测另见[几何数据纹理研究](GEOMETRY_ATLAS_RESEARCH.md)。

## v6 静态编码验证

v6 从新生成资源冷启动后先做 smoke，再运行静态基准。正式静态 case 为 8 秒、预热 1 秒；停止 query 基准后冻结同一 geometry，按最多 4,096 slot 的窗口覆盖全载荷。每个 slot 的完整 3×3 原生 RGBA patch 逐通道零容差检查，alpha 必须为 255。

| 原始 case | 逻辑载荷 | stride / 高度 | 初始 load 总耗时（ms） | 初始 Combine（ms） | 平均 `GetFps()` / 样本数 | 完整验证 |
| --- | ---: | --- | ---: | ---: | --- | --- |
| [`compact_smoke256`](../.runtime/geometry-packet-study/v6/compact_smoke256.case.json) | 256 B | 16 / 16 | 97.7535 | 0.0566 | 未运行基准 | 256 slot、2,304 个 patch 像素通过 |
| [`compact3k_static`](../.runtime/geometry-packet-study/v6/compact3k_static.case.json) | 3,072 B | 64 / 16 | 3.1364 | 0.2342 | 60.0603 / 27 | 3,072 slot、27,648 个 patch 像素通过 |
| [`compact12k_static`](../.runtime/geometry-packet-study/v6/compact12k_static.case.json) | 12,288 B | 128 / 16 | 13.0314 | 0.9668 | 60.0775 / 28 | 12,288 slot、110,592 个 patch 像素通过 |

smoke 的首次 Render 提交占 97.3940 ms，包含初次使用的开销；不能用这一项与后续已预热 case 推导稳态负载规律。3 KiB 与 12 KiB 的 FPS 接近 60 FPS 配置上限；它们证明本次静态驻留与逐窗查询成立，不证明动态上传能维持同样帧率。

## v6 高频更新对照

五组均上传 12,288 字节、seed 54321，初始 generation 1 后提交 128 次更新，最终 receipt 为 generation 129。每组设置 12 秒上限，实际达到 128 次更新后提前结束，再等待 2 秒冻结。表中“双名称”在同一 dataset 内交替使用两个 bank；“每代新名称”让每次 Combine 使用独立名称。每个独立 dataset 另有 epoch 隔离，避免跨 case 名称相撞。

| 原始 case | 编码 / 名称策略 / 更新间隔 | 渲染事件数 / 实际时长（s） | 平均 FPS / 样本数 | 平均渲染事件间隔（ms） | 冻结后最终全量画面 |
| --- | --- | --- | --- | ---: | --- |
| [`legacy12k_double128`](../.runtime/geometry-packet-study/v6/legacy12k_double128.update.json) | legacy8 / 双名称 / 每事件 | 128 / 4.8725 | 27.4443 / 6 | 39.8106 | **失败：全部 12,288 slot 精确等于 generation 59** |
| [`legacy12k_fresh128`](../.runtime/geometry-packet-study/v6/legacy12k_fresh128.update.json) | legacy8 / 每代新名称 / 每事件 | 128 / 9.7827 | 13.2796 / 7 | 86.2165 | generation 129 全量通过 |
| [`compact12k_double128`](../.runtime/geometry-packet-study/v6/compact12k_double128.update.json) | compact8 / 双名称 / 每事件 | 128 / 2.7826 | 45.1642 / 5 | 21.9014 | generation 129 全量通过 |
| [`legacy12k_double128_spaced`](../.runtime/geometry-packet-study/v6/legacy12k_double128_spaced.update.json) | legacy8 / 双名称 / 每 4 个事件 | 509 / 10.6785 | 48.1493 / 30 | 20.8960 | generation 129 全量通过 |
| [`compact12k_fresh128`](../.runtime/geometry-packet-study/v6/compact12k_fresh128.update.json) | compact8 / 每代新名称 / 每事件 | 128 / 2.5803 | 50.4705 / 5 | 20.0649 | generation 129 全量通过 |

表中“事件数”是运行期 `GameRenderTickEvent` 次数；每组实际上传次数均为 128。FPS 是 SDK 的标量 `GetFps()` 样本平均值，事件间隔则由事件时钟差测得，两者不互相替代。部分运行仅有 5–7 个 FPS 样本，不适合将小数差异当作稳定性能排名。

以下 CPU 阶段均值仅包含预热后的采样，单位为 ms：

| case | 生成字节 | 构造 palette 索引 | Deserialize 调用 | Combine 调用 | Render 提交 | 阶段采样数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| legacy8，双名称，每事件；最终失败 | 11.6005 | 0.7296 | 0.0197 | 17.8112 | 0.2054 | 97 |
| legacy8，每代新名称，每事件 | 14.1751 | 1.0274 | 0.0263 | 55.9142 | 0.4268 | 101 |
| compact8，双名称，每事件 | 10.9365 | 2.6896 | 0.0162 | 1.6699 | 0.0781 | 81 |
| compact8，每代新名称，每事件 | 9.9393 | 2.5735 | 0.0144 | 1.0117 | 0.2162 | 78 |

同为每代新名称时，Combine 调用均值从 55.9142 ms 降到 1.0117 ms；这支持新编码对本机这一负载有效。compact8 的 Python 索引分桶反而比 legacy8 更耗时，约 2.57 ms 对 1.03 ms。新编码下字节生成约 9.94 ms，已是所列 CPU 阶段的主要开销。这里测的是调用返回时间，**没有测量原生 GPU 上传或绘制完成时间**，不能据此给出 GPU 吞吐率或端到端每帧时延。

`legacy12k_double128_spaced` 的 v6 阶段计时存在已确认的统计缺陷：跳过上传的事件重复采集上次 `self.timings`，509 个事件／128 次上传却有 463 个 Combine 样本。因此本报告不引用其阶段均值。上传历史中每次真实 `load()` 的独立计时仍可复核；FPS 与事件时钟间隔不直接受该重复采样缺陷影响。v7 源码已用 `did_upload`／`did_query` 限制阶段采样。

这些组在同一受管实例中顺序执行，原生资源驻留、初始化和内存已被前组预热；没有随机化顺序、多轮重复、统一空白内存起点或跨设备实验。因此数值是带有上下文的本机观察，不是受控实验下的通用倍率，也不是移动端结果。

## 旧代来自哪里：证据与可下结论的范围

诊断 runner 不从失败图中猜 seed、不平移窗口，也不把中心像素相似当作成功。它冻结最终 seed、generation、geometry 名称、build serial 和 slot 数后，以实际提交过的 upload history 为候选，逐候选重算独立 PRNG oracle。只有整个窗口全部 3×3 RGBA patch 精确通过且载荷有足够变化时，才分类为某个已提交 generation。

`legacy12k_double128` 的三个窗口均唯一匹配 generation 59，覆盖所有 12,288 slot。最终 CPU receipt 为 generation 129、build serial 132；旧代候选确为之前提交过的 generation 59、build serial 62，且与最终使用相同的 bank 名称。重复使用最终名称调用 Render，以及移除后重新创建 UI 再渲染，均未改变这一结果：

| 编码和条件 | 冻结后原始画面 | 同名重新 Render | 重建 UI 后重新 Render |
| --- | --- | --- | --- |
| legacy8，双名称，每事件 | 全量 generation 59；最终失败 | 仍全量 generation 59 | 仍全量 generation 59 |
| compact8，双名称，每事件 | 全量 generation 129 | 全量 generation 129 | 全量 generation 129 |
| legacy8，每代新名称，每事件 | 全量 generation 129 | 全量 generation 129 | 未请求该控制 |
| legacy8，双名称，每 4 个事件 | 全量 generation 129 | 全量 generation 129 | 未请求该控制 |
| compact8，每代新名称，每事件 | 全量 generation 129 | 全量 generation 129 | 未请求该控制 |

这些对照共同支持以下判断：

- 不是只有 CPU generation 标签超前这一现象：图像完整匹配一个具体的、确实提交过的旧代。
- 单纯再次 Render 或重建 UI 未恢复，因此不能把失败完整归因为已移除的 UI 节点私有缓存。
- 同样的字节数和 legacy8 编码，改成每代新名称后最后一代正确，说明名称复用与内容替换的交互值得优先处理。
- 同样双名称 legacy8，拉开更新间隔后最后一代正确；compact8 减轻 Combine 负载后双名称也通过。这与高频替换导致的原生可见性／失效传播问题相符，但不是对某种具体队列或缓存实现的证明。

通过 MCP 资料库查询 `api CombineBlockPaletteToGeometry` 得到的公开备注明确写道：“如果之前已经拥有一个相同名称几何体模型，合并出来的新模型会覆盖之前的模型。因此需要注意，每次合并不同外观的模型时 geometryName 都应该互不相同。”同一备注只对外观相同的模型建议重用名称以节省存储。载荷改变会改变实际几何外观，因而默认采用每代新名称符合该契约；两个 bank 并不是文档保证可用于连续内容替换的协议。

因此本轮没有宣称“已经修复引擎缓存”。保守处理是默认每代新名称，把 `single`／`double` 保留为明确不安全的诊断路径；即使 compact8 双名称这次通过，也不能外推到所有负载、长期重用或每帧新鲜度。尚缺的证据包括：引擎内部同名替换实现、原生资源的释放时机、逐帧 GPU 完成点，以及每个上传 generation 的实际首次显示时间。

## v7 容量与会话资源保护

v7 冷启动使用修正后的阶段采样，并增加跨 dataset 保留的会话保护：最多 256 个已成功创建的 geometry 名称，且所有名称最后登记的逻辑 record 数之和不超过 2,097,152。每条记录承载一个逻辑字节，因此这一计数相当于 2 MiB 的逻辑命名载荷；它不是原生 GPU 内存、进程工作集或真实资源分配字节数。

`begin_dataset()` 只清除该 dataset 的 receipt 和诊断历史，不清除这两个预算计数，也不声称释放原生资源。达到预算即停止，并要求重启当前 owner 所属实例；减少 Python 历史列表或重新开始 case 都不能绕过保护。当前默认策略为 `fresh`、每事件上传、最多 64 次更新；实际仍由会话预算约束，不能把有界实验入口当作已具备无限流式上传和回收能力的产品功能。

| v7 case | 运行结果 | 可以保留的结论 |
| --- | --- | --- |
| [`compact1m_static`](../.runtime/geometry-packet-study/v7/compact1m_static.case.json)，1,048,576 B，stride 1,024 | **首个 4,096-slot 窗口失败**；537 个 slot patch 不通过，最大通道误差 249 | 1 MiB compact8 未通过；没有完整容量结论。此 case 为 verify-only，不提供稳态 FPS |
| [`compact256k_static`](../.runtime/geometry-packet-study/v7/compact256k_static.case.json)，262,144 B，stride 512 | 26 个窗口、106,496 slot 已通过；在 query 106,496 的 host 调用后因后台保护条件丢失而中止 | case 失败／不完整；不能把已通过的前缀当作完整 256 KiB 容量 |

256 KiB 中止日志明确为 `Owned game is not protected in the background; no activation fallback is allowed`。这次没有观测到导致中止的 payload 像素错误，应归类为基础设施／后台条件失败；但缺少剩余窗口，仍不能通过。1 MiB 则是明确的像素 oracle 失败。两种失败保留各自原始证据，不能混为容量硬上限或同名旧代问题。

此前 v5 的 legacy8 256 KiB 静态全量通过仍然有效，详见[旧报告](GEOMETRY_PACKET_RESEARCH.md#v5-最终静态扫描)。它不自动证明 compact8 的同档位，也不因新 case 中止而失效。在本报告的 PaperDoll 查询通路中，compact8 最大完整静态通过档位为 12 KiB；大档位需要完成独立的冻结全覆盖扫描。后续世界几何写入共享纹理的另一条通路已完成 64 KiB 全量验证，见[几何数据纹理研究](GEOMETRY_ATLAS_RESEARCH.md)，两种绘制负载分别记录。`MAX_BYTES=1048576` 是入口保护值，既不是成功容量，也不是已确定的硬件上限。

## v8 冷启动的有界动态验证

v8 在后台保护恢复后，用重新生成的独立 project 冷启动当时源码，包含修正后的上传历史、阶段采样和跨 dataset 会话预算。提交前又为失败重试补充了跨 dataset 保留的 `native_attempt_serial`：每次原生 Combine 尝试先消耗新编号，成功 receipt 的 build serial 仅计完整成功提交，避免 Render 失败后重用候选名称。这项后续失败路径加固通过单元回归与 MCP 审查，未再次进行实机冷启动；正常编码与 shader 不变。两项均使用 `compact8`、`fresh`、每渲染事件一次上传、8 秒时间上限，达到指定更新次数后提前结束。停止后冻结最后一代，使用同一原生像素 oracle 全量覆盖。

| 原始 case | 字节数 / 更新次数 | 最终 generation | 实际更新时长（s） | 平均 FPS / 样本数 | 最终全量验证 |
| --- | --- | ---: | ---: | --- | --- |
| [`compact3k_dynamic112`](../.runtime/geometry-packet-study/v8/compact3k_dynamic112.case.json) | 3,072 / 112 | 113 | 1.8805 | 60.0775 / 3 | 3,072 slot、27,648 个 patch 像素精确通过 |
| [`compact12k_dynamic32`](../.runtime/geometry-packet-study/v8/compact12k_dynamic32.case.json) | 12,288 / 32 | 33 | 0.5924 | 无样本 | 12,288 slot、110,592 个 patch 像素精确通过 |

3 KiB 在预热后有 52 次上传阶段样本，Combine 调用均值为 0.2706 ms、字节生成 2.5056 ms、构造 palette 索引 0.6073 ms；渲染事件间隔平均 16.6449 ms。其 3 个 FPS 样本接近配置上限，只支持这次短时运行的观察。12 KiB 在 1 秒预热结束之前已完成，因此 FPS、事件间隔和阶段均值的样本数都是 0；不能补成 60 FPS，最后一次 load 的计时也不能冒充稳态均值。

两组在同一新实例内先后执行，最后一个 snapshot 的预算为 146 个名称、752,640 个逻辑 record，低于 256 名称／2,097,152 record 的保护阈值。[v8 独立复核](evidence/geometry-packets/independent-verification-v8.json)重新验证两 case、4 个窗口与全部 15,360 字节，`passed=true`、`completed_cases_recheck_passed=true`、`failed_completed_rechecks=0`。这些成功保留了 v7 两个容量 case 的失败；它们仍只证明冻结后的最后一代，不补足更新期间逐帧新鲜度或长期资源回收。

## 复现与复核

实现集中在 [`codec.py`](../tools/geometry_packet_probe/codec.py)、[`build_probe.py`](../tools/geometry_packet_probe/build_probe.py)、[`runtime.py`](../tools/geometry_packet_probe/runtime.py)、[`geometry_packet.vertex`](../tools/geometry_packet_probe/geometry_packet.vertex) 和 [`run_update_diagnostic.py`](../tools/geometry_packet_probe/run_update_diagnostic.py)。探针独立生成行为包／资源包，不修改产品资源。宿主侧仍复用现有 [`host.py`](../tools/geometry_packet_probe/host.py)，以 owner `manim-geometry-packets` 绑定受保护实例与捕获身份。

在仓库根目录执行以下紧凑流程，路径和 case 名称应为未使用的新目录／名称，保留已有证据。构建完成后冷启动生成项目，不能向仍运行的旧 project 仅复制新 shader 后继续测量，也不能用 `ReloadAllShaders` 混合状态代替冷启动。启动工具复用已经安装的客户端与现有受管工程机制，不复制整个开发客户端或已有世界。

```powershell
python -B tools/geometry_packet_probe/build_probe.py --output .runtime/geometry-packet-study/project-repro-compact
python -B tools/geometry_packet_probe/host.py launch --project .runtime/geometry-packet-study/project-repro-compact --evidence .runtime/geometry-packet-study/repro-compact
python -B tools/geometry_packet_probe/host.py resize --project .runtime/geometry-packet-study/project-repro-compact --evidence .runtime/geometry-packet-study/repro-compact --width 720 --height 1080
python -B tools/geometry_packet_probe/run_case.py --project .runtime/geometry-packet-study/project-repro-compact --evidence .runtime/geometry-packet-study/repro-compact --name compact12k_static --bytes 12288 --encoding compact8 --policy fresh --seconds 8
python -B tools/geometry_packet_probe/run_update_diagnostic.py --project .runtime/geometry-packet-study/project-repro-compact --evidence .runtime/geometry-packet-study/repro-compact --name compact12k_fresh32 --bytes 12288 --encoding compact8 --policy fresh --updates 32 --interval-frames 1 --seconds 8 --full --recreate
```

启动入口在实际 roaming options 路径备份并固定 60 FPS，关闭无限帧率；已有进程与配置冲突时按现有保护拒绝继续。所有启动、调用、resize 与 Windows.Graphics.Capture 截图均须通过 noactivation 后台保护，不激活、不还原或输入游戏窗口。若后台保护丢失，保留失败并停止，不能改用前台完成剩余扫描。实际 WGC PNG 必须为 720×1080 原生物理客户区，不能用逻辑 UI 尺寸、缩放图或自动裁切替代。

复现 v6 对照时，将参数改为 `--updates 128 --seconds 12 --bytes 12288 --full`，分别选择表中的 encoding／policy／interval；双名称失败对照另加 `--recreate`。当前保护下，每组大规模 fresh 对照应在新的受管冷启动会话中运行，避免累计耗尽预算。这样得到的是当前代码的独立复现，性能环境与原始 v6 的同实例顺序执行并不完全一致。`--seconds` 是上限，达到有界更新次数会提前结束；判断实际运行时长必须读取 case 中的 `benchmark.elapsed`。

更新复核入口 [`recheck_updates.py`](../tools/geometry_packet_probe/recheck_updates.py) 从原始 PNG、receipt、查询窗口和 upload history 重算全部候选，并保存实际读入文件的 SHA-256。可对新的 evidence 目录运行：

```powershell
python -B tools/geometry_packet_probe/recheck_updates.py --evidence .runtime/geometry-packet-study/repro-compact --output .runtime/geometry-packet-study/repro-compact/independent-updates.json
python -B tools/geometry_packet_probe/recheck_evidence.py --evidence .runtime/geometry-packet-study/repro-compact
```

更新复核的 `audit_passed` 表示原始证据与重算一致；`final_payload_passed` 表示源 case 最终载荷均正确。保留 legacy8 双名称失败时，前者可为 true、后者应为 false，不能为了总体绿色而删除失败 case。所有动态结果继续保留 `all_render_frames_verified=false`、`gpu_to_python_readback=false`、`actual_mobile_hardware=false`；宿主读取截图用于验证，不构成游戏内 GPU → Python 回读通路。
