# 原生 RGB 混合输入与早期副本探针

2026-11-18 在网易版 `3.10.0.467018`、Windows OpenGL 完成 R2：**26 张实机截图全部 `exact=true`**。四个 layer 15 原生 FrameAni 特效通过公开 `SetMixColor` 传入实际 32 B payload；原生 RGB 混合后，三阶段 post 保留 raw coded 副本、恢复显示 RGB，并让后面的 consumer 从副本读取 payload。游戏 Python 不写文件。

结果仅覆盖本设备上有限次写入后的稳定态。512 KiB、实测 60 FPS、吞吐率、连续更新、跨帧原子更新及其他平台仍未建立。

## 数据与三阶段流程

32 个独立 byte 按 little-endian bit 流切为 43 个 6-bit symbol，bit 256、257 固定零。每个 symbol 的低/中/高两位分别进入 R/G/B：`s = R + 4*G + 16*B`。游戏 Python 将每四个 symbol 大端装入 uint24：`word=s0*262144+s1*4096+s2*64+s3`，通过 RGB 的 `word/2^24` 传入；每个特效三个 word、12 个 symbol，四页补齐至 48 个，只有前 43 个绘制。mix-color alpha `(page+1)/8` 只用于页编号。

shader 在固定 `[72,162,576,216]` ROI 中绘制 43 条 stripe，输出 `vec4(vec3(R,G,B)/3,192/255)`。材质请求 RGB `SourceAlpha/OneMinusSrcAlpha`、alpha `Zero/One`，并保留 `DisableAlphaWrite`。在线性 UNORM8 模型中，原目标 byte 为 `d`、两位值为 `q` 时，coded byte 为 `64*q + round(63*d/255)`；读高两位即可恢复 q，低六位提供有损背景残差。

三阶段 post 在特效写入后执行，早期副本不是写入前场景：

1. `copy.fragment` 复制 coded scene。公开 `PostPassResultToOtherPass(...,0,...,2,3)` 将 pass 0 结果连接到 pass 2 的 `TEXTURE_3`。
2. `restore.fragment` 在 ROI 中执行 `round((codedByte % 64)*255/63)` 恢复显示 RGB；直接传递输入 alpha，ROI 外保持原值。
3. `inspect.fragment` 在后面的 pass 读取早期 raw `TEXTURE_3`，即使前一 pass 已恢复显示 RGB，仍可提取 symbol 和任意地址的 byte。每 byte 从相邻两个 symbol 还原，位移循环为 0/2/4。

mode 0 将同一源像素的 raw RGB、raw alpha 灰度和 restored RGB 写为三个相邻输出像素；ROI 共 **124,416 个源像素**，输出区 `[0,500,720,519]`。mode 1 读 43 个 symbol；mode 2 做 32 byte identity 查询；mode 3 先用 `j=(131*i+29)%32` 读 byte，再以 `j=(j+3*byte+7)%32` 做 dependent 查询。consumer shader 不含 payload seed 或宿主数组。

## R2 实机结果

主证据：`.runtime/weather-effect-blend-native-20261118-r2/evidence/results.json`，schema `weather_effect_k2_blend32_v1`。

| 截图类别 | 数量 | 结果 |
| --- | ---: | --- |
| clear hidden baseline before/after | 2 | 两次完整 ROI 原背景逐像素一致，124,416 像素变化数 0；raw 与 passthrough RGB 也一致 |
| clear coded T3/T1 | 4 | 每张完整 ROI 的 wrong symbol 0、原生整数混合模型错误 0；restored 对稳定 baseline 的最大通道误差 2，误差超过 2 的像素 0 |
| clear symbol/identity/dependent | 9 | 三个宿主 payload × 三种查询，全部精确 |
| wet hidden passthrough | 1 | raw 与 passthrough RGB 完全一致，观察到 2,736 个低 alpha 像素 |
| wet coded T1/T3 | 4 | 每张完整 ROI wrong symbol 0，所有低 alpha 像素均正确解码 |
| wet symbol/identity/dependent | 6 | 两个 payload × 三种查询，全部精确 |

晴天四张 coded 帧为三个 payload 的 T3，以及最后一个 payload 的 T1。`clear-baseline-gate.json` 保存 before/after 完整 ROI 一致性和四张 coded 帧的整数混合/恢复误差 gate；这是晴天背景恢复误差的实测依据。

| 雨天结果 label | 低 alpha 像素 | 其中 wrong symbol | 3,888 个 32 像素块中，alpha 例外数 >4 的块 |
| --- | ---: | ---: | ---: |
| `031_wet_0_t1` | 2,962 | 0 | 7 |
| `031_wet_0_t3` | 3,307 | 0 | 7 |
| `031_wet_1_t1` | 3,132 | 0 | 46 |
| `031_wet_1_t3` | 3,144 | 0 | 10 |

alpha 例外定义为按源 ROI 线性顺序分块后 `Abyte != 255`。这些计数表明，旧的“每 32 像素最多四个 alpha 例外”格式在所测雨天帧会溢出。本轮没有运行该压缩器；consumer 直接读取早期 raw RGB 副本，绕过了这一限制。所有 coded 帧的 `restore_shader_vs_sameframe_raw_errors=0`，证明恢复 pass 与同帧 raw 残差公式一致。

**雨天结果不是真实背景 RGB 恢复误差的真值比较。** 本轮没有 writer 之前的同帧 RGB/Alpha oracle。材质请求保留 destination alpha，post shader 直接传递 alpha；同帧低 alpha 处 payload 可解码的证据，不能替代“writer 前后 alpha 逐像素不变”的独立验证，也不能把雨天 raw→restore 公式一致性写成雨天原始 RGB 的精确恢复。三联诊断只独立输出 raw alpha，没有独立输出恢复目标的 alpha，因此恢复 pass 的 Alpha 恒等当前也由 shader 代码机制支持。

## 保留的 R1 失败与修正

`.runtime/weather-effect-blend-native-20261118-r1/evidence/` 保留首张 hidden baseline 的失败截图、结果和日志。该版使用第四个 vec4 参数 `options`，期望绑定到 `EXTRA_VECTOR4`；实机没有按预期生效，hidden baseline 误启 restore，因此 gate 失败。这不是有效的 baseline 或完成的混合验证。

修正将控制复用到已使用的第三个参数：`EXTRA_VECTOR3.x = mode + 8*restore`；restore 判断 `>7.5`，inspect 用 `mod(...,8)` 取 mode。随后在全新的 `weather-effect-blend-native-20261118-r2` 目录重新按顺序执行，未覆盖 R1。该局部故障不扩张为所有第四参数绑定都不支持的结论。

## 条件、证据与复现

客户端为 `D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.467018/Minecraft.Windows.exe`，720×1080，原生 options 设置 60 FPS cap。受管 owner 为 `manim-weather-effect-blend`；WGC 要求新帧和 noactivation，agent 不激活窗口、不发送桌面输入，允许用户自行前台观察。设置 60 cap 不等于实测达到 60 FPS。

构建复用 order probe 的原生配置副本，仅覆盖 `sequence:billboard_base`；安装目录资产、原生雨/降水材质未修改。独立资源包复制原生 post 配置并将原有 enable 开关置 false，因此没有验证原生 bloom/景深等同时开启的组合。资源、命令和证据由宿主写入，游戏 Python 不写文件，也不使用私有纹理上传。

证据入口均相对仓库根目录：R2 的 `evidence/results.json`、`clear-baseline-gate.json`、`final-host-status.json`、逐帧 PNG/JSON、`launch.json`、`fps-options-receipt.json`；资源来源和 hash 见 `project/material_source_receipt.json`、`native_untouched_materials.json`、`probe_resources.json`。R1 失败与 R2 使用不同目录保留。

`evidence/audit.json` 保存最终独立审计摘要。26 张 PNG 和回执、全部来源哈希均通过；15 张查询进一步检查完整 720×519 输出区域，合计 5,605,200 个像素，RGB 错误为 0。11 张 mode 0 图中，诊断的 restored RGB 与屏幕实际源 ROI 全部逐像素相等。四张湿态图的 raw 与 restored RGB 在所有源像素均不同，误用 restored RGB 会在至少 121,438 个位置改变符号；late raw-copy 查询仍通过，证据不只依赖连接 API 的接受标记。

R1/R2 的 `evidence/cleanup.json` 均记录所属 session 为 stopped、原游戏主 PID 和 MCDK 不存在；R2 结束前已恢复 rainLevel 0、移除四个效果并关闭 oracle。没有关闭或更改其他实例。

以下从仓库根目录执行，需要 Windows、上述客户端、宿主 Python 3（含 Pillow/numpy）和已配置的 MCDK/WGC 调试环境。每次使用新的 `.runtime` 目录；检查各步退出码，失败时保留证据，不覆盖重跑。

```powershell
$probeRun = '.runtime/weather-effect-blend-repro-r2'
$gameExe = 'D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.467018/Minecraft.Windows.exe'
python -B -X utf8 tools/weather_effect_blend_probe/build_probe.py `
  --output "$probeRun/project" --game-exe "$gameExe"
python -B -X utf8 tools/weather_effect_blend_probe/host.py launch `
  --project "$probeRun/project" --evidence "$probeRun/evidence"
python -B -X utf8 tools/weather_effect_blend_probe/host.py resize `
  --project "$probeRun/project" --evidence "$probeRun/evidence" --width 720 --height 1080
python -B -X utf8 tools/weather_effect_blend_probe/runner.py `
  --project "$probeRun/project" --evidence "$probeRun/evidence"
python -B -X utf8 tools/weather_effect_blend_probe/host.py stop `
  --project "$probeRun/project" --evidence "$probeRun/evidence"
```

builder 不启动游戏。runner 的 finally 尝试恢复无雨、删除效果并关闭 oracle，但不关闭进程；执行后仍需 owner-bound `host.py stop`。正常关闭超时才在确认本次 session 后用同 project/evidence 的 `stop --force`，不按进程名称批量关闭。

本轮没有容量扩展、帧时间采样或持续吞吐测试。四次 `SetMixColor` 更新间的帧没有被观察，跨帧原子性未建立。背景恢复是每通道约六位残差的有损重建；晴天已测误差界不能自动推广到动态雨天、其他颜色路径或其他设备。**512 KiB 静态驻留且实测保持 60 FPS 的目标仍未完成。**
