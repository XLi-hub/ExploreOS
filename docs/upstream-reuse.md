# AutoScientists + ClawInstitute：复用边界与源码核对

状态：静态核对与改造方案，2026-10-24；没有运行验收。

## 1. 已核对的对象

| 对象 | 固定依据 | 本次读取范围 |
| --- | --- | --- |
| AutoScientists | commit `c71a92343b9a488ed10134be805845b9473ad18f` | README.md、launch.py、runbook.md |
| ClawInstitute 本地服务 | npm `clawinstitute@0.1.3` | 包内 README、package.json、LICENSE、启动入口、server、workspace 路由与服务、DB client、auth middleware |

发布包地址：[clawinstitute-0.1.3.tgz](https://registry.npmjs.org/clawinstitute/-/clawinstitute-0.1.3.tgz)。本次下载内容 SHA-256：`eac415f6626cee4f921404b5385d9d29316940f55fd86d9d838077dbbb557144`。

npm 元数据的 repository 指向 mims-harvard/ClawInstitute，但本次通过 GitHub 连接器读取该仓库 README、tree、package.json 均返回 404，因此以下服务实现结论依据实际发布包，不能宣称已读取其 GitHub 源仓库。包内 LICENSE 为 MIT；AutoScientists 和任何另用适配器的许可另行记录，不能用依赖包的许可代替。

公开 ClawInstitute 网站是研究交流平台；AutoScientists README 要求启动的 npm 包是可本地运行的协作服务。当前方案使用后者，不要求向公共站点发布问题或材料。

## 2. 已有能力与对应入口

AutoScientists 固定版本的[launch.py](https://github.com/mims-harvard/AutoScientists/blob/c71a92343b9a488ed10134be805845b9473ad18f/launch.py)：

| 入口 | 已观察到的行为 | 复用方向 |
| --- | --- | --- |
| L53 起 | 从 CLAWINSTITUTE_API 取得服务地址 | 保留 API 对接，端点可配置 |
| L575–698 | 注册智能体，生成各自目录、memory、HEARTBEAT 和工作区 | 保留身份和工作记录布局，适配执行后端 |
| L703–709 | 通过 workspace 文件 API 写共享内容 | 保留服务端文件存储，不另建文件事实源 |
| L722–801 | 创建 workshop、订阅、协调 workspace 与运行元数据 | 保留启动链路和稳定 ID |
| L803–869 | 初始化 task、champion、knowledge、roster 与参与者记录 | 保留可用路径，调整数值优化语义 |
| L890 起 | 向 workshop 发布 kickoff 帖 | 保留讨论入口，内容改为开放问题 |

[runbook.md](https://github.com/mims-harvard/AutoScientists/blob/c71a92343b9a488ed10134be805845b9473ad18f/runbook.md) 已将任务差异放入 profile hooks，包含讨论、派发、停滞响应、退出和最终报告。它是由代理执行的 Markdown 程序与伪代码；存在启动/收集结果的协调者，不能描述成完全没有协调者，也不能当作所有规则已经被程序强制执行。

ClawInstitute 发布包已有 `/agents`、`/workshops`、`/workspaces`、`/posts`、`/notifications`；workspace 包含文件、历史、搜索和评论。已有 Express API、PGlite/外部 Postgres 路径和 Next.js 前端。优先使用这些能力，再验证开放问题需要的增量。

## 3. 默认怎样改

| 部分 | 默认处理 | 首个验证点 |
| --- | --- | --- |
| workshop / workspace / posts / 文件历史 | 直接对接现有 API | 创建、互读、回复、版本历史和导出 |
| 心跳、按需读取、知识/失败记录 | 保留布局，改少量任务语义 | 新一轮能读取前轮记录并回应 |
| 讨论、组队与队列 | 保留流程，检查开放任务与小规模配置 | 方向形成、变化与具体发布记录能对应 |
| TASK.md / LAUNCH.md | 新增开放探索 profile | 不要求数值目标、数据集、训练或论文 |
| champion、GPU、优化停滞判定 | 适配为认识集合、一般行动与有界回顾 | 无 GPU/val_bpb 时流程仍成立 |
| Codex 等执行后端 | 优先核对已有适配器，局部覆盖调用 | 独立会话、超时和恢复状态可验证 |
| 问题版本、来源链接、认识变化 | 尽量以现有帖子/文件格式表达 | 保留作者、引用、依据和变更历史 |
| 调用预算、运行核对与并发约束 | 为真实缺口加薄层或服务端修补 | 限额生效、冲突不覆盖、未知结果不盲重试 |
| 界面 | 先使用已有前端 | 能查看实际讨论和共享内容，再决定扩展 |

自定义字段首先是对现有存储格式的扩展，不等于新建一套 Project/Post/Direction 数据库。ClawInstitute 保存共享探索内容；执行适配器只拥有调用尝试、预算和外部进程核对等执行元数据，通过 workshop/workspace/post ID 引用内容。相同状态不能两处各自判断。

## 4. 不能只改提示词的已知边界

**参与者与角色是硬编码的。** launch.py L558–570 声明了 1 个 monitor、6 个 GPU 参与者和 3 个 analyst；runbook 也按三个 analyst 派发。首版三个探索参与者是本项目目标，需要局部改造 roster 与派发，不能声称上游已支持配置一个 count 即完成。协调进程不自动算作探索参与者；如果 monitor 实际参与研究判断，需计入预算并记录职责。

**没有 champion 不代表流程自动通用。** launch.py L811 起初始化 metric/champion，runbook 的晋升、健康检查和停滞段仍依赖实验队列与 KEEP。需检查 profile 外的流程，并把“当前认识”保存为可争论集合，不把得票或同意当作最佳结果。

**If-Match 的存在不足以证明原子认领。** 包内 routes/workspaces.js L480–528、L545–585 接收条件写入并返回冲突；WorkspaceFileService.js L130–181 先读取/比较版本，再以 `WHERE id = ...` 更新，没有在该 UPDATE 中再次匹配版本，所读方法也没有包住整段的事务；L185–200 的 frontmatter patch 检查后调用 write 时未继续传版本。这提示并发竞态窗口，尚未通过并发测试重现。M0 必须验证两写者与认领场景，优先修补服务端 CAS/事务或通过唯一受控写入口限制写入；不能把当前版本直接标为满足原子认领。

**Windows 前端需单独验收。** 发布包 README 标注预构建前端为 Linux-x64；不能保证 npx 在 Windows 下前后端都直接可用。先验证跳过前端的 API 路径，以及 WSL2/Linux 运行原有界面的方案，平台选择再据实测决定。本仓库代码与文档仍在用户指定的 D 盘目录。

**持久化与访问边界要沿用实际配置。** 发布包默认 PGlite、提供 checkpoint 和 DATABASE_URL。checkpoint 不等于本项目所需的崩溃一致性已验收；持久部署优先核对外部 Postgres。包默认关闭认证，且 server.js 使用 app.listen(port)；本地试验要控制可访问范围，远程部署时核对认证与监听/网络边界。无需为此另建协作平台。

## 5. 下一步开发安排

实例 A：验证 ClawInstitute 现有 API、共享内容、条件写与原有前端的平台路径，形成状态所有权与并发缺口报告。

实例 B：核对 AutoScientists 的 profile、角色/roster 硬编码与已有 Codex 适配，形成开放任务的最小覆盖清单。

两边以同一上游 commit、服务版本和共享接口约定汇合。随后做“固定材料上的三个探索参与者、两条方向、一次互评后的行动变化、一次跨轮接续”的小场景；只读 API 测试不需要模型，真实探索按已配置预算单独验收。

先复用、验证、局部改，再决定新组件。这里的静态核对完成了部分 M0 证据准备；M0 的启动、并发、重启和真实交互验收仍未完成。
