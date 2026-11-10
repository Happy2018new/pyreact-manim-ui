# 后台静默实机测试

根据用户要求，所有代理实机测试保持游戏在后台，固定 60 FPS。不能使用会激活窗口的鼠标键盘输入、前台截图或失败后激活再重试。画面检查使用后台 Windows.Graphics.Capture；交互逻辑使用受管 SDK/Pyreact 调用，并在报告中与真实鼠标命中测试区分。

`tools/start_dev.py` 强制要求经过哈希验证的 patched MCDK 与 R13 focus guard。guard 在新建的挂起游戏进程继续执行前安装，只保护本次拥有的游戏进程；旧工程、其他会话和全局安装不修改。缺少工具或验证失败时停止，不降级到普通前台启动。

首次配置，在仓库根目录创建本机配置：

```powershell
Copy-Item -LiteralPath tools/background-tools.example.json -Destination background-tools.local.json
python -B -X utf8 tools/start_dev.py --owner manim-demo
```

示例路径在配置复制到仓库根目录后解析，复用同级 `better-building-editor` 中已有工具，无需复制二进制。其他机器应安装相同来源工具并更新路径及经过验证的哈希；不要把普通官方 MCDK 填入 patched MCDK 字段。配置被 Git 忽略，代码保留可复查的示例 pin。

既有工具来源：`better-building-editor/tools/native_focus_guard/README.md`、`docs/BACKGROUND_FOCUS_STARTUP_RESULT_R13.md`。MCDK 基于 v1.6.1，guard 使用包含 `SetFocus` 修复的 R13 版本；没有采用更早的 guard。它们仅是宿主测试设施，不进入玩家预览包。

启动器清除 `MCDEV_ALLOW_USER_FOREGROUND` 继承值。session 记录 guard 请求、二进制哈希及窗口保护状态。调用和截图继续检查 owner、PID 创建时间、后台状态和 `WS_EX_NOACTIVATE`。用户可以正常切换其他应用；测试不把焦点切到游戏，也不“恢复”或替用户切换焦点。

若窗口被最小化或后台保护失效，相关验证停止并报告原因。受管无激活 resize 只可在未最小化的本项目窗口使用。Esc/F8 等键盘入口可由 SDK 事件路径验证，真实硬件按键仍需人工复核，不能把事件模拟写成真实按键通过。
