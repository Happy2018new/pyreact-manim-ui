# 固定 ManimGL 参考导出

这个工具实际调用官方 **ManimGL 1.7.2** 的 `Text`、`Transform.begin()` 和
`Transform.interpolate()`。字符对象、轮廓对齐、退化轮廓与 `smooth` 时间函数
来自上游。我们只将最终的二次 Bézier 轮廓采样为固定顶点数的多边形，交给
项目编译器。它不是任意 Manim Python 脚本的转译器。

## 安装与运行

在仓库根目录运行。参考环境只用于宿主离线构建，不得复制进游戏 Python。

```powershell
./tools/reference/setup_reference.ps1 -Python 'D:/Program/Python/python.exe'
& '.venv-reference/Scripts/python.exe' tools/reference/export_text_transform.py `
  --output .runtime/reference/o_to_b --render-reference
& '.venv-reference/Scripts/python.exe' tools/build_scene.py `
  --input .runtime/reference/o_to_b/scene.json --output .runtime/compiled/o_to_b
```

`-ShareInstalledPackages` 可让 venv 只读复用宿主已有依赖，减少下载；新增依赖仍
安装在 venv 内，不改全局 Python。本次实跑使用 Python 3.13.13 和这个选项。
安装脚本只接受二进制 wheel，避免意外拉取源码构建链。依赖来源记录在
`.runtime/reference/install-report.json`。

第二个已实际运行的场景为 `C` → `S`：

```powershell
& '.venv-reference/Scripts/python.exe' tools/reference/export_text_transform.py `
  --source C --target S --name manimgl_c_to_s `
  --output .runtime/reference/c_to_s --render-reference
```

默认开放字体 `DejaVu Serif` 已随构建工具附带（约 380 KB），通过上游
`register_font` 临时注册，不依赖系统安装同名字体。字体许可见
[fonts/LICENSE_DEJAVU](fonts/LICENSE_DEJAVU)。ManimGL 来源、精确 wheel 哈希、tag、
commit 和字体哈希见 [upstream.json](upstream.json)，MIT 许可副本见
[LICENSE_MANIMGL.md](LICENSE_MANIMGL.md)。

`--help` 不会导入 ManimGL、创建 OpenGL context 或启动游戏。命令行参数如下，
与 `ExportSettings` 默认值一致：

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `--output` | 必填 | 输出目录 |
| `--source` / `--target` | `O` / `B` | 起始／目标文字 |
| `--name` | `manimgl_o_to_b` | 场景 ID；使用小写字母开头的字母、数字与下划线，最多 48 字符 |
| `--font` | `DejaVu Serif` | 与字体文件对应的 Pango 字体家族名 |
| `--font-file` | 仓库内 `tools/reference/fonts/DejaVuSerif.ttf` | 临时注册的字体；换字体时与 `--font` 一起修改 |
| `--frames` | `61` | 导出帧数，范围 2–256 |
| `--duration` | `2.0` | 动画秒数 |
| `--tolerance` | `0.003` | 已导出帧中二次曲线与弦段的最大距离容差，单位同场景 |
| `--glyph-height` | `4.0` | 起终文字各自通过上游 `set_height` 归一化的高度 |
| `--render-reference` | 关闭 | 额外调用真实 Camera，生成五个时刻的 PNG |
| `--geometry` | `contours` | `contours` 为 schema 1 固定闭合轮廓；`curve_slots` 为 schema 2 原生有向曲线槽位 |
| `--allow-marker-approximation` | 关闭 | 显式允许 schema 2 预览遗漏采样帧之间的原生浮点 skip 窗口，报告保留限制 |

## Schema 2 字形变化预览

schema 2 保留真实上游每个 `raw_points[2*i:2*i+3]` 曲线槽位，采样链包括两端，
每帧另存真实 `skip_marker`，同一个 glyph 的曲线以共同 `base` 累计有向 fan
绕数。它不依赖 CPU `get_subpaths()` 分段稳定，也不自行发明字形匹配。
schema 2 同时保留原生文字的细边层：上游默认 `fill_border_width=0.5`，
按其 shader 单位转换为当前画布的 0.005 场景单位，AA 宽度 1.5 像素；
只覆盖真实有效曲线，不给人工 fan 闭合边描边。

```powershell
& '.venv-reference/Scripts/python.exe' tools/reference/export_text_transform.py `
  --source 8 --target 1 --name manimgl_eight_to_one --geometry curve_slots `
  --allow-marker-approximation --output .runtime/reference/eight_to_one --render-reference
& '.venv-reference/Scripts/python.exe' tools/reference/export_text_transform.py `
  --source UI --target UX --name manimgl_ui_to_ux --glyph-height 3 --geometry curve_slots `
  --allow-marker-approximation --output .runtime/reference/ui_to_ux --render-reference
```

这两个样例是**显式启用近似的预览**，分别为 277 和 150 个采样点。普通采样帧的
控制点与 skip bool 均来自真实 Manim，但上游 float32 乘加可能在极窄时间窗内
让 anchor 与 handle 恰好相等，原生会瞬时跳过该曲线。仅用三个额外时间探针
不能证明覆盖这些窗口；3D 有理零点判定也可能被文字翻转带来的微小 Z 舍入
扰动漏掉。因此导出器结合 XY 近零候选检测，把已知候选、原生探测结果和
`full_timeline_marker_parity_verified: false` 写入报告。

默认严格模式拒绝包含这类候选的 schema 2 场景，需要明确传
`allow_marker_approximation=True`（Python API）或上述命令行开关才生成预览。
该开关不将曲线转成透明混合，也不篡改原始数据。A→M、AI→MC 同样存在内点
浮点窗口，完整时间行为仍是待办；初版预览不等于这些样例已达到 1:1。

## 输出与误差

每次输出包含：

- `scene.json`：编译器 schema 1 场景，坐标为 XY、Y 向上。一个 glyph/VMobject
  对应一个复合 path；`contours` 保留原有顺序、绕向、退化和重复顶点。默认 61 帧、
  2 秒、14.2222 × 8 画布、黑底白字，各文字通过上游 `set_height(4)` 归一化。
- `upstream_control_points.json`：每帧真实上游浮点控制点与固定 contour spans。
  不经过自己的字形匹配或轮廓重排，可独立复查采样。
- `reference_report.json`：实际依赖版本、关键上游源码哈希、输入与字体哈希、
  采样规则、误差、资源哈希与验证状态。
- 加上 `--render-reference` 时，生成进度 0 / 0.25 / 0.5 / 0.75 / 1 的
  `manimgl_*.png` 与联系表。它们由**未经修改的上游 Camera 和上游 shader**
  通过 standalone OpenGL 原生渲染，尺寸 1280 × 720，无应用窗口；不是我们的
  CPU renderer 或自己画的近似参考。

二次曲线 `B(t)=A+Vt+Qt²` 等参数细分为 `n` 段后，曲线与对应弦段的最大
欧氏距离不超过 `|Q|/(4n²)`。工具跨所有导出帧为每个已对齐曲线选同一个
细分数。默认容差 0.003 场景单位，报告给出实际最大上界。这只约束**已导出帧**
的曲线近似；不包含纹理编码量化、抗锯齿或原生填充算法差异。

帧间时间插值另在每个区间的 1/4、1/2、3/4 位置重新调用真实上游，测量
控制点误差。这个数字是实测探针误差，不声称覆盖任意连续时刻。当前 O→B
有 269 顶点，空间弦误差上界约 0.002715、时间探针最大误差约 0.0007481。
在 720 像素高、8 单位画布下分别约 0.2443 和 0.0673 像素，仍不等于最终
像素逐点一致。

## 已声明的边界

目前只接收平面、封闭、纯填充、每字形统一样式的 `Text` 与 `Transform`。
描边单位换算、颜色渐变、公式/LaTeX、中文覆盖、3D 和任意脚本未验证。自交
中间态必须与原生 Camera 单独对照；GPU nonzero 填充和上游有向 fan／混合可能不同，
数值坐标一致不能代替像素验收。

schema 1 固定拓扑 IR 要求上游端点和每个采样时刻的 `get_subpaths()` 边界一致。
**O→B、C→S 已导出；8→1、AI→MC 的 schema 1 导出会明确拒绝。** 后两者上游虽然
对齐了总控制点数，但有效子路径边界不一致，需要扩展 IR/渲染语义；不能靠
自行拆分或新建匹配伪装成上游相同行为。拒绝这些样例是显式限制，不是已支持。

## 验证

```powershell
& '.venv-reference/Scripts/python.exe' -m unittest discover -s tests -p 'test_reference*.py' -v
```

测试覆盖已证明的二次弦误差界、绕向/退化保留、所有帧的固定拓扑、独立重跑
上游得到的控制点、真实中间态以及对变动子路径的拒绝。PNG 和游戏画面差异
另由渲染验收记录；这些单元测试不自动授予 MC 像素一致结论。
