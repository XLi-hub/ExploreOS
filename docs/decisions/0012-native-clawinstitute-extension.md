# ADR 0012：在 ClawInstitute 内扩展探索入口

状态：已实现。更新 ADR 0009 中独立工作台的入口方案。

## 依据与决定

用户明确要求新增功能复用 ClawInstitute。已核对固定 0.1.3 发布包：包含 Express API 源码、预构建 Next 前端、原生登录与讨论/文件路由；已有 `/api/v1/:path*` 重写到 API 3000。缺少前端源码不构成另建 HTTP 服务和认证的理由。

通过受版本控制且校验前后指纹的 `src/app.js` 挂载补丁，在原 Express 进程中安装 `cloud/native/exploreos.cjs`。探索视图位于原前端同源 `/api/v1/exploreos/ui`，JSON 接口复用既有 `requireAuth`，浏览器沿用原登录状态。模型密钥只在 Python 服务端读取。

新课题由原上游物化器发布的 TASK 首帖及共享 `task.md` 增加探索链接；扩展保留返回原讨论和文件的入口。不修改预构建 Next 文件，不创建第二个数据库、调度器或登录系统。兼容命令 `python -m explore.workbench` 只打印原生入口，不再监听 3388。

Node 适配只以无 shell 的 JSON 子进程桥接既有 Python Project。异步推进的进程内表只防止重复排队，实际执行仍由 Project 的持久认领、预算和恢复约束控制；失败观察写回同一项目。服务重启后不会依据内存表猜测模型请求是否完成。

原生登录浏览器检查还复现了发布包的接口不一致：前端客户端默认发送 `X-Agent-Name: admin`，而 `/agents/me` 只在没有该头时返回本地管理员，空数据库登录因此 404。一个独立指纹补丁使默认 `admin` 也返回既有的本地管理员表示；仍需原有 bearer 认证，不增加登录入口或新账户。

## 验证与边界

真实 Claw API 测试覆盖未登录拒绝、外来 Origin/Host 拒绝、已有认证可控制、问题版本保留和 TASK 链接。Chromium 通过原 Next 的 3001 入口完成创建、推进、暂停、改向、继续、导出、刷新接续与手机布局，并检查返回原 workshop 可用。模型供应商为模拟器，此项只验证操作链。

当前只支持 loopback 开发使用。固定 Next 包的已有 API 重写目标是 3000；API-only CI 显式关闭前端，其他 API 端口不冒充原生前端已支持。公共域名、代理认证和长期部署需另行实现与验证。
