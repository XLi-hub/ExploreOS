# ExploreOS 验收指南

适用环境：Linux 云端或个人 Linux 双系统；从包含 M1 改动的分支启动。默认示例为零付费机械测试。

## 安装与零付费验收

在仓库根目录执行：

~~~bash
bash scripts/cloud/setup.sh
bash scripts/cloud/setup_pi.sh
bash scripts/cloud/setup_subagents.sh
.venv/bin/python scripts/cloud/runtime.py start
node scripts/cloud/test_atomic_files.cjs
.venv/bin/python -m unittest discover -s scripts/cloud -p 'test_*.py' -v
.venv/bin/python -m unittest discover -s tests -v
~~~

创建一个两轮机械示例；名称已存在时换一个名称，不要删除未导出的项目：

~~~bash
.venv/bin/python -m explore create morning_demo --scenario merge
.venv/bin/python -m explore advance morning_demo
.venv/bin/python -m explore pause morning_demo
.venv/bin/python -m explore steer morning_demo "现在重点检查旧结论在用户改向后是否仍然适用"
.venv/bin/python scripts/cloud/runtime.py stop
.venv/bin/python scripts/cloud/runtime.py start
.venv/bin/python -m explore resume morning_demo
.venv/bin/python -m explore advance morning_demo
.venv/bin/python -m explore memory morning_demo
.venv/bin/python -m explore export morning_demo
~~~

查看 `.research/morning_demo/exports/brief.md` 与 `export.json`。应看到问题版本、不同方向、提案与确认、变更前后状态、来源和未决问题。这里的模拟代理使用确定性情景，只验证机制，不证明探索质量。

## 开放问题不要求科研资料

无资料也可以开始推理和构想；结果不得伪造引文或标为已验证事实：

~~~bash
.venv/bin/python -m explore create ideas_demo --question "怎样组织一个能保留有用分歧的创意讨论？"
.venv/bin/python -m explore advance ideas_demo
.venv/bin/python -m explore export ideas_demo
~~~

也可以明确提供材料，模型只能从已配置的来源 ID 中选择：

~~~bash
.venv/bin/python -m explore create personal_demo --question "个人知识系统怎样支持经常改变的问题？" --source examples/open-exploration/notes.example.md
.venv/bin/python -m explore advance personal_demo
~~~

示例材料明确是合成情景，不是真实用户研究。自己的材料应为 UTF-8 小文本；当前入口快照前 80 行，过大的片段会在模型调用前拒绝。

继续时可以增加新材料、提出质疑或授权有限的新轮次：

~~~bash
.venv/bin/python -m explore add-source personal_demo /absolute/path/to/new_notes.md --title "新的反例或使用观察"
.venv/bin/python -m explore challenge personal_demo ACTUAL_FINDING_POST_ID "指出原主张的具体问题" --source-id ACTUAL_SOURCE_ID
.venv/bin/python -m explore extend personal_demo --rounds 1
~~~

ID 从 status/export 中取真实值。新增来源不覆盖旧快照；质疑保留原主张与署名，追加轮次不会重置模型预算。

## 检查旧认识如何被重新使用

~~~bash
.venv/bin/python scripts/demo_feedback.py --name feedback_demo
.venv/bin/python -m explore reviews feedback_demo
.venv/bin/python -m explore export feedback_demo
~~~

这是零模型的两轮机械示例：脚本加入合成反例，记录质疑与改向，模拟参与者再读原主张与新材料，保存修订关系和实际取回的旧笔记 ID。查看简报的“问题版本”“质疑与适用边界”“旧认识复查”；名字已存在时换一个。

真实参与者可以保留、修订、撤回或暂不判断，也可以不选复查；协作模式可提出同伴质疑。作者回应不意味着异议已经解决，修订后的内容仍需检查。详细来源、状态规则与测试见 [课题记忆复查](memory-feedback.md)。

## 实际模型调用是单独动作

先取得明确预算，再安装此 checkout 独立的执行器：

~~~bash
bash scripts/cloud/setup_pi.sh
.venv/bin/python -m explore create personal_live --question "个人知识系统怎样支持经常改变的问题？" --source examples/open-exploration/notes.example.md
.venv/bin/python -m explore advance personal_live --backend pi --budget-cny 5
~~~

上例使用新的 Pi Agent 执行器；运行库与 subagent 插件核对见 [Pi 底座](pi-runtime.md)。原 CC 适配仍可显式用 --backend claude；既有项目保持原后端。上例创建新的真实模型项目。系统拒绝用模拟结果填补真实模型案例，也拒绝在同一项目混换执行后端。

密钥优先取云环境的 `DEEPSEEK_API_KEY`；未配置时终端隐藏输入。不要把真实密钥放进命令行或 Git。首次付费运行需要明确预算；已有共享预算池不会因再次传入参数而重置。

本开发环境的池已包含此前测试用量和 M0 的保守预留，验收已有产物和机械示例不需要新模型调用。池中的预留不是供应商账单，未知调用不归零。

## 使用插件前台子任务

已授权预算的真实新项目可用 `advance NAME --backend pi-subagents`；先执行 `bash scripts/cloud/setup_subagents.sh`。`executions NAME` 查看稳定委派身份与实际插件终态，`reconcile NAME` 核对已有回执，不追加模型调用。已有项目不混换后端。

零付费验收运行 `.venv/bin/python -m unittest discover -s tests -p test_subagents.py -v`，细节见 [插件接入](subagent-integration.md)。后台、嵌套委派和工具尚未启用。

## 原开发环境中的真实结果

若保留了本次私有运行目录，可直接打开：

- `.research/live_coll_80169d63/exports/brief.md`：两轮、脚本化用户改向、重启接续及一次真实成员调整，含助手评阅质疑。
- `.research/live_coll_3833998b/exports/brief.md`：一轮协作案例与参与者确认。
- `.research/live_inde_35858e64/exports/brief.md`：无交流多代理。
- `.research/live_sing_d8a21ca0/exports/brief.md`：单代理。
- `.research/personal_589e93db/exports/brief.md`：非科研开放问题，单上下文多视角，合成设计材料。

原始输出与私有记忆不进入 Git，新 checkout 不会凭空拥有这些记录。汇总、证据边界和排除案例见 [M1 验证记录](m1-validation.md)。

## 故障和人工检查

需要逐条记录引文是否支持主张时，使用 `source-audit NAME POST_ID` 和 `assess-source`，见 [来源支持核查](source-support.md)。命令不调用模型；核查判断保留署名、范围和版本，并在下一轮本人复查候选中可见。

pause 停止新派发，cancel 取消当前拥有的进程；status 显示实际状态。`reconcile NAME` 只核对已有结果和稳定发布，不追加模型调用。已确认终止或未发送的失败可用 `retry NAME ACTUAL_SLOT "纠正理由"` 明确授权新尝试，之后再次 advance；未知供应商结果会阻止盲重试。

请重点检查：同伴内容是否确实改变行动；引用是否支持主张的全部范围；旧记忆在新问题下是否仍适用；争议是否被保留。引文匹配、文件存在、调用成功和同伴一致都不能替代这些判断。

结束时执行 `.venv/bin/python scripts/cloud/runtime.py stop`。当前服务与导出用于开发和验收，不能把云环境模板当成长期研究数据的唯一备份。
