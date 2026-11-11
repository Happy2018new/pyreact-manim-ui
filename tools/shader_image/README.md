# ShaderImage 图片资源构建

`python tools/build_shader_images.py` 生成三张本项目原创的程序绘制 PNG 卡片组成的 RGBA 图集、四组实体、图片 shader、运行时元数据与材质。默认图片是 `aurora`（极光山野，384×256）、`sunrise`（日出湖畔，320×320）、`prism`（星光棱镜，256×384）；来源函数位于 `defaults.py`，不依赖外部素材或字体。

导入自己的静态 PNG 时，新建 UTF-8 JSON 文件，例如：

```json
{
  "portrait": {"file": "assets/portrait.png", "title": "人物肖像"},
  "landscape": {"file": "assets/landscape.png", "title": "山间风景"}
}
```

运行 `python tools/build_shader_images.py --manifest path/to/images.json`。图片路径相对于 JSON 文件；id 使用小写字母开头，后续允许小写字母、数字、下划线，最长 48 个字符。只接受静态 PNG，保留原始尺寸与 alpha；不会自动缩放或把图片转成矢量。图集最大 2048×2048，每张图保留 2 像素间隔，最多 64 张。超预算时明确报错，请缩小输入图片或减少数量。重新执行不带 `--manifest` 的命令可恢复默认卡片。

`--output path/to/output` 可输出到隔离目录。图集和所有生成文件都可重建，`tools/shader_image/generated/manifest.json` 记录输入配置、原始 RGBA 校验值、尺寸与 UV。构建器只管理显式允许的图片资源路径与 `entity.material` 中的 `pmanim_image:entity_static`；其他材质、画布 shader 和用户纹理均保留。被人工修改的已生成资源会导致构建停止，且在检查完成前不写入任何文件。应编辑源 PNG、构建源代码或 shader 模板，再重建。

图片使用现有的 `geometry.pmanim_canvas`，因此新部署目录还需先运行 `tools/build_canvas.py --output ...` 提供共享几何。构建器自动合并图片材质；`generated/materials.json` 同时保留单独的材质片段，便于检查。游戏运行时读取 `behavior_pack/manim_ui/images/generated.py` 的 `IMAGES`、`SLOT_COUNT = 4` 与 `ATLAS_SIZE`，不导入 Pillow 或任何宿主构建模块。

Uniform 约定：

| Uniform | 四个分量 |
| --- | --- |
| U1 | 时间（秒）、画布宽高比、整体不透明度、效果（0 无／1 波浪／2 旋涡） |
| U2 | 图片显示宽度、显示高度、旋转弧度、效果强度 |
| U3 | 原生 UI 矩形的 NDC left、top、width、height |
| U4 | 最终图集裁剪区域的 u、v、width、height |

显示宽高以画布高度为单位，包含 contain/cover 计算及用户缩放；负号分别表示水平／垂直镜像。UV 原点在左上。着色器先逆旋转屏幕位置，再除以带符号的显示尺寸，得到图片局部 UV。波浪只在局部 x 方向偏移，最大为图片宽度的 4%，负强度反转偏移；旋涡在局部中心半径 0.5 内平滑衰减，外围保持原图。两种效果的强度均限制在 [-1, 1]。

采样先检查变形后的 UV 是否越界，越界输出透明，再把图集 UV 限制到最终裁剪区域的半纹素内部。Point 采样器每个像素固定读取四个纹素，分别预乘 alpha 后插值，输出预乘颜色并使用 `One / OneMinusSrcAlpha` 混合。这样半透明 PNG 边缘不会因透明纹素的隐藏 RGB 出现黑边或彩边。小于一个纹素的裁剪收敛到中心采样。普通 PNG 的圆角 alpha 会保持平滑；旋转后矩形的几何边界仍按局部 UV 裁切，没有额外的几何边缘抗锯齿。

离线验证命令：

```powershell
.venv-reference/Scripts/python.exe -m unittest discover -s tests -p 'test_shader_image_build.py' -v
.venv-reference/Scripts/python.exe -m unittest discover -s tests -p 'test_shader_image_gpu.py' -v
```

GPU 测试只在后台创建桌面 OpenGL 上下文，覆盖 GLSL 330／400／450、图片方向与裁剪、旋转和镜像、半透明边缘与混合、波浪／旋涡局部坐标以及退化裁剪。它们不启动游戏，不能代替网易客户端纸娃娃渲染与 UI 生命周期验收。
