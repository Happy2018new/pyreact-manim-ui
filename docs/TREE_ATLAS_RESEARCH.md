# 私有数据纹理树与限量更新实测

状态更新：用户后续已终止完全私有纹理上传路线，不再扩大本页的纹理树实验。当前采用场景 RGB／alpha 压缩路线，结果见[512 KiB 实机研究](SCENE_CODEC_512K_RESEARCH.md)。

2026-11-18；网易客户端 3.10.0.448891、RTX 4060 Laptop GPU、原生客户区 720×1080、60 FPS 上限。本轮在隔离研究包中实现并测试五叉树，未更改生产动画或 better-building-editor。

**64 KiB 的完整共享数组与每帧约 3 KiB 增量上传已通过实机最终状态验证，但 64 KiB 常驻仍只有约 15.8 FPS，没有解决大数组以 60 FPS 运行的目标。** 像素工作量大幅减少后，数千个 pass 的逐帧成本仍然存在；不能仅靠限制 Python 上传量推断帧率能恢复。

## 数据路径与实现

```text
进入链前的画面 C0 ── save ────────────────────────────┐
                                                     ↓ TEXTURE_4
游戏 Python → 36 B 叶 RT → 最多五路合并 → … → 根 RT → consumer
                                                     ↑ TEXTURE_3
```

每个叶 RT 为 12×1，含 12 个 uint24 word，共 36 B。三个 payload vec4 使用 EXTRA_VECTOR1..3，保留引擎的 EXTRA_VECTOR4。父节点通过固定 TEXTURE3..7 采样最多五个子节点，只产生自己子树的局部纹理。consumer 实现 `A[i]` 和 `A[(i+A[i]+salt)%len(A)]`，隐藏诊断时恢复 C0。数据 producer 不采样场景 RGB／alpha，载荷只在私有纹理 RGB 中流动。

子树有 p 个叶子时，其布局为 `columns=ceil(p/1080)`、`width=12*columns`、`height=ceil(p/columns)`。数据按连续 word 的行主序存储；逻辑载荷长度与最后一叶的分配填充分别记录。

64 KiB 使用 1,821 个叶、457 个父节点，共 **2,278 个数据 pass**，另有 save 和 consumer。根为 24×911，请求的数据输出总量为 **131,124 像素／帧**；旧 24 B 逐页整图链约为 5,997 万。这是配置中的输出像素统计，未计纹理读次数，也不是原生显存分配或 GPU 时间测量。即使像素量下降，2,280 个 process／pass 仍需由引擎执行。

初次 `finish()` 完整初始化全部叶；后续 `write(seed)` 只生成并提交预算内的循环叶段。预算 3,072 B 时实际每帧为 **85 叶、3,060 B、255 次 vec4 SetParameter**。不再每帧生成整个大数组。跨尾部时分成两段提交，仍使用同一段连续生成序列。

每次增量记录 seed、起始叶、叶数、当次预算、物理／有效字节和 CPU 时间。宿主从初始 seed 独立生成数据并重放历史，再绑定 benchmark 前后历史边界、每帧 seed 与帧数。上传中途失败会标记载荷不一致、清理过程并拒绝把旧 words 当作 native 当前值。

## 原生实测

| 常驻逻辑容量 | 工作方式 | 引擎 FPS 均值 | 平均渲染事件间隔 | SDK 上传均值／p95 |
| --- | --- | ---: | ---: | ---: |
| 1,000 B | 静态，不逐帧上传 | 60.08 | 16.66 ms | 0／0 ms |
| 3 KiB | 每帧最多 3,060 B 增量 | 59.95 | 16.70 ms | 0.342／0.384 ms |
| 12 KiB | 每帧 3,060 B 增量 | 58.72 | 16.98 ms | 0.336／0.352 ms |
| 64 KiB | 静态，不逐帧上传 | 15.82 | 63.65 ms | 0／0 ms |
| 64 KiB | 每帧 3,060 B 增量 | 15.42 | 64.69 ms | 0.333／0.361 ms |
| 关闭研究链 | 无数据 pass | 60.08 | 16.66 ms | 0／0 ms |

均为短时粗测：1,000 B 为 4 秒，其他为 6 秒，含 1 秒预热。64 KiB 静态／增量分别只有 5 个引擎 FPS 样本，不能当作高精度长期保证。3 KiB 时桌面 GPU 回归曾短暂并行，因此该档位仅说明接近限帧值，不能据此宣布严格稳定 60 FPS 的容量上限；没有继续二分寻找边界。

64 KiB 增量完成 93 次更新，全部历史完整，累计物理提交 284,580 B。**这不是单帧或同时驻留容量**：同时驻留为 65,536 B，每次仍最多 3,060 B。生成／打包平均约 0.718 ms，SDK 调用平均约 0.333 ms；SDK 时间不等待 GPU 完成，两项均不能当作端到端上传延迟。初次 64 KiB 生成约 16.19 ms、SDK 调用约 7.04 ms，尚未分帧初始化。

静态 64 KiB 已明显低于 60 FPS，而限量更新仅再增加约 1 ms 的平均帧间隔，说明当前主要障碍仍在常驻渲染链。尚未用原生 CPU／GPU profiler 将 process 管理、draw 调度与各类同步逐项归因，不能把其中某一项写成已测得的唯一原因。

## 正确性与缓存负对照

1,000 B、3 KiB、12 KiB，以及 64 KiB 静态和增量后的最终状态，均完成全部逻辑字节的 identity 与 dependent 查询。64 KiB 两次扫描各有 22×2 个窗口，源数组在翻页期间保持不变。每个诊断格检查原生 PNG 的完整 3×3 RGBA patch，零容差，包括末行填充。增量后的 64 KiB 扫描通过独立历史重放，覆盖更新区、未更新区及循环跨尾后的最终状态。

另在同一 64 KiB 驻留数据上，**只关闭第一个叶子的绘制**，不改 payload、不停父节点、不重写数据。首 1,000 B 的检查中恰好索引 0..35 的 36 格失败；恢复该叶后，同一 1,000 B 全部正确。这否定当前树连接下“关闭未更新叶后仍能读旧 RT”的假设。不能把桌面 OpenGL 的持久纹理实验当作原生缓存支持。

离线 43 项回归通过，含 5 项真实桌面 GPU 测试：多层／非满子树、五 sampler、断开非首输入负对照、32 轮局部叶更新、64 KiB 全量、完整 RGBA 恢复及场景独立。首轮 GPU 校验发现整数除法边界落入前一子树，已通过整数单元中心除法与显式余数修复；修复后全部通过。首次原生小例因 builder 漏装 `isolated_runtime.py` 依赖而失败，已补齐并保留失败记录。

原生截图证明最终诊断读值正确；未验证每个显示帧的原子可见性、每帧 freshness、GPU→游戏 Python 回读或手机性能。WGC 的合成 alpha 不证明原生中间 RT 的 alpha 保留；完整 RGBA 恢复仍以桌面 GPU 对照为证。本轮没有用完整原生 C0 对照替代此限制。

另一份[独立离线审计](evidence/tree-atlas/independent-audit.json)未调用 runner 的 replay／像素验证函数，另写整数 LCG、历史重放和 Fraction／divmod／PIL 检查。四个主要 case 共 98 张数据 PNG、292,896 格、2,636,064 个 RGBA 像素的完整 3×3 patch 全部零误差；457 个输入文件 hash 与终审重读一致。它还复核了前 36 B 的缓存负对照失败、恢复正确、安装源及关闭链后的 baseline。

## 后续判断

2026-11-18 后续用户调整：仍以完全不修改场景 RGBA 的私有纹理为最高优先级，同时允许在最终视觉不变且透明物／特效兼容的条件下研究 alpha 暂存。新增[私有入口与无损 alpha 压缩静态研究](PRIVATE_TEXTURE_STATIC_OPTIONS.md)区分 U5–U16、Image 自身纹理消费和压缩兜底；均未由本轮静态分析变成已验证能力。以下保留本树采用的严格场景隔离条件。

树形合并已经完成概念验证。**不要继续把调分支数、缩 RT 或增加相同节点当作 64 KiB／60 FPS 的解决方案。** 要显著减少逐帧绘制次数，需要新的批量输入，或确实可跨帧保存且可寻址的 GPU 纹理能力。

公开接口复查未找到几何体／实体／纸娃娃直接画入私有 RT 并交给后处理 sampler 的桥接入口：`RenderBlockGeometryModel`、`RenderEntity`、`RenderSkeletonModel` 返回 bool，参数没有目标 RT；`PostPassResultToOtherPass` 的源只能是自定义后处理 process／pass。材质写入掩码不负责选择 framebuffer。此前几何方案先把数据写入场景 alpha，不能在当前约束下复用，即使最终画面可恢复。

上述依据来自 `ModAPI/接口/后处理/自定义.md` 和 `NeteaseGuide/mcguide/18-界面与交互/30-UI说明文档.md` 及相关 Render API；结论是本次未找到公开入口，不是宣称引擎内部绝对不存在。下一研究门槛是先确认真实的批量写入／私有持久纹理接口，再做小 PoC。生产动画继续使用既有离线资源与少量运行时参数，不因本轮数组正确性通过而切换到通用 all in runtime。

## 证据与复现

- 小型结果：[summary.json](evidence/tree-atlas/summary.json)。原始配置、命令、PNG、历史、逐窗判定和所有失败保留于 `.runtime/tree-atlas-study/v1/evidence/`。
- 实现：`tools/runtime_packet_probe/tree_assets.py`、`tree_runtime.py`、三个 tree shader、`run_tree_case.py`。
- 后台保护、60 FPS、owner／session 路由与用户自行前台观察规则同[私有 RT 概念验证](ISOLATED_ATLAS_POC.md)。本轮未发送桌面输入或激活窗口。
- 测试结束后所有研究过程已 disabled，清理错误为空，基线恢复约 60.08 FPS；保留本轮 owned 游戏供观察。

先用 `build_probe.py` 创建全新带 marker 的隔离工程，再在冷启动前调用 `build_tree_assets(resource_pack)`，复制项目 `.mcdev.json`，使用受管 `host.py launch` 和 `resize --width 720 --height 1080`。已运行的实例只允许使用预装资源。

```powershell
python -B -X utf8 tools/runtime_packet_probe/run_tree_case.py --project <项目> --evidence <证据目录> --name tree64_static --bytes 65536 --seconds 6
python -B -X utf8 tools/runtime_packet_probe/run_tree_case.py --project <项目> --evidence <证据目录> --name tree64_incremental --bytes 65536 --seconds 6 --dynamic --reuse-config <证据目录>/tree64_static.config.json
.venv-reference/Scripts/python.exe -B -X utf8 -m unittest discover -s tests -p 'test_runtime_packet_tree*.py' -v
```

每次用新 case 名；超时后只读检查，不重放 mutation。静态后增量复用同一份驻留配置，不再注册或完整初始化。`--scan full` 为默认；`samples`／`none` 不得报告全量像素验收。history 上限 512 条，超出时显式标记不完整并拒绝完整 oracle 重放；这是开发探针，不是生产长时间运行队列。
