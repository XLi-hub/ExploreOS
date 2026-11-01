# 参与 ExploreOS 开发

ExploreOS 面向开放问题的多智能体探索。欢迎能让真实问题更清楚、让证据更容易检查、让后续探索更可靠的改进。先阅读 [产品核心](docs/product-core.md) 与 [项目约定](AGENTS.md)。

## 报告问题

请说明源码提交或安装包 SOURCE_COMMIT、安装方式、操作步骤、预期和实际结果，以及是否可以在零付费示例中复现。运行中断时先保留记录，不通过删除数据或重置预算隐藏问题。

不要提交 API 密钥、实例登录令牌、私人材料、数据库或完整服务日志。公开 issue 使用可分享的最小样例；敏感问题见 [安全报告](SECURITY.md)。

## 本地云开发

按 [CLOUD.md](CLOUD.md) 安装 Python 3.11、Node 22.19+ 与固定上游依赖。在 codex/ 任务分支开发，保留用户已有改动。共享内容沿用 ClawInstitute，运行控制只补已核实的缺口。

~~~bash
bash scripts/cloud/setup.sh
bash scripts/cloud/setup_pi.sh
bash scripts/cloud/setup_subagents.sh
.venv/bin/python scripts/cloud/runtime.py doctor
.venv/bin/python scripts/cloud/runtime.py start
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/cloud/runtime.py stop
~~~

安装与 CI 默认零模型调用。真实执行必须使用明确授权的预算，不把模型凭据放进 CI。机械测试不能冒充协作质量证据。

## 提交变更

说明用户遇到的具体问题、最终行为、如何验证和实际限制。涉及运行状态时检查认领、过期写、重复结果、取消、超时、预算预留和恢复；纯文档修改检查链接与差异即可。

原生界面沿用现有 API、认证和 workspace 链接。界面变更应通过 scripts/check_native_ui.cjs 的真实浏览器流程，覆盖创建、材料、改向、导出、恢复以及移动端；演示数据应明确标记。

对照评测保持审计与恢复设施一致，分别改变语义共享与协作机制。修改执行实现后重新冻结协议，不混用历史指纹。

提交 PR 后检查该提交的 cloud checks 与 product container；发布还需要 main 上同提交的检查、安装包与实际验收。不要通过修改验收占位状态来消除未完成的质量或部署条件。流程见 [发布说明](docs/releasing.md)。

## 设计与依赖

优先使用清楚的语言、可追溯的原文与诚实的状态。界面主路径关注问题、发现和下一步，执行细节按需展开。新增依赖说明用途、版本和许可；依赖的许可不能代替本项目的授权声明。
