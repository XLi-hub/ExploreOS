# 类似项目与运行底座：按多智能体探索需求评估

修订日期：2026-10-24。本文整理此前静态阅读与本次论文核对，不代表候选部署或性能验证。

## 1. 选型问题

产品的重点是多个智能体如何共同探索：独立上下文、共享提案与经验、相互质疑、方向调整和持续记忆。

默认先复用 AutoScientists + ClawInstitute。其他项目作为适配参考与具体缺口的备选，不再与原生路线平行搭建整套平台。具备子代理、记忆或报告功能，只能成为候选线索。

证据级别分别标明“作者资料描述”“已阅读部分实现”“本地验证”。当前没有候选完整跑通的结论。仓库功能和兼容性需要在 M0 对固定版本重新检查。

## 2. 核心机制参考

| 项目 | 已有阅读范围 | 对本项目的用途 | 待核实问题 |
| --- | --- | --- | --- |
| [AutoScientists](https://github.com/mims-harvard/AutoScientists) | 论文相关方法、消融、局限和实现附录；README、启动脚本、runbook 与部分参考文件 | 首要探索协议参考，迁移关系见单独文档 | 实际调用链、共享状态服务、协议哪些由程序强制；开放任务接口怎样替换 |
| ClawInstitute 本地 npm 包 | 0.1.3 包内 README、许可、启动、workspace/DB/auth 实现 | 默认共享服务与已有前端，详见[复用核对](upstream-reuse.md) | 条件写竞态、持久化、平台/前端兼容性与开放内容映射；GitHub 仓库本次返回 404 |
| [AutoScientists-Codex](https://github.com/yptang98/AutoScientists-Codex) | README、适配脚本与测试 | 参考原协议与执行后端分离的适配方式 | 固定版本、运行前提、会话与恢复的真实范围 |
| [EvoScientist](https://github.com/EvoScientist/EvoScientist) | README 与版本说明 | 比较协作、记忆及持续研究的产品取舍 | 方向是否由固定组织决定，能否支持开放问题及本项目协议 |
| [Arbor](https://github.com/RUC-NLPIR/Arbor) | README 与公开结构说明 | 参考方向分叉和工作区隔离 | 其任务/评价边界与本项目是否兼容 |

AutoScientists + ClawInstitute 作为默认实现路线进入 M0。静态检查已确认部分可复用能力，也发现具体缺口；最小运行验证仍未完成。默认路线并不等于兼容性已验收。

## 3. 可评估的执行底座与工具组件

| 候选 | 此前阅读范围 | 可评估用途 | 关键验证 |
| --- | --- | --- | --- |
| 现有编码代理的轻量适配 | 尚无本项目实现 | 提供模型会话、文件和工具能力，探索协议由项目层承载 | 独立会话、结构化输出、并发、退出和费用记录是否可控 |
| [Deep Agents](https://github.com/langchain-ai/deepagents) | README、包文档、[官方概览](https://docs.langchain.com/oss/python/deepagents/overview) | 候选代理执行与上下文底座 | 共享空间协议、持久身份和检查点的所有权映射 |
| [DeerFlow](https://github.com/bytedance/deer-flow) | README、后端说明与公开核心概念文档 | 候选完整运行/交互底座 | 是否能接入动态协作而不被既有主代理组织限制，以及依赖成本 |
| [GPT Researcher](https://github.com/assafelovic/gpt-researcher) | README 与作者 Deep Research 说明 | 资料研究组件候选 | 来源与结果能否进入本项目共享记录；不以报告生成代替协作协议 |
| [OpenResearch](https://github.com/alphaXiv/OpenResearch) | README、原生会话存储与 Windows 说明 | 可选代码/实验工具和记录能力 | 本地运行前提、进程与恢复接口；此前本机未配置 orx |

表中是此前整理的备选，并非并行开发计划。M0 先验证原生路线和已有 Codex 适配；只有具体缺口需要时，才评估对应组件，不启动第二套完整协作平台。

## 4. 其他工程参考

- [AutoResearchClaw](https://github.com/aiming-lab/AutoResearchClaw)：此前读取其研究到论文的流程说明，可参考阶段记录和失败处理。
- [ARC](https://github.com/JasonCodeMaker/Agentic-Research-Control-Panel)：此前读取研究意图、证据和运行记录的组织方式。
- [R&D-Agent](https://github.com/microsoft/RD-Agent)：此前读取数据驱动研发循环的场景说明。

这些项目不因被列出就成为首版依赖。新增依赖需说明具体缺口、读取实际接口与许可，并验证升级成本。

## 5. 需要防止的错误等同

- 子代理委派能力，不直接等于自主形成和调整方向。
- 持久聊天，不直接等于可追溯的共享研究记忆。
- 一个恢复命令，不直接等于能接管任意外部运行进程。
- 多人给出相同结论，不直接等于多份独立证据。
- 更高实验效率，不直接等于更低模型费用或更短实测耗时。

此前读过的 [AutoScientists-Codex 适配脚本](https://github.com/yptang98/AutoScientists-Codex/blob/main/plugins/autoscientists-codex/skills/autoscientists-codex/scripts/autoscientists_codex.py) 与 [测试](https://github.com/yptang98/AutoScientists-Codex/blob/main/tests/test_adapter.py)，不能替代真实后端的恢复验证。

此前读过的 [OpenResearch 会话存储](https://github.com/alphaXiv/OpenResearch/blob/main/src/local/native_store.rs) 与 [Windows 说明](https://github.com/alphaXiv/OpenResearch/blob/main/docs/windows.md)，也仅构成进一步核查入口。

## 6. M0 的共同验证场景

三个智能体使用同一开放问题和固定材料包，分别形成初始方向，在共享记录中发布、互读、回应，并执行一个受同伴内容影响的行动。

过程中制造一次过期写入或参与者失败，再恢复。随后让参与者提出方向调整，保存确认、生效或未决记录。

观察：

- 会话、身份、局部工作记录是否真实分离。
- 调度器是否只管理运行，研究决策是否有明确提案来源。
- 读取游标、帖子、认领与方向变更能否持久化。
- 模型、讨论、工具和重试是否进入统一用量记录。
- 不替换大段上游内部代码时能否接入协议。
- Windows 上启动、并发、退出和重启的实际行为。
- 谁拥有运行状态，如何避免双重调度或双重事实来源。

相同材料、模型和预算用于对照。模拟代理可验证机制接口；真实互动和探索质量需另行运行。

## 7. 引入上游的方式

记录仓库、固定 commit、实际读取的许可与通知文件、依赖及改动位置。优先组合或小范围适配。

默认路线已由 ADR 0003 明确为 AutoScientists + ClawInstitute。验证时记录保留与局部改造清单；若具体组件必须替换，再写 ADR 列出阻塞、无法满足的需求与代价。
