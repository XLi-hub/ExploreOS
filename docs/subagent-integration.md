# pi-subagents 前台委派接入

日期：2026-10-25。固定 `pi-subagents@0.82.0` 与 Pi Coding Agent / Agent core / pi-ai / pi-tui `1.4.0`。本次把前一步的源码核对推进为可运行的前台子任务路径；后台、嵌套委派与 Fleet 工作台不在此次验收中。

## 怎样使用

~~~bash
bash scripts/cloud/setup.sh
bash scripts/cloud/setup_subagents.sh
.venv/bin/python scripts/cloud/runtime.py start
.venv/bin/python -m unittest discover -s tests -p test_subagents.py -v
~~~

以上检查使用真实 SDK、插件、服务与版本化预算存储，供应商用替身，不需要模型密钥。

新的真实项目在已明确授权模型预算后使用：

~~~bash
.venv/bin/python -m explore create plugin_example --question "一个读书小组怎样在关注点改变后继续利用旧发现和分歧？"
.venv/bin/python -m explore advance plugin_example --backend pi-subagents --budget-cny 5
.venv/bin/python -m explore executions plugin_example
.venv/bin/python -m explore export plugin_example
~~~

`advance` 默认仍为模拟后端。已有 `pi`、`claude` 或模拟项目不混换执行器。现有共享池包含开发历史，不因新项目、再次传预算或追加轮次而清零；已有产物的核对不增加模型调用。

## 实际复用的公开接口

宿主通过 `DefaultResourceLoader` 的显式 extension factory 加载插件，在 `bindExtensions` 完成后调用：

- `pi-subagents/capability-ceiling`：只允许 `exploreos-leaf`，工具上限为空，拒绝额外扩展。
- `pi-subagents/preflight`：核对 fresh 上下文、实际角色文件、工具和指令继承配置，记录启动配置摘要。
- `pi-subagents/delegation`：使用标准 request/started/update/response/cancel 事件族。调用携带 `requestId + ownerRunId + nodeId`，只接受同一身份的回执。

前台子会话由插件的既有执行器创建和收尾，没有复制其 child-session、workflow 或调度实现。其终态 `launchContractDigest` 必须与 preflight 的同名字段一致。preflight 的外层 `digest` 是另一种摘要，不能混用。

父会话不调用模型，只发一次确定的结构化委派。叶子接收 ExploreOS 提供的身份、问题、记忆和材料上下文，负责当前阶段的实际探索输出。当前一个调用对应一个隔离的 Node 宿主，插件子会话运行在其进程内；同项目的阶段秩序与探索内容协议继续由 ExploreOS 控制。

## 所有权与记录

| 内容 | 权威与处理方式 |
| --- | --- |
| 问题、方向、发现、质疑与记忆复查 | ClawInstitute 的既有帖子及版本化状态 |
| 轮次、行动认领与发布结果 | ExploreOS 的既有 CAS 和稳定 publication intent |
| 子会话启动、插件 runId 和终态 | pi-subagents；桥只记录公开事件回执，不修改插件原生运行状态 |
| 派发对应关系 | 认领后、启动前保存稳定身份与相对回执路径；显式重试使用新的请求身份并保留旧尝试 |
| 供应商费用 | 现有共享预算池，在真正请求前原子预留；插件 usage/cost 仅是运行观察，不替代准入或账单 |

调用的私有目录中保存 `delegations/<调用ID指纹>/receipt.json` 和隔离宿主配置/插件原生记录。回执是公开事件的持久投影，记录实际 `runId`、父会话、启动摘要与终态。不是新的可独立控制的任务数据库。`executions` 同时显示控制器状态和插件观察，包含已退休的失败尝试；JSON 导出也保留这些观察。

## 有限执行与恢复

当前只启用 fresh、无工具、单供应商请求的前台叶子。项目/全局上下文和技能继承关闭；宿主只加载固定插件及桥，角色文件在此调用的私有目录中生成并核对。后台计划、自动 missions 和嵌套委派关闭。没有改变用户的全局 Pi 配置。

SDK 重试和自动压缩关闭。注册给子会话的模型传输只允许一次 stream 请求，并仍经过同一 loopback 准入网关。真实 DeepSeek key 留在 Python 控制进程内存，子宿主仅取得临时中继凭据。退出前运行插件 shutdown；隔离包装进程随后结束，避免 SDK/插件的常驻 housekeeping timers 挂住一次有限调用。

取消通过完整委派身份通知插件，然后核对拥有的宿主进程退出；必要时仍由原执行层终止进程组。宿主退出不证明远端供应商已经停止，未知费用预留继续保留。

恢复时不能仅凭供应商返回了合法 JSON 就认定子任务完成：

1. 宿主或子进程还活着时不接管它。
2. 完成必须有匹配身份、版本、启动摘要、无工具/单 turn 观察和结果的插件终态回执，且供应商结果已核对。
3. 插件失败时保留失败，即使供应商文本看起来可用。回执缺失、损坏、身份不符或尚无终态时保留 unknown，不从“找不到”推断未执行，也不直接重新派发。
4. 明确发生在委派前的失败可登记为未派发。已知终态失败或已知无效输出只允许带理由的显式新尝试；供应商消耗未知时仍禁止重试。

## 验证和限制

十项新增机械检查覆盖：公开委派与重复派发拒绝、三参与者独立对照的一整轮、取消与保留预留、回执丢失后恢复而不重复调用、失败终态不能变成发现、身份错配、意外工具请求、项目指令/扩展隔离，供应商 500 不触发 SDK 或供应商重试，以及插件已写终态但控制进程被 SIGKILL 后不重复调用的接续。

本地全量 42 项探索/SDK 检查、5 项 M0 检查及独立 PGlite 事务/并发检查通过；从完整 lock 重装插件宿主后核对运行。GitHub CI 以该提交的实际结果为准。

另有一次真实“插件前台叶子 → 中继 → DeepSeek”兼容调用，usage 输入 245、输出 126 tokens，插件返回匹配的 completed/runId/启动摘要。开发池包含此前历史预留后准入记账为 ¥4.74560 / ¥5，M1 以后累计 57 次供应商请求，未知请求 0。记账不等于实际账单。

这证明接入和有限恢复机制，不证明长期探索质量、插件比直接 Pi 更有效或协作普遍优越。真实兼容测试是单个叶子；三参与者完整轮次使用替身模型。当前保留较严格的未知状态策略，缺失回执时可能需要人工核查原生记录；没有自动重建丢失回执或断言后台任务已结束。

后续需要工具型、后台或长期子任务时，应继续复用插件的公开能力，并单独验证权限、请求预算、运行所有权和恢复。工具上限不是操作系统沙箱，此次也没有启用任意代码执行或联网研究工具。
