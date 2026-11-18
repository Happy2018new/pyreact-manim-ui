# 场景压缩通路：512 KiB／60 FPS 研究

2026-11-18。用户已终止完全私有纹理上传路线，本轮只研究几何 RGB 输入、alpha 压缩保存和画面恢复。消费 shader 使用显式连接的后处理结果纹理仍属于此通路；不继续研究 uniform bank 或私有纹理树上传。沿用游戏运行时不写文件、后台 noactivation、60 FPS 上限和 owned session 规则。

## 顺序与判定

1. **RGB 异常。** 用已知原色的原生几何背景，经真实硬件混合测试全部 byte 值及 payload 符号；先验证背景本身，再验证编码 RGB、恢复误差及 alpha。post shader 合成 fixture 不计为硬件混合验证。旧首次 1,356 点／最大 52 的失败保留；受控样本通过也不能凭空为旧样本指定原因。
2. **真实 alpha 与效果。** 在测试世界检查水、玻璃、天气／粒子、发光与附魔相关场景中的 alpha 精度、每 32 点的例外数、数据覆盖及恢复。区分真实场景与合成边界 fixture。检查原生 bloom／DOF 等固定读取原始颜色的路径；恢复 T0 不能自动修复原始 T1，必要时预装定点派生的采样恢复材质，原效果参数和 pass 结构必须记录。overflow 不能被截断或统计为有效载荷。
3. **扩容与静态性能。** 依序 256／512 KiB，游戏内存生成、真实 geometry 输入、完整 identity／dependent 查询、负对照、冻结内容身份、初始化与内存观测。性能每档 2 秒暖机、25 秒样本，同分配 baseline 原生隐藏附件；分别报告 writer、压缩恢复与依赖查询的实际 pass 和启用的原生效果。暂不测试连续更新。

达到 60 FPS 只指本机固定客户端／视口／场景下的静态目标，不替代手机、任意业务 shader 或长期稳定性。颜色损失有既定量化上界，alpha 声称无损必须实际验证精度与覆盖，不从最终 WGC 的 alpha 推断中间渲染目标。

## 先验空间预算

k=2 输入每源像素 6 bit，32 个源像素对应 24 B 净载荷。512 KiB = 524,288 B，至少需要 `ceil(524288/24)=21846` 个块、**699,072 个源像素**。旧 720×1080 安全诊断带仅 673,920 点、505,440 B，不能装入完整 512 KiB。

扩容探针实际使用 1080×1440，source ROI `[8,128,704,993]`，对应 699,072 点、524,304 B 分配及 16 B padding。每页最多 65,536 个 6-bit Q-record，满页对应 48 KiB 的原始字节流；512 KiB 共 11 页，各页 palette 最多 `256×256×16`。这里按几何记录分页，不把 Q-record 错算为一个完整字节。

本机屏幕物理分辨率读取为 **2560×1600**。直接 alpha8 每点 1 B 的全屏原始预算为 4,096,000 B = 4,000 KiB = 3.90625 MiB（十进制 4.096 MB）。这是全屏每点均可用且渲染目标同分辨率时的预算，上轮已验证的直接 alpha 容量仍为 2 MiB，未进行全屏写满验收。

## 状态

三阶段研究已完成。**512 KiB 完整数组与本机静态约 60 FPS 目标在固定晴天、关闭原生后处理的隔离条件下通过；通用天气／原生效果兼容没有通过。** 第一阶段验证了受控原生混合的颜色上界，没有为旧异常确定原因；第二阶段保留了雨天载荷错误与 bloom 替换未证实的结果。旧的容量／64 KiB 性能基线见[上一轮报告](LARGE_ALPHA_AND_SCENE_CODEC_RESEARCH.md)。

## 第一阶段：受控原生混合

已通过真实 geometry 背景和 writer 的完整码域测试。背景仍走原生 block geometry，共享已验证的材质路径，以 source A=1 写入已知 `(x,(73x+19) mod 256,(151x+47) mod 256)`，不是 post shader 计算混合结果。背景锚点距相机 6，writer 为 3；反转创建／attachment 顺序各测试一次。几何中的每个 x／符号组合均由游戏内存构造。

| k | 每种顺序的源像素 | 覆盖 | encoded 对整数混合 | restored 对解码 oracle | 距已知原色最大差 |
| --- | ---: | --- | --- | --- | ---: |
| 1 | 2,048 | 256 个原色值 × 8 个 RGB 符号 | 0 错 | 0 错 | 1 |
| 2 | 16,384 | 256 个原色值 × 64 个 RGB 符号 | 0 错 | 0 错 | 2 |

24 张 domain 截图均符合预期结果，包含四张隐藏背景的负对照（每个被测像素均拒绝已知原色）。同帧 alpha 差值的 byte 诊断为零，但不单靠该 PNG 声称 subbyte 精度。实体距相机的选择属于本机实测路径，不是公开的跨阶段排序保证。

故意把同一 writer 画两次时，16,384 点全部符合连续两次 UNORM8 混合模型；payload 高位仍能通过，而恢复颜色全部超过预期误差，距原色最大差 191。这个负对照证明“数据读对”不能替代“画面正确”。它没有证明旧首次 1,356 点异常也是重复覆盖。

旧异常的独立位置分析得到：首次 1,356 点位于源区 bbox `[8,561,44,597]`，后来 writer-off 的 555 点变化位于 `[111,598,135,646]`，集合交集为零。以旧 baseline 为精确原色推导“同一 writer 恰好两次”后，1,356 点中没有一点在容差 2 内符合旧 restored。因此只能排除这个严格特定模型，不能给旧异常强行归因。

另一个自然场景重复测试保留了分时基线失败：off-repeat 相对 off-before 有 2,607 点变化；off-after 与 off-repeat 精确相同。encoded 与 off-repeat 的单次混合公式逐点相等，restored 距 off-repeat 最大 2。这次新失败可由不同截图时刻的原色变化解释，但不用于覆盖旧失败。冻结时间／关闭 mob 生成等接口回执也不等于画面已静止。

独立审计重放 38 张 PNG、114 个图片／state／receipt SHA256 和 52 个命令 SHA256；没有导入原 codec／verifier。完整证据在 `.runtime/scene-codec-native/rgb-domain-evidence-v4/`，旧异常模型分析在 `.runtime/scene-codec-historical-rgb-audit-20261118/`。

## 第二阶段：真实场景与原生效果

真实水／玻璃、发光方块与附魔物品、可见半透明粒子的 64 KiB identity／dependent 均通过，alpha 恢复 byte 诊断也通过。三类特征都实际出现在截图中，未仅以创建 API 成功作验收；每类的 87,424 个源点在所拍 alpha 图中均为 255。结果仅属于当前材质／距离／相机与帧，不推广到所有透明物。

**雨天发现真实载荷失败，尚未关闭**：一张 alpha 采样中 300／87,424 点非 255，另帧分块最多两个例外、没有 overflow；但 identity 290／65,536 错（最大 162），dependent 386 错（最大 237）。同帧 alpha byte 差值仍为零。确认原生 bloom／DOF 的实际 flag 均关闭后，late identity 仍有 83 点错误、最大 166，原始 RGB 的 Q 符号有 68 点沿雨线差异。这不是压缩块例外预算不足，alpha fallback 不能单独修复 RGB 的污染；未添加不适用于该失败的 overflow fallback。

同帧诊断从同一个 raw texel 编码“Q 符号错误／原 A／残差 flag”。两个 solid 控制帧全零；五个雨帧的坏 Q 数为 617／1,740／241／72／448，全部落在对应原 alpha 非 255 的像素，`badQ && A255` 始终为零，残差 flag 始终为零。自然动态雨中不使用不同时刻的 alpha 图与 Q 图作逐像素因果对照。

本机原生雨 shader 的纹理槽是雨纹理、地形遮挡／亮度和 lighting，没有 scene-color fetch。普通雨混合会改变已编码 RGB；同帧结果支持天气在 writer 后混合的解释，但没有 GPU draw-call trace。目前未找到可以保证 actor block geometry 晚于天气绘制的公开 API。关雨、删除雨片元或遮挡天气会改变原画面，不能计为通用修复；单独修复 payload 的冗余码也不自动恢复正确雨色。本轮没有扩大为新的上传方案，雨天兼容继续开放。

另一个原生生命周期事实已保存：调用原生效果名的 `SetEnableByName` 会重建后处理链，动态 `AddPostProcess` 注册随之消失；返回值和实际开启 flag 也不总与请求一致。兼容 runner 先切原生状态、等待、再安装并连接自定义链；不能把原生切换成功回执当作旧动态链依旧存在。

原生效果 overlay 离线保持参数、pass 数、RT、shaderPassName 和原生数学，只派生最终材质中对原始 T1.rgb 的采样恢复。实际加载另外用诊断包验证：派生 bloom final 恒输出洋红、DOF final 恒输出青色，并在同一包用自定义 pass 直接运行相同材质作阳性。

| 请求用例 | 实测重点 |
| --- | --- |
| 请求关闭原生效果 | setter 返回 false／false、实际 bloom flag 仍 true；没有哨兵颜色，不能称为确认 native-off 基线 |
| 请求 bloom-only | 无洋红，不能证明 native bloom final 执行 |
| 请求 DOF-only／both | 各有 672,415 个青色点，DOF 派生 final 实际执行；DOF-only 的实际 bloom flag 仍 true |
| 自定义 pass 直接运行派生 bloom／DOF 材质 | 分别有 672,415 个洋红／青色点，证明两个 shader 资源都可加载和执行 |

安全诊断区域共 673,920 点，其中另有 1,505 点被游戏 UI 覆盖，故未将哨兵覆盖数错误记为全区。DOF 的“shader 确实执行”不等于已完成无载体身份等价；native bloom 替换没有成功证据。合成 alpha=0／127／128／255 的 RGB 结果逐点相同，未观察到预期 bloom 阈值响应；且先前雨转晴画面亮度漂移，不能把分时差异写成原生效果贡献。未继续运行预构建 identity 包或扩大为原生引擎改写。

独立审计重放 64 张 PNG、192 个图片／state／receipt SHA256 和 83 个命令 SHA256，保留 `all_native_compatibility_passed=false`、`native_bloom_replacement_succeeded=false`。证据索引 `.runtime/scene-codec-compat/stage2-summary.md`，审计 `.runtime/scene-codec-compat/newindependent-compat-audit.json`。本阶段所有 owned MC 已以非 STILL_ACTIVE 退出码确认停止；某些进程对象仍被句柄保留，未声称这些对象全部消失。

## 第三阶段：扩容与性能

256 KiB 首次原生完整 identity／dependent 和 349,888 点源区 integrity 已零错，负对照拒绝 261,088／262,144 结果；但原生 bloom flag 仍为 true，隔离 gate 主动中止，在该次运行中没有采集 FPS 或提交 512 KiB。失败证据保留于 `.runtime/scene-codec-large-native-20261118-r1/`。

最终 r2 使用完整原生 post 配置的离线派生，仅修改 enable 为 false，参数／pass／材质／渲染顺序不改，启动及采样实际读取九个原生 flag 均为 false。测试为单活动 MC、1080×1440、固定晴天、time=6000、60 FPS 上限、noactivation 和被动 WGC。baseline 保留一个明确 passthrough copy pass，writer 比较也保持同一个 copy pass，避免全自定义链关闭的引擎重置；正式性能的 pass 口径为 **copy baseline 1／writer+copy 1／restore 3／dependent 4**。

| 逻辑容量 | source ROI `[x,y,w,h]` | 源像素 | 分配载荷 B | padding B | 活跃页 |
| --- | --- | ---: | ---: | ---: | ---: |
| 256 KiB | `[8,128,704,497]` | 349,888 | 262,416 | 272 | 6 |
| 512 KiB | `[8,128,704,993]` | 699,072 | 524,304 | 16 | 11 |

两档均在测量前后完整检查 identity、dependent 与所有源像素 integrity，正向 query 和 guard 均为零错误。共 19 张原生截图，其中 17 张正向累计 **6,992,000 个 query 像素**；没有剔除数据像素。两个隐藏几何负对照分别检出 261,088／262,144 和 522,157／524,288 错误，恢复几何后全量通过；10 个错误 generation oracle 全部拒绝。

独立审计不导入原 encoder／verifier，重新计算 17 页的 PRNG、6-bit packing、全局偏移、sum32、host SHA256 和零 padding，并检查 141 条命令及 141 份回执的哈希与冻结身份，重放所有 PNG 和八组原始计时向量。审计通过，且其自检能检出 query／guard 单字节篡改和删除长帧。GPU integrity 逐源点建立 decoded alpha byte 误差零及无 overflow；原始 alpha header 字节没有单独截图，不能把 CPU header 模型检查声称为原始 header 的 GPU 读回。

每档 2 秒暖机、25 秒采样，原始 GetFps 和 render interval 向量完整保留。dependent 档每帧执行完整逻辑长度的依赖查询；源区、诊断区和 guard 分开布局，不能把查询截图看作正常玩家画面。

| 容量 | profile | 自定义 pass | GetFps 均值 | 间隔均值 ms | p99 ms | 最大 ms | >33.3 ms 次数 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 256 KiB | copy baseline | 1 | 60.07751 | 16.66724 | 18.0588 | 24.9390 | 0 |
| 256 KiB | writer+copy | 1 | 60.07751 | 16.66614 | 18.0883 | 25.1906 | 0 |
| 256 KiB | restore | 3 | 59.89983 | 16.71745 | 18.0962 | **90.6435** | **1** |
| 256 KiB | dependent | 4 | 60.07519 | 16.66689 | 18.0615 | 25.1567 | 0 |
| 512 KiB | copy baseline | 1 | 60.07826 | 16.66802 | 18.1196 | 25.9826 | 0 |
| 512 KiB | writer+copy | 1 | 60.07751 | 16.66685 | 18.0818 | 24.6797 | 0 |
| 512 KiB | restore | 3 | 60.07751 | 16.66659 | 18.0782 | 25.3580 | 0 |
| 512 KiB | dependent | 4 | 60.07751 | 16.66641 | 18.0127 | 25.7111 | 0 |

256 KiB restore 的一次 90.6435 ms 长帧原样保留，没有删掉或重新采样。该档为 99 个 FPS／1,495 个间隔样本，其余七档为 100／1,500。GetFps 约 60.08 属于计时读数，不能解释为修改了 60 上限。限帧测试不能推出未限帧吞吐、GPU 时间或剩余性能空间；静态不再从 Python 上传仍需 GPU 每帧执行几何和编解码。

512 KiB 时共驻留 17 页，包括旧 256 KiB 的六个隐藏页和当前 11 页；17 次 attempt／17 次 build，合计 786,720 B 分配载荷和 1,048,960 Q-record。这些是逻辑资源计数，**不是 native／GPU 实际内存字节**。观测到系统可用 commit 约 13.4 GB 降至 12.9 GB，但没有隔离进程／GPU 分配测量，不能把这个差额全部归因于 payload。

运行包 r2 的 baseline 方法早于本地 copy-profile 修正，原包没有被事后改写；实机用保存且带 SHA256 的显式 host commands 实施等价 1-pass controls。实际 enabled／order 和冻结身份回执都在独立审计中检查，不能拿当前本地源码替代当时运行包。资源 bundle SHA256 为 `3cd4e7ee11091aae049bc360fecf85977e0c8e5ca1914220a4a7b25767923806`。

此 bundle 只覆盖 `source_manifest.json` 的显式输入，base builder 传递带入的部分模板／入口／调度器未全部计入，不能单凭此值声称完整构建包可重建。完整保存的运行包、输入清单、命令和原生结果共同界定本轮证据。

最终 attachment 全隐藏，自定义和原生 enabled 列表为空。owned PID 47332 自然退出，session `085c31a07f354b02926e512fbea7bce2` 已 stopped；首次 normal stop 的 10 秒超时保留，随后只读确认退出，没有 force stop。释放记录中活动 MC 为零，两个零线程进程残留对象不算运行实例。

## 证据与交付边界

- 开发工具：[原始 codec](../tools/scene_codec_probe/README.md)、[真实场景／原生 overlay](../tools/scene_codec_compat_probe/README.md)、[大容量探针](../tools/scene_codec_large_probe/README.md)。
- 独立重放脚本：[码域](../tools/independent_scene_codec_domain_audit.py)、[兼容](../tools/independent_scene_codec_compat_audit.py)、[大容量／帧率](../tools/independent_scene_codec_large_audit.py)。这些脚本不导入被审计的 encoder／verifier。
- 小型审计归档：[证据索引](evidence/scene-codec-512k/index.json)。大 PNG、完整运行包、原始向量及命令在 `.runtime/` 保留，不提交 Git。
- 第三阶段完整结果：`.runtime/scene-codec-large-native-20261118-r2/evidence/large_codec.results.json`；独立报告：同目录 `independent-large-codec-audit.json`。

本轮聚焦回归为原 codec 16 项、兼容 helper 13 项、大容量探针 9 项，共 **38 项通过**；额外独立审计及其变异自检也通过。没有为了收尾再次启动 MC。

本轮不测试连续更新，不实现游戏运行时写文件，不改变产品渲染路线，也不宣称手机、任意业务 shader、雨天、bloom 或全部透明物兼容。下一项生产化前置工作应解决天气与 writer 的执行关系以及原生后处理的原始输入恢复；尚无公开可用排序入口时应保留限制，不能通过关闭雨冒充修复。

## 后续实验：透明几何体与原生雨

在网易客户端 3.10.0.448891 上，对同一份 64 KiB 载荷和同一个几何体依次做默认、透明、恢复默认对照。两次运行分别向 `SetActorBlockGeometryTransparency` 传入 1.0 和 0.5，调用前先用 `EnableActorBlockGeometryTransparent` 启用透明。固定 720×1080，源区 87,424 点，关闭并读取确认九个原生后处理开关。两包的 16 份 shader 与材质文件逐字节一致。以被动截图检查同一个 raw texel 的 6-bit 数据符号和原始 alpha，并分别检查全量直接读取、依赖读取和 alpha 分块。

| 透明参数 | 晴天全量读取 | 雨天直接读取错误数／每张 65,536 字节 | 雨天依赖读取错误数／每张 65,536 次 |
| --- | --- | --- | --- |
| 1.0 | 0 错 | 273、29、110、114、347 | 869、461、637、408、465 |
| 0.5 | 0 错 | 126、158、118 | 5,149、294、279 |

两个参数的雨天全量读取均失败，恢复默认后仍能复现。透明组的所有坏符号都落在同次取样中 alpha 非 255 的源像素上。0.5 组的三张 alpha 分块诊断均未溢出，说明 RGB 载荷能在 alpha 压缩之前独立被污染。整个测试里也观察到一个 32 像素块最多有 **9 个 alpha 例外**，现有格式只能保存 4 个。各诊断截图取自不同雨帧，不能用跨图的数量差推断透明参数让污染增加或减少。

本机 `data/shaders/glsl/rain_snow.fragment` 从三个纹理槽读取雨雪贴图、地形遮挡和光照，输出雨色和透明度。`data/resource_packs/vanilla/materials/ui3D.material` 中的 `precipitation` 使用 `SourceAlpha`／`OneMinusSrcAlpha`，GPU 把雨色混合到当前场景目标，且材质未禁用 alpha 写入。源码和数据支持雨在几何载体之后修改场景颜色的解释。透明 API 未建立晚于天气的绘制顺序，原生调用顺序没有 GPU 跟踪。原生资源里的雨片元没有场景颜色绑定，搜索展开资源也未发现可直接复用的 framebuffer fetch。落地水花另使用 `minecraft:rain_splash_particle`，本实验未逐条分离两类绘制调用。

一次几何体绘制中，顶点和片元调用只获得当前顶点或图元分配的数据。uniform 能提供数组长度，普通片元输出与几何属性没有全局完成计数或同步机制。GPU 还要对片元输出做混合才会写入场景目标。现有探针借助后续绘制采样已完成的结果纹理来实现任意索引。若引擎以后提供可直接绑定的只读数据缓冲，消费 shader 可在自己的绘制中读取，那么几何转纹理这一步可以省掉。

1.0 的已知色对照因编码图与背景逐点相同而无效，无法据此验证透明模式下的 RGB 恢复精度。0.5 跳过此对照。1.0 在 81 张截图完成后遇到清理错误，随后只读确认载体隐藏、效果关闭，实例自然退出。该运行另有一项生成后覆写的元数据哈希不符，其他生成文件仍匹配。0.5 的 45 张截图及清理均完成，生成文件哈希吻合。两个实例均已释放。

独立审计重放 126 张截图，检查 8,762,368 个查询像素和 74,803,712 个保护区域像素，保护区零错误。候选失败，研究停在 64 KiB。晴天 512 KiB／60 FPS 的既有结论适用范围不变。运行结果与审计位置见[归档索引](evidence/rain-geometry/index.json)，离线复查方式见[透明几何体探针](../tools/rain_geometry_probe/README.md)。
