# 运行时数据入口探针

这些文件用于验证“游戏 Python 生成新数据，GPU 实际消费并更新”。它们不接入正式播放器，不把接口返回 `True` 当作通过，不是已支持 all-in-runtime 的声明。实机由父任务使用当前项目 owner 的后台实例操作，固定 60 FPS。

## 准备静态资源

```powershell
D:/Program/Python/python.exe -B -X utf8 tools/runtime_probe/prepare.py --output .runtime/runtime_data_probe/resource_pack
```

输出独立资源包和同级 `runtime_data.py`。它复用游戏原生 `shaders/uv_fullscreen.vertex`；包含隔离材质 `pmanim_runtime_probe`、通用诊断 shader、两个蓝／紫占位 PNG 和写入所有权 marker。若向**隔离开发副本**合并文件，应合并 `materials/postprocess.material` 的独占 key，不能覆盖原播放器材质。marker 也须复制。

`prepare.py` 只生成占位数据。用于判断成功的 256 个数值必须随后在游戏 Python 中生成；不能把宿主生成的纹理冒充运行时数据。

## 父任务实机顺序

通过受管 SDK 执行，明确传入当前实例实际加载的探针包目录 `probe_pack`。`post` 为父任务通过公开 API 获取的后处理组件。先关闭当前播放器效果；以下调用不获取实例、不操作窗口。

```python
import runtime_data as rd

# 0. 校准：蓝/紫 16×16 棋盘必须可见，确认材质/槽位/截图区域。
baseline = rd.install_effect(post, "baseline", "textures/pmanim_runtime_probe/placeholder")
# 截图后关闭。以下每一步也独立截图，再关闭上一步效果。
rd.disable_effect(post, "baseline")

# 1. pack 加载后才创建的新路径，seed 可选本次会话新随机数。
first = rd.write_dataset(probe_pack, "fresh_a", 12345)
first_effect = rd.install_effect(post, "first", first["texture"])

# 2. 同路径更新；先保留 first receipt，避免被覆盖。
updated = rd.write_dataset(probe_pack, "fresh_a", 54321)
# 不重载：截图，验证是否还是第一份数据。

# 3. 不同新路径 + 独立 effect，验证资源路径缓存影响。
rd.disable_effect(post, "first")
second = rd.write_dataset(probe_pack, "fresh_b", 54321)
second_effect = rd.install_effect(post, "second", second["texture"])

# 4. 若数据网格通过，切换同一数据至 128 个二维点绘制。
rd.disable_effect(post, "second")
points = rd.install_effect(post, "points", second["texture"], mode=1)

# 清理自己的效果，不声称存在未经资料验证的 RemovePostProcess。
rd.disable_effect(post, "points")
```

每份 receipt 包含 128 个点／256 个 uint16、PNG 和原始 RGBA 的 CRC32、资源路径以及 `gpu_verified=False`。游戏实际环境的 `hashlib` 没有 `sha256`，因此游戏端不依赖该模块；宿主验证器检查 CRC32 后另外计算带 `host_` 前缀的 SHA-256。纹理为 16×16 RGBA8，RG 保存高低字节，B=0、A=255；占位纹理 B=255，不能与生成数据混淆。没有 gamma/sRGB 元数据；材质要求 Point 采样。运行时只使用 `struct`、`zlib` 等 Python 2 标准库。

可选后续分支：分别验证公开 `ReloadOneShader` / `ReloadAllShaders` / `ReloadAllMaterials` 后的画面，必须记清哪次成功依赖哪种重载。不能因“shader 重载成功”推断纹理已重载。不要在正常 tick 中运行这些开发重载操作。

## 像素验证

通过后台 WGC 得到截图；`--rect` 为截图中实际完整数据网格区域（不含边框），不传则使用完整截图。假如实际 Y 方向反了，应显式记录 `--flip-y`，不可悄悄挑选不同数据集。

```powershell
D:/Program/Python/python.exe -B -X utf8 tools/runtime_probe/verify_capture.py --capture .runtime/probe/fresh_a.png --receipt .runtime/probe/fresh_a.receipt.json --rect 0 0 1280 720 --output .runtime/probe/fresh_a.verify.json
```

验证器比对全部 256 个格子的 RGB 字节，默认最多允许 2/255 截图误差，同时报告完全一致数量、最大偏差及每项观测值。必须同时具备游戏执行回执、运行时 PNG 和两次不同数据对应的实际截图，才能认定运行时传输及更新成立。仅首帧通过不能认定可持续更新；只有开发资源目录写入通过不能直接扩张为发布环境支持。

覆盖同一路径之前，应将对应 PNG 和 receipt 一起保存到 `.runtime/` 证据目录，再用 `--data-png` 指向保存的文件。宿主验证器会拒绝与 receipt CRC32 不符的已覆盖文件。

## UI 路由的资料事实

2026-11-10 的公开资料检索结果：

- 网易 `ImageUIControl.SetSprite(texturePath)` 文档限定从资源包 `textures` 开始的路径；`SetTextureFileSystem`、`SetImageUrl`、`SetUrl` 未检索到公开 API。
- Bedrock Wiki 的 Sprite 属性列出 `texture_file_system`，包括 `InUserPackage`、`RawPath`、`RawPersistent` 等，同时标注 `Usage is Unknown`；`force_texture_reload` 描述为路径改变时重新加载。
- 网易原版 `GameAssets/resource_packs/vanilla_netease/ui/player_tips.json` 的 `player_head_image` 也使用 `texture_file_system: "RawPath"`，并将 `#selected_player_head_image` 绑定到 `#texture`。这确认原版资产使用该属性，但仍不是自定义模组写入／更新的实机证据。
- 因此 `RawPath` + 游戏生成 PNG 值得做隔离 JSON UI 实机探针，但不应声称这些属性在当前网易版本已经受支持。尚未找到通用 base64 图像上传 API，未找到不等于不可能。
- `write_dataset` 的 `absolute_png` 与 `texture` 可分别供 UI 子代理测试本地路径与普通资源路径。只有 UI 画面更新通过仍需进一步验证自定义 shader 读取、裁剪、遮挡、多实例和发布可用性。

原始截图和回执保存在 `.runtime/`。探针资源无需随正式模组发布。

结构审查会提示运行时探针的 `os` 以及宿主准备脚本的 `sys` 属于受限模块：本目录只用于授权的本地开发自测，不能把文件系统探针直接放进线上产品。即使开发客户端接受 PNG 文件更新，正式模组仍须找到符合平台规则的公开数据／图片入口；这一条件单独验收。
