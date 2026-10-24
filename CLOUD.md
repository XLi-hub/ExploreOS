# 云端开发起步包

本仓库提供 AutoScientists + ClawInstitute 的 Linux 云端环境、固定事务补丁与 M0 验收入口。限定结果见 [M0 验证记录](docs/m0-validation.md)；完整开放探索产品仍待 M1 实现。开发在云端，用户本机使用目标为双系统中的 Linux。

## 1. 环境配置

| 项目 | 值 |
| --- | --- |
| GitHub 仓库 | XLi-hub/autoscientists-engineering |
| 当前 M0 分支 | codex/m0-validation，基于 codex/open-exploration-design |
| 系统 | Linux x64；CI 使用 Ubuntu 24.04 |
| Python | 3.11 |
| Node.js | 22 |
| GPU | 不需要 |
| 起步所需模型密钥 | 无 |
| 默认服务 | 仅 ClawInstitute API，认证开启，独立开发数据库 |
| 运行状态 | .runtime/；依赖虚拟环境为 .venv/，都不进入 Git |

环境准备和后续任务应选择包含 M0 改动的分支或合并后的分支。是否已合入 main 以 GitHub 为准。

在 Codex Cloud 创建环境时选择此仓库，并可粘贴：

> 请为这个仓库准备 Linux 云端开发环境。选择包含 M0 改动的分支；如果当前 checkout 有用户改动先保留，不强制覆盖。使用 Python 3.11 和 Node.js 22。读取 CLOUD.md，执行 bash scripts/cloud/setup.sh，再执行 doctor、start、smoke seed、m0 seed、stop、start、smoke verify、m0 verify、stop。安装阶段不启动研究代理，不需要模型密钥。把安装命令记录到 Install script，把服务启动和状态检查记录到 Start skill。确认检查结果后准备发布环境。

安装入口：

~~~bash
bash scripts/cloud/setup.sh
~~~

如果准备界面最初检出 main，在环境准备会话中先检出上述分支，再运行安装入口。不要把切分支命令作为每次编码任务的自动启动动作。

当前 OpenAI 官方文档使用 Install script 与 Start skill，并要求完成准备后 Publish；若界面仍显示 Legacy 的 Setup script / Maintenance script，把安装入口用于 Setup，将 doctor 用于缓存恢复后的检查。首次编码任务也要选准备分支。

## 2. 网络与凭据

环境需要访问 GitHub、npm 和 PyPI。当前 Cloud 可选择 Package managers 网络预设，核对实际下载目标；自定义列表至少包含：

- github.com
- codeload.github.com
- raw.githubusercontent.com
- registry.npmjs.org
- pypi.org
- files.pythonhosted.org

若依赖需要额外下载域名，按失败日志添加对应目标；不要通过关闭 TLS 校验来绕过。此起步包不安装 Claude Code 或 Codex CLI，不复制本机登录目录，setup 不读取模型密钥。真实执行入口另行配置；单独授权的 M0 模型探针还需访问 api.deepseek.com。

服务启动时在当前云任务内生成开发 token。不要在环境模板发布前启动并遗留一份要被不同任务共享的数据库/token；环境准备中的验证结束后应按第 5 节处理测试状态。

## 3. 安装实际做什么

1. 检查 Git、Python、Node 和 npm；版本不符会明确退出，环境准备会话负责调整运行时。
2. 下载固定 AutoScientists commit 的稀疏工作副本，保留 README、启动/运行文档、requirements 和 system；不下载科学任务数据集。
3. 创建独立 .venv，安装固定直接 Python 依赖。
4. 校验已审阅 ClawInstitute 发布包 SHA-256，将固定 0.1.3 版本安装到 .runtime/clawinstitute。
5. 核对修补前文件指纹并应用受版本控制的事务/条件写补丁；检查版本与入口，记录已安装 Python 包，不启动后台服务。

固定版本见 [cloud/versions.json](cloud/versions.json)。上游副本只是忽略目录里的外部依赖，不是复制进本仓库的产品代码。修改上游时先形成可跟踪的覆盖/补丁方案，不能把唯一改动留在 .runtime。

JavaScript 直接与传递依赖使用已验证的 [完整 npm lock](cloud/package-lock.json)，每次 setup 都执行 npm ci。Python 直接依赖固定，传递依赖仍以实际安装记录为准。补丁与文件指纹保存在 [cloud/patches/](cloud/patches/manifest.json)；doctor 会拒绝缺失或被修改的补丁版本。

## 4. 启动、检查与停止

均从仓库根目录运行：

~~~bash
.venv/bin/python scripts/cloud/runtime.py doctor
.venv/bin/python scripts/cloud/runtime.py start
.venv/bin/python scripts/cloud/runtime.py status
.venv/bin/python scripts/cloud/smoke.py seed
.venv/bin/python scripts/cloud/m0.py seed
.venv/bin/python scripts/cloud/runtime.py stop
.venv/bin/python scripts/cloud/runtime.py start
.venv/bin/python scripts/cloud/smoke.py verify
.venv/bin/python scripts/cloud/m0.py verify
.venv/bin/python scripts/cloud/runtime.py stop
~~~

Start skill 可写：

> 在仓库根目录运行 .venv/bin/python scripts/cloud/runtime.py start，再运行 status。仅在任务需要上游 API 时启动。不执行 runbook.md，不启动真实研究代理。需要验证时运行 smoke seed；测试后的状态位于 .runtime。结束验证后 stop。不要把 token 或私有服务日志写入答复或提交。

默认 API 为 http://127.0.0.1:3000/api/v1。helper 仅管理当前 checkout 的进程和隔离数据库，不连接外部 DATABASE_URL；通过进程身份校验避免停止其他服务。

已有前端留在安装包中，默认跳过。若云端工具支持相应访问方式，可用 EXPLORE_FRONTEND=1 启动并单独验证；当前 API CI 不等于前端浏览器验收，也不提供公共托管链接。普通编码任务无需浏览器界面。

同一 VM 中需要多个服务时，分别设置 EXPLORE_API_PORT 与 EXPLORE_FRONTEND_PORT。不同云任务各有自己的文件与运行状态；两个账号依靠分支、提交和 PR 协作，不共享 .runtime 数据库。

## 5. 验证范围与环境发布

smoke seed 是确定性脚本，创建三个测试身份、一个 workshop、共享文件、帖子和回复；检查认证、历史和顺序发生的旧版本写入拒绝。stop/start 后 verify 检查已保存记录。

smoke 本身不证明真实智能体交流或并发原子性。新增 m0 seed 验证 PUT/PATCH/仅创建的八路竞争、重复提交与导出，m0 verify 验证重启后导出一致性。独立数据库的事务回滚、检查点后的 SIGKILL 恢复，以及模型调用预算/未知结果测试命令见 M0 记录；这些机械测试不发起模型调用。

准备环境时，验证完成后停止服务，发布模板前应使用全新的任务状态。当前 checkout 可能已有真实 M0 模型记录，不能将其数据库按一次性 bootstrap 数据直接删除；先导出并保留。新任务启动服务时生成各自 token 与数据库，不共享真实模型探针数据。

研究结果需要独立导出和持久存储规划，不能把开发环境快照当作常驻研究服务。

## 6. 下一开发任务与可选模型探针

> 读取 docs/m0-validation.md，继续 M1：先验证 AutoScientists 原有 Claude Code 执行入口与 DeepSeek 兼容接口的预算、工具权限和取消边界，再实现开放任务分支与三人名册。保留 ClawInstitute 为共享内容权威，处理帖子幂等和未知结果。固定上游未找到独立 Codex 适配器；不要以模型供应商的 Codex 接入文档代替上游执行兼容性验收，不启动原 runbook 的无限循环。

M0 真实模型探针是单独命令，不进入 setup 或 CI。获得明确模型预算后，在已启动服务的终端执行：

~~~bash
.venv/bin/python scripts/cloud/m0_live.py live --budget-cny 5
.venv/bin/python scripts/cloud/m0_live.py verify
~~~

密钥来自云环境的 DEEPSEEK_API_KEY，未配置时隐藏输入。不要将真实密钥写入命令行、Git 或环境模板文本。最多九次请求、两路并发，预算是按保守费率预留的准入限额；供应商实际账单另查。未知调用保留预留且不自动重试，已有 ledger 阻止重复 live。查看已有结果使用 verify，不会追加模型调用。

CI 定义：[Cloud bootstrap](.github/workflows/cloud-bootstrap.yml)。它安装锁定依赖并执行数据库故障、并发、API 与优雅重启检查；服务日志留在私有目录，不上传含 token 的原始日志，也不使用模型密钥。

## 7. 官方配置参考

- [当前 Codex Cloud 环境](https://learn.chatgpt.com/docs/environments/cloud-environments)
- [Legacy 环境](https://learn.chatgpt.com/docs/environments/cloud-environment)
- [AutoScientists 固定版本](https://github.com/mims-harvard/AutoScientists/tree/c71a92343b9a488ed10134be805845b9473ad18f)

所有开发变更在云端 checkout 完成，通过 GitHub 分支交付，不写入用户本机仓库。此文提供配置输入，不表示已经替用户创建或发布新的 Codex Cloud 环境。
