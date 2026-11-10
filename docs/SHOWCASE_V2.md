# 万象变换 / METAMORPHOSIS

120 秒、1920×1080、60 FPS 的第二版作品。根据用户反馈，重点改为连续的公式、字形和几何变换，并增加霓虹填充、形变回声、双向轨道光点和完整的两分钟音乐编排。旧 41 秒视频保留，不覆盖。

## 成片

- `dist/client-showcase-v2/metamorphosis-120s.mp4`
- `dist/client-showcase-v2/poster.png`
- `dist/client-showcase-v2/contact.png`
- 导出参数及文件哈希：同目录 `metamorphosis-120s.render.json`。

视频由部署的 shader 和图集通过桌面 OpenGL 导出，音乐在导出时加入。**这是离线作品视频，不是实机录屏。** 本轮遵照用户「直接做，不需要验收，我来看」的要求，没有启动 Minecraft，也没有运行完整验收或测试套件；不沿用旧版的实机性能结论。

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

公式由真实 LaTeX 排版，按独立字形和分数线提取位置。相同字形优先匹配，保留其身份；其余字形按移动距离对应。字形中心、尺寸和形状连续插值，缺失／新增符号缩小收束或展开。形状通过逐字形 SDF 插值完成，不是对整张公式图片做透明度交叉淡化；也不声称与原生 Manim 逐曲线 Transform 完全一致。

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
.\.venv-reference\Scripts\python.exe -B -X utf8 tools/showcase_v2/render_film.py --contact dist/client-showcase-v2/contact.png --poster dist/client-showcase-v2/poster.png --overwrite
```

帧直接写入编码器，不堆积 7200 张图片。游戏内入口继续使用原「作品演示」，时长读取场景的 120 秒配置；本轮没有对新片进行实机验收。`tools/verify_showcase.py` 已改为读取场景时长，留待需要实机时使用。
