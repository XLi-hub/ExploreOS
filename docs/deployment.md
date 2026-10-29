# 安装与持久运行

面向 Linux amd64 上的单一可信使用者。产品沿用 ClawInstitute，不增加另一套服务、账号或数据系统。当前可构建的镜像包含固定版本的上游、Pi 和前台插件，使用非 root 用户；模型调用需在界面明确开始。

## Docker Compose 安装

也可以在 [产品容器检查](https://github.com/XLi-hub/ExploreOS/actions/workflows/product-container.yml) 的成功运行页下载 `exploreos-linux-amd64-*` 附件，解压其中的安装包，按内附 README 加载已验证镜像并启动。包包含启动配置、空的模型配置示例、源提交/镜像标识和 SHA-256 校验，不包含真实材料、数据库或密钥。Actions 附件保留 14 天；源码及下面的构建入口持续保留。安装包使用 `docker compose up --no-build -d`，无需获取 npm/Python 依赖。

主机需要 Git、Docker Engine 和 Compose。检出希望使用的提交，在仓库目录执行：

~~~bash
cp .env.example .env
chmod 600 .env
docker compose up --build -d
docker compose ps
~~~

默认可体验零付费演示。在本机编辑私有 `.env` 的 `DEEPSEEK_API_KEY` 后，执行 `docker compose up -d` 更新容器，再在探索界面明确选择真实探索与共享预算。已有预算不会通过重建、改向或追加轮次增加。

打开 **http://127.0.0.1:3001/api/v1/exploreos/ui**，按页面链接使用原 ClawInstitute 登录。初始登录令牌可在运行主机的私人终端读取，再粘贴到原登录页：

~~~bash
docker compose exec -T exploreos cat .runtime/service/home/token
~~~

这是协作服务的本地登录令牌，模型密钥单独放在 `.env`，不填入登录页。登录后，新建探索、填写问题、选择真实或演示、按需添加材料，再推进一轮。阶段成果支持来源追溯、改向、简报下载与接续。

端口只发布到主机 loopback。部署在自己的服务器时，可通过 SSH 保持同样的私有访问入口：

~~~bash
ssh -N -L 3001:127.0.0.1:3001 YOUR_USER@YOUR_SERVER
~~~

然后在自己的浏览器打开上面的地址。已有源码服务占用 3001 时先按 [云端说明](../CLOUD.md) 停止原服务；数据迁移使用备份恢复。当前版本不提供公共多租户托管。

## 启停、升级与数据

~~~bash
docker compose stop
docker compose up -d
docker compose exec -T exploreos .venv/bin/python scripts/cloud/product.py health
~~~

Compose 使用三个命名卷：`service` 保存现有 PGlite 与登录令牌；`research` 保存参与者工作目录、来源与预算引用；`backups` 保存私有归档。停止、重新创建容器和同一 Compose 项目的 `down` 保留这些卷；不要使用 `down --volumes` 清除要保留的数据。

容器的前台管理进程仅管理原 ClawInstitute 进程。SIGTERM 会执行原优雅停止；服务进程退出时容器失败退出，Compose 可重启服务。重启不推进探索，不安装/启动付费唤醒，不清除未知结果；中断的模型调用仍先通过原恢复操作核对。

健康检查覆盖 API 认证与原生页面，不能证明模型服务连通、权限有效或探索质量。升级前先保存私有备份、记录代码提交，再在实际使用范围内验证。源码安装也可用 `.venv/bin/python scripts/cloud/product.py serve` 作为宿主管理器的前台启动命令；不要同时运行第二个管理进程。

## 冷备与恢复

先停止服务和所有手动启动的探索/唤醒进程，按 [备份恢复说明](backup-restore.md) 操作。容器中的一次备份示例：

~~~bash
docker compose stop
docker compose run --rm --no-deps exploreos .venv/bin/python scripts/cloud/backup.py create /opt/exploreos/.runtime/backups/instance.tar.gz
docker compose cp exploreos:/opt/exploreos/.runtime/backups/instance.tar.gz ./instance.tar.gz
chmod 600 instance.tar.gz
docker compose up -d
~~~

归档包含私有研究与协作登录令牌，保存在命名卷仍不是异地备份。供应商密钥、服务日志与执行依赖不进入归档。同名归档不会被覆盖；下一次使用新的名字。

恢复必须使用相容的代码/依赖版本与**空的数据卷**，先让原实例退出运行。下面用新的 Compose 项目名 `exploreos-restored` 保留原卷；尚不要启动新服务，先复制归档并让非 root 产品用户可读：

~~~bash
docker compose stop
docker compose -p exploreos-restored create
docker compose -p exploreos-restored cp ./instance.tar.gz exploreos:/opt/exploreos/.runtime/backups/restore.tar.gz
docker compose -p exploreos-restored run --rm --no-deps --user 0 exploreos chown 10001:10001 /opt/exploreos/.runtime/backups/restore.tar.gz
docker compose -p exploreos-restored run --rm --no-deps exploreos .venv/bin/python scripts/cloud/backup.py restore /opt/exploreos/.runtime/backups/restore.tar.gz
docker compose -p exploreos-restored up -d
~~~

恢复保留已有预算、未知消耗和历史，不执行模型或启动唤醒。需要另行配置 `.env`。已有数据会被拒绝覆盖；不要为迁移删除原实例，先保留备份并完成恢复核对。不能同时从两份实例消费同一个物理复制的预算历史。

## 云开发环境构建

带会话代理/CA 的云环境构建时保留代理，并用 BuildKit secret 挂载合并 CA；不关闭 TLS 校验，也不把会话证书写进镜像：

~~~bash
docker build --platform linux/amd64 --secret id=system_ca,src=/etc/ssl/certs/ca-certificates.crt -t exploreos:local .
docker compose up --no-build -d
~~~

实际模型运行还需为容器配置可达的会话代理及只读 CA 信任，遵守环境网络策略；容器不能绕过目的域名限制。当前托管开发环境的 `api.deepseek.com` 仍未放行。普通 Linux 主机使用自身网络与 CA 配置。

## 可复现的产品安装检查

~~~bash
docker build --platform linux/amd64 -t exploreos:product-check .
python3 scripts/cloud/verify_container.py
~~~

检查仅创建专属随机容器与卷，使用演示代理；实际验证首次启动、原生创建/材料/一轮/简报/导出、拒绝第二个管理器、优雅停止，以及新容器使用原卷后状态与未知预算保留完全一致。预算样本是明确的合成未知记录，不接触供应商。检查结束仅清理自己创建的测试资源，不操作现有实例。这不替代目标主机或真实质量验收。
