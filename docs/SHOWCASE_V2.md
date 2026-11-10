# 万象变换 / METAMORPHOSIS

本文记录形变修订版 V4。后续 V5 增加空间折叠、几何聚能与游戏内配乐，并新增独立童话片；当前入口、成片和构建命令见 [双片说明](DUAL_PRESENTATIONS.md)。

120 秒、1920×1080、60 FPS 的作品。当前为形变修订版：加快公式切换，18 组文字／公式转换包含不同字形的实际形变，另外 3 组保留符号身份匹配及位置交换。连续几何变形、霓虹填充、形变回声、双向轨道光点和完整的两分钟音乐编排保留。旧视频不覆盖。

## 成片

- 当前：`dist/client-showcase-v4/metamorphosis-shape-morph-120s.mp4`
- 封面：`dist/client-showcase-v4/poster.png`
- 分镜：`dist/client-showcase-v4/contact.png`
- 导出参数及文件哈希：同目录 `metamorphosis-shape-morph-120s.render.json`。
- 原两分钟版：`dist/client-showcase-v2/metamorphosis-120s.mp4`。
- 调速与渲染修正的中间版：`dist/client-showcase-v3/metamorphosis-reviewed-120s.mp4`，其中公式主要为平移和淡入淡出，已由当前版本替代。

视频由部署的 shader 和图集通过桌面 OpenGL 导出，音乐在导出时加入。**这是离线作品视频，不是实机录屏。** 用户最初要求自行监修，中间版因此完成了一部分离线检查；之后用户明确改为「做好后直接给我验收，不必检查」。当前形变修订版按最后指示直接导出，未继续逐帧监修、测试套件或实机验收，不沿用中间版的通过结论。准备中的受管 MC 实例已关闭。详见 [修订记录](SHOWCASE_REVIEW.md)。

## 时间轴

| 时间 | 变换内容 |
| --- | --- |
| 0–12 秒 | 分散字形聚拢，MORPH → MATH → MAGIC → 思想 |
| 12–28 秒 | 圆 → 方 → 三角 → 六边形 → 星 → 花瓣 → Lissajous，旁侧矩阵同步变换 |
| 28–48 秒 | 平方展开、一般二次方程与求根公式逐字形对应移动及变形 |
| 48–66 秒 | 指数形式 → 三角形式 → 欧拉恒等式；圆／椭圆与正余弦投影 |
| 66–84 秒 | `f(x)=x³` → `f′(x)=3x²` → 定积分；曲线、移动切线和渐密黎曼条 |
| 84–102 秒 | 逐项加入 3、5、7 次谐波，公式、旋转圆链、波形和频率柱共同变化 |
| 102–114 秒 | 思想 → 形状 → 公式 → 万象 → 欧拉恒等式，周围连续多层几何形变 |
| 114–120 秒 | 公式字形移动并变成宋体片尾标题，音乐收束 |

本片编排了 **21 组文字／公式转换**，另有几何变换链、谐波合成及高潮形变循环。具体转换源、目标和时间写在 `tools/showcase_v2/film.json`，不将静止停留或镜头淡入算作新的形变。

## 实现

公式由真实 LaTeX 排版，按独立字形和分数线提取位置。18 组形变事件优先将不同轮廓按位置、体型与角色约束配对，中文、英文及公式之间也可转换；另 3 组优先保留相同符号身份，展示位置交换。细规则线只与兼容规则线对应，不把加号等正文拉成分数线。相同目标的停留段保持身份匹配，避免公式停住后仍在内部交换。

不同字形之间连续插值 SDF、中心和尺寸；过渡保持实体填充，只添加轻微边缘提亮。当前配对共 82 条不同字形形变、36 条身份平移、79 条出生、41 条消失；出生／消失和同字形移动不计为形变。这是逐字形 SDF 插值，不声称与原生 Manim 逐曲线 Transform 完全一致。孔洞数量改变时会出现轮廓的分裂与合并，最终观感由用户验收。

公式按章节共用字号和基线。实际转场为 0.8 秒，片尾为 1 秒，其余时间用于停留及配合几何演出；总片长仍为 120 秒。共同符号不因新增分数、积分而突然缩放。

34 个分组复用 76 个独立 SDF，存入一张 4096×4096 图集。图集同时包含宋体、英文和公式字形；游戏没有引入字体解析或 LaTeX 运行时。几何段插值同一参数位置的顶点坐标，形变回声采样不同时间，填充按实际轮廓计算。

配乐由本地振荡器和噪声合成，120 BPM；八个章节有不同密度、鼓组、贝斯、琶音和对位旋律，118–120 秒淡出。没有复用旧 41 秒音轨循环，没有下载商业音乐或采样。

## 重建

使用已提交图集和排版数据重建当前作品：

```powershell
python -B -X utf8 tools/build_showcase.py
```

修改公式或文字后：

```powershell
.\.venv-reference\Scripts\python.exe -B -X utf8 tools/showcase_v2/build_type.py
.\.venv-reference\Scripts\python.exe -B -X utf8 tools/showcase_v2/build_film.py --assets .runtime/showcase-v2
```

输出视频：

```powershell
.\.venv-reference\Scripts\python.exe -B -X utf8 tools/showcase_v2/render_film.py --output dist/client-showcase-v4/metamorphosis-shape-morph-120s.mp4 --contact dist/client-showcase-v4/contact.png --poster dist/client-showcase-v4/poster.png
```

帧直接写入编码器，不堆积 7200 张图片。路径已存在时需要显式使用 `--overwrite`，历史版本位于不同目录。游戏内入口继续使用原「作品演示」，时长读取场景的 120 秒配置；当前修订没有进行实机验收。`tools/verify_showcase.py` 支持指定截图时间和跳过全片播放，保留给之后需要实机时使用。
