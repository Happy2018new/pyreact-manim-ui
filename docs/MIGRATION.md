# 开发技能与 agent 配置迁移

## 来源与范围

迁移来源为同机 `better-building-editor` 工作区的 `.agents/skills` 与 `.codex/config.toml`。仅复制可维护的 Markdown 和 Python 调试脚本；没有复制游戏、世界、投影业务、字体图集、知识库、缓存或可执行文件。

迁移了九个技能：`ffi-cache`、`hash-key`、`mc-search`、`mod-workflow`、`next-opt`、`py-except`、`py-init`、`pyreact-debugging`、`pyreact-ui-building`。移除 `pyreact-debugging/bin`、缓存和投影专属 `references/projection.md`。保留通用实例身份校验、桌面锁和重定向 AppData 修复。

源工作区未发现根 `AGENTS.md` 或自定义 agent 定义文件。根 `AGENTS.md` 与 `.agents/README.md` 为本项目新建，规定文字优先、离线编译/游戏播放边界、并行文件所有权与证据要求。运行中的子代理会话不能通过复制文件迁移。

## MCP 与外部工具

`.codex/config.toml` 复用已有 mcdk-assistant v0.2.7 LITE 的 `--stdio` 入口，路径仍位于来源工作区的 `.tools/mcdk-runtime/v0.2.7/`。这是有意保留的本机共享工具引用，不是新仓库自带的二进制。其他机器或移动来源仓库后，需要把该配置的 `command` 改成实际安装路径。

来源记录的 mcdk-assistant 资料基准为 `172b3bc8289912e58a096349f568d1b921005d8c`。配置不复制凭据，也不修改全局 MCP 设置。工具配置在会话重连后是否加载，应通过实际 `tools/list` 与帮助核对。

MCDevTool 与 mcdk-assistant 是两个独立工具。MCDevTool 沿用用户目录中的安装，按迁入技能的 setup 流程检查。此迁移不下载或复制调试二进制；可选 native profiler 需要按 setup 的实际支持另行准备。

## 技能适配

- `mc-search`、`mod-workflow` 的本地记录链接改为本文，范围示例改成新项目命名。
- `pyreact-debugging` 移除投影专项回归说明，改为 `references/project.md`。
- 去除 UI 技能中仅属于旧项目的 `cacheLayout` 扩展说明，避免把尚未引入的框架补丁当成新项目可用 API。
- 通用 Python 调试脚本保持行为，更新来源注释；它们的扩展诊断指令是否可用，取决于游戏内实际安装的框架。
- 技能迁移之后，已独立引入 Pyreact 框架及 UI 模板用于播放器。框架位于 `behavior_pack/manim_ui/pyreact`，来源与保留补丁见其中的 `INTEGRATION.md`；宿主编译工具不依赖游戏框架。

## 来源许可

- 七个 mcdk-assistant 技能保留 [BSD 3-Clause 原文](vendor/mcdk-assistant.LICENSE.txt)。
- 两个 Pyreact 技能及其上游脚本/文档保留 [PyreactMC LICENSE](vendor/PyreactMC.LICENSE.txt) 和 [NOTICE](vendor/PyreactMC.NOTICE.txt)。框架基准是 `9580d0123584ae8b4b4b3a7b0357250e151c54cd`，含来源项目本地修改；实际引入的运行时另附完整许可、NOTICE 和来源说明。
- 新项目的原创代码许可由仓库所有者决定，本次未擅自复制旧项目根许可。

## 验证边界

本轮迁移检查结果：九个技能、二十个 Python 调试脚本解析通过；技能 Markdown 本地链接无缺失；共享 MCP 可执行文件存在；`instances.py --help` 正常返回。详细回执保存在忽略目录 `.runtime/migration-verification.json`。

源工程保持不变。独立受管实例已经加载当前项目并显示文字与播放面板；实际画面与后续功能验收分别登记，不由迁移成功推断。完整参考依赖只装入忽略的 `.venv-reference`，没有复制游戏或世界进仓库。
