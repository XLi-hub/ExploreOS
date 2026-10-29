# ExploreOS

面向开放问题的多智能体持续探索系统：多个智能体提出方向、交换证据、相互质疑、根据新材料调整分工，并积累能够接续和修订的共同认识。

ExploreOS 关注问题如何越探越清楚、失败如何被后来者利用、用户改向后如何继续。产品、生活与工作方式、机制比较、创意、诊断和科研都可以是任务。核心定位与验收见 [产品核心](docs/product-core.md)。

**状态：2026-10-28。已有探索 CLI、ClawInstitute 内探索视图、来源核查/记忆复查、固定对照评测、1–8 个身份、跨课题引用和有界唤醒。56 个两轮机械评测案例已通过；真实协作质量与长期运行仍待验收。证据见 [路线图工程验证](docs/roadmap-validation.md) 和 [M1 个案](docs/m1-validation.md)。**

验收可直接按 **[验收指南](docs/acceptance-guide.md)** 运行零付费示例，检查发现、质疑、方向变化与跨轮记忆。真实模型另行启用，不进入安装或 CI。

产品使用目标与实际交付缺口见 **[产品交付](docs/product-delivery.md)**。原生入口现以问题和阶段成果为主：自动生成项目代号、保存探索设置、下载可追溯的 Markdown 简报，并区分当前发现、旧问题记录和未生效回应。

日常安装可按 **[安装与持久运行](docs/deployment.md)** 使用 `docker compose up --build -d`，打开 `http://127.0.0.1:3001/api/v1/exploreos/ui`。数据库、课题与预算引用保存在命名卷，重建容器保留；默认不启动探索或付费计划。

也可从 [产品容器检查](https://github.com/XLi-hub/ExploreOS/actions/workflows/product-container.yml) 的成功运行下载预构建安装包，按内附 README 校验、加载镜像并启动。

云端配置从 **[CLOUD.md](CLOUD.md)** 开始：Python 3.11、Node 22、固定 AutoScientists 与 ClawInstitute 版本、安装入口和真实 API 检查。后续开发完全通过 GitHub 与云端进行。

安装并启动服务后，运行 `.venv/bin/python -m explore.workbench`，在运行机器打开 `http://127.0.0.1:3001/api/v1/exploreos/ui`，沿用 ClawInstitute 原登录。浏览器可以创建、导入材料、推进与追加有限轮次、改向/暂停、核对失败、关联其他课题发现和导出。真实模型执行需另行配置凭据与明确预算；默认仍是零付费机械演示。

## 已确认的方向

多智能体协同探索是产品核心，从首个可用版本开始验证。任务可以宽泛，不要求事先具备标准答案、数值指标、数据集或实验方案。

阅读、检索、推理、比较、代码分析、数据分析、原型和实验，都可以成为探索手段。探索中允许产生新问题、修订解释、改变方向，并保留分歧。

## 核心过程

    用户提出开放问题与关注点
                    ↓
    多个具有独立上下文的智能体提出初始方向
                    ↓
    在共享探索空间发布提案、发现、质疑和反例
                    ↓
    智能体选择方向与行动，形成临时分工
                    ↓
    获取材料 / 推理 / 比较 / 分析 / 可选验证
                    ↓
    共享结果与失败，修订认识，分叉 / 合并 / 暂存 / 重开方向
                    ↓
    阶段简报与可继续的项目记录

默认沿用 AutoScientists + ClawInstitute，在已有 workshop、workspace、讨论、心跳和共享记录上做开放任务适配。先验证上游链路，补齐必要缺口；不先重建协作服务或完整界面。研究方向由智能体交互形成，协调层管理调用与执行边界。详见[复用核对](docs/upstream-reuse.md)。

## 首版必须证明什么

- 至少三个具有独立会话与持久身份的智能体参与同一问题；初始视角可配置，分工可变。
- 同伴的发现或质疑能实际改变后续行动，并能追溯到对应记录。
- 至少保留两条可区分的探索路线；讨论能够留下未解决的分歧。
- 在有理由时改变方向或分工，保留依据与历史。
- 跨两轮接续，并在进程重启、用户改向、预算耗尽时维持准确状态。
- 真实模型用于探索质量验收；模拟代理用于机械测试。
- 单代理与独立多代理作为对照，与协作协议一起评估。

可执行 CLI 示例默认采用模拟代理、本地材料、零付费预算。另有三个独立上下文的真实两轮案例，以及单代理、无交流多代理和协作多代理的初步对照；内容质量与长期收益仍需评阅。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [验收指南](docs/acceptance-guide.md) | 安装、零付费示例、任意开放问题、改向与记忆检查 |
| [M1 验证记录](docs/m1-validation.md) | 已实现能力、真实案例、排除样本与未验收边界 |
| [真实探索链](docs/m1-case-study.md) | 同伴内容、材料、成员调整、记忆接续及共同误判的记录 ID |
| [记忆复查](docs/memory-feedback.md) | 旧发现、质疑、新材料与后续行动怎样关联；零模型示例 |
| [来源支持核查](docs/source-support.md) | 检查原文支持范围，记录署名判断、分歧与后续取回 |
| [固定对照评测](docs/evaluation-pilot.md) | 八任务冻结包、四配置/三消融、重复运行、匿名评阅与报告 |
| [探索工作台](docs/workbench.md) | 浏览器中的问题、方向、证据、认识变化和运行控制 |
| [备份与恢复](docs/backup-restore.md) | 私有冷备、空实例恢复、预算保留与隔离验证 |
| [有限持续运行](docs/daily-use.md) | 人数/并发、跨课题引用、唤醒、停用和恢复 |
| [路线图工程验证](docs/roadmap-validation.md) | 已实现、已验证和仍待真实验收的边界 |
| [插件前台委派](docs/subagent-integration.md) | 已接入的 subagent 路径、运行所有权、回执与恢复边界 |
| [Pi 执行底座](docs/pi-runtime.md) | Pi 接入、真实兼容测试、subagent 插件能力与接入边界 |
| [产品核心](docs/product-core.md) | 论文机制、与通用子代理团队的关系、记忆与持续探索的价值验收 |
| [云端开发入口](CLOUD.md) | 可直接使用的环境准备说明、安装、服务与检查命令 |
| [M0 验证记录](docs/m0-validation.md) | 调用链与所有权、并发复现/补丁、真实模型观察和 M1 改造清单 |
| [产品设计](docs/product-design.md) | 多智能体探索的用户体验、交互与首版边界 |
| [系统架构](docs/architecture.md) | 共享空间、心跳、协作协议、并发与恢复 |
| [AutoScientists 机制迁移](docs/autoscientists-transfer.md) | 原论文依据、泛化方案和待核对实现 |
| [上游复用核对](docs/upstream-reuse.md) | AutoScientists + ClawInstitute 的源码依据、可用能力和已知缺口 |
| [类似项目调研](docs/research-landscape.md) | 机制参考与运行底座的不同职责 |
| [评测设计](docs/evaluation.md) | 协作收益、消融、成本和开放问题评价 |
| [实施路线与验收](docs/roadmap.md) | 从机制核对到最小多智能体探索系统 |
| [开发协作方式](docs/development-workflow.md) | 双账号、任务 worktree、集成评审与云端接入时机 |
| [当前复用决策](docs/decisions/0003-upstream-first.md) | 默认沿用 AutoScientists + ClawInstitute，优先局部适配 |
| [产品核心决策](docs/decisions/0002-multi-agent-exploration.md) | 多智能体成为核心、取代旧版产品顺序 |
| [旧版决策](docs/decisions/0001-local-research-workbench.md) | 已被 ADR 0002 取代，保留历史 |
| [配置示例](examples/project.example.json) | v0.2 接口提案，尚不可执行 |
| [开发协作约定](AGENTS.md) | 后续开发与验证规则 |

## 当前进度

- [x] 连接 GitHub，当前开发与交付全部在云端。
- [x] 确认宽泛开放问题与多智能体协同探索的核心定位。
- [x] 阅读 AutoScientists 论文相关方法、实验、消融和实现附录，修订设计。
- [x] 完成 M0 的 Linux 服务、调用链核对、并发修补与有界真实互读，限制见验证记录。
- [x] 实现 M1 候选，通过机械检查并完成有界真实案例。
- [x] 接入 Pi 执行库，补齐课题记忆的复查/修订与同伴质疑协议。
- [x] 交付ClawInstitute 内探索视图、固定评测驱动、跨课题引用与有界唤醒，完成机械与浏览器检查。
- [ ] 用户验收 M1 的来源支持、分歧、行动变化与开放任务价值。
- [ ] 用固定材料与真实问题评估协作收益。

《日常探索模式》的原始会话正文仍未读取。本次方向依据当前聊天中用户明确的需求，以及用户提供的 ExploreOS HTML 方案；不推断原会话的额外要求。

产品、自有软件和当前 GitHub 仓库均名为 ExploreOS，远端为 `XLi-hub/ExploreOS`。此前文档中的旧仓库名属于改名前记录。
