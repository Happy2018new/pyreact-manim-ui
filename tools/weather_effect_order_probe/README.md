# 原生帧动画特效与雨天采样探针

2026-11-18 在网易版 `3.10.0.467018`、Windows OpenGL 上完成 R1 和 R2。R1 验证了特效层级与雨天 RGB 覆盖的关系；R2 在同一条件下，经四个公开 `FrameAniControl.SetMixColor` 控制传入宿主选择的任意 32 字节数组，并验证稳定态的直接画面、同源 RGB/Alpha 配对及后处理索引读取。游戏 Python 不写文件。

结果限定为这台设备和该原生客户端上的有限次写入后稳定态。**尚未建立 512 KiB 容量、实测 60 FPS、吞吐率、连续更新、跨帧原子更新或其他平台兼容性。** 这是小容量通路与渲染顺序探针，不是已完成的大容量数据通路。

## 实现与测量方法

| 阶段 | 传入数据 | 特效端处理 | 能证明的范围 |
| --- | --- | --- | --- |
| R1，`--mode scalar` | 一个标量 seed，经公开 `SetMixColor` 的红色分量传入 | `effect.fragment` 根据 seed 和条带编号过程生成 32 个 byte 标记 | 层级、雨天覆盖和采样顺序；这 32 字节不是任意 payload |
| R2，`--mode packed` | 游戏 Python 的 `write(values)` 接收宿主实际提供的 32 个整数 byte | `effect_packed.fragment` 从四个特效的 mix color 解包 byte，不含 payload seed | 已测试数组在该客户端上的有限次传输和稳定态读取 |

R1 的 byte 公式为 `s = (seed + 43*i) % 251`、`b = (s*s + 17*s + 73*i) % 256`。R1/R2 均将 byte 显示为 `(b, (71*b+43)%256, (131*b+17)%256)`，让 RGB 三个通道共同参与精确比较。

R2 每个特效承载九个 byte：每三个 byte 合并成一个 uint24，分别通过 RGB 传入 `word / 16777216.0`；alpha 为 `(page+1)/8`，其中 `page=0..3`。四页覆盖全局 32 条 stripe，最后一页只用五个 byte，其余补零。shader 使用 highp，按 `floor(component * 16777216.0)` 解码，不能在该 uint24 运算中加 `0.5`；再按 `65536/256/1` 提取高、中、低 byte。每页 discard 自己范围外的 fragment，输出 alpha 为 1。

构建器读取已安装客户端的原生 `sfx.material`，完整复制后仅修改 `sequence:billboard_base`，其余 material 条目保持一致。覆盖项使用 RGB `One/Zero` 和 `DisableAlphaWrite`，因此可写入标记 RGB 并保留场景原有 alpha。原生 `point_sequence` 等继承链保留；没有使用未经确认的 frame `materialname` 字段。`material_source_receipt.json` 保存来源与生成文件的 hash；`native_untouched_materials.json` 记录未覆盖材质。原生 precipitation/weather/particle 材质和降水 shader 未修改。

隔离资源包还完整复制原生 `graphics_settings/post_process.json`，仅将原有 `process_array[*].enable` 置为 false，再安装探针 oracle。因此结果没有覆盖原生 bloom、景深等后处理同时开启的情况，也不代表原始 post 开关组合已验证。

`effect.vertex` 将有效区固定到 720×1080 画面的 `[72,162,576,216]`，共 **124,416 个源像素**。`post.fragment` 提供三种读取模式，T0/T1 分别指 `TEXTURE_0` / `TEXTURE_1`：

- mode 0：从一个源 texel 一次读取 RGBA，将 RGB 与 alpha 灰度写到相邻输出像素。配对来自同一纹理、同一帧、同一源像素；输出区为 `[0,600,720,346]`。
- mode 1：identity 索引，读取 32 条 stripe。
- mode 2：dependent 索引；先取 `j=(131*i+29)%32`，读取该位置的红色 byte，再用 `j=(j+3*byte+7)%32` 决定第二次读取的位置。reader shader 中不包含宿主 payload。

runner 在控制调用后等待稳定，再取新的 WGC 帧。它没有观察四次 `SetMixColor` 写入之间的帧，因此不能证明多特效更新具有跨帧原子性。

## R1：层级与原生雨天覆盖

主证据为 `.runtime/weather-effect-order-native-20261118-r1/evidence/results.json`。晴天 `layer 1/15 × seed 42/201 × T0/T1` 的八次 pair 比较，每次 124,416 个源像素 RGB 全部精确。

雨天主轮使用 seed 201、T0，结果如下。低 alpha 指采样到的 alpha byte 小于 255；表中是每次独立采集的统计，不能跨截图逐像素配对。

| 雨天采集 | layer 1 RGB 错误 | layer 1 低 alpha | layer 15 RGB 错误 | layer 15 RGB 完整且低 alpha |
| --- | ---: | ---: | ---: | ---: |
| 0 | 3,572 | 3,572 | 0 | 3,097 |
| 1 | 3,494 | 3,494 | 0 | 2,577 |
| 2 | 3,171 | 3,171 | 0 | 3,115 |

layer 1 的 RGB 错误集合恰等于同源配对中的低 alpha mask：`corrupt_rgb_and_alpha_not255_pixels` 等于所有 RGB 错误，`intact_rgb_and_alpha_not255_pixels=0`。layer 15 的全部源 RGB 精确，同时存在上表数量的低 alpha 像素。这建立了该配置下 layer 15 能在雨天覆盖后写回标记 RGB、并保留同一源纹理中雨天 alpha 的实机见证。

补充验证保留了两轮独立证据，不能将首轮失败删除或计为通过：

- `evidence/focused_wet/` 是首轮失败记录。Python 对象仍报告 `installed=true`，但 `001_recreate.state.json` 的 `actual_post_order` 已没有 `weather_effect_oracle`，随后调用报 `Post sampler control rejected`。这轮没有形成有效的 focused 画面结果。
- 确认实际 order 缺失后，在同一实例中重新安装 oracle 一次，结果写到 `evidence/focused_wet_retry/`。T1、layer 15 的三次 pair 低 alpha 数为 **4,594 / 3,484 / 4,458**，每次 124,416 个源像素 RGB 全精确，且所有低 alpha 像素的 RGB 完整。
- retry 的 `query_results.json` 中，`seed 42/201 × T0/T1 × identity/dependent` 共八项查询全部精确。

当时的 focused 操作脚本保留在 `.runtime/weather-effect-order-native-20261118-r1/focused_wet.py`，用于复查过程。它依赖当时仍存活的实例和固定历史目录，不是可直接重跑的通用 CLI；原实例现已关闭。

## R2：宿主任意 32 字节稳定态通路

主证据为 `.runtime/weather-effect-order-native-20261118-r2/evidence/results.json`，schema 为 `weather_effect_packed32_v1`，共 **25 项，全部 `exact=true`**。三个数组直接来自宿主：包含 byte/uint24 边界模式、一个宿主 SHA-256 digest 和另一组边界模式；digest 也以完整 byte list 传入，GPU 不使用 seed 生成 payload。数组和 hash 保存在每项结果中。“任意”描述输入接口可接收独立 byte 数组，不表示穷举了所有 32 字节组合。

| 项目 | 数量 | 覆盖 | 结果 |
| --- | ---: | --- | --- |
| direct | 3 | 三个宿主 32 字节数组 | 全部精确 |
| clear pair | 4 | 三个 payload 的 T0，以及最后一个 payload 的 T1 | 每项 124,416 源像素 RGB 全精确 |
| clear query | 6 | 三个 payload 的 T0，identity/dependent | 全部精确 |
| wet pair | 4 | 两个 payload × T0/T1，layer 15 | 每项 124,416 源像素 RGB 全精确 |
| wet query | 8 | 两个 payload × T0/T1 × identity/dependent | 全部精确 |

四次 wet pair 均有原生雨天 alpha 见证：

| 结果 label | RGB 错误 | 低 alpha | RGB 完整且低 alpha |
| --- | ---: | ---: | ---: |
| `030_wet_0_t0_pairs` | 0 | 3,078 | 3,078 |
| `030_wet_0_t1_pairs` | 0 | 2,989 | 2,989 |
| `030_wet_1_t0_pairs` | 0 | 3,350 | 3,350 |
| `030_wet_1_t1_pairs` | 0 | 3,232 | 3,232 |

`evidence/audit.json` 记录了独立 PNG 审计：重新检查全部 25 张 PNG，将 direct 扩大到完整源 ROI，将 identity/dependent 扩大到完整 720×346 输出区，合计 **4,856,256 次 RGB 三元组比较，0 错误**。源码、生成资源与材质 hash 匹配；原生降水材质 hash 未变化；采集均为新帧、noactivation，且采集前后前台窗口未被改变。

## 实机条件与证据位置

- 客户端：`D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.467018/Minecraft.Windows.exe`，Windows OpenGL。
- 画面：客户端有效区 720×1080，无损 PNG，`Windows.Graphics.Capture`；采集验收要求 `frame_qpc_100ns >= request_qpc_100ns`。
- 窗口：受管 owner 为 `manim-weather-effect-order`，窗口受 noactivation 保护；agent 不激活窗口、不发送桌面输入。launch 明确允许用户自行前台观察，receipt 为 `background_only=false`、`user_foreground_allowed=true`、`agent_activation_allowed=false`，不能描述为禁止用户手动前台的测试。
- 帧率：原生 roaming options 中设置 60 FPS cap，关闭无限帧率。`fps-options-receipt.json` 记录实际 options 路径；该配置不是帧时间测量。
- 文件写入：资源构建、命令脚本、PNG 和 JSON 证据由宿主开发工具输出；游戏 Python 仅调用 API，不写文件，也不使用私有纹理上传。

证据均放在 `.runtime/`，不作为大体积文件提交 Git：

| 路径（相对仓库根目录） | 用途 |
| --- | --- |
| `.runtime/weather-effect-order-native-20261118-r1/evidence/results.json` | R1 主轮晴天、雨天及隐藏对照 |
| `.runtime/weather-effect-order-native-20261118-r1/evidence/focused_wet/` | 首轮 stale oracle 失败证据 |
| `.runtime/weather-effect-order-native-20261118-r1/evidence/focused_wet_retry/results.json` | R1 T1 雨天同源 pair |
| `.runtime/weather-effect-order-native-20261118-r1/evidence/focused_wet_retry/query_results.json` | R1 八项 identity/dependent 查询 |
| `.runtime/weather-effect-order-native-20261118-r2/evidence/results.json` | R2 全部 25 项，含 payload、状态及逐项指标 |
| `.runtime/weather-effect-order-native-20261118-r2/evidence/audit.json` | R2 独立 PNG、来源 hash、采集及范围审计 |
| `.runtime/weather-effect-order-native-20261118-r2/project/material_source_receipt.json` | 原生 material/post 来源及精确覆盖范围 |
| `.runtime/weather-effect-order-native-20261118-r2/project/probe_resources.json` | 打包模式、运行时边界与源码 hash |
| 各轮 `evidence/launch.json`、`fps-options-receipt.json`、逐帧 `.json` | 启动、帧率配置和被动 WGC receipt |
| 各轮 `evidence/cleanup.json` | 所属游戏和 MCDK 进程关闭确认 |

R1/R2 都已完成清理，`cleanup.json` 均为 `state=stopped`，所属 game/MCDK 进程均已不存在。R2 先恢复无雨、删除四个效果并关闭 oracle；正常关闭超时后，在校验 owner、project 和进程创建身份后使用 owner-bound force。没有操作其他实例。

## 已核对的文档事实

以下来自 MCP ModSDK 文档和所测版本的原生资源；文档承诺与实机结果分别陈述。

| 事实 | 来源及限制 |
| --- | --- |
| `CreateEngineSfxFromEditor` 从编辑器特效 JSON 创建特效，返回 id 或 None，创建后需播放 | ModSDK `ClientSystem.CreateEngineSfxFromEditor` 文档 |
| `FrameAniControl.SetMixColor` 使用 RGBA float，范围 `[0,1]`，返回 bool | ModSDK 同名接口；文档没有承诺 RGB uint24 分数的精度。R2 仅补充了该客户端和所测数组的实机证据 |
| `SetLayer` 文档范围 0..15，默认 1；非 1 开启特效分层，较大层级较后 | ModSDK `FrameAniControl.SetLayer`；与原生雨的具体先后关系采用本探针实测结果 |
| frame `blend_mode` 默认 1，1 为标准透明 alpha 混合，2 为加色混合 | `NeteaseGuide/mcguide/16-美术/9-特效/70-中国版特效属性详细说明.md` 的序列帧“混合模式 blend_mode”段；0 没有文档映射，90 文档没有给出另一套映射 |
| `materialname` 只在已查文档的粒子属性段得到确认 | 不能据此推断 frameeffect 也支持该字段；本探针使用隔离的原生 sequence material override |
| 原生帧动画 mix color 进入 `EXTRA_VECTOR3` | 所测客户端 `shaders/glsl/sfx.fragment` 中 `vec4 SFX_MIX_COLOR = EXTRA_VECTOR3`，并用于最终颜色乘法；`uniformExtraVectorConstants.h` 声明对应 uniform |

## 复现实机命令

以下 PowerShell 命令从仓库根目录执行，需要 Windows、上述已安装客户端、宿主 Python 3/Pillow 和已配置的 MCDK 受管调试环境。运行链复用 `.agents/skills/pyreact-debugging/scripts`、`tools/start_dev.py`、`tools/capture_owned.py` 及 sibling `better-building-editor` 的 WGC helper。构建本身不启动游戏；launch、resize、runner 和 stop 都操作该次创建的受管实例。

每次选择全新的 `.runtime` 目录，保留历史证据；builder 拒绝覆盖已有项目，launch 拒绝覆盖既有 receipt，runner 拒绝复用已有 `commands` 目录。逐步执行并检查退出码；runner 失败时先检查对应 log，不要覆盖原证据重放。

```powershell
$probeRun = '.runtime/weather-effect-order-repro-r2'
$gameExe = 'D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.467018/Minecraft.Windows.exe'

python -B -X utf8 tools/weather_effect_order_probe/build_probe.py `
  --output "$probeRun/project" --game-exe "$gameExe" --mode packed

python -B -X utf8 tools/weather_effect_order_probe/host.py launch `
  --project "$probeRun/project" --evidence "$probeRun/evidence"

python -B -X utf8 tools/weather_effect_order_probe/host.py resize `
  --project "$probeRun/project" --evidence "$probeRun/evidence" --width 720 --height 1080

python -B -X utf8 tools/weather_effect_order_probe/runner_packed.py `
  --project "$probeRun/project" --evidence "$probeRun/evidence"

python -B -X utf8 tools/weather_effect_order_probe/host.py stop `
  --project "$probeRun/project" --evidence "$probeRun/evidence"
```

R1 主轮使用另一全新目录，将 `--mode packed` 改为 `--mode scalar`，并将 `runner_packed.py` 改为 `runner.py`。R1 focused retry 是上面说明的历史补充验证，不在通用 runner 内。

runner 的 finally 会尝试恢复无雨、移除特效和关闭 oracle；它不会关闭游戏进程，运行后仍需执行 `host.py stop`。如正常关闭超时，先核对本次 `launch.json` 对应的 session，再使用同一 project/evidence 的 `stop --force`；该入口校验 owner/project 和所属进程身份，不使用按名称批量结束进程的方式。

## 尚未建立的能力

当前只建立了 32 B、四个特效、有限次写入后稳定读取。未做容量扩展、GPU/CPU 时间或实际 FPS 采样、吞吐率测量、连续上传，也未证明四次控制调用在同一帧原子生效。Android、其他客户端版本、其他 GPU/精度实现及原生 post 开启组合都需要重新验证。

按每个特效九个 byte 直接外推，512 KiB 至少需要 `ceil(524288/9) = 58,255` 个特效/draw 载体；当前实现还存在最后一页填充。这只是容量算术，不能作为性能结论或推荐方案。**512 KiB 静态驻留且实测保持 60 FPS 的目标尚未完成。**
