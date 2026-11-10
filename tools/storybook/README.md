# 风借来的一颗星

独立原创童话开场，120秒、1920×1080、60 FPS。以有限色纸片剪影讲述红斗篷少女和一颗发光种子的旅程。字幕为固定400字重宋体。

在工程根目录运行：

```powershell
.venv-reference/Scripts/python.exe -B -X utf8 tools/storybook/build_film.py
```

构建只更新本目录 `generated/`，以及独立的生产 shader 和贴图：

- `resource_pack/shaders/glsl/story_showcase.fragment`
- `resource_pack/textures/manim/story_showcase.png`

不修改数学片、播放器、场景注册、材质或音频。场景与材质由集成层注册。

渲染输入沿用现有后处理约定：`EXTRA_VECTOR1=(时间秒,物理画布宽高比,物理画布像素高,不透明度)`；`EXTRA_VECTOR2=(翻转Y,顶部比例,高度比例,保留)`。`TEXTURE_0` 是原画面，`TEXTURE_2` 绑定宋体图集（Point/Clamp，shader手动双线性）。宽高比16:9时世界范围为x±8、y±4.5；内部为2.18:1电影宽幅构图，字幕处于画面内部。

七幕分别为0–16失星村落、16–34掌心种子、34–54云海纸船、54–76暴风森林、76–96星光生根、96–110光叶归鸟、110–120片名。`generated/story.json` 给出字幕、章节、字体/资源哈希与参数说明。主角斗篷、发尾、云面和丝带风均有轮廓形变；船→云、种子→树、叶→鸟是连续距离场形状变化。

字体使用工程已缓存的固定Noto Serif SC官方源，源SHA256见构建脚本。`setup_cjk.build_subset` 以fontTools4.62.1实例化400字重并重命名为Pyreact Manim Song；独立字体子集和SIL OFL1.1许可放在generated目录。图集编译复用现有`tools/showcase_v2/build_type.py`，不需要新依赖，不调用LaTeX/Manim，不覆盖数学图集。

本构建不运行游戏、录制、导出视频或执行实机验收。音轨、最终视频导出和播放注册由集成层完成。
