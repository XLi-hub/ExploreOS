# 类似项目与候选底座

调研日期：2026-10-24。范围：公开的一手仓库、作者文档和部分源码。没有部署候选、调用付费模型或运行 GPU 实验。

## 1. 需求变化后的选型重点

用户明确希望探索宽泛的开放问题。因此通用的长任务代理、项目记忆和研究工具，比自动训练模型或生成论文更接近首版。

先前调研的 AutoScientists 相关项目仍有价值，但主要作为可选实验能力和协作策略的参考。

“作者文档描述”“读过相应实现”和“本地跑通”是不同证据级别。以下没有本地跑通项。

## 2. 通用开放探索候选

| 项目 | 一手资料描述的能力 | 本次检查 | 与本产品的关系 |
| --- | --- | --- | --- |
| [DeerFlow](https://github.com/bytedance/deer-flow) | 通用长任务代理、工具、技能、沙箱、记忆和子代理 | 根 README、backend/README.md 与公开核心概念文档 | 优先评估完整工作台底座；验证部署代价和跨轮项目认识 |
| [Deep Agents](https://github.com/langchain-ai/deepagents) | 可扩展代理 harness、文件上下文、子代理；基于 LangGraph 的持久化能力 | 根 README、包文档、官方概览 | 优先评估轻量运行底座；问题地图和产品交互仍需设计 |
| [EvoScientist](https://github.com/EvoScientist/EvoScientist) | 多角色研究、跨会话记忆、技能积累、定时任务和 WebUI | README、版本说明 | 评估持续探索体验；需确认能否摆脱固定科学任务流程 |
| [GPT Researcher](https://github.com/assafelovic/gpt-researcher) | 网页与本地资料研究、问题拆解、带引用报告、递归深度研究 | README、官方 Deep Research 发布说明 | 资料研究能力候选；验证持续课题与开放式重述的限制 |
| 现有编码代理的轻量封装 | 借助现有文件与工具能力，增加项目认识、方向和来源记录 | 目前是本项目提出的替代方案，未实现 | 作为最小成本对照，不预设要构建完整代理平台 |

DeerFlow 是完整产品候选，Deep Agents 是代码运行底座候选，GPT Researcher 更接近资料研究组件。不能只比较功能勾选数就认为可直接互换。

对“持久记忆”要分别核实：用户偏好、当前会话检查点、项目原始记录、可追溯研究认识。具备其中一种不意味着全部具备。

## 3. 实验研究及可靠性参考

| 项目 | 已查阅能力 | 使用建议 |
| --- | --- | --- |
| [AutoScientists](https://github.com/mims-harvard/AutoScientists) | Claude Code 子代理、ClawInstitute 协调、共享讨论与实验记录、方向重组 | 借鉴开放方向和经验共享，不把其实验优化结构变成通用任务门槛 |
| [AutoScientists-Codex](https://github.com/yptang98/AutoScientists-Codex) | 固定版本运行时安装、诊断、Codex 指引和原版协议映射 | 若后续需要原版实验策略，可优先验证适配器 |
| [OpenResearch](https://github.com/alphaXiv/OpenResearch) | 编码代理接入、本地实验记录、算力与产物管理 | 作为代码/实验工具候选；本机尚无 orx 命令 |
| [Arbor](https://github.com/RUC-NLPIR/Arbor) | 假设树、独立 worktree、运行产物、恢复入口 | 借鉴方向分叉和版本隔离，勿把数值优化当通用开放探索评价 |
| [AutoResearchClaw](https://github.com/aiming-lab/AutoResearchClaw) | 分阶段研究到论文、恢复、人工介入、结果与引用核验 | 当未来有报告/论文交付时评估，其固定阶段不是本项目默认路径 |
| [ARC](https://github.com/JasonCodeMaker/Agentic-Research-Control-Panel) | 研究意图版本、运行记录、证据绑定与控制面板 | 借鉴事实记录和解释之间的边界 |
| [R&D-Agent](https://github.com/microsoft/RD-Agent) | 数据驱动研究开发循环、场景实现与可视化记录 | 数据/模型研发分支的参考，非首版通用工作台优先项 |

## 4. 读源码后需要保留的区别

### AutoScientists-Codex

检查了独立适配脚本和测试文件。恢复准备命令主要补充运行指引和协调信息，并非完整的任意训练进程恢复机制。

参考：
- [适配脚本](https://github.com/yptang98/AutoScientists-Codex/blob/main/plugins/autoscientists-codex/skills/autoscientists-codex/scripts/autoscientists_codex.py)
- [测试](https://github.com/yptang98/AutoScientists-Codex/blob/main/tests/test_adapter.py)

### OpenResearch

检查了文件树、原生会话存储实现和 Windows 说明。Windows 仍标为 Beta，文档列出远程控制、进程及退出行为的限制。

参考：
- [原生会话存储](https://github.com/alphaXiv/OpenResearch/blob/main/src/local/native_store.rs)
- [Windows 文档](https://github.com/alphaXiv/OpenResearch/blob/main/docs/windows.md)

### DeerFlow 与 Deep Agents

作者资料已明确区分工具、上下文、记忆和运行机制，这与本项目的模块边界接近。运行状态、项目知识和长期记忆仍需实际映射，不假设一套检查点能解决所有问题。

参考：
- [DeerFlow 后端说明](https://github.com/bytedance/deer-flow/blob/main/backend/README.md)
- [DeerFlow 核心概念](https://github.com/bytedance/deer-flow/blob/main/frontend/src/content/en/introduction/core-concepts.mdx)
- [Deep Agents 官方概览](https://docs.langchain.com/oss/python/deepagents/overview)

## 5. 评估方法

优先做静态接口评估，再按可配置资源运行一到两个候选，不一次安装全部系统。

两个对照问题：

1. “为什么自主代理短期演示与长期使用之间有差距？”
2. “有没有更适合开放探索的个人知识组织方式？”

第一问适合因果解释与反例，第二问适合比较和创造性方案。测试中途追加一个新关注点，暂停并重启，再继续同一课题。

观察：

- 能否从宽问题自主开始，而不要求用户先填完整计划。
- 是否能改变问题拆解并保留旧认识。
- 来源是否真正支持结论，推断是否标清。
- 是否保存矛盾、未知与失败尝试。
- 是否跨轮接续，避免重复检索和伪造记忆。
- 工具失败和预算结束后状态是否准确。
- 需要修改上游多少代码，升级时是否易维护。
- Windows 环境需要哪些组件，能否形成稳定启动方式。

零费用模拟验证只覆盖记录、状态和导出；研究质量必须用真实模型/工具的实际结果评估。

## 6. 当前结论

暂定优先顺序：

1. DeerFlow：先判断完整产品能否小改满足需求。
2. Deep Agents 或现有代理轻量封装：作为依赖与定制成本较小的对照。
3. EvoScientist：比较持续研究、记忆和技能的用户体验。
4. GPT Researcher：需要强资料研究能力时评估为组件。
5. AutoScientists / OpenResearch 等：以后进入实验、代码研发场景再选。

这是基于当前阅读的工程判断，尚无运行成绩支持最终选型。下一步将结果写入独立决策记录，不直接宣布选定底座。

## 7. 引入上游的方式

在选择时记录仓库、固定 commit、实际读取的许可/通知文件，以及改动位置。优先组合和适配，避免把本仓库变成多个上游源码的混合副本。

AutoScientists-Codex 的作者也采用固定上游运行时与独立适配层分开的方式；这仅是一个工程参考，不替代对所选组件自身条款的核实。
