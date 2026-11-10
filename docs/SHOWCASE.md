# 作品演示：让想法，成为可见

这是一段 41 秒的完整演示作品。深色舞台、青金双色与宋体中文贯穿全片，使用五段连续镜头展示文字、公式和二维程序化运动。

| 时间 | 镜头 |
| --- | --- |
| 0–5 秒 | 一个光点扩展成轨道，英文开场逐渐显现 |
| 5–13 秒 | 宋体「想法」化为轮廓光点，经连续移动重组成「可见」 |
| 13–24 秒 | 旋转向量引出正弦波，配合真正 LaTeX 排版的欧拉公式 |
| 24–33 秒 | 青金圆环形成变化的几何花瓣，轨道光点与刻度共同运动 |
| 33–41 秒 | 图形收束，显示「让想法，成为可见」与 PYREACT / MANIM |

## 直接展示

- 高清视频：`dist/client-showcase/let-ideas-be-seen.mp4`，1920×1080、60 FPS、41 秒，H.264 / AAC 立体声。
- 封面：`dist/client-showcase/poster.png`。
- 分镜：`dist/client-showcase/contact.png`。
- 游戏安装包：`dist/client-showcase/pyreact-manim-showcase.mcaddon`。

视频由游戏使用的同一 shader 和纹理通过桌面 OpenGL 离线导出，包含本地合成的原创配乐。**它是高清作品导出，不是 Minecraft 录屏。** 游戏版目前没有这条配乐；实机测试另外保存实际截图和状态证据。

游戏中从原播放器右上角 **「作品演示」** 进入。页面挂载完成后从零开始全屏播放，不显示普通调试面板或进度条。右下角仅保留「重播」「返回」；Esc 或返回恢复进入前的场景和暂停位置。片尾停留，方便讲解。主播放器关闭后仍可在游戏 HUD 通过 F8 重开。

## 内容与运行边界

复杂标题和公式预先排版到 2048×2048 图集；256 个来自真实宋体轮廓的点对存储在两行 RGBA 数据中。点对按最小平方移动距离对应，再由 shader 插值和位移。它属于**字体轮廓点云重组**，没有声称是 Manim 的逐曲线 Transform 或任意 runtime 中文输入。

圆环、向量、波形、轨道及几何花瓣由时间参数实时计算。影片仅上传既有播放 uniform，不需要逐帧更新纹理、重载材质或生成新的 shader。片段源代码约 10 KB，图集 517,040 字节；未增加完整字体或 TeX 工具到玩家包。

该场景为专门编写的全屏 shader，不进入通用透明画布改写器。`canvas_compatible=False` 明确限制这一点，原十个独立画布示例保持可重建。开发客户端自身的顶部调试文字仍可能显示在实机截图中，高清导出没有这些文字。

## 重建

使用已提交的图集和元数据重建游戏资源，无需重新生成字体：

```powershell
python -B -X utf8 tools/build_showcase.py
```

修改文字后，使用已有参考环境重新生成字体图集，再部署：

```powershell
.\.venv-reference\Scripts\python.exe -B -X utf8 tools/showcase/build_typography.py
python -B -X utf8 tools/build_showcase.py --assets .runtime/showcase-assets
```

完整 `tools/build_demo.py` 在重建基础十例与画布后，也会重新部署本作品。完整 Noto Serif SC 源字体缓存仍由 `tools/reference/setup_cjk.py` 准备；LaTeX 环境沿用原项目配置。

导出视频、配乐、封面和分镜：

```powershell
.\.venv-reference\Scripts\python.exe -B -X utf8 tools/showcase/render_film.py --width 1920 --height 1080 --fps 60 --duration 41 --output dist/client-showcase/let-ideas-be-seen.mp4 --contact dist/client-showcase/contact.png --poster dist/client-showcase/poster.png
```

再次导出使用 `--overwrite`；只审查画面使用 `--stills-only`。帧直接写入 ffmpeg，没有堆积几千张图片。音乐由 `tools/showcase/score.py` 生成，无下载音乐或第三方音乐采样。

后台实机入口为 `tools/verify_showcase.py`，必须传本项目 session、owner、后台 WGC helper 和新证据目录。验证包括六个关键帧、连续完整播放、终点停留、返回恢复以及前后无激活检查；不把回调调用视为真实鼠标／触摸验收。

测试与交付摘要见 [showcase evidence](evidence/showcase/verification.json)。字体与工具来源仍遵守 [第三方声明](../THIRD_PARTY_NOTICES.md)。
