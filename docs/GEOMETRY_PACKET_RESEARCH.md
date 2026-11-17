# 运行时 Python → 原生建筑几何 → shader 数据传输研究

本文保留的是“每个 primitive 只能读取自身记录”的几何通路历史基线。当前已经验证的跨记录索引方案是“几何写入场景 alpha → 复制纹理 → fragment consumer 按索引读取”，请以[几何数据纹理研究](GEOMETRY_ATLAS_RESEARCH.md)为准；本文的旧限制不适用于该新增 pipeline。

编码优化与高频同名更新的后续证据见[compact8 与更新研究](GEOMETRY_PACKET_COMPACT_RESEARCH.md)。


本探针将游戏 Python 运行时生成的字节写入 BlockPalette 的方块坐标，调用 `CombineBlockPaletteToGeometry` 生成原生网格，再由自定义 vertex shader 从 `POSITION` 恢复字节。载荷由网格承载；透明 Image 设置的 `CURRENT_COLOR` 只携带查询窗口和布局参数。该通路沿用 BBE 的建筑几何与 PaperDoll 渲染能力，探针运行在独立生成的资源包和行为包中。

仓库内保留[紧凑结果摘要](evidence/geometry-packets/summary.json)、[v4 独立复核](evidence/geometry-packets/independent-verification-v4.json)、[v5 独立复核](evidence/geometry-packets/independent-verification-v5.json)及[冻结／更新对照](evidence/geometry-packets/freeze-update-controls.json)。完整原生截图、状态与命令保留在 `.runtime/geometry-packet-study/`。独立复核保留源失败案例，因此总 `passed=false`；所有源成功案例的 `completed_cases_recheck_passed=true`。

v4 的 3 KiB 静态与逐渲染事件全量重建均完成了最后一代的全字节验证，平均 `GetFps()` 分别约 60.07 与 59.30；12 KiB 静态约 60.06 且完整通过，动态运行却读到了旧代数据，不能作为成功的动态传输档位。v5 已补充“CPU 字节变化但网格冻结”的原生对照，证明改变 CPU 副本本身不会改变 shader 输出。最终 v5 静态扫描中，64 KiB 与 256 KiB 均完成全窗口、全 slot 的零容差验证；1 MiB 在首个窗口失败，不能把保护上限或失败运行当成容量结论。

这里的“字节”指逻辑载荷：一个 slot 表示一个 0–255 整数，实际需要一个自定义方块面及其原生顶点、索引和引擎资源。总载荷字节数不能当作网格显存占用，也不能当作原生顶点属性的字节数。

性能结果与最大完整通过档位应以本轮最终的 case、逐窗截图及独立复核摘要为准。生成器中的 `MAX_BYTES=1048576` 是实验保护值，不能据此宣称 1 MiB 已经测试或是引擎上限。

## 已完成的 v4/v5 档位与旧代失败

以下均为 8 秒基准、预热 1 秒，表中 FPS 为 `GetFps()` 样本平均值。v4 无探针画面的基线约为 60.0775 FPS；约 59–60 FPS 是接近配置上限的实测范围，不把某个 59.x 值视为刚性容量边界。

| 逻辑载荷 | 模式 | 平均 FPS | 最后一代原生像素验证 | 原始 case |
| --- | --- | ---: | --- | --- |
| 3,072 B／3 KiB | 静态驻留，仅改 query | 60.0718 | 全 3,072 字节通过 | [`bytes3072_static`](../.runtime/geometry-packet-study/v4/bytes3072_static.case.json) |
| 3,072 B／3 KiB | 每个渲染事件全量重建 | 59.2998 | 全 3,072 字节通过 | [`bytes3072_dynamic`](../.runtime/geometry-packet-study/v4/bytes3072_dynamic.case.json) |
| 12,288 B／12 KiB | 静态驻留，仅改 query | 60.0551 | 全 12,288 字节通过 | [`bytes12288_static`](../.runtime/geometry-packet-study/v4/bytes12288_static.case.json) |
| 12,288 B／12 KiB | 每个渲染事件全量重建 | 22.5995，失败运行 | 首窗即失败，不能作为有效动态传输结果 | [`bytes12288_dynamic`](../.runtime/geometry-packet-study/v4/bytes12288_dynamic.case.json) |

12 KiB 动态结束时，receipt 声明 uploaded generation 为 178、build serial 为 656，但首窗 4,096 个中心字节全部精确匹配同 seed 的 generation 98；按 generation 178 检查，4,082 个 slot 的完整 3×3 patch 不通过。这个观察指向旧代网格或更新状态，尚未将根因定为缓存、上传队列或原生同名资源替换。它不能用 FPS 和 CPU 计时代替正确性，也不能直接归因为 stride 128 的顶点精度，因为该 stride 的静态 case 已完整通过。

## v5 最终静态扫描

以下三个 case 均使用 v5 的独立 dataset epoch 名称，执行 8 秒、预热 1 秒的静态基准，再冻结 geometry 后按窗口覆盖全部 slot。每个 query 窗口最多把 4,096 个 resident record 映射到屏幕；256 KiB case 的 262,144 个 record 是通过多个冻结窗口逐窗验证的，并非 262,144 个全屏 primitive 同时可见的 UI 绘制负载。64 KiB 和 256 KiB 的 `verification.passed`、每个窗口的 3×3 RGB+alpha 检查以及完整 slot 覆盖均通过；1 MiB 在首个窗口就被独立 oracle 拒绝，因此不计入成功档位。

| 逻辑载荷 | stride | 初始 load 总耗时（ms） | generation / palette / deserialize / combine / render（ms） | 平均 `GetFps()` | 画面结论 | 原始 case |
| --- | ---: | ---: | --- | ---: | --- | --- |
| 65,536 B／64 KiB | 256 | 110.5313 | 49.4126 / 11.5613 / 0.0305 / 49.0225 / 0.5044 | 60.0634 | 65,536 slot 全覆盖通过 | [`bytes65536_static`](../.runtime/geometry-packet-study/v5/bytes65536_static.case.json) |
| 262,144 B／256 KiB | 512 | 494.1819 | 194.6662 / 50.3085 / 0.0283 / 248.8577 / 0.3212 | 60.0775 | 262,144 slot 全覆盖通过 | [`bytes262144_static`](../.runtime/geometry-packet-study/v5/bytes262144_static.case.json) |
| 1,048,576 B／1 MiB | 1,024 | 4,053.5782 | 792.6529 / 199.3087 / 0.0325 / 3,058.3223 / 3.2618 | 56.1330（最低样本 16.8176） | 首窗失败；不计入成功容量 | [`bytes1048576_static`](../.runtime/geometry-packet-study/v5/bytes1048576_static.case.json) |

1 MiB 失败运行的渲染事件平均间隔约 18.2458 ms，基准共记录 443 个 frame；这些性能值只描述一次失败运行，不能转写成“1 MiB 可用”或“1 MiB 的稳定帧率”。该 case 的首个窗口未通过 payload oracle，因而没有完整驻留验证。运行期间观察到游戏进程 `WorkingSetSize=5,320,302,592` bytes，约 **5.32 GB（4.96 GiB）**；这只是本机本次实验的单进程工作集峰值，不是几何净显存或单独的资源分配大小。原生 geometry 的资源清理、名称复用与长期生命周期仍未被单独量化，不能据此推导通用内存上限。

截至本扫描，保守的成功结论是：**该实现已在本机对单个同时驻留的 256 KiB 逻辑载荷完成静态全量验证；1 MiB 档位当前失败，尚未建立更高容量或引擎硬上限。** 这里的“全量”指 resident geometry 的所有 slot 都被 4,096-slot 查询窗口逐窗覆盖并通过像素 oracle，不表示 26 万个几何记录在一帧中同时铺满屏幕。该结论只适用于 v5 探针、当前客户端／GPU、720×1080 原生客户区和本文件所述的几何编码与验证协议。

## v5 的资源名隔离与冻结／更新对照

v4 不同 case 会重复使用同两个 geometry 名称。v5 在每个独立 dataset 开始时调用 `begin_dataset()`：递增 epoch、先清除旧 receipt 身份，再使用 `pmanim_geometry_packet_payload_epoch{epoch}_bank{0|1}` 命名。这样不同 case 使用独立名称；同一动态 case 内仍只交替使用两个 bank。epoch 不代表已清空原生资源，也不宣称已经解决同名连续更新问题，动态结果仍必须经过原生像素检查。

[`freeze-update-controls.json`](../.runtime/geometry-packet-study/v5/freeze-update-controls.json) 记录的 3,072 字节原生对照全部通过：

| 步骤 | CPU 操作与网格状态 | 独立像素结果 |
| --- | --- | --- |
| 初始上传 | seed 54321、generation 100，全量 Combine | 全 3,072 字节、27,648 个 patch 像素精确通过 |
| CPU 更新而网格冻结 | 在游戏 Python 另生成 generation 101 的 3,072 字节，不调用 Combine，保留 generation 100 geometry | 图像仍完整等于 generation 100；geometry identity 与载荷哈希均不变 |
| 反例检查 | 对同一冻结截图伪用 generation 101 oracle | 3,061 个 slot 不匹配，新代标签不能把旧图判为通过 |
| 真正上传新代 | 对 generation 101 再次执行 load／Combine | 全 3,072 字节通过，generation、build serial 与图像载荷哈希均按预期改变 |

初始与冻结载荷共同的 SHA-256 为 `be7cad536dc1fca3a27777546b2267c034128140c8a062d76daa41e4d88b0602`，实际上传新代后为 `c9945daaad2090206ec9318e440e4b56921f129c555a30ccbe8a25d4b224f078`。这证明本对照中的图像变化依赖原生网格更新；它不补足动态基准逐帧验证，也不把两个 bank 的长期重用视为已经验证。

## 数据如何进入 shader

令载荷长度为 `N`，`S` 为满足 `S² ≥ N` 的最小二次幂，且最小取 2。第 `i` 条记录的字节为 `b[i]`，palette 中的坐标和线性索引为：

```text
x = i // S
y = b[i]
z = i % S
volume = (S, S, 256)             # 原生 palette 顺序为 (z, x, y)
palette_index = y * S * S + x * S + z
```

每条记录具有独立的 X/Z，因此即使多个字节值相同也不会占据同一 palette cell。运行时生成 `bytearray` 与稀疏索引列表，用 `DeserializeBlockPalette` 写入 palette，再调用 `CombineBlockPaletteToGeometry`。静态查询不重新生成 palette 或 geometry。

自定义方块只提供一个零厚度 up 面，模型 origin 为 `[-4,0,-4]`、size 为 `[8,0,8]`，对应局部 X/Z 的 `[-0.25,0.25]`。方块启用 `netease:no_crop_face_block`，材质关闭背面剔除、深度测试与深度写入，减少原生表面消除和深度状态对数据展示的影响。

本轮 PaperDoll 的原生 `POSITION` 会按 palette 体积的三个轴居中。v4 shader 先恢复：

```text
source = POSITION.xyz + (S/2, 128, S/2)
cell = floor(source + 0.5)
record = cell.x * S + cell.z
byte = mod(cell.y, 256)
```

局部 quad 角点由 `source.xz - cell.xz` 恢复，选中记录再被排成二维表格，直接写入 clip space。未选中的记录送到裁剪范围外。所有原生网格记录仍由同一 resident geometry 提供，截图窗口只改变哪些记录被展示。

控制颜色传递 `start`、`count`、`columns`、诊断 `mode`、`stride` 和 Y 恢复偏移。shader 没有接收 payload seed、generation 或预期字节，也没有实现 PRNG。正常模式的 fragment shader 仅输出该 primitive 恢复的字节灰度。

## 实验的能力边界

这条通路让一批运行时数据通过几何属性进入 vertex shader，每个 primitive 携带自己的记录。当前 fragment shader 接收该 primitive 的 varying，尚没有索引其他记录的读取机制。因此，它可以验证“大批记录同时驻留并逐窗展示”，但不能直接等同于单个 shader 可任意索引的 uniform 数组、SSBO 或数据纹理。

本探针没有将数据转换成可被任意 shader 访问的纹理，也没有实现 GPU payload 回读到游戏 Python。宿主 Python 对 WGC 截图解码，是画面验证步骤；它不是游戏内的 GPU → Python 通信接口。

位置信息与局部面形状必须由原生网格格式保留。BBE 的上下文网格采用较小的局部坐标，以保护 packed 顶点中的细几何。本探针随着 `N` 增大提高 `S`，因而每个较大档位都需要重新完整验证。小档位通过不能证明更大坐标仍保留 ±0.25 的角点精度；大档位失败也需要区分坐标精度、原生网格容量、更新延迟和缓存问题。

## 测量与画面验证协议

画面使用宽 720、高 1080 的原生物理客户区与 Windows.Graphics.Capture PNG。逻辑 UI 尺寸单独记录，不拿 `GetScreenSize()` 返回值替代截图尺寸。shader 将数据绘制在 X 为全宽、Y 为 `[64,1064)` 的固定区域；receipt 的 `display_rect_norm` 为 `[0,64/1080,1,1000/1080]`。上下留白与 oracle 使用同一固定布局，不做图像缩放、偏移搜索或自动裁切。

每个查询最多展示 4,096 条记录，固定 64 列，行数向上取整。独立 oracle 只根据 seed、uploaded generation 和 slot index 重算预期值，不读取 receipt 内的 CPU payload 副本。每条记录检查中心完整的 3×3 原生像素区域；九个像素的 RGB 必须逐通道精确等于预期字节，alpha 必须为 255，容差为零。诊断 mode 1、2、3 不可作为 payload 通过证据。

完整验证先加载全量 palette 并完成基准，再停止更新、冻结 seed、generation、slot count、geometry name 与 build serial。逐窗只修改 query，保存原生截图、捕获身份与时间来源、状态和验证结果；窗口之间的 geometry identity 必须不变，最后要求每个 slot 恰好覆盖一次。缺失、重复、identity 改变或任何像素错误均不能通过。这支持同一 geometry 的完整驻留，不能将轮流替换的小 payload 相加计容量。

动态基准在每次 `GameRenderTickEvent` 中重新生成字节、构造 palette 并组合原生网格。性能计时包含 Python 数据生成、索引打包、反序列化、Combine 与 Render 提交等阶段；各阶段记录的是调用耗时，不能直接解释为 GPU 完成耗时。帧间隔、`GetFps()` 与更新代数分别记录，避免把三者当成同一个指标。

现有 runner 在基准停止后验证最后一代，不能据此断言基准期间每次重建都正确显示。原始回执因此固定记录 `all_render_frames_verified=false`、`gpu_to_python_readback=false`、`actual_mobile_hardware=false`。

如果某个动态 case 完成了计时但最终画面未通过，它仍是失败 case。其 FPS 可作为该次失败运行的观察，不能填入“已验证动态容量”或“有效上传吞吐”栏。静态通过和动态通过也应分开列出。

离线独立复核工具重新读取原始 PNG、状态和捕获来源，复算各窗口与完整覆盖哈希，并核对原 case 摘要。历史失败 case 保留且不被重写；因此总报告中的 `passed=false` 可能表示目录中仍保留历史失败，应同时查看 `source_failed_cases`、`completed_cases_recheck_passed` 和 `failed_completed_rechecks`，不能只读一个总布尔值。

## 迭代与失败证据

所有版本的原始证据保留在 `.runtime/geometry-packet-study/`，生成项目使用独立的 `project-v1` 至 `project-v5` 目录。早期失败用于解释探针修正，不能当作修正后数据通路的容量限制。

| 版本 | 观察与处理 | 对结论的影响 |
| --- | --- | --- |
| v1 | 游戏 Python 环境不具备探针使用的 `hashlib`；移除对游戏侧哈希的依赖，宿主 oracle 与证据哈希仍保留 | 上传链路尚未完成，不能据此判断几何容量 |
| v2 | vertex shader 使用了 GLSL 保留字 `layout`；改为 `layoutPacket` | shader 编译失败，不能据此判断数据是否可由 POSITION 携带 |
| v3 | 缺少 X/Z 半体积居中恢复；后续 `ReloadAllShaders` 又出现其他原生 shader 缺失与超时 | 两项问题混杂，该实例结果不用于正常性能比较；对受管实例执行强制停止，保留证据 |
| v4 | 补齐 XYZ 半体积恢复并从新资源冷启动，完成小数据 smoke 原生像素检查后再进行正式扫描 | 性能、完整驻留与动态正确性分别以本版逐 case 证据判定 |
| v5 | 独立 case 使用新 epoch 名称；补齐原生 CPU 变化／geometry 冻结／重新上传对照 | 避免独立 case 共用名称；不能据此认定已修复同一动态 case 内的资源替换 |

不得把 `ReloadAllShaders` 后的混合状态或旧实例继续运行产生的结果并入 v4 冷启动测量。也不得在出现旧代数据时只保留 FPS、删除失败像素记录，或用新的 generation 标签重新解释旧截图为成功。

## 实现与复现入口

研究代码位于 [`tools/geometry_packet_probe/`](../tools/geometry_packet_probe/)，主要入口为：

| 文件 | 职责 |
| --- | --- |
| [`build_probe.py`](../tools/geometry_packet_probe/build_probe.py) | 构建有 ownership marker 的独立测试项目，不启动游戏 |
| [`host.py`](../tools/geometry_packet_probe/host.py) | 复用 owner 绑定、后台 noactivation 的启动、调用、resize、WGC 截图与停止工具 |
| [`runtime.py`](../tools/geometry_packet_probe/runtime.py) | 游戏 Python 数据生成、palette 编码、geometry 重建、查询与计时 |
| [`geometry_packet.vertex`](../tools/geometry_packet_probe/geometry_packet.vertex) | 从原生 POSITION 恢复记录与字节，并将查询结果排成二维格 |
| [`run_case.py`](../tools/geometry_packet_probe/run_case.py) | 单个静态／动态 case 的基准、冻结、逐窗截图及完整覆盖汇总 |
| [`run_controls.py`](../tools/geometry_packet_probe/run_controls.py) | 游戏 Python 生成新数据但冻结 geometry，再真正上传新代的原生对照 |
| [`verify_capture.py`](../tools/geometry_packet_probe/verify_capture.py) | 原生 3×3 像素零容差 oracle 与跨窗口覆盖检查 |
| [`recheck_evidence.py`](../tools/geometry_packet_probe/recheck_evidence.py) | 从原始 PNG 与 receipt 独立复核，保留源 case 失败状态 |

正式复现应使用独立 project 和独立 evidence 目录，以 owner receipt 定位实例。每个 case 使用新名称，保留此前命令、截图、错误与回执，避免覆盖历史记录。
