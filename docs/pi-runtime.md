# Pi 执行底座与 subagent 插件核对

日期：2026-10-25。用户建议改用 Pi，并要求核对它的 subagent 插件。本页区分已经接入的运行库、真实兼容测试和仍未集成的插件能力。

## 当前选择

新的真实执行路径采用 `@earendil-works/pi-agent-core@1.4.0` 与 `@earendil-works/pi-ai@1.4.0`。这是 Pi 的通用 Agent 运行库和模型接口，直接嵌入一个受控 Node 子进程；不是通过 Pi CLI 再包一层命令。原项目的 Claude Code 入口保留供已有项目和对照使用。

Pi 负责单个参与者的会话、事件、模型传输和取消。ExploreOS 提供该次有限上下文，检查来源、认识版本、记忆与协作协议；ClawInstitute 继续保存共享内容。AutoScientists 的身份、任务物化与目录布局仍复用，但不执行其 CC 无限 runbook。

底座能够处理子会话不等于探索本身有价值。ExploreOS 需要在证据改变认识、保留异议、复查旧失败和跨轮继续方面证明作用；Pi 和插件可替换大量执行设施，不需要把通用编排宣称为自有竞争力。

## 安装和使用

~~~bash
bash scripts/cloud/setup.sh
bash scripts/cloud/setup_pi.sh
.venv/bin/python scripts/cloud/runtime.py start
.venv/bin/python -m explore create pi_example --question "什么样的共同记录能支持问题不断变化的讨论？"
# 只有已明确授权模型预算时才执行以下付费动作：
.venv/bin/python -m explore advance pi_example --backend pi --budget-cny 5
~~~

模型费用仍使用已有共享池，新项目或再次传入参数不重置额度。无 `--backend pi` 的 advance 默认使用模拟实现。Pi 需要 Node >=22.19.0；版本和完整 npm lock 进入 Git，安装使用 `npm ci --ignore-scripts`，没有全局 Pi 配置或登录要求。

Pi 原 `@mariozechner/*` 包已被 npm 标记迁移。核对后使用当前官方 `earendil-works/pi` 的发布包；`cloud/versions.json` 与 `cloud/pi/package-lock.json` 固定所用版本与完整性。Pi 库许可为 MIT。GitHub 连接器最初无法读取旧仓库路径，实际依据是发布包源码及新仓库文档，不能把旧路径的失败当作源码不存在。

## 受控执行边界

- 每次调用一个新 Agent 会话，只从 ExploreOS 的有界记录接续，禁止隐藏的额外历史或自动压缩调用。会话 ID 和事件回执进入已有调用账本。
- 当前工具列表为空，不安装或自动发现 Pi CLI 的 skills、扩展和本机认证。即使模型意外返回工具请求，也不能执行工具或追加供应商调用。
- Agent 在一个 turn 后结束，stream 层也只允许一次请求。Pi provider 的 `maxRetries` 为 0；中继再次拒绝重复调用 ID。
- 子进程只获得一次性 loopback 中继凭据，真实 DeepSeek key 留在控制进程内存。实际出站继续使用环境代理与 CA 配置。
- 取消先终止拥有的 Node 进程组，必要时强杀并收尸；供应商尚未核对的预留不释放。Pi 与 CC 共用认领、预算、幂等发布和恢复逻辑。

已有 CC 或模拟项目不直接混换后端；新 Pi 案例单独创建，避免把不同执行器的记录混成同一验收。

## 实际验证

五项测试运行真实 Pi SDK、真实中继和共享准入存储，供应商使用替身，不产生模型费用：三个 Pi 上下文走完一轮控制协议、并行会话不串上下文、供应商 500 不重试、取消保留未知预留并停止子进程、意外工具请求不能执行或触发下一次请求。CI 安装固定 Pi 库后运行这些测试。

另完成一次真实 Pi → 本地中继 → DeepSeek Anthropic 接口的兼容调用，返回结构化 JSON。供应商 usage 为输入 94、输出 93 tokens，请求版本与 Pi 会话事件已记录，结果已知。包含此前 M0/M1 预留后的共享准入记账为 ¥4.73062 / ¥5，累计 56 次 M1 以后请求；这不是供应商账单。

本次真实调用只证明执行和协议兼容，没有用它证明新增记忆复查字段的探索质量、三参与者效果或 Pi 优于 CC。原 M1 的三上下文案例继续按原 CC 执行器记载，不追溯改标签。

## Subagent 插件：已经核对的能力

区分两个对象：Pi 发布包内的 `examples/extensions/subagent` 是较小的官方示例；用户提到的完整社区方案，本次按 [nicobailon/pi-subagents](https://github.com/nicobailon/pi-subagents) 核对，固定发布包为 `pi-subagents@0.82.0`，许可 MIT。

该版本依赖 Pi >=1.2.0 的新包命名空间。查看了 README、`docs/extension-api.md`、`docs/configuration.md`、`docs/tool-reference.md`，以及 `src/runs/shared/child-session.ts` 和发布 bundle；没有把旧版“每个孩子必定一个 pi 进程”的官方示例描述套到社区新版上。

| 能力 | 插件当前已有 | 对 ExploreOS 的取用判断 |
| --- | --- | --- |
| 子上下文 | 前台为宿主进程内独立 AgentSession；后台在 detached runner 中运行；支持 fresh/fork | 后续工具型子任务优先复用；独立对照必须明确使用 fresh 并核对实际输入 |
| 流程与规模 | 单个委派、workflow 串行/并行、深度与累计 spawn 上限、并发限制 | 不另造相同通用 workflow 引擎；不能把固定工作流等同于探索方向形成 |
| 控制与观察 | 状态、steer、interrupt、stop、resume、FleetView 与运行产物 | 工作台/长期后台任务有明确复用价值，后续优先通过公开接口接入 |
| 用量与能力边界 | usage/tool budget、能力上限、模型范围、工具与扩展配置；结构化委派可设置零工具叶子 | 不是“插件没有预算”；仍需核对如何接入本项目跨任务、每次供应商请求前的原子预留与未知结果 |
| 公开集成点 | `pi-subagents/preflight`、结构化 delegation、event-bus RPC、`external-runs`/后台工作接口 | 使用公开接缝，不复制插件内部调度实现；preflight 不是实际执行证明 |
| 丢失 spawn 响应 | 可以按原 requestId 关联已有运行；文档明确 correlation 不等于 idempotent spawn | 未知派发不能直接重发；需要保留 runId/index 与本项目调用的对应关系 |

## 为什么本次没有直接加载整个插件

插件运行在 Pi Coding Agent 的扩展宿主中，并拥有自己的 session、run、后台控制与恢复产物。本次接入的是更小的 Agent core，尚未建立该扩展宿主与 ClawInstitute 的所有权映射。把插件直接当成一个普通工具挂进当前单请求叶子，会绕开目前已验证的派发和恢复边界。

本次对插件进行了源码和文档核对，没有安装到用户全局配置，也没有声称插件运行已验收。这个判断针对当前接缝的验证状态，不是认定插件能力不足。

后续若需要工具型子任务、FleetView 或长期后台执行，应由插件拥有子运行与进程状态，ExploreOS 引用其稳定运行身份并保留探索内容权威，避免两边各自修改同一运行状态。接入验收先覆盖 fresh 上下文、工具上限、请求前预算、取消和未知 spawn，再启用后台或嵌套委派；不是继续自建另一套子代理平台。
