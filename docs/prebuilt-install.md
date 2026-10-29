# ExploreOS 安装包

这是 Linux amd64 的单用户产品候选包。需要 Docker Engine 与 Compose，模型配置和真实质量验收状态见源码仓库；演示有明确标记，不能作为真实探索结果。

解压到自己的目录后执行：

~~~bash
sha256sum -c SHA256SUMS
docker load -i exploreos-image.tar.gz
cp .env.example .env
chmod 600 .env
docker compose up --no-build -d
docker compose ps
~~~

打开 **http://127.0.0.1:3001/api/v1/exploreos/ui**，使用原 ClawInstitute 登录页。本机私人终端可读取初始登录令牌：

~~~bash
docker compose exec -T exploreos cat .runtime/service/home/token
~~~

随后填写一个问题、选择零付费演示或真实探索，添加材料并推进一轮。真实探索需要先在自己的 `.env` 配置 `DEEPSEEK_API_KEY`，执行 `docker compose up --no-build -d` 更新配置，再在界面保存明确的共享预算。安装、启动、重启及查看记录均不会自动调用模型。

`SOURCE_COMMIT.txt` 是构建时的代码提交，`IMAGE_ID.txt` 是镜像内容标识。校验文件用于检查传输完整性，不替代对下载来源的信任。数据库和课题分别保存在命名卷，停机用 `docker compose stop`，再次使用 `docker compose up --no-build -d`。保留需要的数据卷，不执行 `down --volumes`。

服务器安装可使用 `ssh -N -L 3001:127.0.0.1:3001 YOUR_USER@YOUR_SERVER` 后从本机访问。共享记录、材料、认识变化与失败核对沿用 ClawInstitute；当前包只发布 loopback 端口。

备份、迁移、恢复、来源版本和实际限制请按 `SOURCE_COMMIT.txt` 查阅 [ExploreOS 部署说明](https://github.com/XLi-hub/ExploreOS/blob/main/docs/deployment.md) 与 [产品交付说明](https://github.com/XLi-hub/ExploreOS/blob/main/docs/product-delivery.md)。已有源码或容器实例占用 3001 时先停止原服务；迁移采用冷备恢复，保留预算与未知调用记录，不同时运行同一份预算历史的副本。
