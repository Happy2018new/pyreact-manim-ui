# Geometry atlas 流式研究的小型证据归档

本目录保存容量、连续更新、冻结诊断及坐标校准的结果摘要。来源是本地被 Git 忽略的 `.runtime/geometry-atlas-study/`；**不跟踪原生 PNG、完整项目、游戏资源副本、日志或逐 byte 数组**。本目录可供审阅结果与来源哈希，完整像素重放仍需要原始本地证据。归档过程没有运行游戏，也没有执行第二套独立像素算法。

研究解释见 [流式研究报告](../../../GEOMETRY_ATLAS_STREAMING_RESEARCH.md)。报告与本目录分别保留批次范围；本目录包含 b7c 冷启动的最终四个 case、两组 live 以及来源对照；b2／b3／b4 的失败仍原样保留。

| 归档文件 | 内容与原始来源 | 保存方式 |
| --- | --- | --- |
| [b2-capacity-summary.json](b2-capacity-summary.json) | `b2/summary-v1.json`：4 个容量／更新 case，含 512 KiB 完整扫描失败 | 原文件逐 byte 复制 |
| [b3-streaming-summary-29.json](b3-streaming-summary-29.json) | `b3/summary29.json`：最终 29 个性能 case | 原文件逐 byte 复制 |
| [b5-old-template-summary.json](b5-old-template-summary.json) | `b5/summary4.json`：旧模板冷启动的 4 个 case | 原文件逐 byte 复制 |
| [b5-scatter-derived-diagnosis-512k.json](b5-scatter-derived-diagnosis-512k.json) | `b5/512-derived-scatter-diagnosis.json`：33 个白洞规律与末槽值覆盖的派生几何分析 | 原文件逐 byte 复制 |
| [b6-decoder-aba.json](b6-decoder-aba.json) | `b6/decoder-aba-results.json`：本批次同几何 A→B→A 的 18 张冻结图对照 | 原文件逐 byte 复制 |
| [independent-b2-b3-replay-summary.json](independent-b2-b3-replay-summary.json) | `independent-b2-b3-updates.json`：33 个 b2／b3 case 和 5 组 live 的离线重放 | 精简来源、计数、失败语义及哈希审计，省略逐窗 artifact manifest |
| [b4-half-grid-calibration-summary.json](b4-half-grid-calibration-summary.json) | `b4/half3k_double50_100.updates.json` 与八组 `half_center_*_identity.state/verify.json` | 默认失败摘要与八个 center 的结果、原始路径及 SHA-256，省略完整预期／观测 byte 和失败数组 |
| [b7c-calibrated-summary.json](b7c-calibrated-summary.json) | 新模板校准后四个最终 case，含 512 KiB 全量通过 | 原汇总逐 byte 复制 |
| [independent-b7c-replay-summary.json](independent-b7c-replay-summary.json) | 四个 case／270 冻结窗、两组 live／六帧、来源对照八窗的离线重放 | 精简原始审计并保留源 SHA、project hashes 与 2,172 个 raw 文件的审计结论 |
| [b7c-source-controls-summary.json](b7c-source-controls-summary.json) | writer off／restore 与 fresh gen2 六个采样窗；gen2 不声明全量 | 精简源回执并附已重放结果 |
| [manifest.json](manifest.json) | 十个结果文件的来源、源 SHA-256、归档 SHA-256、大小与保存方式 | 本目录生成的来源索引 |

`manifest.json` 中的 `original_source` 相对于仓库根目录，`archive_file` 相对于本目录。六份完整复制保留原始 schema、路径和历史字段；其内部引用仍可能指向本地忽略目录或原采集机绝对路径。它们不是可独立搬移的完整实机证据包。四份精简摘要使用独立 schema，保留原文件 SHA-256，避免把摘要生成和原始审计混为一谈。

b2／b3 重放摘要的范围仅为 **b2 的 4 个 case＋b3 的 29 个 case，以及 5 组 live／15 张图**，不含 b5 新增 64 KiB live、b6 或 b4。源审计的 `audit_passed=true` 表示重放与保存结果一致：33 个 case 中仍有 **4 个原实验失败**，其名称与原错误均保留；其余 29 个通过包含 **18 个完整载荷通过与 11 个仅抽样通过**。15 张 live 图中 9 张白帧为 unmatched，6 张匹配；白帧在 fingerprint 预筛被拒绝，`full_patch_checked=0`。审计通过不能改写这些图像结果，也不能证明每代新鲜度或每帧正确。

源独立审计记录了 **4,169 个唯一原始文件**的声明哈希全匹配、重放后不变及 canonical manifest SHA。归档保留的是当时的审计结论；这次提取重新核对了 33 个 case 源文件与 5 个 live 源文件的哈希，没有重新检查全部 4,169 个原始文件。`independent_saved_evidence_replay=true`、`independent_second_oracle=false` 继续保留。

b4 校准保留同一份 3 KiB 冻结几何上的八个 center。identity 全 3,072 个输出的失败数依次为 **2791、0、3027、287、2824、3060、144、2791**；`center=(1,0.5,0.5)` 在这一查询中通过，恢复 `(0.5,0.5,0.5)` 后原观测 byte 和失败数组重现。默认 half3k case 仍为失败：identity 错 2791、dependent 错 3040，两者均 unmatched。各 state／verify 的源 SHA 以及 PNG 的路径／SHA 留在精简摘要，PNG 本身不复制。

**原生顶点存储格式仍未知。** b4 的 center 结果属于原生坐标校准，不能证明 half 打包、原生 POSITION 格式、特定编译器变换或驱动根因；3 KiB 冻结 identity 通过也不能扩大成 512 KiB 容量或正确流式更新。b5 的末 quad 窄三角带是由 shader 公式、atlas 布局和截图坐标推导的模型，不是原生顶点捕获。b6 的 getter 只确认控制值读回，未捕获 GPU 分支执行轨迹；b5 与 b6 重启后名称／serial 相同，也不代表跨批是同一个原生对象。

本目录只保留短时固定条件下的结果。正式性能样本与受宿主 IPC／捕获干扰的 live 诊断分别解释，live 性能继续排除；没有 GPU completion fence、逐代完整图像、移动端测量或长期运行保证。

最终 b7c：512 KiB identity 的 524,288 个源地址全量精确通过；dependent 的 524,288 queries 全过，第二地址有重复，实际涉及 331,726 个源地址。两者共 256 张原生图，零误差。独立重放使用相同 oracle，不是第二种期望算法；2,172 个 raw 文件哈希匹配且重读不变。源审计 SHA 为 `91031247c4544c99f440d24206a99e0b175775cb8145659a9fe9e4bad4842950`。

b7c 还有六张 live payload 匹配；3 KiB 约 10 Hz、59.18 FPS，12 KiB 2 Hz、56.82 FPS。机器开始时另有独立 MC，未受本任务控制，本批不作独占性能基准。关闭 writer 有 4,082／4,096 cells 不匹配，恢复后零错；gen2 两模式首中尾各查 12,288 queries，每窗同图拒绝旧代，但保持 `gen2_full_capacity_verified=false`。这些正向结果没有取消本目录前述历史失败，也不证明长期每代／每帧正确、原生顶点格式或 GPU 可见完成时刻。
