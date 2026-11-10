# 中文灰色三角区域：独立精度诊断

结论：灰色三角区域来自 **ManimGL 原生 FP16 填充缓冲区的有符号 alpha 消去误差**。Transform 对齐增加曲线分段，使误差累积更明显。它不是当前 Minecraft shader 丢失中文笔画造成的。

本目录是独立诊断，**没有替换、修正或覆盖上一级目录的 40 帧原生参考**。图中 FP32 版本临时修改了上游填充纹理的精度，必须称为“修改上游精度的诊断参考”，不能称为未修改的原生参考，也不用于宣布严格 1:1 通过。

## 受控条件与结果

使用固定 ManimGL 1.7.2、项目宋体子集和 1280×720 的独立无窗口 Camera。每种情况分别在新进程中运行 FP16 与 FP32；两组输入点缓冲区的 SHA-256 完全相同，上游代码文件哈希相同。

FP32 实验只在进程内替换 `VShaderWrapper.get_fill_canvas()` 返回的颜色附件：`dtype='f2'` 改为 `dtype='f4'`。原生填充 shader、合成四边形、深度附件和几何全部复用。`finally` 恢复原 factory、相机配置和缓存配置；不修改已安装的 ManimGL 源文件。

| 情况 | “中”／“文”的原生控制点数 | 原生灰像素在 FP32 中恢复为黑色的数量 | 当前 shader 对未修改 FP16 的 IoU | 当前 shader 对修改 FP32 的 IoU |
|---|---:|---:|---:|---:|
| 直接 Text，不做 Transform | 81／95 | 0 | 不适用 | 不适用 |
| 中文 → 变换，起点 | 327／459 | 6,153 | 82.279% | 99.507% |
| 数学 → 中文，终点 | 555／379 | 12,920 | 69.066% | 99.622% |

“恢复为黑色”的统计定义固定为：FP16 最大通道值大于 16，而相同像素的 FP32 最大通道值不超过 1。直接 Text 仍有更低亮度的 FP16 消去残余，只是没有达到该统计阈值。

灰区对应的原生填充 alpha 中，FP16 出现大量 `-0.04296875`、`-0.07421875`、`-0.08203125` 等残余；相同几何在 FP32 中大量对应零附近的 `4.47e-8`。原生后续负 alpha 恢复会把非零残余变成可见灰色覆盖。

两个对齐端点在独立进程内的**第一次渲染**与已有正式参考逐像素一致；同一 Camera 连续重复三次也完全一致。因此不是此前导出的遍历顺序、旧帧残留或 Camera 清屏遗漏。

## 证据

- `summary.json`：同源代码和几何哈希、灰像素统计、原生 alpha 分布、原始和修改精度的 PNG 哈希及比较指标。
- `direct-vs-aligned-native-fp16.png`：直接 Text、两种对齐端点的未修改原生 FP16 对照。
- `native-fp16-vs-modified-fp32.png`：两个对齐端点的 FP16、修改 FP32、差异放大四倍。

## 复现

在仓库根目录、已配置的固定参考环境中执行：

```powershell
foreach ($sceneCase in @('direct', 'change', 'math')) {
    foreach ($precisionCase in @('f2', 'f4')) {
        .venv-reference/Scripts/python.exe -B -X utf8 tools/reference/diagnose_fill.py `
            --scene $sceneCase --dtype $precisionCase `
            --output .runtime/native-fill-diagnosis-repro
    }
}
```

每个目录输出三次端点截图和 `report.json`。可选 `--order forward` 或 `--order reverse` 会在重复端点前先按不同顺序渲染五帧。工具拒绝把 `.runtime/reference` 或其子目录当作输出，以免覆盖正式参考。这个工具不启动 Minecraft，也不创建或激活桌面窗口。

## 对 Minecraft 的影响

游戏资源只包含几何、数据纹理和生成的 shader，并不导入原生 Camera 的图片。当前 shader 在片元中以 float32 计算有符号覆盖，没有使用这套逐三角形混合的原生 FP16 填充缓冲区，所以不应为了提高原生参考 IoU 而加入灰色残影。

本轮保留正式原生参考、当前游戏渲染和独立诊断。将 FP32 设为未来的新参考基准，需要明确记录上游改动及基准变化；本次没有实施。
