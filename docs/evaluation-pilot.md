# 固定任务包、对照与评阅

这是 M2 的可执行评测基础设施。真实模型质量、协作收益和人工评阅必须另行完成；模拟输出不能补入真实模型结果。

## 任务与冻结

[pilot.json](../examples/evaluation/pilot.json) 包含八个任务，五个是开放问题，三个是有明确核查点的技术/材料问题。材料全部是明确标注的合成或固定技术情景，不冒充真实用户调研。每个任务有原问题、第二轮关注点、争议和评阅规则；可核查任务还预先写有检查点。

~~~bash
.venv/bin/python -m explore.evaluation freeze examples/evaluation/pilot.json .research/pilot-frozen.json --repeats 3
.venv/bin/python -m explore.evaluation prepare pilot .research/pilot-frozen.json
~~~

freeze 不需要模型或服务。它快照材料，固定模型标识、输出上限、每轮调用上限、两个问题版本、重复次数、抽样规则、匿名排序种子和协议指纹。更改内容会使完整性检查失败；不同机器上的相同材料和指定种子得到相同协议。prepare 在现有 ClawInstitute 中登记实验设计；项目本身继续拥有调用、预算、发布和恢复状态。

新协议还记录核心执行代码、脚本、版本锁和补丁的内容指纹。升级实现后不能继续追加旧协议的调用，需冻结新 campaign；旧协议的历史仍能导出，报告标注当前实现是否吻合。供应商权重版本的限制仍保留，代码指纹不冒充模型版本证明。

默认有四种配置和三项消融：

| 名称 | 变化 |
| --- | --- |
| single | 一个参与者 |
| multiple_perspectives | 一个参与者检查多个视角 |
| independent | 多参与者不读取同伴语义 |
| collaborative | 多参与者共享发现、质疑和方向调整 |
| no_peer_critique | 保留同伴发现，关闭结构化同伴质疑通道 |
| fixed_directions | 保留发现与讨论，不应用方向/成员调整 |
| no_execution_failure_memory | 原始执行失败照常记录，后续私有上下文不取回这些失败笔记 |

最后一种只消融执行失败笔记，不宣称已经涵盖所有领域中的失败经验。消融不移除执行审计、原子认领、预算和恢复机制。每个配置的调用上限相同，但单代理可能用不完额度；报告列出实际调用，不能把上限相同描述为实际成本相同。

## 执行与接续

零付费机械检查建议另建一次重复的 campaign，避免混用后端：

~~~bash
.venv/bin/python -m explore.evaluation freeze examples/evaluation/pilot.json .research/mechanics-frozen.json --repeats 1
.venv/bin/python -m explore.evaluation prepare mechanics .research/mechanics-frozen.json
.venv/bin/python -m explore.evaluation advance mechanics --maximum-cases 56
.venv/bin/python -m explore.evaluation export mechanics
~~~

默认 advance 为模拟执行。相同 campaign 再次 advance 会跳过已完成案例；每个案例仍使用原来的项目、调用身份和恢复状态。暂停或失败的案例需要先到对应项目 status/reconcile/retry 处理，不自动重试未知请求。案例的材料、问题干预、语义策略或额度若偏离冻结协议，会停止并报冲突。

真实调用必须使用另一个 campaign，并已配置 `DEEPSEEK_API_KEY` 和明确共享预算：

~~~bash
.venv/bin/python -m explore.evaluation advance pilot --live --backend pi --budget-cny AUTHORIZED_TOTAL_LIMIT --maximum-cases 1
~~~

不要直接运行金额占位符。已有共享预算不因重复运行或新案例清零；耗尽后不开始新请求。默认完整设计是 8 × 7 × 3 = 168 个两轮案例，不宜在没有明确总预算时一次性启动。供应商型号使用实际模型标识和运行回执；SDK 锁定不等于供应商权重版本已冻结。

## 匿名评阅与报告

导出目录包含：

- `review-packet.json`：隐藏显式配置/成员标签，随机排序的输出、原文、评阅维度和抽样下标。
- `private-key.json`：匿名案例与实际配置对应关系，评阅时单独保管。
- `report.json` / `report.md`：全部计划案例、未开始/未完成/失败项、实际调用、可得的供应商用量、分任务/配置/重复的结果，以及逐条评阅。

输出内容或长度仍可能透露配置，不能保证完全盲评。主张按预先约定的哈希顺序抽取，每例最多五条；实际帖子 ID 在非匿名报告中保留，可用 source-audit 检查支持范围。开放问题不预写唯一答案，也不自动计算探索质量总分。

评阅文件为六个维度的 JSON，每项取 `useful` / `mixed` / `weak` / `uncertain`：question_clarity、explanation_coverage、counterexamples、evidence_scope、continuity、useful_next_steps。

~~~bash
.venv/bin/python -m explore.evaluation review pilot ACTUAL_BLIND_ID ratings.json --reviewer "reviewer_a" --reason "指出具体发现、边界和缺口" --review-id first-review
~~~

保留不同评阅者的分歧和理由。同一评阅 ID 的相同提交去重，不同内容拒绝覆盖。少于三次重复应标为个案；没有人工评阅不推断收益。共享池的预留/结算是准入记账，不是供应商账单。
