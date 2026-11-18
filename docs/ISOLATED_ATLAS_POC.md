# 不借用场景 RGBA 的共享数组概念验证

2026-11-18，Windows 网易 3.10.0.448891，RTX 4060 Laptop GPU，原生客户区 720×1080，60 FPS 上限。用户允许私有数据纹理用 RGB 存载荷，禁止场景 RGB／alpha 作为数据载体；随后要求停止反复测试大载荷全量更新，改为大数组驻留、每帧限量上传。3 KiB／帧是候选预算，尚未验证为可维持 60 FPS 的上限。

**96 B、64 KiB、128 KiB 均已完成原生客户端完整读取。** 隔离的数据通路成立，当前逐页汇聚的驻留渲染成本仍很高，增量传输产品实现尚未完成。

后续已完成[36 B 叶五叉树与限量更新实测](TREE_ATLAS_RESEARCH.md)：64 KiB 常驻及每帧 3,060 B 更新的最终状态全量正确，但静态约 15.82 FPS、增量约 15.42 FPS，尚未满足大数组 60 FPS。以下保留原线性链的历史结果，不能与后续树方案混为同一实现。

## 数据通路

```text
进入链前的画面 C0 → save（TEXTURE_0，完整 vec4） ───┐
                                                 ↓ TEXTURE_4
游戏 Python → 两个载荷 vec4／页 → 独立数据 RT 链 → consumer
                                     TEXTURE_3   ↓
                                      恢复 C0 或显示诊断
```

producer 只读当前页 uniform 与前一 producer 的私有 RT，不采样场景颜色。最后一个 RT 包含全部页，consumer 通过 `byteAt(index)` 实现 `A[i]` 和 `A[(i+A[i]+salt)%len(A)]`。同一 consumer 的 mode 0 恢复完整 C0，mode 1／2 显示对应诊断，矩形外始终返回完整 C0。

每页八个 uint24，共 24 B；逻辑数组长度与分配页数分开，填充不计载荷。每个 process 只用 EXTRA_VECTOR1..3，保留引擎 EXTRA_VECTOR4。先 disabled 注册、设参、连线并核对顺序，再在同一回调内启用；失败清理顺序为 producer→consumer→save，并记录清理失败。

## 原生正确性

| 载荷 | producer | 数据 RT | 直接读取 | 依赖读取 | 换代范围 |
| --- | ---: | --- | --- | --- | --- |
| 96 B | 4 | 8×4 | 三代各全 96 B | 三代各 96 query | 动态运行后再验证两代 |
| 64 KiB | 2,731 | 120×183 | 全 65,536 B | 全 65,536 query | 第二代首／中／尾采样 |
| 128 KiB | 5,462 | 168×261 | 全 131,072 B | 全 131,072 query | 按用户调整，复用原驻留代，不再写下一整代 |

上述检查全部零误差。每个诊断格检查原生 PNG 中的完整 3×3 RGBA patch；每窗最多 3,072 B。翻页只改查询地址，不替换源数据。直接读取覆盖全部不同源地址；依赖读取的目标有重复，query 数不等于不同目标地址数。源载荷和查询输出分别计算 hash。

128 KiB 原次扫描在直接读取前 86,016 B 通过后，被用户前台观察触发旧保护而中断，没有像素错误；失败记录保留。随后复用同一 namespace、words、seed 58201 与驻留数据，以 `--reuse-config --frozen-only` 完成两个模式各 43 窗全扫；没有重新注册、finish 或重写初代。

隐藏诊断后，三个容量的场景主体 `[0,64,720,1026)` 与无链基线逐像素相同，全截图差异仅位于顶部变化的开发文字。改变输入背景 phase 后，128 KiB 首 3,072 B 仍正确，支持载荷独立于场景颜色。

**WGC 没有暴露中间 RT 的真实 alpha，原生 alpha 完整保留仍未被上述对照证明。** 桌面 GPU 使用包含全部 alpha 字节值的背景，完整 RGBA 恢复通过；不扩张为所有原生颜色空间及 alpha 行为均通过。

## 驻留与更新成本

以下是用户调整前已取得的短时测量，后续停止重复扩大整代更新：

| 情况 | FPS 参考 | 样本 |
| --- | ---: | --- |
| 96 B 动态 | 60.08 | 8 秒，28 个引擎 FPS 样本 |
| 64 KiB 动态 | 9.69 | 8 秒，5 个 FPS 样本 |
| 128 KiB 无 Python 上传，保留 producer | 6.43 | 8 秒，3 个 FPS 样本；mean event interval 159.95 ms |
| 关闭研究链后的基线 | 60.08 | 8 秒，28 个 FPS 样本 |

每个 producer 每帧复制／更新整张 atlas，因此停止 Python 上传仍有大量 pass。关闭全部 producer、保留 save／consumer 后，首 3,072 B 有 3,059 格失败；恢复 producer 后完整 128 KiB 通过。这只否定当前连接方式的“停 producer 后仍可读取旧 RT”，不推断所有持久 RT 机制均不可能。

后续目标：先降低未更新数据的逐帧汇聚成本，再调度脏页，设置每帧字节和时间预算。初始化也分帧；3 KiB／帧作为候选。需要验证更新区、未更新区、跨页依赖及提交版本，不把最终静态正确当作每个动态帧正确。

目前没有任意 UI sampler 共享、移动端、GPU→游戏 Python 回读、跨帧持久 GPU 状态或每一动态帧正确的完整证据。

## 实现、证据与复现

- `tools/runtime_packet_probe/isolated_assets.py`、`isolated_runtime.py`：独立配置、资源与生命周期。
- `isolated_copy.fragment`、`atlas2d.fragment`、`isolated_consumer.fragment`：画面保存、载荷生产与消费。`isolated_reference.fragment` 仅为独立背景 fixture。
- `run_isolated_case.py`：原生全扫；`--frozen-only` 避免额外整代写入，`--reuse-config` 复用驻留数据且强制 `--seconds 0`。
- [小型结果摘要](evidence/isolated-atlas/summary.json)。原始命令、PNG、WGC 来源与逐窗结果：`.runtime/isolated-atlas-study/v1/evidence/`。
- 独立执行重放：3 case、6 generations、12 mode scans、142 PNG、412,224 有效 query、3,710,448 patch pixels，零错误；595 个输入 artifact 的 SHA-256 匹配。复用同一 oracle，不算第二套算法。见 [重放摘要](evidence/isolated-atlas/independent-replay-summary.json)。

```powershell
.venv-reference/Scripts/python.exe -B -m unittest discover -s tests -p 'test_runtime_packet_isolated*.py' -v
python -B -m unittest discover -s tests -p test_background_policy.py -v
python -B -m unittest discover -s tests -p test_start_background.py -v
```

23 项隔离资源／生命周期／GPU 检查、16 项后台与用户前台许可、4 项启动检查全部通过。GPU 检查包含 64 KiB 全量、32 代复用、完整 RGBA 恢复和断链负对照。

用户明确允许自行将测试游戏置于前台观察时继续 SDK／WGC 测试，采用显式 `MCDEV_ALLOW_USER_FOREGROUND=1`；仍保留实例身份、noactivation、可见和非最小化约束，agent 不激活窗口或发送桌面输入。截图如实记录实际窗口状态和前台许可。
