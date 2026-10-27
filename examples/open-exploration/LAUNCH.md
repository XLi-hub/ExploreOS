# 开放任务 profile

此文件沿用 AutoScientists 的 TASK/LAUNCH 发现和复制机制。执行使用 `python -m explore` 的有限入口，不能让模型逐条执行原版无限 runbook。

## Hook: launch_command

使用显式 open_exploration 分支创建独立目录、身份、workshop 和 workspace。

## Hook: bootstrap_extras

保存问题版本、来源指纹、三份身份及授权预算，不探测 GPU。

## Hook: discussion_policy

三个初始提案独立形成，返回后开放互读；失败者记录缺席。

## Hook: seeding_policy

方向来自参与者提案，执行器仅校验并持久化。

## Hook: pre_cycle_check

核对暂停、取消、问题版本、预算和未知执行结果。

## Hook: analyst_prompt_extras

使用 explorer 身份和心跳，保持私有摘要与共享帖子边界。

## Hook: gpu_dispatch

改为最多两个安全模型调用并发；仅执行允许的资料读取。

## Hook: champion_promotion

导出带出处和分歧的认识集合，没有 champion 或最优分数。

## Hook: stagnation_response

保留信息不足和重复探索，允许提出参与关系变更，不按 KEEP 数量决策。

## Hook: periodic_hooks

核对未决提案及受影响参与者的明确确认。

## Hook: exit_condition

本轮三个有限阶段结束、预算边界或用户暂停；不自行无限继续。

## Hook: final_report

从已有记录确定性导出阶段简报、原始来源和执行缺口，不追加模型调用。

## Hook: never_do_extras

不伪造缺席结果，不盲重试未知调用，不把共享摘要当作独立证据，不超出材料和工具权限。
