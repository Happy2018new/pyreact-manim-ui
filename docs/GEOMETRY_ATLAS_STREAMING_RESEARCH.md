# 共享数据纹理的容量扩展与连续更新研究

本轮已将这条共享数组通路的**全量实机验证容量从 64 KiB 提升至 512 KiB（524,288 字节）**。b7c 冷启动使用半格几何模板与实图校准中心 `(1,.5,.5)`：同一份冻结的 512 KiB 载荷，经场景 alpha、copy pass 和显式 `TEXTURE_3` 连接，identity／dependent 各完成 524,288 个 query、各 128 张原生截图，全部 3×3 RGBA patch 零误差。identity 覆盖全部 524,288 个源地址；dependent 的第二地址有重复，实际涉及 331,726 个不同源地址。**完整载荷容量由 identity 建立，不能将 dependent query 数等同于不同地址数。**

512 KiB 旧模板失败不是一个已证实的容量硬上限。b2 原始全扫仍保留 identity 510 错、dependent 1,037 错；b5 同几何诊断将问题收窄到 consumer 之前的几何输入／逐顶点 cell-record 恢复、atlas 行 wrap 与局部裁剪组合。新模板需要额外校准原生 X 偏移，b4 默认中心的失败同样保留。半格端点布局和统一校准中心已通过新一轮冷启动全扫；native POSITION 格式、JSON→native X 变换与精确光栅裁剪机制没有直接捕获，不能写成已证明某种 half 格式或驱动 bug。

连续更新方面，**帧率、冻结末代正确性、运行中正确性必须分别判断**。b3 的 3 KiB 无等待能实现约 60 Hz CPU 提交和约 60 FPS，末代全量正确，但另一次同参数运行中三张图为白帧；12／64 KiB 高频也出现白帧或精确匹配旧代。固定双 bank 加等待和 pending 背压后已有成功抽查：b7c 的 3 KiB、50 ms 等待／100 ms 请求，实际 9.9917 Hz、59.1800 FPS、最大事件间隔 26.8103 ms，末代全量和另一次三张 live 全过；12 KiB、150／500 ms 为 2 Hz、56.8218 FPS，仍有长帧。b7c 开始时另有独立 MC 实例，本批不作为独占机器性能基准。旧批次更完整的固定档位比较继续保留，当前没有证明长期每代／每帧新鲜且稳定 60 FPS 的档位。

512 KiB 冻结后 8 秒静态测量为约 60.06 FPS，不包含重建上传；本批单次 synthetic payload 构造＋编码＋原生提交约 1.789 秒，其中已有 bytes 的 encode＋native 部分约 485.53 ms。它适合容量验证和初始化／低频方向，不能视为高频传输方案。关闭 writer 会破坏首窗，恢复后首窗通过；新 generation 2 的 identity／dependent 首中尾六窗通过且同图拒绝真实旧代 oracle，gen2 仍只计采样，未声称第二次完整容量扫描。

本报告覆盖 b2 容量、b3 的 29 组连续更新性能、b5 旧模板冷启动、b6 同几何解码对照、b4 失败及校准，以及 b7c 的四个最终 case 与两组 live。所有结论限于所列固定条件的桌面开发客户端；没有移动端硬件、GPU completion fence、GPU→游戏 Python 回读或长期每帧正确性证据。小型可审阅结果见 [归档索引](evidence/geometry-atlas/streaming/README.md)，原生 PNG／生成项目继续留在本地 ignored 目录。

最终证据入口为 [b7c 四例汇总](evidence/geometry-atlas/streaming/b7c-calibrated-summary.json)、[b7c 重放摘要](evidence/geometry-atlas/streaming/independent-b7c-replay-summary.json)和 [writer／新代来源对照](evidence/geometry-atlas/streaming/b7c-source-controls-summary.json)。下面的旧批次入口与计数只指 b2／b3／b5 的性能和诊断，不能替代 b7c 新模板结果。

证据入口为 [b2 汇总](../.runtime/geometry-atlas-study/b2/summary-v1.json)、[b3 最终 29 组汇总](../.runtime/geometry-atlas-study/b3/summary29.json)、[b3 基础矩阵 CSV](../.runtime/geometry-atlas-study/b3/summary-matrix24.csv)、[b5 汇总](../.runtime/geometry-atlas-study/b5/summary4.json)和表中的原始 `.updates.json`。三个性能批次分别为 4／29／4 case，`summary_errors` 均为 0；37 个源文件的 SHA-256 已与对应汇总逐一核对。b3 展示时保留原 [24 组基础矩阵](../.runtime/geometry-atlas-study/b3/summary-matrix24.json)，再列五组补充；六组 `.live.json` 的 18 张原生图单列运行中正确性，b6 另有 18 张冻结解码对照，不增加性能 case 或容量测量次数。汇总读取已有回执和验证结果，不重新检查 PNG；本报告对正式 case 的回执、逐窗验证统计与哈希核对，也不替代另一套独立像素算法。运行中白帧则另行读取原生 PNG 检查整个输出 ROI。原始证据保留在 `.runtime/geometry-atlas-study/b2/`、`b3/`、`b5/` 与 `b6/`。

## 本轮实际测量的工作

沿用 [alpha／共享复制纹理通路](GEOMETRY_ATLAS_RESEARCH.md#数据实际经过的路径)：游戏 Python 构造 compact8 字节几何，世界 scatter 每帧把全部源 record 写入场景 alpha；pass 0 复制 RGBA，pass 1 写 poison 哨兵，pass 2 从显式连接的 `TEXTURE_3` 按索引取 alpha，并输出可供宿主像素检查的灰度。每字节仍需一个 quad。consumer 最多显示 4,096 个查询结果，**不表示该帧只 scatter 4,096 个源 record**。

全部 b2／b3／b5 case 固定原生物理 720×1080、后台 noactivation、60 FPS 配置，隐藏 HUD 与准星；正式默认路径为 `direct_source=false`、`flip_y=true`。三批均使用旧的 XZ 四分之一方块平面模板；b5 为旧模板的新一次冷启动，b4／b7c 使用半格模板，属于不同资源版本；b4 默认中心失败，b7c 使用实图校准中心。本机为网易开发客户端 3.10、RTX 4060 Laptop GPU。这些是桌面开发客户端结果，没有移动端硬件测量。

| 驻留逻辑载荷 | 源 atlas 列数 | 每源格物理尺寸 | 左上角 | 本轮使用 |
| --- | ---: | ---: | --- | --- |
| 3 KiB | 64 | 4×4 px | `(8,64)` | b2／b3 静态与自主连续更新 |
| 12 KiB | 64 | 4×4 px | `(8,64)` | b3 静态与自主连续更新 |
| 64 KiB | 256 | 2×2 px | `(8,64)` | b3 静态与自主连续更新，末代仅抽样 |
| 128 KiB | 512 | 1×1 px | `(8,32)` | 静态抽样 |
| 256 KiB | 512 | 1×1 px | `(8,32)` | 静态抽样 |
| 512 KiB | 512 | 1×1 px | `(8,32)` | b2 全扫失败保留；b7c 校准后全量通过 |

512 KiB 的源布局覆盖 `x=[8,520)`、`y=[32,1056)`，在固定目标内。每次显示窗口都放大到 `[x=0,y=64,width=720,height=1000]`。正式冻结末代验证按固定坐标检查每个结果格完整 3×3 RGBA patch，RGB 必须逐通道精确等于期望 byte，alpha 必须为 255，容差为零；不缩放图像、不偏移搜索、不自动裁切。源 atlas 的 1 px 小格与输出验证格的 3×3 patch 是两个不同位置的概念。运行中分类先做 fingerprint 预筛，仅对预筛通过的候选执行完整 patch 检查，详见后文。

设冻结载荷为 `B[0..N-1]`，`j` 为 query 起点加输出格序号。b2／b3 检查以下两个模式：

| 模式 | fragment consumer 运算 | b2／b3 参数 |
| --- | --- | --- |
| identity | 返回 `B[j]` | mode 0，salt 0，salt2 0 |
| dependent | `k=(131*j+salt) mod N`；先读 `first=B[k]`，再返回 `B[(k+257*first+salt2) mod N]` | mode 2，salt 37，salt2 91 |

大索引 consumer 将 `128*j` 分段取模后再与 `3*j+salt` 合并，保持上述整数公式，同时避免直接构造超出 float32 精确整数范围的 `131*j` 中间值。第二次地址依赖真实的第一次纹理采样。shader 不接收 seed、generation 或载荷副本；宿主 oracle 根据 seed、generation 和整数公式重算期望。完整 dependent 查询仍可能多次访问同一个第二地址，因此必须分别报告 query 覆盖和第二源地址覆盖。

`run_update_case.py` 在不超过 12 KiB 时默认遍历全部 query；更大载荷默认只选三个互不重叠的 4,096 格窗口，起点为 `0`、`(N-4096)//2`、`N-4096`。只有显式 `--full` 才对大载荷逐窗扫描全量。64 KiB 的起点为 0／30,720／61,440；128 KiB 为 0／63,488／126,976；256 KiB 为 0／129,024／258,048。跨窗冻结载荷和几何身份，只改查询参数，不将大载荷拆成小载荷重新上传。

## 自主调度与时间统计的含义

动态运行由游戏内 `GameRenderTickEvent` 驱动。正式性能测量由宿主提交一次 benchmark start，等待测量终止后才读取 terminal receipt；b2／b3／b5 共 37 个性能 case 均记录 `host_requests_between_start_and_terminal=0`。该区间没有宿主 IPC 轮询、截图、query 修改或宿主 `GetFps()` 请求；游戏内回调自行收集帧率。其像素验证在运行结束、pending candidate 排空、最终 generation 冻结后执行，不能由此宣称每个更新代或每个渲染帧都已核验。另行执行的 30 秒 live 正确性诊断包含宿主请求及捕获，全部性能数据排除，不并入这些性能表。

请求的 8 秒**包含最初 1 秒预热**，并非另加 1 秒再采 8 秒。进入预热门槛后记录 render-event 间隔，每 15 个渲染事件采一次 `GetFps()`。CPU 上传样本则包含预热期间所有成功的调度上传。末尾 pending publication 可延长实际 elapsed，上传／发布 Hz 的分母为包含最终排空在内的实际 elapsed。

| 指标 | 本报告采用的定义 | 不能据此推导 |
| --- | --- | --- |
| `GetFps()` | SDK 标量样本的均值、最小值、最大值 | 单靠均值不能排除间歇上传卡顿 |
| render-event interval | 预热门槛后的相邻渲染事件时间差；列 p95、p99、最大值和超时计数 | 不是 GPU 单帧执行时间 |
| render-event Hz | `1000 / interval_mean_ms` | 不等同于 SDK `GetFps()`，也不是 `frames/elapsed` |
| generation | 游戏 Python 生成全量 payload 的同步 CPU 时间 | 不包含编码及原生创建 |
| encode | compact8 编码与 palette 数据组织的同步 CPU 时间 | 不是跨语言原生调用时间 |
| native | 每次 `deserialize_ms + combine_ms + attach_ms`，先逐次求和再求分位数 | 不将各阶段 p95 相加，也不代表 GPU 完成 |
| total | 从开始生成至原生创建、首次挂载及 bank 透明度标记完成的同步 CPU 时间 | 不包含后续发布 API、四组 actor uniform 更新或最终 query，不能称为端到端可见延迟 |
| `publish_wait_ms` | 挂载提交结束至发布 API 返回之间的 CPU elapsed | 包含固定等待、事件量化及 API 开销，没有 GPU fence 或原生可见性时间点 |

分位数采用排序后 `floor((n-1)*q)` 位置。失败的 `_submit_upload` 尝试不会进入成功上传时间样本，但其停顿仍可能体现在帧间隔中。少量长帧可能落在 p95 之外，因此持续更新至少同时查看 p99、最大值、`>33.3 ms` 和 `>50 ms` 计数。

调度器达到 `max_updates` 或名称／record 预算后会停止上传，却继续采样到请求时长结束。此时即使 `status=completed`、`duration_completed=true`，也可能存在长静态尾段。只有 dynamic、measurement success、duration completed、`truncated=false`、`budget_limited=false`、`end_reason=duration` 同时成立，才列为“全时段持续更新资格通过”；像素正确性另判。静态测量的这些动态字段在汇总中为 null，不表示静态测试被截断。

## 双 bank 与 BBE 等待策略的区别

`fresh` 为每次上传创建新 geometry 名称，发布时隐藏上一代。`double` 复用两个固定 bank 名称，两份几何保持挂接；通过 `.25/.75` 透明度标签标识 bank，再以 actor uniform selector 选择实际 scatter 的 bank。两种策略都只允许一个 pending candidate，发布之前不会再次覆盖该候选。`published_at` 和顶层 generation 表示 CPU 已提交发布的身份，不是 GPU 已可见的证明。

本探针接受常量 `publish_delay_ms`。b2 动态样例固定为 0 ms，b3 比较固定 0／50／150 ms 等待；这些都属于固定延迟双 bank 对照。BBE 的实际调度在 [occupancy.py](../../better-building-editor/behavior_pack/modern_projection/projection/occupancy.py) 中根据状态规模及构建耗时自适应：

```python
resource_wait = max(.15, len(state)/419430.4, last_build_ms*.04)  # 有 model 时
first_attach_delay = max(.2, resource_wait)
next_build_delay = max(.35, last_build_ms*.008)
```

`len(state)` 是该投影的世界状态规模，不能直接替换成本探针的 payload byte 数。若一次构建为 50 ms，构建耗时项会给出 2 秒资源等待，构建冷却为 400 ms。BBE 首次挂接、已有 actor 的 pending 发布及后续构建冷却分别受这些条件约束；**固定 0／50／150 ms 双 bank 实验没有实现整套 BBE 自适应公式**。记录中的 `previous_bank_publication` 是同一 bank 的上次发布时间，也不是它的上次停用时间，不能用两者差值声称测得 bank 的空闲静置时间。

## b2 容量与冻结末代像素结果

| 原始 case | 实际测量 | identity 覆盖与结果 | dependent 覆盖与结果 | 可保留的结论 |
| --- | --- | --- | --- | --- |
| [smoke3k_double500](../.runtime/geometry-atlas-study/b2/smoke3k_double500.updates.json) | 3,072 B；dynamic double；500 ms；固定等待 0 ms | 全 3,072 源 slot；1 窗；0 错 | 全 3,072 query；1,975 个不同第二地址；0 错 | 冻结 generation 17 完整通过；同图旧代 oracle 被拒绝 |
| [cap128k_static_sample](../.runtime/geometry-atlas-study/b2/cap128k_static_sample.updates.json) | 131,072 B；static fresh | **抽样** 12,288 源 slot；3 窗；0 错 | **抽样** 12,288 query；11,763 个不同第二地址；0 错 | 仅抽样通过；完整驻留容量未验证 |
| [cap256k_static_sample](../.runtime/geometry-atlas-study/b2/cap256k_static_sample.updates.json) | 262,144 B；static fresh | **抽样** 12,288 源 slot；3 窗；0 错 | **抽样** 12,288 query；12,040 个不同第二地址；0 错 | 仅抽样通过；完整驻留容量未验证 |
| [cap512k_static_full](../.runtime/geometry-atlas-study/b2/cap512k_static_full.updates.json) | 524,288 B；static fresh；`--full` | 全 524,288 源 slot；128 窗；**510 错** | 全 524,288 query；331,726 个不同第二地址；128 窗；**1,037 错** | **完整扫描失败**；不能计为通过容量 |

128／256 KiB 的 `case_passed=true` 指请求的采样控制通过，两例均为 `complete_payload_verified=false`、`verified_payload_capacity_bytes=null`。512 KiB 的 `full_query_coverage=true` 表示扫描覆盖完整，不能把 coverage 与 correctness 混为一谈；其 `complete_payload_verified=false`。四例的 `all_render_frames_verified=false`，动态样例也没有逐代保存完整图像来证明每次中间更新的新鲜度。

## b2 帧率、帧间隔和更新节奏

四例均请求 8 秒，实际得到 481 次渲染事件、421 个预热后的间隔样本和 28 个 `GetFps()` 样本。静态例在初始上传完成后才测量；以下静态帧率**不包含反复生成、编码和 Combine 上传**。512 KiB 行同时保留其像素失败标记，避免将高帧率误当作正确性通过。

| 载荷／模式 | 实际 elapsed（s） | `GetFps()` 平均／最低／最高 | render-event Hz | 间隔平均／p95／p99／最大（ms） | `>33.3 ms`／`>50 ms` |
| --- | ---: | --- | ---: | --- | ---: |
| 3 KiB dynamic，500 ms | 8.0128733 | 60.0775／60.0775／60.0775 | 60.0129 | 16.6631／18.3349／18.6720／24.1900 | 0／0 |
| 128 KiB static，抽样通过 | 8.0128561 | 60.0775／60.0775／60.0775 | 60.0103 | 16.6638／18.3634／18.6864／19.5052 | 0／0 |
| 256 KiB static，抽样通过 | 8.0110601 | 60.0692／59.9613／60.0775 | 60.0078 | 16.6645／18.6516／18.9691／19.4528 | 0／0 |
| 512 KiB static，**像素失败** | 8.0124130 | 60.0775／60.0775／60.0775 | 60.0088 | 16.6642／18.4082／18.6796／19.1489 | 0／0 |

3 KiB 动态样例有 16 uploads／16 publishes，实际上传、发布速率均为 **1.9967868455 Hz**；上传起点间隔均值 500.0145 ms，发布间隔均值 500.0367 ms。`skipped_updates=0`、`overruns=0`、`pending_skips=0`，无预算或最大次数截断，结束原因为 duration，满足本报告的持续更新资格。

这支持“此固定条件下 3 KiB／500 ms 的一个 8 秒样本完成持续调度，末代完整正确，所采集间隔没有超过 33.3 ms”，仍不足以给出长期运行、每代可见时间、其他载荷／间隔或其他设备的平滑性承诺。原始上传和发布次数为 CPU 侧成功提交次数，不能称为 16 次 GPU fence 确认。

## b2 一次上传的同步 CPU 成本

动态行统计 16 次成功调度上传，包含预热期上传；静态行仅为各 case 的初始一次构造／提交参考。大载荷没有重复上传分布，不能把单次值标为稳定 p95，也不能按其倒数推出可用更新频率。

| 样本 | generation（ms） | encode（ms） | native 合计（ms） | total（ms） |
| --- | ---: | ---: | ---: | ---: |
| 3 KiB dynamic，均值 | 2.7547 | 0.7513 | 0.4350 | 3.9410 |
| 3 KiB dynamic，p95 | 3.4940 | 1.0184 | 0.5240 | 4.9137 |
| 3 KiB dynamic，最大 | 4.0506 | 1.1669 | 0.6930 | 5.9105 |
| 128 KiB，初次提交 | 125.0890 | 30.5306 | 14.5038 | 170.1234 |
| 256 KiB，初次提交 | 246.6746 | 60.4587 | 16.9547 | 324.0880 |
| 512 KiB，初次提交，像素失败 | 472.8046 | 112.8630 | 64.0927 | 649.7603 |

3 KiB 在动态测量开始前的首次加载另为 total 83.7776 ms、native 80.6628 ms，其中 attach 80.3002 ms。这个首次使用参考与后续 16 次调度样本单独报告；现有证据不能将其全部精确归因于某项 C++／GPU cache 行为。512 KiB 的 native 为 deserialize 0.0147 ms、Combine 63.9921 ms、attach 0.0859 ms；它的 CPU 成本记录有效，但不能抵消末代像素失败。

## b3 24 组连续更新矩阵

本节只展示 [summary-matrix24.json](../.runtime/geometry-atlas-study/b3/summary-matrix24.json) 中冻结的 24 个基础 case：3／12／64 KiB 各一组静态基线和五组 double、固定等待 0 ms 的更新间隔；再对 12／64 KiB 各增加 500 ms 间隔下的 double 等待 50／150 ms、fresh 等待 0 ms 对照。基础间隔依次为 500、250、100、50、16.6666667 ms，名字中的 `_16` 指最后这一档，不是精确 16 ms。

每例请求 8 秒。21 个动态 case 的测量均 success、duration completed、无次数截断、无预算截断、`end_reason=duration`；不存在停止上传后静态采样至结束的问题。持续资格只表明调度仍在运行，**不保证达到请求频率，更不保证末代画面正确**。3 KiB 的 6 例与 12 KiB 的 9 例均完成全量 identity／dependent 检查；64 KiB 的 9 例均为两个模式各 3 窗，各检查 12,288 个输出，`full_verification_requested=false`、`complete_payload_verified=false`。

基础间隔矩阵在同一载荷 dataset 上顺序运行并复用已有 bank；固定等待和 fresh 对照使用新的 dataset。它们是本次会话的单次短时样本，没有随机化运行顺序或多次重复，细小 FPS 差不能当作某协议的普遍收益。下表的上传数均等于发布数，Hz 为实际总次数／实际 elapsed；“末代全量”只适用于 3／12 KiB，“末代抽样”只适用于 64 KiB。

| 3 KiB，double，固定等待 0 ms | 上传数 | 实际上传／发布 Hz | `GetFps()` 均值 | 间隔 p95／p99／最大（ms） | `>33.3`／`>50 ms` | 冻结末代 |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| [static](../.runtime/geometry-atlas-study/b3/3k_static.updates.json) | — | — | 60.0692 | 18.1941／18.4743／19.9664 | 0／0 | 全量通过 |
| [500 ms](../.runtime/geometry-atlas-study/b3/3k_double0_500.updates.json) | 16 | 1.9966 | 60.0634 | 18.2574／18.7064／27.0943 | 0／0 | 全量通过 |
| [250 ms](../.runtime/geometry-atlas-study/b3/3k_double0_250.updates.json) | 32 | 3.9938 | 60.0775 | 18.1787／18.4383／18.7831 | 0／0 | 全量通过 |
| [100 ms](../.runtime/geometry-atlas-study/b3/3k_double0_100.updates.json) | 80 | 9.9820 | 60.0692 | 18.1517／18.6754／19.1984 | 0／0 | 全量通过 |
| [50 ms](../.runtime/geometry-atlas-study/b3/3k_double0_50.updates.json) | 160 | 19.9637 | 60.0692 | 18.1646／18.3981／23.9534 | 0／0 | 全量通过 |
| [16.6667 ms](../.runtime/geometry-atlas-study/b3/3k_double0_16.updates.json) | 480 | 59.8868 | 60.0692 | 18.2578／18.6319／19.1675 | 0／0 | 全量通过 |

3 KiB 在五档更新间隔下均未采到超过 33.3 ms 的间隔；最快一档的 480 次构造／提交全部完成，调度无 skipped／overrun。它证明本实现的 CPU 提交和渲染事件可以在这次样本中接近每帧一次。其 480 次 CPU 发布没有逐次 GPU fence，也没有运行中逐代截图；后文的同参数 live 抽查出现白帧，因此**不能将这行推荐为持续正确、可用的 60 Hz 共享数组**。

| 12 KiB，double，固定等待 0 ms | 上传数 | 实际上传／发布 Hz | `GetFps()` 均值 | 间隔 p95／p99／最大（ms） | `>33.3`／`>50 ms` | 冻结末代 |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| [static](../.runtime/geometry-atlas-study/b3/12k_static.updates.json) | — | — | 59.7218 | 19.5611／20.0383／37.1301 | 2／0 | 全量通过 |
| [500 ms](../.runtime/geometry-atlas-study/b3/12k_double0_500.updates.json) | 16 | 1.9979 | 59.4863 | 18.8428／20.9441／22.3844 | 0／0 | 全量通过 |
| [250 ms](../.runtime/geometry-atlas-study/b3/12k_double0_250.updates.json) | 32 | 3.9992 | 58.9651 | 19.6201／22.4592／26.1821 | 0／0 | 全量通过 |
| [100 ms](../.runtime/geometry-atlas-study/b3/12k_double0_100.updates.json) | 80 | 9.9848 | 57.6068 | 20.7522／22.7923／27.2080 | 0／0 | 全量通过 |
| [50 ms](../.runtime/geometry-atlas-study/b3/12k_double0_50.updates.json) | 160 | 19.9684 | 47.3849 | 32.3294／42.1975／47.0112 | 14／0 | 全量通过 |
| [16.6667 ms](../.runtime/geometry-atlas-study/b3/12k_double0_16.updates.json) | 273 | 34.0253 | 34.1210 | 39.0670／43.9750／50.0863 | 43／1 | 全量通过 |

12 KiB／500 ms 在本次样本中接近 60 FPS，100 ms 已降至约 57.6 FPS。50 ms 虽然调度仍达到约 20 Hz，却有 14 个超过 33.3 ms 的间隔；16.6667 ms 请求只能实现约 34.0 Hz，并累计 207 个 skipped／overrun。末代全字节正确不能代替平滑性结论。静态基线本身也有两个长帧，不把某个动态样本的细小改善归因为更新有益。

| 64 KiB，double，固定等待 0 ms | 上传数 | 实际上传／发布 Hz | `GetFps()` 均值 | 间隔 p95／p99／最大（ms） | `>33.3`／`>50 ms` | 冻结末代 |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| [static](../.runtime/geometry-atlas-study/b3/64k_static.updates.json) | — | — | 60.0775 | 18.2799／18.4837／18.8100 | 0／0 | 抽样通过 |
| [500 ms](../.runtime/geometry-atlas-study/b3/64k_double0_500.updates.json) | 16 | 1.9967 | 48.6578 | 20.1024／119.3500／134.1444 | 14／14 | 抽样通过 |
| [250 ms](../.runtime/geometry-atlas-study/b3/64k_double0_250.updates.json) | 32 | 3.9999 | 44.8093 | 77.0637／91.7632／96.6794 | 28／28 | 抽样通过 |
| [100 ms](../.runtime/geometry-atlas-study/b3/64k_double0_100.updates.json) | 80 | 9.9985 | 15.8110 | 98.3982／103.0741／109.3304 | 70／70 | **失败，匹配旧代** |
| [50 ms](../.runtime/geometry-atlas-study/b3/64k_double0_50.updates.json) | 91 | 11.3457 | 11.3537 | 97.4706／100.3289／104.4238 | 81／81 | **失败，匹配旧代** |
| [16.6667 ms](../.runtime/geometry-atlas-study/b3/64k_double0_16.updates.json) | 81 | 10.0279 | 10.1472 | 117.9010／126.2895／128.1083 | 70／70 | **失败，匹配旧代** |

64 KiB 静态接近 60 FPS，只说明常驻几何每帧 scatter 加三 pass 在本条件下能维持该帧率。每 500 ms 重建一次时，p95 仍只有 20.1024 ms，p99 却升至 119.3500 ms，14 个间隔超过 50 ms；仅看 p95 会漏掉这一组反复停顿。250 ms 同样不平滑。100 ms 的实际提交速率约 10 Hz，但渲染约 15.8 FPS 且最终画面失败；50／16.6667 ms 则分别出现 68／398 个 skipped／overrun。不得将实际提交次数写成画面已显示相同数量的新代。三个高负载失败例的 `GetFps()` 样本仅为 7／6／5，间隔样本为 105／81／70；这些均值与尾部统计只描述各自短时样本。

## b3 固定等待与 fresh 对照

以下均请求每 500 ms 更新，共完成 16 uploads／16 publishes，实际速率约 2 Hz；所有 12 KiB 末代全量通过，所有 64 KiB 末代仅抽样通过。等待位于构造／提交之后，不能把一段同步生成、编码或原生调用拆散到多个渲染事件。

| 载荷／协议 | 固定等待（ms） | `GetFps()` 均值 | 间隔 p99／最大（ms） | `>33.3`／`>50 ms` | total CPU 均值／p95／最大（ms） |
| --- | ---: | ---: | --- | ---: | --- |
| 12 KiB double | 0 | 59.4863 | 20.9441／22.3844 | 0／0 | 15.6037／16.6024／17.3628 |
| [12 KiB double](../.runtime/geometry-atlas-study/b3/12k_double50_500.updates.json) | 50 | 59.7916 | 18.6843／23.3859 | 0／0 | 14.6194／17.4037／19.4132 |
| [12 KiB double](../.runtime/geometry-atlas-study/b3/12k_double150_500.updates.json) | 150 | 59.5171 | 19.6321／26.6692 | 0／0 | 15.1188／17.0788／21.3625 |
| [12 KiB fresh](../.runtime/geometry-atlas-study/b3/12k_fresh0_500.updates.json) | 0 | 59.4886 | 22.4185／25.6729 | 0／0 | 15.5123／18.0641／19.1034 |
| 64 KiB double | 0 | 48.6578 | 119.3500／134.1444 | 14／14 | 100.9446／113.8569／121.2352 |
| [64 KiB double](../.runtime/geometry-atlas-study/b3/64k_double50_500.updates.json) | 50 | 52.3271 | 87.6710／104.0653 | 14／14 | 77.9376／90.9727／93.6087 |
| [64 KiB double](../.runtime/geometry-atlas-study/b3/64k_double150_500.updates.json) | 150 | 51.4982 | 89.4556／125.9917 | 14／14 | 83.7494／101.0752／116.2057 |
| [64 KiB fresh](../.runtime/geometry-atlas-study/b3/64k_fresh0_500.updates.json) | 0 | 50.7801 | 87.9653／207.0904 | 14／14 | 90.4020／164.6161／192.2891 |

12 KiB 四组都接近静态帧率；64 KiB 四组都保留了 14 个超过 50 ms 的间隔。固定等待 50／150 ms 与 fresh 的样本均不能支持“已经解决 64 KiB 单次更新停顿”。fresh 的最大间隔反而达到 207.0904 ms。这些单次结果不建立协议间稳定排序，也不检验 BBE 的完整自适应策略；更不能把 500 ms 下末代抽样通过推广到 100 ms 等更快间隔。

## b3 五组补充：稀疏更新与固定等待背压

五例均另做无宿主请求的 8 秒性能测量，调度成功、到达请求时长、无预算或次数截断。64 KiB 继续只验证末代两个模式各三个窗口；3／12 KiB 验证末代全量。它们包含在最终 `summary29.json` 中，展示时与基础 24 组分开。

| 补充 case | 请求间隔／固定等待（ms） | 上传数／实际 Hz | `GetFps()` 均值 | 间隔 p95／p99／最大（ms） | `>33.3`／`>50 ms` | total CPU 均值／p95／最大（ms） | 末代 |
| --- | --- | --- | ---: | --- | ---: | --- | --- |
| [64k_double0_1000](../.runtime/geometry-atlas-study/b3/64k_double0_1000.updates.json) | 1,000／0 | 8／0.9991 | 56.2001 | 18.4603／77.1745／85.5743 | 7／7 | 73.3995／76.9955／79.1839 | 抽样通过 |
| [64k_double0_2000](../.runtime/geometry-atlas-study/b3/64k_double0_2000.updates.json) | 2,000／0 | 4／0.4990 | 58.2521 | 18.2810／18.9574／88.1849 | 3／3 | 81.6059／82.2273／89.2948 | 抽样通过 |
| [64k_double0_5000](../.runtime/geometry-atlas-study/b3/64k_double0_5000.updates.json) | 5,000／0 | 2／0.2496 | 59.4848 | 18.2237／18.4622／85.8083 | 1／1 | 76.2241／73.2078／79.2404 | 抽样通过 |
| [3k_double50_50](../.runtime/geometry-atlas-study/b3/3k_double50_50.updates.json) | 50／50 | 82／10.2271 | 60.0327 | 18.3238／19.1321／26.2421 | 0／0 | 3.8807／5.2412／6.9263 | 全量通过 |
| [12k_double150_100](../.runtime/geometry-atlas-study/b3/12k_double150_100.updates.json) | 100／150 | 40／4.9961 | 57.3144 | 22.9012／30.0751／42.4870 | 4／0 | 19.6681／28.6654／35.8238 | 全量通过 |

64 KiB 降低更新频率后，FPS 均值逐渐接近静态值，超过 50 ms 的间隔也从 7 次降至 3 次、1 次，但单次最大间隔仍为约 86–88 ms。2,000／5,000 ms 的 p99 已接近普通帧间隔，仍掩盖各自的少量长帧；它们只能称为低占空比更新，不能据高 FPS 均值宣称每次更新平滑。5,000 ms 例在 8 秒内开头立即上传、约 5 秒再上传，共 2 次，因此记录的 `2/elapsed≈0.2496 Hz` 不是长期稳态的 0.2 Hz。其 CPU 只有两个样本，按既定分位数规则 p95 会取较小值并低于均值，不能当作可靠尾部估计。

3 KiB 的固定等待 50 ms 样例没有 overrun，却有 `pending_skips=skipped_updates=78`：下一到期槽遇到未发布 candidate 就被跳过。上传起点、发布间隔均值分别为 98.0171／97.9988 ms，因此请求每 50 ms 并未实现 20 Hz；实际为约 10.23 Hz。该代价与约 60 FPS、冻结末代全量通过同时记录，不能只保留后两项。它的运行中匹配对照见下文。

12 KiB 等待 150 ms、请求间隔 100 ms 时同样出现背压：40 uploads／40 publishes，同时有 40 个 pending skips、0 overruns；上传起点、发布间隔均值为 199.7435／199.5361 ms，实际约 5 Hz。其 CPU generation／encode／native 均值为 14.6307／3.4880／1.5494 ms，total 均值 19.6681 ms；27 个 FPS 样本的均值 57.3144，399 个间隔中有四个超过 33.3 ms。结合三张 live 匹配，可以称为所查运行中 query 正确、性能仍低于稳定 60 FPS。基础 12 KiB／500 ms 的约 59.5 FPS 仍没有同参数 live 对照，不能据帧率单独给出持续正确的强保证。

## b3 每次构造／提交的 CPU 分布

以下为基础 double、固定等待 0 ms 的全部 15 个动态 case。CPU 样本数等于上表上传数，包含预热期。native 仍为每次三个原生阶段相加后再求统计；total 不含发布等待及后续 actor uniform 更新。静态初始参考不混入这些分布，复用 dataset 的 initial snapshot 也不当作本 case 的一次新上传。

| 载荷／请求间隔（ms） | generation 均值 | encode 均值 | native 均值 | total 均值／p95／最大 |
| --- | ---: | ---: | ---: | --- |
| 3 KiB／500 | 2.8994 | 0.7668 | 0.5061 | 4.1722／5.4126／5.5418 |
| 3 KiB／250 | 2.9205 | 0.7159 | 0.4851 | 4.1214／4.9339／5.6279 |
| 3 KiB／100 | 2.5974 | 0.6497 | 0.3831 | 3.6303／4.4193／7.2218 |
| 3 KiB／50 | 2.7148 | 0.6681 | 0.4053 | 3.7882／4.7972／6.1206 |
| 3 KiB／16.6667 | 2.7461 | 0.6908 | 0.4107 | 3.8476／5.0454／8.2826 |
| 12 KiB／500 | 11.5087 | 2.7315 | 1.3635 | 15.6037／16.6024／17.3628 |
| 12 KiB／250 | 11.8763 | 2.9642 | 1.3821 | 16.2227／17.5637／24.6109 |
| 12 KiB／100 | 11.3705 | 2.6487 | 1.3027 | 15.3219／18.3630／21.0666 |
| 12 KiB／50 | 15.0536 | 3.6242 | 1.7919 | 20.4697／28.7369／38.4145 |
| 12 KiB／16.6667 | 15.7039 | 3.6325 | 1.5651 | 20.9015／29.6112／41.2077 |
| 64 KiB／500 | 74.5256 | 18.4663 | 7.9526 | 100.9446／113.8569／121.2352 |
| 64 KiB／250 | 57.3178 | 13.4525 | 4.5833 | 75.3536／86.6637／89.0380 |
| 64 KiB／100，末代失败 | 63.6566 | 14.1647 | 4.6435 | 82.4648／92.1107／99.7614 |
| 64 KiB／50，末代失败 | 61.8812 | 14.4804 | 4.8039 | 81.1655／89.2399／93.9876 |
| 64 KiB／16.6667，末代失败 | 68.8714 | 15.6880 | 7.2080 | 91.7674／107.5573／121.8901 |

表中所有成本单位均为 ms。64 KiB 基础样例的 generation 加 encode 约占 total 均值的九成以上，表明游戏 Python 构造与编码是本实现里可见的大项；原生调用还未返回 GPU 完成，不能因此排除其他 GPU 或驱动工作。不同运行中同尺寸 CPU 成本有波动，不应按某行均值的倒数反推最大可用更新 Hz。固定发布等待也不会消除这些已经发生的同步 CPU 时间。

## b3 64 KiB 的旧代匹配失败

三个更快间隔的 case 均以 `status=failed`、`passed=false` 保留。每例 identity 的三个源窗口与 dependent 的三个 query 窗口都被判为 `stale_generation`，并在该例六张截图中精确匹配到同一个已提交旧代。分类对每个候选 generation 分别重算两次 dependent 地址、检查完整 3×3 patch，不靠偏移搜索或只更换 generation 标签。

| double、固定等待 0 ms | CPU 提交的最终 generation | 六窗匹配的旧 generation | identity 失败 cells／12,288 | dependent 失败 cells／12,288 |
| --- | ---: | ---: | ---: | ---: |
| 100 ms | 129 | 123 | 12,248 | 12,239 |
| 50 ms | 220 | 134 | 12,247 | 12,246 |
| 16.6667 ms | 301 | 269 | 12,240 | 12,227 |

这比“当前代 oracle 没通过”更具体：在所查窗口中，最终画面确实对应较早已提交的 payload。它没有证明中间每代何时可见，也没有 GPU fence、原生缓存回读或驱动内部状态；不能由 generation 差直接计算精确延迟，更不能仅凭名称复用就断言某一项 C++ cache 机制。500／250 ms 的抽样通过和三项失败应分别保存；运行中抽查见下节，更多等待／更新间隔及新模板冷启动的后续 b5／b7c 结果见下文，仍不代表长期每帧新鲜度。

## b3／b5 运行中抽查：白帧与固定等待后匹配

六组 live 诊断各请求连续运行 30 秒，均为 double，在运行中执行三次“before receipt → 原生 WGC capture → after receipt”。receipt 显示这段过程仍在提交新 generation，但它不能将某张捕获图原子绑定到 before 或 after 的某个 generation。宿主 IPC 与捕获会扰动调度，所以六组都明确标记 `performance_excluded=true`，其 FPS、间隔、CPU 或实际 Hz **全部不列为性能结果**。无干扰的 8 秒性能样本与这六组 live 诊断是分开的运行。

| live 原始记录 | 载荷／请求间隔／等待 | 模式／查询范围 | 运行中原生图 | 分类 | 与独立性能样本的关系 |
| --- | --- | --- | ---: | --- | --- |
| [live3k_16](../.runtime/geometry-atlas-study/b3/live3k_16.live.json) | 3 KiB／16.6667／0 ms | dependent，query 0–3,071 | 3 张，全部输出白色 | 3／3 unmatched，无候选匹配 | 正式样本约 60 FPS、冻结末代全量通过；仍不能证明运行中可用 |
| [live12k_50](../.runtime/geometry-atlas-study/b3/live12k_50.live.json) | 12 KiB／50／0 ms | dependent，query 0–4,095 | 3 张，全部输出白色 | 3／3 unmatched，无候选匹配 | 正式样本约 47.38 FPS、冻结末代全量通过；运行中首窗失败 |
| [live64k_100](../.runtime/geometry-atlas-study/b3/live64k_100.live.json) | 64 KiB／100／0 ms | dependent，query 0–4,095 | 3 张，全部输出白色 | 3／3 unmatched，无候选匹配 | 正式样本约 15.81 FPS、冻结末代匹配旧代；live 白帧另列 |
| [live3k_delay50_50](../.runtime/geometry-atlas-study/b3/live3k_delay50_50.live.json) | 3 KiB／50／50 ms | dependent，query 0–3,071 | 3 张，均匹配提交候选 | 3／3 matched，完整 query patch 通过 | 独立性能样本约 60.03 FPS、实际 10.23 Hz，末代全量通过 |
| [live12k_delay150_100](../.runtime/geometry-atlas-study/b3/live12k_delay150_100.live.json) | 12 KiB／100／150 ms | dependent，query 0–4,095 | 3 张，均匹配提交候选 | 3／3 matched，仅此首窗 | 独立样本约 57.31 FPS、实际 5.00 Hz；live 的 FPS 排除 |
| [live64k_delay150_100](../.runtime/geometry-atlas-study/b5/live64k_delay150_100.live.json) | 64 KiB／100／150 ms | dependent，query 0–4,095 | 3 张，均匹配提交候选 | 3／3 matched，仅此首窗 | b5 独立样本约 45.70 FPS、实际 3.35 Hz；live 的 FPS 排除 |

前三组的 9 张白帧均为原生 720×1080 RGB PNG。本报告另用 PNG 像素逐通道扫描输出矩形 `[left=0,top=64,right=720,bottom=1064]`，每张 **720,000 个像素 RGB 全为 `(255,255,255)`**；矩形外仍有场景色，不能称整张 PNG 纯白。该检查没有偏移、缩放或更改图像。分类记录里的 8 个 fingerprint 中心也全部为白色，记录到的候选均未通过预筛，`matching_payload_count=0`、`full_query_patch_verifications=0`。这表示候选已被 fingerprint 差异拒绝，没有执行任何候选的全窗口 patch 比较，不能写成“已对每个候选完成全窗口验证”。fingerprint 的 RGBA 表示中 alpha=255 不证明 RGB PNG 保存了原生场景 alpha。

后三组共 9 张图均先通过 8 点 fingerprint，再对一个匹配 payload 的整个 query 做 3×3 patch 检查，误差为零。匹配 seed／generation 都能对应终态记录的真实提交 candidate，没有用 before receipt 的 generation 强行生成唯一期望。各自捕获的 before／画面匹配／after generation 如下：

| live 协议 | 第 1 张 | 第 2 张 | 第 3 张 | 每张验证范围 |
| --- | --- | --- | --- | --- |
| 3 KiB，间隔 50 ms／等待 50 ms | 110 → **119** → 130 | 168 → **186** → 194 | 222 → **234** → 242 | 全 3,072 个 dependent query、27,648 个 patch 像素 |
| 12 KiB，间隔 100 ms／等待 150 ms | 15 → **19** → 24 | 37 → **42** → 47 | 60 → **64** → 68 | 首 4,096 个 dependent query、36,864 个 patch 像素 |
| 64 KiB，间隔 100 ms／等待 150 ms | 37 → **41** → 45 | 54 → **58** → 62 | 71 → **75** → 79 | 首 4,096 个 dependent query、36,864 个 patch 像素 |

九张图都匹配 before／after 之间某个已提交代，支持运行期间确实有有效 payload 到达 consumer。12／64 KiB 都只检查首窗，不能当成整个载荷通过。它们不证明整段每代都可见，dependent 的全 query 也不等于覆盖全部第二源地址。分类的 `resource_identity_verified=false` 仍保留：图像验证的是 payload 内容，无法单凭图像独立确认原生 geometry 的对象身份或 GPU 完成时点。这里没有精确可见延迟，也没有对全部渲染帧的验证。

live 的 `unmatched` 表示所查画面未匹配记录到的已提交候选，不能替换成 stale-generation 成功匹配；也不能从九张白帧推导整段每帧都白或所有参数均失败。固定等待后九张匹配图是有用的正向对照，但参数和实际更新频率均有改变，不能外推为任意载荷／间隔的通用修复。停止后等待并得到正确末代，也不能抹去运行中白帧。当前必须分别保留“无宿主干扰的性能”“冻结末代是否正确”“运行中抽查是否有有效载荷”三项结论。

## b5 旧模板冷启动的 64 KiB 等待对照

b5 重新冷启动旧四分之一方块模板版本，先创建 512 KiB 几何并做下文所述静态／冻结参数诊断，再为三个 64 KiB case 各开启新 dataset／epoch。旧 512 KiB writer 已在 dataset 切换时隐藏，但会话保留该几何名称且没有原生资源回收证明。这与 b3 的运行历史不同，**b5 单列，不把两批 FPS 差归因为等待参数本身**。[b5 summary4.json](../.runtime/geometry-atlas-study/b5/summary4.json) 中三组动态测量均成功、持续至约 8 秒、无预算或次数截断，末代仍只查两个模式各三个窗口。

| b5 64 KiB、请求间隔均 100 ms | 上传数／实际 Hz | `GetFps()` 均值 | 间隔 p95／p99／最大（ms） | `>33.3`／`>50 ms` | pending skips／overruns | total CPU 均值／p95／最大（ms） | 冻结末代 |
| --- | --- | ---: | --- | ---: | --- | --- | --- |
| [double，等待 0 ms](../.runtime/geometry-atlas-study/b5/64k_double0_100.updates.json) | 65／8.0659 | 8.3991 | 169.4835／218.6063／222.3842 | 60／60 | 0／15 | 114.1900／165.4447／207.2633 | **失败，六窗均匹配旧 generation 4；CPU 最终为 66** |
| [double，等待 50 ms](../.runtime/geometry-atlas-study/b5/64k_double50_100.updates.json) | 40／4.9972 | 35.7879 | 100.9669／119.6158／127.7732 | 35／35 | 40／0 | 89.1634／111.3704／118.8109 | 仅抽样通过 |
| [double，等待 150 ms](../.runtime/geometry-atlas-study/b5/64k_double150_100.updates.json) | 27／3.3521 | 45.6981 | 84.4481／96.8711／125.6063 | 24／24 | 53／0 | 84.5750／94.3423／116.2835 | 仅抽样通过 |

三组 uploads 均等于 publishes。相应上传起点间隔均值为 123.9015／199.7061／300.0463 ms：固定等待显著改变了实际提交节奏，后两组并没有维持请求的 10 Hz。FPS 上升与更低更新频率、同步 CPU 成本波动及不同 epoch 同时出现，不能称为“纯等待使同一上传负载更快”。后两组也都有大量超过 50 ms 的间隔，没有建立平滑 60 FPS。无等待组只有 4 个 `GetFps()` 样本、60 个间隔，等待 50／150 ms 分别为 17／22 个 FPS 样本和 254／324 个间隔。

会话计数在三个 case 结束时依次为 3／5／7 个名称、655,360／786,432／917,504 个 record，均保留 `native_reclamation_verified=false`；这些不是 VRAM 测量。无等待组的末代匹配旧代再次说明同名双 bank 立即发布在此条件下不可靠。等待后末代抽样通过没有验证每个中间代；上述另一次 150 ms 等待的 live 已得到三张首窗匹配图，其 FPS 等性能全部排除，45.6981 FPS 仍只取自独立 `.updates.json`。

## b2 512 KiB 失败与有限 center 诊断

失败 case 的 generation 为 1，geometry 为 `pmanim_geometry_atlas_epoch4_version20`，build serial 20，center `(0.5,0.5,0.5)`。identity 与 dependent 各检查 4,718,592 个输出 patch 像素，最大通道误差均为 255。两组 128 个窗口全部失败；原始 case 以 `status=failed`、`passed=false` 保存，不能因为测量阶段完成而改写为成功。

| 验证 | 失败分布 | 能确认的规律 |
| --- | --- | --- |
| identity | 510 failed cells；126 窗各 4 错，2 窗各 3 错 | 512 个 `source_index % 1024 == 1023` 索引中，511 个 observed=255；其中只有 470,015 的 expected 本来为 255。最后槽 524,287 的 expected=observed=154。因此 510 错＝511 个白值减去 1 个自然 255 |
| dependent | 1,037 failed cells；每窗 4–14 错 | 可分成互不重叠的 530 个 `source_index % 1024 == 1023` 与 507 个窗口内 `ordinal % 1024 == 414`；两组覆盖全部错误 |

全部 256 个窗口的 classification 为 `unmatched`，`matched_generations=[]`。错误具有索引规律，但没有匹配到某个已提交旧代；控制项的报错文字 `Final gather or previous-generation rejection failed` 不能直接解释成已经证明旧 generation 残留。最后槽与前 511 个行末索引表现不同，为“有后继记录时的边界冲突”提供了诊断线索，仍未证实根因。

随后保持同一份 512 KiB geometry，仅改变 center.z。每次只检查 identity 首窗 `query=[0,4096,0,0]`，x／y 均保持 0.5：

| center.z | 首 4,096 cells 错误数 | 最大误差 | 该窗口结果 |
| ---: | ---: | ---: | --- |
| 0.499 | 2,727 | 255 | 失败 |
| 0.501 | 4 | 196 | 失败 |
| 0.49 | 0 | 0 | 通过 |
| 0.51 | 4 | 196 | 失败 |
| 0.25 | 0 | 0 | 通过 |
| 0.75 | 8 | 196 | 失败 |
| 0.5 | 4 | 196 | 失败 |

对应证据为 `cap512k_center_0` 至 `cap512k_center_6` 的 `*_center.state.json` 和 `*_identity.verify.json`。这说明 center 变化会改变首窗结果，两个设置可使首窗精确通过；没有对应全量 identity、全量 dependent 或动态回归，**不能称为 512 KiB 已修复**。

b2 使用旧的 XZ 四分之一方块平面模板。原生输入量化或边界解码是后续实验假设；宿主 float／half 模拟没有重现原生错误分布，不能断言引擎使用 half 打包，也不能将失败写成硬件 512 KiB 上限。较安全的半格模板的 b4 失败校准及 b7c 冷启动结果另见下文，不回填为 b2 的已验证实现。

## b5 512 KiB 冷启动重现与同几何参数诊断

[original512_sample](../.runtime/geometry-atlas-study/b5/original512_sample.updates.json) 在旧模板新一次冷启动中重新创建 524,288 B，seed 54,321、generation 1、geometry `pmanim_geometry_atlas_epoch1_version1`、build serial 1。这次仅取首／中／尾三个窗口，identity 共 12,288 源 slot 中 11 错，dependent 共 12,288 query 中 23 错；二者 classification 均 unmatched。静态测量均值仍为 60.0692 FPS，p99／最大间隔为 18.2691／18.6941 ms，无超过 33.3 ms 的间隔，**高静态 FPS 仍不能抵消像素失败**。初次同步构造／提交为 662.3115 ms，属于一次冷加载参考。

随后 [512-frozen-diagnostics.json](../.runtime/geometry-atlas-study/b5/512-frozen-diagnostics.json) 记录 11 个控制、21 张图，`geometry_rebuilt_between_variants=false`。所有 variant 保持同一 seed、generation、geometry 名称与 serial，不重新 Combine 或上传，仅改变指定 uniform／采样路径。三窗起点为 0／260,096／520,192；未列三窗的 variant 仅检查首 4,096 个 identity 输出。

| 同几何控制 | 实际改变 | identity 首／中／尾失败 cells | 能支持的范围 |
| --- | --- | --- | --- |
| baseline | 512 列，left=8，center.z=0.5，共享复制纹理 | 4／4／3 | 重现原静态三个窗口的行末错误 |
| direct | consumer 改读原始 `TEXTURE_1` | 4／未查／未查 | 首窗同样错误，没有消除所见四处异常 |
| consumer X −0.2／+0.2 px | 仅 consumer 采样位置为 left=7.8／8.2；源仍为整数 baseline | 各 4／未查／未查 | 两个微偏移均保留首窗相同四错 |
| consumer Y −0.2／+0.2 px | 仅 consumer 采样位置为 top=31.8／32.2；源仍为整数 baseline | 各 4／未查／未查 | 两个微偏移均保留首窗相同四错 |
| source left=9 | source 与 consumer 同步平移 1 px | 4／未查／未查 | 平移未消除首窗四错 |
| columns=511 | source 与 consumer 同步改列数 | 4／7／8 | 错误位置与分布改变；未通过 |
| columns=640 | source 与 consumer 同步改列数 | 3／7／7 | 错误位置与分布改变；未通过 |
| center.z=0.49 | 恢复 512 列／left=8，只改 center.z | **0／0／0** | 12,288 个 identity 源 slot 抽样通过 |
| restore center.z=0.5 | 恢复 baseline uniform | **4／4／3** | 同一几何恢复原来的三窗错误 |

UV 微偏移明确标为诊断 consumer uniform，不能称为源 geometry 移动或通过图像偏移搜索找对齐。direct／copy、四种 ±0.2 px 微偏移与 left=9 在首窗都保留同样四处错误；列数变化则改变错误位置。列数 511／640 的三窗分别共 19／17 错，其中各有 7 个非白错误的 observed 值都为 154，与载荷最后槽的值相同；其余错误为 observed=255。这是对几何解码／覆盖问题的进一步线索，仍不构成底层原因或某种原生数据格式的证明。

center.z=0.49 的正向三窗与恢复 0.5 的反向三窗，支持这一参数能控制本次抽样错误。它只检查 identity 的 12,288／524,288 个源 slot，即 2.34375%，没有相同参数的完整 identity、完整 dependent、动态更新或新模板冷启动验证，**不能将 b2 的完整失败改成 512 KiB 已修复**。b5 是旧模板冷启动重现及冻结诊断；b4 半格模板是另一版本，默认中心验证失败；b7c 校准后的结果单列，不能混写。

## 512 KiB 失败的原因定位与证据边界

直接图像证据支持将异常收窄到 **consumer 采样之前，旧四分之一模板输入／逐顶点 cell-record 恢复与 atlas 行 wrap／局部裁剪的组合**：同几何下 direct／copy 与 consumer ±0.2 px 均保留首窗错误，整体平移 1 px 也不消失；改变 atlas 列数会改变错误位置，改变 center.z 可使三窗通过，恢复后原错误返回。这是当前定位，不是对底层原生顶点格式、驱动或编译器某一实现的定论。

### 冻结图像上的白洞规律与末槽值覆盖

[512-derived-scatter-diagnosis.json](../.runtime/geometry-atlas-study/b5/512-derived-scatter-diagnosis.json) 复用 baseline、columns=511、columns=640 各首／中／尾三个 identity 窗口，共九窗；所有回执的几何名称、build serial 1、native attempt serial 1、seed 54,321、generation 1、524,288 slots 及单次上传历史相同。这是已有图像的派生分析，没有重新上传，也没有增加容量测量或原生顶点测量。

九窗合计 47 个失败观测，包括 33 个 observed=255 白洞与 14 个 observed=154 非白错误。白洞可由以下谓词精确描述：

```text
index % atlas_columns == atlas_columns - 1
AND index % 1024 >= 513
排除 index == 524287 以及 expected == 255
```

在这九个已查窗口内，预测的白洞集合与实际白洞集合完全相同：33 个白洞全部命中，且没有多预测或漏预测。末槽排除确实被这些窗口覆盖；本九窗没有谓词命中且 expected 本为 255 的自然白值样本，不能将这一排除项计作额外验证。b2 全扫描中独立确认过自然 255，仍保留为前述完整失败分布的证据。

14 个非白错误分别来自 columns=511／640 的 7／7 个源格，observed 全为 **154**，等于源最后槽 524,287 的 byte。派生模型将“最后 record 预计有效的 atlas 上边缘”与旧 shader 的无效 clip 位置 `gl_Position=(2,2,0,1)` 相连；后者在 720×1080 viewport 对应 `C=(1080,-540)`。设最后槽预计有效边为 `A=(left+last_index%columns, top+floor(last_index/columns))`、`B=A+(1,0)`，得到：

| atlas 列数 | 推导点 A | 推导点 B | 推导无效点 C |
| ---: | --- | --- | --- |
| 512 | `(519,1055)` | `(520,1055)` | `(1080,-540)` |
| 511 | `(9,1058)` | `(10,1058)` | `(1080,-540)` |
| 640 | `(135,851)` | `(136,851)` | `(1080,-540)` |

按这一理想窄三角带模型，**14／14 个错误源像素 footprint 与三角形相交，11／14 个像素中心在内部**；另外三个中心稍在外侧，最大水平外偏为 **0.236161 px**。这与末 record 局部裁剪后向外覆盖的解释相容，也允许后续 primitive 遮住部分轨迹，但没有精确重建全部光栅化过程。

**上述位置均由 shader 公式、atlas 布局和截图坐标推导，不是原生 POSITION／索引／顶点缓冲捕获。** 三个中心仍在理想三角形之外，sample location、属性精度及具体裁剪行为尚未取得原生状态证据，不能把 footprint 相交写成已捕获的真实原生三角形。

### b6 同几何 A→B→A 解码对照

[decoder-aba-results.json](../.runtime/geometry-atlas-study/b6/decoder-aba-results.json) 在 **b6 本批次内部的同一份旧模板几何**上，依次选择原 sourceQuarter 解码 A、数学等价改写 B、恢复 A；三阶段间 `native_geometry_rebuilt=false`。b6 与 b5 的名称／serial 虽重置为相同值，上传历史的构建时间不同，不能跨批视为同一个原生对象。每阶段各取 identity／dependent 首、中、尾三窗，合计 18 张原生图；dependent 仍为 mode 2、salt 37、salt2 91，每窗 4,096 个输出。

| 阶段 | 解码 selector／`EXTRA_ACTOR_UNIFORM4` getter 读回 | identity 首／中／尾失败 cells | dependent 首／中／尾失败 cells |
| --- | --- | --- | --- |
| a_first | A=0；`[1,0,0,0]` | 4／4／3 | 10／7／6 |
| b_equivalent | B=1；`[1,0,1,0]` | 4／4／3 | 10／7／6 |
| a_restore | A=0；`[1,0,0,0]` | 4／4／3 | 10／7／6 |

逐 query 对照验证文件，A／B／A 的 `observed_payload_sha256` 和完整 `failures` 数组均完全相同，不只错误总数相同。getter 的 `.z` 确认 B 选择值读回为 1、随后恢复为 0；**getter 不是 GPU 顶点状态捕获，也不证明实际 GPU 分支执行轨迹**。这次等价解码改写在所查样本中没有改变或修复错误，不能据此宣称已定位某个编译表达式 bug，也不能排除全部解码／编译器机制。

目前缺少原生 attribute 格式、实际逐顶点 shader 输入／输出及 sample location 的直接捕获，因此不能断言 half 打包、某项 C++ cache 或特定编译器变换就是根因。较大间距的半格模板在后续 b4／b7c 中验证；工作区新源码和离线一致性证明不能替代冷启动原生验证。本节上述直接诊断均属于旧四分之一模板，b4／b7c 新模板结果另列如下。

## 半格模板、原生坐标校准与 b7c 冷启动验证

旧模板在高坐标处采用四分之一步长。新 atlas 专用模板改为 JSON `origin=[0,y,0]`、`size=[8,0,8]`，scatter 使用 `cell=floor(source.xz+.25)`、`corner=2*(source.xz-cell)`。理想输入下，同一 record 的所有顶点恢复出同一个 cell，避免 record 边界被拆成有效与无效顶点；半格端点也能在本探针域内承受 binary16 输入量化。这是保守输入设计，**不代表已经证明引擎采用 binary16**。

b4 的首次原生测试否定了原来的对称坐标假设：3 KiB、generation 81、默认 center `(0.5,0.5,0.5)` 的完整 identity 有 **2,791／3,072** 个错误，dependent 有 **3,040／3,072** 个错误。同一份冻结几何不重建，只将 center 改为 `(1,0.5,0.5)`，完整 identity 变为 **0 错误**；随后恢复旧中心又重现 2,791 错误。`(1,.5,1)` 仍有 287 错误，`(.75,.5,.5)` 有 144 错误，不能把任意偏移都算作修复。

该结果支持为当前模板校准 X 偏移，但没有直接捕获 native POSITION。离线压力输入因此改用明确的推断端点集合 `X={i-1,i-.5}`、`Z={i-.5,i}` 与固定校准中心 `(1,.5,.5)`；端点顺序、JSON→native X 变换和真实 attribute 格式仍未知。`runtime.py` 的初始化、候选 uniform 与发布重置均使用同一 `ATLAS_CENTER`；诊断用 `set_center` 保留。它不修改 packet 探针模型或产品资源。

b7c 从独立的 `project-b7` 冷启动，固定 720×1080、后台 noactivation、60 FPS 配置。第一次 b7 启动在选择客户端路径时被拒绝，没有启动测试游戏；指定与此前一致的 3.10 executable 后建立 b7c 新证据目录。b7c 开始时机器上另有独立 MC 进程 PID 35704，本任务未操作该实例，后续观察到其已退出；未连续记录它的生命周期，**本批性能不作为独占机器基准，也不将与 b3 的差异单独归因于模板修正**。

| b7c case | 固定等待／请求间隔 | 末代 identity／dependent | 运行中三帧 | SDK FPS 均值 | 实际提交 Hz |
| --- | --- | --- | --- | ---: | ---: |
| 3 KiB double | 50／100 ms | 两模式全量通过，各 3,072 queries | 三帧 matched，各 3,072 dependent queries | 59.1800 | 9.9917 |
| 12 KiB double | 150／500 ms | 两模式全量通过，各 12,288 queries | 三帧 matched，各首 4,096 dependent queries | 56.8218 | 2.0000 |
| 512 KiB static sample | 无动态更新 | 两模式首／中／尾通过，各 12,288 queries | 未测动态 | 59.9963 | — |
| 512 KiB static full | 无动态更新、复用上一行同一冻结载荷 | 两模式各 524,288 queries、128 窗全过 | 未测动态 | 60.0609 | — |

512 KiB full 的 identity 完整载荷 SHA-256 为 `dab47722209710719601ce02869f4e26b4c8d671b868e06ae0f63c0e325b0eb6`，观测值与独立整数 oracle 一致；dependent 查询输出 SHA 为 `033e7b79b31ed8c23d59c51127aa73ea0f1816d0107e326ae066fccd2c072adf`。两模式各检查 4,718,592 个 patch 像素，合计 9,437,184 个，失败 cells 与最大通道误差均为 0。跨 256 窗只改 query，seed、generation、geometry name／serial、upload history、center 和源布局不变，没有拆批上传来替换源数据。

来源控制另取八张图：关闭 writer 首 4,096 identity 查询不再匹配；同一几何恢复后精确通过。随后上传 512 KiB generation 2，首／中／尾 identity 和 dependent 六窗各自精确通过，每窗同图都拒绝实际 generation 1 oracle。generation 2 的每模式只查 12,288 queries，所以明确保持 `gen2_full_capacity_verified=false`。这些控制建立当前数据来自几何 writer，不能代替持续逐帧新鲜度。

3 KiB 的 p99／最大 render-event 间隔为 21.2948／26.8103 ms，`>33.3 ms=0`；12 KiB 为 47.0178／48.4644 ms，`>33.3 ms=14`、`>50 ms=0`。两组无 max-updates／预算截断，性能采样期无宿主请求；运行中捕获为另外的 30 秒诊断，全部性能排除。3 KiB 可支持本机约 10 Hz 的短时平滑候选；12 KiB 在此批不能声称稳定 60 FPS。六张 live 匹配只建立所查帧的实际 payload 来源，不证明每个 generation、每个渲染帧或长期运行都正确。

本批 3 KiB／12 KiB 的同步 CPU total 均值为 9.2580／35.1650 ms，其中 synthetic byte generation 占 6.7090／26.1507 ms，encode 为 1.7090／6.5664 ms，native 为约 0.8399／2.4479 ms。512 KiB 单次 total 为 1,788.5838 ms，拆分为 generation 1,303.0514、encode 338.8325、deserialize 0.0303、Combine 146.2938、attach 0.3758 ms。**synthetic generation 是测试数据构造，不等于已有 bytes 的传输成本；total 也不包含 GPU 完成等待。** 大载荷更适合初始化或低频更新，冻结后约 60 FPS 不意味着可以每帧重传。

b7c 保存证据的独立离线重放已完成：4／4 case、270 个冻结 query 窗（其中 full512 为 256 窗）、2／2 live／六帧、来源控制八窗全部与原记录一致；2,172 个唯一原始文件声明 SHA 全匹配，审计后重读未变。原审计 SHA 为 `91031247c4544c99f440d24206a99e0b175775cb8145659a9fe9e4bad4842950`，小型 [审计摘要](evidence/geometry-atlas/streaming/independent-b7c-replay-summary.json) 保留完整来源。它是使用同一整数 oracle 的独立执行重放，`independent_second_oracle=false`，不是第二套像素算法。

离线回归使用 `.venv-reference/Scripts/python.exe -B -X utf8 -m unittest discover -s tests -p 'test_geometry*.py'`，**137 项全部通过**，包含 actual shader desktop OpenGL 及 GLES 100／300、校准端点的 float32／binary16 压力输入、调度、证据失败保存和重新分类。runtime／scheduler 另通过 Python 2.7 编译检查。native 生成包的 scoped MCP review 无解析失败，保留 query 参数较多与单次上传函数较长的结构性建议；这些测试和审查不能替代实机全量图像结果。

## 资源预算、适用范围与复现入口

当前扩大的探针输入保护为 `MAX_BYTES=524288`，会话主动预算最多 256 个 geometry 名称、2,097,152 个逻辑 record。这些是探针约束，不是 VRAM、实际原生分配量或引擎容量上限。b2 动态 3 KiB 最终占用两个名称、6,144 个计数 record；随后的 128／256／512 KiB 新名称使会话累计达到 5 个名称、923,648 个计数 record。bank 名称复用和预算计数稳定没有证明原生内存已回收或可以无限更新。

源码入口为 [runtime.py](../tools/geometry_atlas_probe/runtime.py)、[update_scheduler.py](../tools/geometry_atlas_probe/update_scheduler.py)、[run_update_case.py](../tools/geometry_atlas_probe/run_update_case.py)、[summarize_updates.py](../tools/geometry_atlas_probe/summarize_updates.py)和 [verify_capture.py](../tools/geometry_atlas_probe/verify_capture.py)。调度、统计与失败保存的离线测试独立于原生 PNG 证据；之后的源码修正或模板变更需要新的冻结批次，不能仅因同一工作区代码已更新就声称 b2／b3／b5 已覆盖。

在已按 [主报告流程](GEOMETRY_ATLAS_RESEARCH.md#实现与复现)冷启动、调整为原生 720×1080 的独占 owner 项目上，使用新的 evidence 目录和 case 名称运行，例如：

```powershell
python -B tools/geometry_atlas_probe/run_update_case.py --project .runtime/geometry-atlas-study/project-repro --evidence .runtime/geometry-atlas-study/repro-stream --name double3k100 --bytes 3072 --policy double --interval-ms 100 --publish-delay-ms 50 --seconds 8
python -B tools/geometry_atlas_probe/run_update_case.py --project .runtime/geometry-atlas-study/project-repro --evidence .runtime/geometry-atlas-study/repro-stream --name static512k_full --bytes 524288 --policy fresh --static --full --seconds 8
python -B tools/geometry_atlas_probe/summarize_updates.py --evidence .runtime/geometry-atlas-study/repro-stream --json .runtime/geometry-atlas-study/repro-stream/summary.json
```

参数和默认值应以对应冻结版本的 `--help` 为准；重现新版模板会产生新批次，不能替换 b2 旧模板证据。原始证据禁止覆盖，失败也应保留。所有实机操作必须继续后台静默、保持 noactivation 与 60 FPS，后台保护失效即停止，不以激活窗口补完。

本报告验证显式连接的后续 **fragment consumer** 能在当前设备上从 512 KiB 冻结数组按索引取数，并完成依赖取数；512 KiB 原失败已通过新版冷启动全扫修正。3 KiB 约 10 Hz 的等待＋背压组合有有限平滑性与 live 匹配证据；12／64 KiB 的同步构造和编码成本仍影响帧率，无等待还会出现白帧／旧代。没有 GPU completion fence，不能将 native API 或 uniform getter 返回等同于 GPU 可见；没有 vertex 随机取数、游戏内 GPU→Python 回读、跨帧持久 GPU 状态、任意 UI 自动共享、移动端或长期每帧正确性验证。

最终 owned 实例已恢复 HUD／准星并停止，未操作其他会话实例。
