# 独立 UI 画布探针

状态：主代理已在受管实例确认两个独立颜色/进度的图元和 O→B 数字纹理确实渲染（`ui-initial.png`、`ui-glyph.png`）。原生纸娃娃的脚底锚定导致画面偏底；正在验证将平面 UV 精确映射到真实控件矩形的修正。这个目录不自动部署、不启动或操作 Minecraft，不属于正式用户功能。

当前已证明的接口事实：

- 图片 `SetSprite`、`SetSpriteUV`、`SetSpriteUVSize`、`SetSpriteColor`、`SetSpriteClipRatio` 是公开接口。
- 完整 Sprite 属性表与公开接口检索中，没有找到图片绑定任意自定义 material 或逐控件 uniform 的依据；这不是引擎绝对不支持的证明。
- `netease_paper_doll_renderer` 可以通过 `asNeteasePaperDoll().RenderEntity` 渲染指定实体 identifier。
- `SetEntityUIExtraUniforms(identifier, index, vec4)` 可向实体 UI shader 的 `EXTRA_ACTOR_UNIFORM1..4` 传值。它按 identifier 共享，因此本探针使用独立 identifier 测试实例隔离。
- `BaseUIControl.SetAlpha` 文档仅承诺 image/label 生效；纸娃娃透明度必须单独验证，本探针写入 fragment 输出 alpha。
- JSON UI 文档定义了 `clips_children`、`layer` 和 `enable_scissor_test`；它们对自定义实体材质的实际行为仍需截图验证。
- `texture_file_system: RawPath` 和 `force_texture_reload` 是 Wiki 列出的图片字段；网易原版 `player_tips.json` 的 `player_head_image` 确实使用 RawPath。任意运行时文件地址及重载仍需实机验证，不能仅凭字段存在宣布动态纹理可用。

资料由 MCP `minecraft_docs` 检索：

- `api RenderEntity`
- `api SetEntityUIExtraUniforms`
- `api SetAlpha`
- `api SetSprite`
- `wiki clips_children --top 5`
- `wiki image --top 30` 中的 Sprite 表
- `read NeteaseGuide/mcguide/18-界面与交互/30-UI说明文档.md`
- 原版 `materials/entity.material`、`shaders/glsl/entityVertexUtil.h` 和 `entity/creeper.entity.json`
- `read GameAssets/resource_packs/vanilla_netease/ui/player_tips.json`

生成隔离资源：

```powershell
& 'D:/Program/Python/python.exe' -B -X utf8 tools/ui_canvas_probe/build_probe.py
```

产物位于 `.runtime/ui-canvas-probe/`。由主代理向其唯一受管实例叠加 BP/RP。`ui/_ui_defs.json` 必须把 `ui/ui_canvas_probe.json` 合并进去，不可覆盖现有定义。`materials/entity.material` 同理按 material key 合并。增加实体与 UI 资源后，按当前工具支持的资源重载方式操作；不能假定 Python reload 会读取新资源。

游戏初始化完成后，通过公开 SDK 客户端执行环境调用：

```python
import manim_ui.canvas_probe as cp
p = cp.open_probe()
print(p.results)
# 初始左侧青色环、右侧品红环，时间与 alpha 不同。
p.set_state('left', 0.8, 1.0, (0.2, 0.9, 1.0))
# 检查右侧是否不受左侧进度改变影响。
p.resize('right', (140, 90), (180, 100))
p.sync_layout()  # UI 完成布局后同步；resize/show_glyph 也会主动同步。
# 实际复用已有 O -> B 纹理与几何 shader 的两个时刻。
p.show_glyph('left', 0.0)
p.show_glyph('right', 2.0, opacity=0.5)
# runtime_data 探针生成的地址可分别测试资源包图片与 RawPath。
p.set_image(receipt['texture'])
p.set_image(receipt['absolute_png'], raw_path=True)
cp.close_probe()
```

矩形映射使用 `GetGlobalPosition`、`GetSize` 与 `Game.GetScreenSize` 将原生控件边界写入 `EXTRA_ACTOR_UNIFORM3`。顶点保留纸娃娃原有 Z/W 和 UI 绘制次序，只替换 XY；不在全屏后处理上模拟 UI。`results` 中记录原始测量值及 NDC 矩形。

这次修正只更换顶点 shader 与探针 Python。复制后调用公开 `ReloadAllShaders`、关闭旧探针并在 Python 模块更新后重建即可。`fit_images()` 用公开 `SetImageAdaptionType("originNineSlice", (0,0,0,0))` 在现有 UI 上修复纯色矩形，构建出的 JSON 同时声明 `keep_ratio: false`，因此这项修复不必依赖重载 JSON。

应保留背景静默截图：初始两个实例；仅改变左侧；右侧缩小；半透明字形覆盖蓝色底纹；橙色前景遮挡；卸载后完全消失；重新创建后初值恢复。API 返回成功只能算接口执行证据。

O→B 桥接只接受当前固定单字形 fixture 的 shader 结构，若生成器变更会直接报错。它不代表已实现通用 UI 编译器，也不构成 all-in-runtime。
