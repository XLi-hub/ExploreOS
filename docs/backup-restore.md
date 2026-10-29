# ClawInstitute 数据的备份与恢复

备份复用现有 ClawInstitute/PGlite 数据目录，不建立另一套研究数据库。它覆盖数据库、`.research/` 中的课题/个人记忆/评测引用、原本地服务 token，以及已有的评测待运行记录。源码与依赖从 Git 和固定锁文件恢复；独立模型密钥配置、服务日志、运行进程记录和依赖包不纳入归档。

归档包含私有课题数据及 ClawInstitute 本地访问凭据，文件权限为 600。保存在你控制的持久存储中，不提交 Git，也不公开上传。当前云任务内生成的归档仍不是异地备份。

## 生成与检查

先停止探索控制进程及唤醒 watcher，再正常停止本 checkout 的协作服务。使用前台产品管理器时先停止管理器；其共享文件锁也会阻止另一个容器误做热备。备份会拒绝仍在运行的服务/控制器、源目录中的符号链接或特殊文件，以及复制期间发生变化的数据。

~~~bash
.venv/bin/python scripts/cloud/runtime.py stop
.venv/bin/python scripts/cloud/backup.py create .runtime/backups/instance-2026-10-28.tar.gz
.venv/bin/python scripts/cloud/backup.py inspect .runtime/backups/instance-2026-10-28.tar.gz
.venv/bin/python scripts/cloud/runtime.py start
~~~

每次使用新的归档名；已有归档不覆盖。检查逐个读取数据、核对文件内容 SHA-256 和清单，只输出数量、体积与提交标识。摘要校验用来发现内容损坏，不证明归档来自可信的人。

## 恢复到空实例

在 Linux 上准备干净 checkout，并按 [CLOUD.md](../CLOUD.md) 安装相同版本的 ClawInstitute 及锁定依赖，先不启动服务。运行时 pins 必须与归档一致。若要继续冻结评测，还需保持对应执行代码指纹；升级代码后按评测规则另冻 campaign。

~~~bash
.venv/bin/python scripts/cloud/backup.py inspect /private/path/instance.tar.gz
.venv/bin/python scripts/cloud/backup.py restore /private/path/instance.tar.gz
.venv/bin/python scripts/cloud/runtime.py start
~~~

恢复先验证整个归档，再写入私有暂存目录。目录穿越、符号/硬链接、重复路径、校验错误及不兼容 pins 都会拒绝；非空 `.research`/数据库、已有 token 或评测待运行记录不会被替换。允许已有但完全空的数据目录或挂载卷，保留其目录本身，在目标文件系统私有暂存后安装。可捕获的安装错误会回滚本次移动；硬中断后应保留 `restore-*`/`.restore-*` 暂存目录及原归档核对，不把它当作任意断电点的原子恢复。跨文件系统恢复需要额外暂存空间。备份工具不自动启动服务、研究代理或定时计划。

本地服务 token 随数据保留，供应商模型凭据按原配置方式单独提供。调用账本、预算引用和未知结果照原样恢复，不因换机器清零。恢复后的执行应接替已经停止的原实例，不能让两个数据库副本同时消费同一份总预算授权；旧进程/未知请求仍须通过原有 reconcile 流程核对。

当前实现支持自带的 PGlite 物理数据目录。外部 PostgreSQL、跨版本数据库升级、在线热备和自动保留/异地轮换策略需要各自的部署方案，不属于这里的验证范围。

## 实际恢复验证

~~~bash
.venv/bin/python scripts/cloud/runtime.py start
.venv/bin/python scripts/cloud/verify_backup.py
~~~

该检查创建明确标注的零模型样本，包含两版材料、两个身份、帖子/回复及一条人工构造的未知额度预留。随后正常停服、冷备、恢复到隔离目录，使用同一上游数据库与文件服务读取恢复后的数据，确认完整历史、原样预算记录和可用的原课题状态，再重启原服务。

归档保留在忽略的 `.runtime/backups/`；隔离副本在检查结束后移除。原模型总预算与真实供应商请求不变。此项验证数据恢复能力，不能替代真实探索质量或长期无人值守运行验收。
