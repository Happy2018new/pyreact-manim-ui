# ManimGL 1.7.2 原生填充与可变分段

此记录来自实际运行与固定上游源码检查，不是拟定的新匹配规则。源码以
[commit f427fc67df75513be0cd3f3329e327a9a19401c3](https://github.com/3b1b/manim/tree/f427fc67df75513be0cd3f3329e327a9a19401c3)
为基线；导出报告记录所用文件哈希。

`VMobject.get_outer_vert_indices()` 生成 `(0,1,2), (2,3,4), ...`。整个 VMobject 的
总 raw point 数在 `Transform.begin()` 后可保持固定，因此曲线槽位数固定。
但是槽位不总是可见曲线，`get_subpaths()` 的几何分段可能变化。

原生实际填充不是旧 `VMobject.get_triangulation()` 的 earcut 路线。当前
`VShaderWrapper` 和 `quadratic_bezier/fill/geom.glsl` 对每个槽位执行：

```glsl
if (verts[0] == verts[1]) return;
```

这会精确跳过首 anchor 与 handle 相等的分段标记。其余曲线发出一个
`(shared_base, anchor_0, anchor_1)` 有向三角形和 Bézier 边缘修正三角形；
`shared_base` 是整个 VMobject 的第一个点。`fill/frag.glsl` 通过正负朝向的
alpha、单独浮点 fill framebuffer 和 `VShaderWrapper` 的混合规则累积绕数，
再合成到主画面。不是简单“每个轮廓分别取 union”。

所以，未来若用独立 open edge-chain 表达所有曲线，需要同时保留：

1. 每个曲线槽位的原始 anchor/handle，以及精确的 `anchor_0 == handle` 跳过条件。
2. 有效曲线到 **同一 shared_base** 的闭合边，或数学上等价的有向 fan 累积。
3. 原生抗锯齿、alpha 与合成的差异；有向几何绕数相同也不自动保证像素相同。

仅把所有 raw 曲线视作无条件可见的边会画出原生已跳过的 move 段。仅画开放边
而丢失 fan 的闭合边，也可能在转换的开放链中产生不同填充。可以考虑每个曲线
独立生成闭合多边形 `[shared_base, anchor_0, sampled..., anchor_1]` 后**共同**
累计 nonzero winding，但还需要动态跳过条件；不能直接把每个多边形作为独立
普通路径各自填充并合成。

本次 DejaVu Serif 实测：

| 文字转换 | 起点 subpaths 长度 | 终点 subpaths 长度 | 总控制点数 |
| --- | --- | --- | --- |
| O → B | 39 / 25 / 61 | 39 / 25 / 61 | 127 |
| 8 → 1 | 41 / 45 / 45 | 133 | 133 |
| A → M | 51 / 101 | 153 | 153 |
| C → S | 75 | 75 | 75 |

这些是**对齐之后**的数据。schema 1 固定 contour IR 导出器只接受其中分段保持
一致且封闭的情况。schema 2 已实现固定 curve/fan IR，8→1 与 UI→UX 已生成显式
启用 marker 近似的预览，保留真实 raw 控制点、实际采样帧 skip bool 与原生参考；
不需要自行发明字形对应关系。

## 浮点 skip 窗口待办

仅解析 3D 差向量的精确有理零点还不充分。文字由上游坐标翻转产生的约
1e-17 Z 分量存在 float32 舍入差，可能让解析的 3D 零点消失，但实际乘加后
三个分量仍同时舍入为零。8→1 的 curve 8 在进度约 `0.4625146097552342`、
UI→UX 第二 glyph 的 curve 2/16 在约 `0.5719394389734742` /
`0.5707257874426854` 已观察到真实原生 skip。普通均匀帧和 180 个间隔探针
未命中这些时刻，因此不能将探针通过描述为全时间一致。

A→M 的解析事件位于约 `0.3130717421873268`、`0.31363226051009696`、
`0.31363237016797274`。真实原生在这些时刻 skip；但插入三个事件 key 后，
邻近事件区间还有额外的 float32 skip，单点事件模型不足。AI→MC 另有解析
候选在反求时刻因乘加残差反而没有 skip。完整支持需要明确建模上游实际的
浮点相等时间窗／运行时求值边界，不能用 bool 透明度混合伪装完成。

当前默认严格模式拒绝这类候选。调用方只有显式设置
`allow_marker_approximation=True` 才能生成预览，报告列出 XY 近零风险候选、
原生核查与所有已知限制，`full_timeline_marker_parity_verified` 保持 false。

## 原生文字的填充细边层

上游 `StringMobject` 默认 `fill_border_width=0.5`，不同于普通 VMobject 的
默认 0。即便文字 `stroke_width=0`，`VShaderWrapper.fill_border_vao` 仍将
`fill_rgba` 与这个宽度送进原生 stroke shader，用 MAX 混合叠到有向 fill。
因此绕数彼此抵消的曲线附近也可能留下细线，不能把它们当成错误轮廓删除。

`stroke/vert.glsl` 将宽度乘 `0.01 * frame_scale`，相机的 `frame_scale` 为
`frame_height / 8`。当前 8 单位高画布中，full width 是 0.005 场景单位，
在 720 像素高视口中为 0.45 像素；`anti_alias_width=1.5` 采用像素单位。
原生边框片元 alpha 另乘 0.95，最终 fill 合成整体乘 1.06。

schema 2 路径导出 `fill_border_width`（已换成场景单位）与
`anti_alias_width`（像素单位）。compiler 的近似实现应只计算有效真实曲线
采样链的距离，不包含到 shared_base 的人工闭合边；细边覆盖与 fill 取 max。
多边形采样、连接拐角与原生 supersampling 仍有差异，补齐这层不等于像素完全一致。
