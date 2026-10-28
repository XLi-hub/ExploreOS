# 有限持续运行、规模与跨课题记忆

这里提供 M4/M5 的有界工程能力。规模扩展和记忆是否有收益仍须真实对照；没有启动无人值守付费计划，也没有添加 GPU、任意 shell 或外部科学计算工具。

## 人数与并发

现有上游开放任务补丁已支持 1–8 个身份。本次将该参数从 CLI 传到原物化器，不另造身份系统：

~~~bash
.venv/bin/python -m explore create group_demo --participants 4 --concurrency 2 --question "哪些竞争解释值得继续检查？"
.venv/bin/python -m explore advance group_demo
~~~

默认仍是三个参与者、两个并发调用。单代理配置只启用一个参与者；人数增加不等于模型多样性，也不证明质量提高。每轮调用额度随人数设定，所有请求仍走原有认领、预算、超时和恢复设施。固定 M2 任务包不随本项默认值改变人数。

## 明确关联另一个课题的发现

同一课题内也可以产生初始集合以外的方向：参与者在检查材料或推理后选择 fork，提出新的暂定路线；原路线保留，组内分工改变需相关成员确认。自己的暂停路线可在新条件下重开。方向变化不自动验证新解释，更多路线也不等于探索更有用；依据与前后状态可从工作台展开。

~~~bash
.venv/bin/python -m explore link-memory target_project origin_project ACTUAL_FINDING_POST_ID \
  --conditions "仅在原来的使用条件与材料范围内参考" \
  --reason "这个反例可能帮助检查新问题的适用边界"
~~~

关联记录保留来源 workspace、帖子、原问题、正文指纹、原反馈版本、条件和迁移理由。plan/reflect 按需取回至多三个关联，重新核查原课题的争议、修订/撤回和关注点变化；来源不可读时明确标记，不默认为有效。

跨课题记录始终要求适用性检查，也不进入目标项目的外部证据列表。不从摘要自动生成通用事实，不读取其他参与者私有笔记。完整来源保留在原课题，目标仅保存带条件的引用与观察快照。

## 配置有限唤醒

以下示例默认零付费：

~~~bash
.venv/bin/python -m explore.schedule configure group_demo --interval-seconds 86400 --additional-rounds 4
.venv/bin/python -m explore.schedule status group_demo
.venv/bin/python -m explore.schedule enable group_demo
.venv/bin/python -m explore.schedule watch group_demo
~~~

configure 只保存禁用的配置，不安装系统定时器，不启动后台守护进程。watch 是明确启动的前台唤醒进程；使用者需选择运行机器并保持协作服务与该进程运行。默认按 UTC 的 epoch 时间计算间隔；错过多个周期不会批量补跑。达到授权的有限轮数后自动停用，不无限追加。

真实后端在 configure 时使用 `--backend pi` 等明确选择，enable 时提供已授权的 `--budget-cny`，运行机器需配置 `DEEPSEEK_API_KEY`。定时器绑定原共享预算 workspace，不能通过重新启用、更换项目或配置新周期重置费用。没有模型凭据和明确预算时只运行机械示例。

## 暂停、停用与恢复

~~~bash
.venv/bin/python -m explore.schedule disable group_demo
# 若还需要取消当前拥有的执行：
.venv/bin/python -m explore.schedule disable group_demo --cancel
~~~

停用与暂停在同一个 CAS 中保存；新派发检查唤醒代次，旧计划不能继续创建新轮次。已经拥有的调用默认收尾；cancel 使用原执行器取消语义，未知供应商消耗仍保留。之后手动 resume/advance 可以显式接管未完成的轮次，历史留下接管记录。

重新启用一个已经暂停的项目时，先明确执行 `explore resume NAME`，再 enable/watch；启用定时配置本身不抹去原来的暂停意图。

唤醒只拥有“到期事件”和目标轮次，模型执行仍由 Project 唯一拥有。重复唤醒最多认领一次；重启时先检查目标轮次，已完成的不再执行，已失败或未知的请求不自动重试。人工恢复后先确认原唤醒的目标已经完成，再推进下一个周期。

本地通知只在有新阶段记录、变更或需要检查的失败时保存到项目；没有发送邮件、Slack 或其他外部通知。通知不证明新发现有用或真实。云开发环境不是长期数据唯一备份，持续部署还需选择持久运行机器、备份和合适的数据库。

## 容量与历史

上游 API 对单次 JSON 写入有 1 MB 限制。阶段边界会把已完成调用的大载荷移到同一 workspace 的不可变归档，保留执行元数据和指纹；导出会重新取回原始请求/输出。未知调用不被归档成已完成，私有记忆也可从已保存调用重建。

如果归档后的轻量索引仍达到容量边界，系统在新派发前暂停并要求显式导出/接续，原始记录仍可读取。它不会静默丢弃历史或宣称无限运行；实际持久部署需按容量和使用量规划课题接续。实现与检查见 [ADR 0010](decisions/0010-bounded-audit-archives.md)。
