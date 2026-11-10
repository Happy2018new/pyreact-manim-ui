# 正式 UI 画布构建资源

`pmanim_canvas.vertex` 是生产画布的稳定顶点源。`tools/build_canvas.py` 将它复制到资源包，并把当前已部署的静态场景转换成透明 UI shader。构建不依赖 `tools/ui_canvas_probe/` 实验目录。

更新静态场景后运行：

```powershell
D:/Program/Python/python.exe -B -X utf8 tools/build_canvas.py
```

使用 `--output <目录>` 可生成隔离的行为包／资源包输出。清单 `generated_files.json` 记录本工具生成的文件和材质键的 SHA-256，属于宿主构建元数据，不是游戏资源。

后续构建删除场景时，只会删除旧清单登记、仍与登记摘要一致、位于允许命名空间的旧 shader 和实体文件，以及本工具的旧材质键。共享场景 PNG、其他材质、未登记文件不会被清理。生成文件若被手动修改，构建在写入／清理前报错并保留它，先检查差异，再决定如何迁移改动。没有旧清单时，只接管与本次生成结果完全相同的已有文件。

整个清理过程只删除逐项验证过的文件，不递归删除目录；路径不得越过输出根目录，也不得经过符号链接。

聚焦测试：

```powershell
.venv-reference/Scripts/python.exe -B -X utf8 -m unittest discover -s tests -p test_build_canvas.py -v
```

默认包含小型真实 OpenGL 合成与参数图元测试。全部复杂场景 shader 编译耗时较高，仅在环境变量 `PMANIM_FULL_CANVAS_GL=1` 时启用。桌面 GL 不能替代 Minecraft 的最终实机验收。
