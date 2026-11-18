# 大容量 alpha 与场景压缩实机研究

2026-11-18。本轮按用户指定的顺序验证单次提交容量、alpha 压缩与 RGB 有损混合，再测静态驻留帧率；不测试连续更新。所有载荷由游戏 Python 在内存中生成，经原生 block palette／geometry 提交，没有游戏 Python 写 PNG、覆盖资源包或运行时 payload 文件。

## 已验证的容量

直接覆盖场景 alpha 的路线，已在本机 **2560×1440** 原生客户区验证 **至少 2 MiB 完整数组**。1 MiB、1.5 MiB、2 MiB 均逐字节完成直接查询和依赖查询，零错误。这里没有遇到容量失败，不能把 2 MiB 写成绝对上限。

| 驻留数据 | 64 KiB 几何页 | 直接查询 | 依赖查询 |
| --- | ---: | ---: | ---: |
| 1 MiB = 1,048,576 B | 16 | 1,048,576 次，0 错 | 1,048,576 次，0 错 |
| 1.5 MiB = 1,572,864 B | 24 | 1,572,864 次，0 错 | 1,572,864 次，0 错 |
| 2 MiB = 2,097,152 B | 32 | 2,097,152 次，0 错 | 2,097,152 次，0 错 |

每字节占一个原生像素的 alpha8。若所有屏幕像素都可用，纯存储预算为 `width × height` 字节；2560×1440 对应 3,686,400 B，约 3.516 MiB。它只是该分辨率下的一字节／像素预算，未测量为可用最大容量，也不是所有渲染目标或编码方案的理论上限。实际布局还需要边界、覆盖、精度、geometry 和内存约束。本轮仅按用户要求测到 2 MiB，没有继续搜索极限。

每页 palette 固定为 `256×256×16`，使用 compact8，一个 anchor 关联一页；全局页偏移由 actor uniform 加在局部边界检查之后。源数据按 2048 列排布，起点为 `[8,32]`。完整诊断位于 `[16,128]` 起的原生像素，避开引擎调试文字；没有排除任何载荷像素。依赖查询的第二次地址由第一次取出的值决定，模乘使用有界分解，避免 2 MiB 索引中间值超出 float32 精确整数范围。

独立审计不导入原编码器／verifier，重放 9 张 native PNG，共 9,568,256 次正例查询；同时检查 guard、所有页的宿主 SHA-256、运行时 sum32 指纹、实体／geometry 名称、seed、generation 和上传序号。隐藏 writer 的 64 KiB 负对照有 65,279／65,536 个字节不符，恢复后全量通过；错误 generation oracle 也拒绝全部正例。运行时 sum32 不是密码学指纹，其限制没有由接口成功返回掩盖。

首次初始化的累计 CPU／SDK 提交区间如下。它们是各页实际调用区间相加，**不含宿主 IPC、等待和截图，没有 GPU completion fence**；采集时允许另一 correctness 实例并行，不能解释成单实例端到端上传延迟或带宽。

| 数据 | 生成字节 | 编码 | Deserialize | Combine | attach 与 controls | 指纹 | 合计 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 MiB | 862.163 ms | 190.807 ms | 0.235 ms | 69.772 ms | 78.266 ms | 3.727 ms | 1,204.969 ms |
| 1.5 MiB | 1,298.074 ms | 287.970 ms | 0.344 ms | 100.807 ms | 78.685 ms | 5.602 ms | 1,771.482 ms |
| 2 MiB | 1,744.356 ms | 383.623 ms | 0.583 ms | 141.023 ms | 79.587 ms | 7.563 ms | 2,356.735 ms |

早期失败原样保留：游戏 hashlib 缺 sha256、超屏窗口白区、resize 后参数重置与偏移、调试文字覆盖、宿主 resize 包装错误。这些属于探针或窗口校准问题，不能作为大容量失败。

## alpha 压缩与 RGB 有损混合

实机原型采用以下内存路径：

```text
游戏 Python bytearray → compact8 geometry
  → 世界 draw：混合 RGB 携带 3k bit／像素，保留原 alpha
  → encode pass：近似恢复 RGB，压缩原 alpha，将载荷搬入空位
  → 显式保存的组合纹理：可按 array[index] 读取载荷
  → decode pass：精确恢复原 alpha
  → 可选 consumer：直接／索引／两次依赖取数
```

对原通道 byte `x` 和 k bit 载荷 `b`，令 `n=2^(8-k)`。当前原生混合候选是 `encoded = n*b + round((n-1)*x/255)`，恢复为 `round((encoded mod n)*255/(n-1))`。CPU 穷举所有 x／b 对；本机原生 k=2 后续稳定样本的 87,424×3 个通道精确满足该混合公式。自然场景没有穷举全部 256 种原通道值，不能以 CPU 穷举代替原生全码域验证。

alpha 以 32 像素为块：4 B 例外 mask、4 B 非基准值、24 B 载荷。基准值 255 由 uniform 提供；每块最多四个例外才能独立无损恢复。五个例外和变化 alpha 的 fixture 显式拒绝并显示无效，不截断例外或把无效块报告为数据成功。产品仍需要覆盖前的有效性判断或明确回退，此实验的拒绝机制不是通用回退实现。

| 模式 | RGB 每通道载荷 | 每 32 像素净数据 | 理想 UNORM8 恢复误差上界 | 本轮真实 geometry 数据 |
| --- | ---: | ---: | ---: | --- |
| k=1 | 1 bit | 12 B | 每通道 1／255 | 3 KiB、64 KiB，全部逻辑字节的三种查询与 alpha 恢复通过 |
| k=2 | 2 bit | 24 B | 每通道 2／255 | 3 KiB、64 KiB，全部逻辑字节的三种查询与 alpha 恢复通过；RGB 首次失败及复测见下文 |

RGB 是**输入通路**，压缩后的 alpha 是相同数据的**后续保存位置**，容量不能相加。以全屏像素数 N 估算，当前 k=1／2 分别约为 `3kN/8` B，还要扣掉不安全区、块对齐及溢出块。k=2 恰好占满每块 24 B 的空位。

本轮隔离场景的安全区为 x `[0,720)`、y `[128,1064)`，共 **673,920 点**。shader 把被测 alpha 编码为可见 RGB 后核验，未使用 WGC 自带的合成 alpha 冒充原 alpha。所有样本均为 255，残差 flag 与残差显示字节均为 0；21,060 块均为零例外。其条件容量是 k=1 的 252,720 B／k=2 的 **505,440 B**，alpha 空位预算也是 505,440 B；**实际完整 geometry 载荷测到 64 KiB**，不是已经上传并验收了 505,440 B。

64 KiB 的逻辑字节与矩形补齐分开记录：k=1 使用 174,816 个像素，分配 65,556 B；k=2 使用 87,424 个像素，分配 65,568 B；32 像素块的第一层补齐均为 65,544 B。查询只宣称覆盖 65,536 个逻辑字节，补齐部分另外由混合公式核验。

## 颜色异常与证据边界

3 KiB 的 k=1／2，以及 64 KiB 的 k=1，在稳定分时基线中满足预期颜色误差。**64 KiB k=2 首次 RGB 比较失败：1,356／87,424 点超过 2，最大通道差 52。该失败仍是失败，未用后续样本覆盖。** 数据三种查询与 alpha 恢复当时均通过。

同一 geometry 和 salt、未重建后的 followup 中，三次 off 基线完全一致；原生 encoded RGB 与上述混合公式逐通道零差，restored 与直接解码零差，距稳定基线最大 2。之后两张 on／on_repeat 也均最大 2。但是最后 off_after 有 555 点相对旧基线变化、最大 166，说明该自然场景并非全程静止。首次异常原因未确定，不能由这些分时截图推断永久误差保证。

独立审计核对 87 张 native PNG／state／WGC receipt 及 109 个控制命令哈希；四个真实 geometry 数据集总计 **411,648 次逻辑查询，0 错**，alpha 精确保持及恢复，隐藏 writer 负对照均拒绝超过 99% 的字节。fixture 的四例外／overflow／header 也独立重放，但明确属于算术 fixture，不当作硬件混合验证。`native_payload_and_alpha_passed=true`，同时保留 `all_initial_observations_passed=false`。

探针禁用了既有后处理，当前结果仅属于隔离的自定义链。还未证明雨雪、水、玻璃、粒子、附魔、bloom／DOF 和不同 renderer 的完整兼容；固定读取原始 `TEXTURE_1` 的原生效果可能绕过恢复链。观察到 alpha 恒 255 只适用于这个场景和阶段，不能推广为所有游戏画面。

## 静态帧率

测试设备为 Windows、NVIDIA GeForce RTX 4060 Laptop GPU，客户端为 3.10.0.448891。固定 60 FPS，每档 2 秒暖机、25 秒样本，不重新提交载荷。两个研究实例按单实例串行安排：alpha 有系统进程前置检查，确认其退出后才放行组合实例；组合没有另存全系统进程 census，也未在每个采样窗口持续监控其他进程。大 alpha 使用 2560×1440；组合压缩使用 720×1080；两种分辨率与查询负载不同，不能直接按容量或 FPS 作跨方案比例推算。`GetFps()` 与渲染事件间隔分别记录，都不是 GPU 时间戳或 completion fence。

### 直接 alpha，2560×1440

| 活动载荷 | 可见原生页 | 平均 GetFps | 平均事件间隔 | p99 间隔 | 最大间隔 | >25 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 0 | 60.074 | 16.6667 ms | 18.3168 ms | 23.4425 ms | 0 |
| 1 MiB | 16 | 60.075 | 16.6661 ms | 18.4451 ms | 22.8324 ms | 0 |
| 1.5 MiB | 24 | 60.078 | 16.6663 ms | 18.3598 ms | 23.7880 ms | 0 |
| 2 MiB | 32 | 60.078 | 16.6658 ms | 18.2868 ms | 22.6513 ms | 0 |

每档约 25.013 秒，1,501 个渲染事件间隔、100 个 GetFps 样本。四档均保留完整 2 MiB 资源和 32 个 anchor，并非逐档新建未分配的游戏。baseline 使用原生 `SetActorBlockGeometryVisible(False)` 隐藏全部附件并关闭数据链；其他档位仅显示对应页前缀，writer、copy／私有数组／consumer 三 pass 运行，query3 禁用诊断 gathers。身份和上传序号冻结。因此本机静态 2 MiB carrier 未出现可见帧率下降，但不能推出 GPU 零成本、剩余算力或业务随机读取性能。

### 组合压缩，720×1080

| 档位 | 自定义 post pass | k=1 平均 GetFps | k=1 p99 间隔 | k=2 平均 GetFps | k=2 p99 间隔 |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline：原生附件全部隐藏 | 0 | 60.0682 | 18.1193 ms | 60.0596 | 18.2341 ms |
| 仅当前 native writer | 0 | 60.0775 | 18.1226 ms | 60.0689 | 18.2397 ms |
| 压缩与恢复：raw+encode+decode | 3 | 60.0775 | 18.1052 ms | 60.0752 | 18.2655 ms |
| 再启用 65,536 结果的 dependent consumer | 4 | 60.0775 | 18.2245 ms | 60.0729 | 18.3277 ms |

每档 100 个 GetFps 样本，1,500／1,501 个暖机后事件间隔；均值约 16.67 ms，全部无 >25 ms，最大 24.2669 ms。组合 runtime 的 `frames=1620/1621` 包括约 120 个暖机帧，与 alpha runtime 的采样期帧计数语义不同，不能用 `1621/25` 计算 FPS。

每个 k 内保持同一数据与分配；baseline 通过原生可见性 setter 隐藏附件，其余 profile 只显示当次 geometry。快照通过 `CheckEnabledByName` 记录实际启用集合，fixture／inspect／diagnostic 始终关闭。k=2 保留 k=1 的已隐藏 native 分配：1 name／174,816 records 变为 2 names／262,240 records；跨 k 的基线不作为完全相同内存条件的比较。采样中无上传；采样前 identity／dependent 各 65,536 结果和采样后 dependent 的 65,536 结果均为零误差。dependent 最终地址有 48,449 个不同位置，采样后没有另拍 identity，故不声称 after 是逐地址全数组比较。

独立性能审计核对控制命令、状态与汇总数值，并重放查询 PNG；逐帧原始样本向量未导出，p99 只能核对采样实现与回执一致性，不能从原始向量重新计算。结果支持“本机固定场景、60 FPS 上限下无可见持续下降”，不证明 GPU 成本为零或任意设备／业务负载仍有同样余量。

## 证据与复现

- 大 alpha 工具：[geometry_atlas_large_probe](../tools/geometry_atlas_large_probe/README.md)；独立审计：[independent_large_audit.py](../tools/independent_large_audit.py)。
- 组合工具：[scene_codec_probe](../tools/scene_codec_probe/README.md)；独立审计：[independent_scene_codec_audit.py](../tools/independent_scene_codec_audit.py)。
- 大 alpha 原始证据：`.runtime/geometry-atlas-large-20261118-r3/evidence-centered/`；早期失败在同名 r1／r2 和 r3 初始 evidence 中。
- 组合原始证据：`.runtime/scene-codec-native/evidence-v2/`；性能使用独立新实例和新证据目录。
- 归档结果：[大 alpha 摘要](evidence/large-alpha/summary.json)、[正确性审计](evidence/large-alpha/independent-audit.json)、[性能审计](evidence/large-alpha/independent-perf-audit.json)；[组合摘要](evidence/scene-codec/summary.json)、[组合正确性审计](evidence/scene-codec/independent-audit.json)、[组合性能审计](evidence/scene-codec/independent-static-perf-audit.json)。原始目录和哈希均保留在摘要中；Git 不收录完整运行包与大截图。

离线检查：3 项大 alpha 边界／float32／完整截图检查和 15 项组合编码／位流／容量／native 控制检查均通过；generated behavior scope review 10／10 文件可解析，3 条提示均来自继承的 base runtime，本轮新 runtime 无提示。大 alpha 的容量／性能与组合的正确性／性能分别完成独立证据重放。最终两个 owned MC 均 quiesce 并确认进程退出，未留下测试游戏。

本轮不切换生产渲染路线，不宣称通用 GPU→Python 回读、跨帧持久 GPU 状态、全部材质共享数组、手机性能或连续更新已通过。静态载荷仍由几何 draw／后处理每帧重建数据纹理；“Python 没有再次上传”不等于“GPU 停止运行传输链”。
