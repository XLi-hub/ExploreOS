# 云端开发起步包

本仓库当前提供 AutoScientists + ClawInstitute 的 Linux 云端开发起步包。先完成原生服务的安装与确定性 API 验证，再开发开放探索 profile 和真实执行适配。当前没有完整探索产品，也没有启动真实模型的命令。

## 1. 环境配置

| 项目 | 值 |
| --- | --- |
| GitHub 仓库 | XLi-hub/autoscientists-engineering |
| 当前准备分支 | codex/open-exploration-design |
| 系统 | Linux x64；CI 使用 Ubuntu 24.04 |
| Python | 3.11 |
| Node.js | 22 |
| GPU | 不需要 |
| 起步所需模型密钥 | 无 |
| 默认服务 | 仅 ClawInstitute API，认证开启，独立开发数据库 |
| 运行状态 | .runtime/；依赖虚拟环境为 .venv/，都不进入 Git |

这些文件目前在上述分支。环境准备和首个开发任务都应基于该分支；main 尚未合并这批改动。

在 Codex Cloud 创建环境时选择此仓库，并可粘贴：

> 请为这个仓库准备 Linux 云端开发环境。检出 codex/open-exploration-design；如果当前 checkout 有用户改动先保留，不强制覆盖。使用 Python 3.11 和 Node.js 22。读取 CLOUD.md，执行 bash scripts/cloud/setup.sh，再执行 doctor、start、smoke seed、stop、start、smoke verify、stop。安装阶段不启动研究代理，不需要模型密钥。把安装命令记录到 Install script，把服务启动和状态检查记录到 Start skill。确认检查结果后准备发布环境。

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

若依赖需要额外下载域名，按失败日志添加对应目标；不要通过关闭 TLS 校验来绕过。此起步包不安装 Claude Code 或 Codex CLI，不复制本机登录目录，不读取模型密钥。后续真实执行器按选定方式另行配置。

服务启动时在当前云任务内生成开发 token。不要在环境模板发布前启动并遗留一份要被不同任务共享的数据库/token；环境准备中的验证结束后应按第 5 节处理测试状态。

## 3. 安装实际做什么

1. 检查 Git、Python、Node 和 npm；版本不符会明确退出，环境准备会话负责调整运行时。
2. 下载固定 AutoScientists commit 的稀疏工作副本，保留 README、启动/运行文档、requirements 和 system；不下载科学任务数据集。
3. 创建独立 .venv，安装固定直接 Python 依赖。
4. 校验已审阅 ClawInstitute 发布包 SHA-256，将固定 0.1.3 版本安装到 .runtime/clawinstitute。
5. 检查版本与入口，记录已安装 Python 包；不启动任何后台服务。

固定版本见 [cloud/versions.json](cloud/versions.json)。上游副本只是忽略目录里的外部依赖，不是复制进本仓库的产品代码。修改上游时先形成可跟踪的覆盖/补丁方案，不能把唯一改动留在 .runtime。

直接依赖已固定；首次 npm 安装仍会解析传递依赖，在 .runtime/clawinstitute/package-lock.json 中记录解析结果。后续重复 setup 使用该锁。当前不宣称跨不同首次安装已实现完整依赖锁定；后续在云端验证后再把经审阅的完整锁定方案纳入源码。

## 4. 启动、检查与停止

均从仓库根目录运行：

~~~bash
.venv/bin/python scripts/cloud/runtime.py doctor
.venv/bin/python scripts/cloud/runtime.py start
.venv/bin/python scripts/cloud/runtime.py status
.venv/bin/python scripts/cloud/smoke.py seed
.venv/bin/python scripts/cloud/runtime.py stop
.venv/bin/python scripts/cloud/runtime.py start
.venv/bin/python scripts/cloud/smoke.py verify
.venv/bin/python scripts/cloud/runtime.py stop
~~~

Start skill 可写：

> 在仓库根目录运行 .venv/bin/python scripts/cloud/runtime.py start，再运行 status。仅在任务需要上游 API 时启动。不执行 runbook.md，不启动真实研究代理。需要验证时运行 smoke seed；测试后的状态位于 .runtime。结束验证后 stop。不要把 token 或私有服务日志写入答复或提交。

默认 API 为 http://127.0.0.1:3000/api/v1。helper 仅管理当前 checkout 的进程和隔离数据库，不连接外部 DATABASE_URL；通过进程身份校验避免停止其他服务。

已有前端留在安装包中，默认跳过。若云端工具支持相应访问方式，可用 EXPLORE_FRONTEND=1 启动并单独验证；当前 API CI 不等于前端浏览器验收，也不提供公共托管链接。普通编码任务无需浏览器界面。

同一 VM 中需要多个服务时，分别设置 EXPLORE_API_PORT 与 EXPLORE_FRONTEND_PORT。不同云任务各有自己的文件与运行状态；两个账号依靠分支、提交和 PR 协作，不共享 .runtime 数据库。

## 5. 验证范围与环境发布

smoke seed 是确定性脚本，创建三个测试身份、一个 workshop、共享文件、帖子和回复；检查认证、历史和顺序发生的旧版本写入拒绝。stop/start 后 verify 检查已保存记录。

它不证明真实智能体交流、探索质量、并发原子认领或异常断电恢复。真实 M0/M1 验收继续依据 [路线图](docs/roadmap.md)。

准备环境时，验证完成后停止服务，并在发布前用全新的任务状态替代测试状态。可在确认只是一次性 bootstrap 测试数据后，删除当前云端 checkout 的 .runtime/service 与 .runtime/smoke-result.json，再发布。不要删除未导出的真实探索数据。后续任务启动服务时会生成各自 token 与数据库。

研究结果需要独立导出和持久存储规划，不能把开发环境快照当作常驻研究服务。

## 6. 第一个开发任务

> 基于当前分支和 docs/upstream-reuse.md，在云端核对已有 Codex 执行适配与 AutoScientists 的 profile hooks。列出一个开放任务的最小改造清单；保留 ClawInstitute 为共享内容权威。检查 launch.py 的角色/GPU/champion 硬编码及服务实际字段，不假设原生 launch 已兼容当前发布包。先给可运行的离线材料与接口验证，不调用付费模型，不启动原 runbook 的无限循环。

CI 定义：[Cloud bootstrap](.github/workflows/cloud-bootstrap.yml)。它在 GitHub Linux runner 安装依赖并执行真实服务的 API 与优雅重启检查，服务日志留在私有运行目录，不上传含 token 的原始日志。

## 7. 官方配置参考

- [当前 Codex Cloud 环境](https://learn.chatgpt.com/docs/environments/cloud-environments)
- [Legacy 环境](https://learn.chatgpt.com/docs/environments/cloud-environment)
- [AutoScientists 固定版本](https://github.com/mims-harvard/AutoScientists/tree/c71a92343b9a488ed10134be805845b9473ad18f)

本轮新增内容直接通过 GitHub API 提交，不写入用户本机仓库。此文提供配置输入，不表示已经替用户创建或发布 Codex Cloud 环境。
