# ADR 0006：Pi 作为新的参与者执行路径

日期：2026-10-25。状态：Pi 库已接入并通过一次真实兼容测试；subagent 插件完成核对，运行接入待验证。

用户明确建议使用 Pi 底座，并要求查看 subagent 插件。该要求更新 ADR 0003 中对上游执行器的默认取用：保留 AutoScientists 的可用任务/身份布局和 ClawInstitute 共享空间，新的真实参与者执行采用 Pi 的 Agent core 与 pi-ai。原 Claude Code 路径保留为已有案例/对照，不混换同一项目后端。

采用当前官方 `@earendil-works/*@1.4.0` 固定发布包，而非已弃用的 `@mariozechner/*`。当前每次唤醒一个无工具、单请求 Agent；记忆与协作状态由 ExploreOS 提供，付费请求继续经过共享原子准入。

`pi-subagents@0.82.0` 已核对，具备应当复用的子会话、流程、控制与可视化能力。当前没有它要求的 Coding Agent 扩展宿主与运行身份映射，因此不直接加载整个插件。未来工具型或长期子任务优先通过其公开 preflight/delegation/RPC 接缝取用，明确由谁拥有运行状态，避免重造通用编排。

具体源码依据、实际调用、费用及未验收边界见 [Pi 执行底座与插件核对](../pi-runtime.md)。本决定不表示 Pi 具有更高探索质量，也不改变 [产品核心](../product-core.md) 中持续探索收益必须实测的要求。
