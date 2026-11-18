# 场景恢复与着色器取数的同帧探针

这个独立探针沿用批量测试的 compact8 方块调色板、两份几何、原生 stencil 和晚期序列帧。每个字节分布在四个相邻像素的红通道高两位。玩家画面和接收端按各自需要使用同一份编码像素。

三个自定义后处理按顺序执行。第一步复制编码场景。第二步从副本恢复源区 RGB，同时传递采到的 alpha。第三步从当前位置的恢复画面取背景，并通过 SDK 显式连接的 TEXTURE_3 读取保存的编码场景，解码任意地址。诊断可以另从 TEXTURE_4 检查恢复结果。可见用例的 16 根柱形从数组不同位置取值，字节决定柱高和颜色，最后的 shader 透传柱形以外的场景。

720×1080 的 64 KiB 用例使用源区 [8,128,512,512]。第 12 层的已知颜色参考覆盖完整源区，图案在每个 RGBA 通道遍历全部 256 个值。对照先检验参考实际画出来的颜色，再启用三层数据特效和恢复。雨天直接从同一帧的副本和恢复纹理读取 alpha。已知参考在晚期编码前给出了可核对的 alpha；真实雨帧的两个采样都在晚期编码之后。

原生 UI 测试使用普通 JSON UI 图像和 clips_children 面板。实体轮廓测试使用当前客户端自带的原生描边材质对。纯画面用例使用可见柱形；原生夹具与全量读回同屏时，诊断区从 y=650 开始，保留上方夹具并覆盖全部数据和剩余诊断像素。

## 复现

使用当前安装的 3.10.0.467018 客户端，在仓库根目录运行。全程使用同一个后台 noactivation 受管实例，帧率上限固定为 60 FPS。每页原生几何提交前检查至少 4 GiB 的系统可用提交量。下方各证据目录首次运行须为空。

```powershell
$run = '.runtime/weather-stencil-integrated-repro'
$game = 'D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.467018/Minecraft.Windows.exe'
python -B -X utf8 tools/weather_stencil_integrated_probe/verify.py --self-test
python -B -X utf8 tools/weather_stencil_integrated_probe/build_probe.py --output "$run/project" --game-exe $game --include-ui --include-outline
python -B -X utf8 tools/weather_stencil_integrated_probe/host.py launch --project "$run/project" --evidence "$run/evidence"
python -B -X utf8 tools/weather_stencil_integrated_probe/runner.py --project "$run/project" --evidence "$run/evidence"
python -B -X utf8 tools/weather_stencil_integrated_probe/compat_runner.py --project "$run/project" --evidence "$run/compat-evidence" --previous-evidence "$run/evidence"
python -B -X utf8 tools/weather_stencil_integrated_probe/host.py stop --project "$run/project" --evidence "$run/evidence"
```

初始 runner 会保留实例供同一会话内的兼容性复测。两条夹具的运行接口见 [原生 JSON UI 裁剪](../integrated_ui_clip_fixture/README.md)和[原生实体描边](../integrated_outline_fixture/README.md)。实测结果见[主研究报告](../../docs/SCENE_CODEC_512K_RESEARCH.md)。

本轮首个描边对照保留了自然背景漂移和材质名校验失败。存档里的同实例恢复使用 compat_recovery.py、同一实体及静止石墙背景。512 KiB 的 expansion_runner.py 接收初始及通过的兼容性证据目录，native_vignette.py 接收已完成的 512 KiB 证据目录。恢复、扩容、渐晕与清理的实际命令回执见[证据索引](../../docs/evidence/weather-stencil-integrated/summary.json)。
