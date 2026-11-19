# Stencil 兼容性候选的复测

这一套测试使用同一份 64 KiB 数据。分别构建隔离的资源包，通过画面和完整数据读回判断各候选。上一次的实机基线见[原生兼容性报告](NATIVE_STENCIL_COMPATIBILITY.md)。

## 离线准备

在仓库根目录运行以下命令。准备和校验只读取已安装的客户端资源，并在仓库的 `.runtime` 内生成测试包和校验清单。重复准备时换一个新的目录名，以保留已有证据。

```powershell
$client = 'D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.467018/Minecraft.Windows.exe'
$batch = '.runtime/native-stencil-candidates-next-r2'
python -B -X utf8 tools/native_stencil_candidate_matrix/matrix.py prepare --base $batch --game-exe $client
python -B -X utf8 tools/native_stencil_candidate_matrix/matrix.py verify --base $batch
```

## 下次实机

允许启动游戏后，在同一目录执行以下命令。运行器逐项启动单个受管实例，固定 60 FPS 上限，使用不激活窗口的 WGC 截图，记录用例结果并验证实例已停止后才进入下一项。单项失败会留下日志及截图，清理无法验证时停止整轮。

```powershell
$batch = '.runtime/native-stencil-candidates-next-r2'
python -B -X utf8 tools/native_stencil_candidate_matrix/matrix.py run --base $batch
```

每个用例目录保存 `launch-evidence`、`run-evidence`、`cleanup-evidence`。批次根目录的 `matrix-run-*.json` 保存整体执行情况。同时运行三个阴影用例时，会额外生成 `shadow-comparison.json`，重新解码原始截图并判断原版是否复现冲突、候选掩码是否改善阴影。矩阵的执行完成表示用例已留下证据，具体是否兼容以各项判定为准。想先跑某一项时，在准备和运行命令后都加 `--cases <用例名>`。选择 `dof-active` 会自动加入 `dof-identity`，前者依赖后者的实际参考帧。已有运行证据的用例需要在新批次中重跑。

| 用例 | 辨别条件 |
| --- | --- |
| `dimension` | 两次主世界 → 下界 → 主世界。每次完成后由事件驱动重建，禁止宿主手动重新绑定。先抓重建后的被动画面，再检查全部数据、源符号和保护区。 |
| `particle` | 保留原生序列帧材质，由三个独立粒子依次处理底色、读取 bit 64 和读取 bit 128。验证普通序列帧和晴、雨场景中的全量读回。 |
| `particle-pack-first`、`particle-pack-last` | 交换额外原生 SFX 包的实际顺序。截图同时检查额外包专有 UI、普通序列帧和全量数据。 |
| `shadow-255`、`shadow-191`、`shadow-63` | 同时比较原生模板读掩码、只屏蔽 bit 64、屏蔽两位。逐类记录四种模板符号落在阴影上时的结果。掩码变体用于验证冲突机制，原生绘制后批量写入的入口仍需确认。 |
| `dof-identity`、`dof-active` | 先以无载荷对照验证原生景深路线和模糊效果。通过后才测试有载荷的恢复版本。对照比较最后的画面与全量数据，覆盖手动焦距和中心自动对焦。 |
| `bloom-control` | 对照保持 RGB 不变，只改变白色光源块的 alpha。检查光源外是否出现可重复的光晕，再判断原生 Bloom 是否实际执行。 |

独立粒子的读出顺序、阴影掩码的结果、景深替换的路由与维度资源恢复都需要进游戏证实。单项通过后再组合复验阴影、普通特效、景深、附魔背包、目标方块高亮、界面裁剪和抗锯齿。手机段需要可部署的网易版 Android 客户端和已连接的手机，本矩阵是 Windows 测试。512 KiB 和 alpha 打包留到原生兼容性复验通过后。

本批原生运行及后续定向复测见[候选实机结果](NATIVE_STENCIL_CANDIDATE_RESULTS.md)。
