# 两位 stencil 数据上传扩容探针

本探针复用网易版 block palette 和 actor geometry。每页最多容纳 65,536 个实际 Python 字节。每页分别生成 bit 64 和 bit 128 两份几何，每个字节在每份几何中占一个 4×1 像素的四边形。片元按横向位置选取该字节的低到高四组 2 bit，再按材质选择其中一位写入 stencil。另有一个不写颜色和深度的 opaque 四边形清除源区的这两个 stencil 位。游戏运行时仅使用内存。

三个原生序列帧特效固定在第 13、14、15 层。第 13 层把源区 RGB 缩到低六位，后两层按 stencil 分别给红通道加 64、128。后处理用点采样取连续四个红通道的高两位，恢复一个字节。恢复玩家画面时从 RGB 低六位重新缩放，整数模型的每通道量化误差上界为 2。材质请求保留目标 alpha。原生 stencil 位没有公开的保留机制，实体轮廓与 UI 仍需单独检查。

| 载荷 | 测试设定分辨率 | 源区 | 源像素数 | 活跃载荷页 | 两个 bitplane 的四边形总数 |
|---:|---:|---|---:|---:|---:|
| 64 B | 720×1080 | x=8, y=128, 256×1 | 256 | 2 | 128 |
| 64 KiB | 720×1080 | x=8, y=128, 512×512 | 262,144 | 2 | 131,072 |
| 256 KiB | 1080×1440 | x=8, y=128, 1024×1024 | 1,048,576 | 8 | 524,288 |
| 512 KiB | 2304×1280 | x=8, y=128, 2048×1024 | 2,097,152 | 16 | 1,048,576 |

这些是测试设定。证据以 WGC 回执和原生截图的尺寸为准。每档独立生成一份完整宿主字节流，并用最多 4,096 个整数一组提交给游戏 Python，游戏和 GLSL 无需知道宿主生成规则。SHA-256 标记宿主原始文件，游戏侧另计算 Adler-32 核对收到的字节。

诊断逐像素核对 identity、dependent、源区符号和剩余诊断像素。512 KiB 的诊断从 y=128 开始以避开原生调试文字，其余档从 y=64 开始。dependent 查询第二次读取的地址取决于第一次读取的字节。原始诊断由一次纹理采样输出同一像素的红色、alpha 和绿蓝范围检查。隐藏数据几何时保留清除和三个原生特效，恢复可见后重新验证。雨天使用测试世界的原生雨，记录本地天气回执。

性能对照使用晴天、固定镜头、相同的几何分配和视口，所有档位都保留两道后处理。三档分别为隐藏几何的 copy＋直通、活跃几何与三个晚期特效的 copy＋画面恢复、活跃几何与三个晚期特效的 copy＋全量依赖读取诊断。每档 2 秒暖机、至少 25 秒采样，保存每 15 帧读到的 GetFps 和相邻渲染事件的原始间隔。依赖读取诊断画面与正常恢复画面分别测量。分辨率扩大后以该分辨率自己的隐藏基线作比较。

## 复现

在仓库根目录运行，下方路径指向本轮使用的网易版 3.10.0.467018。每次选用全新 .runtime 目录。runner 需要宿主 Python 3、Pillow、NumPy 和已有的 MCDK 被动截图环境。按此流程使用一个 owner 为 manim-stencil-bulk 的 noactivation 游戏实例，固定 60 FPS 上限。每次原生分页提交前会检查至少 4 GiB 的可用系统 commit。

```powershell
$run = '.runtime/weather-stencil-large-repro'
$gameExe = 'D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.467018/Minecraft.Windows.exe'

python -B -X utf8 tools/weather_stencil_large_probe/verify.py --self-test
python -B -X utf8 tools/weather_stencil_large_probe/build_probe.py --output "$run/project" --game-exe $gameExe
python -B -X utf8 tools/weather_stencil_large_probe/host.py launch --project "$run/project" --evidence "$run/evidence"
python -B -X utf8 tools/weather_stencil_large_probe/runner.py --project "$run/project" --evidence "$run/evidence" --capacities 64,65536,262144,524288
python -B -X utf8 tools/weather_stencil_large_probe/host.py stop --project "$run/project" --evidence "$run/evidence"
```

runner 会在每档调整受管游戏窗口的分辨率，以不激活窗口的方式把它移到物理屏幕工作区内，并核对实拍尺寸。导入、读回和内存预检失败会留下原始证据。进程私有提交量是 Windows 所见的进程计数，原生几何合成计时是 CPU 调用时间。运行时没有 GPU 完成栅栏。本轮实测和限制见[主研究报告](../../docs/SCENE_CODEC_512K_RESEARCH.md)。
