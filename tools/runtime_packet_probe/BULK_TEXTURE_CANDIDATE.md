# 大块动态纹理候选研究

2026-11-17 只读调研。本文的新候选均未实现、未实机验证；不把纹理尺寸容量等同于可持续上传吞吐。

既有 `tools/runtime_probe/runtime_data.py` 可在游戏 Python 2 内生成数据并写 PNG；编码函数支持任意正尺寸，现有生成器、shader、验证器固定为 16×16、256 个 uint16。后处理将纹理绑定到 `TEXTURE_2`，shader 既展示编码格，也解码绘制 128 个点。

2026-11-10 实机结果：已有路径在首次使用前由游戏覆盖后，256/256 texel 完全一致；第二次覆盖仍读旧数据，重载 shader 无效，全材质重载后新数据才完全一致。重载超出 IPC 等待期，无准确耗时。启动后新增路径持续缺失；普通 Image、RawPath 及 ASCII 路径复核也未显示新文件。依据见 `docs/RUNTIME_ACCEPTANCE.md` 和对应 `data-probe-summary.json`。

RawPath 需区分 setter 与 binding：旧 UI 探针对固定 RawPath Image 调用 `SetSprite(absolute_png)`，该 API 公开契约仅保证资源路径。资料库原版 `player_tips.json` 却以 `#selected_player_head_image` 绑定到 `#texture`。旧失败没有涵盖构造时直接指定路径或 binding 更新。`force_texture_reload` 仅描述路径改变时重载，未保证同路径内容刷新。

容量候选固定 alpha=255，以 RGB 存数据：128×128 为 48 KiB，256×256 为 192 KiB，512×544 为 816 KiB。最小缓存实验预登记 A/B 占位纹理，游戏首次引用前写新 PNG，复用现有后处理，检查首次读取、A→B→A、覆盖 A 后再读 A，不执行全材质重载。另用一个 Image 对照 RawPath 构造、binding、SetSprite，先测 16×16，再扩大尺寸。

消费端须独立证明：当前 packet 只验证 `CURRENT_COLOR`，未验证 Image 纹理会继承给紧邻 paperdoll sampler；Image 自定义 material 的公开依据亦未找到。应让 shader 按指定索引置换采样。必须核对全部 payload 字节，可将 512×544 分四页 256×272 验证，保存 receipt、PNG、截图；抽点、CRC、接口成功均不能代替全数据 GPU 校验。重复更新成本与发布环境入口仍待验证。
