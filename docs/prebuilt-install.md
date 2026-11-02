# ExploreOS 安装包

面向 Linux amd64 的个人自托管产品预览。需要 Docker Engine 与 Docker Compose v2。真实质量和正式发布条件以本包源码提交对应的仓库文档为准；安装与演示不会自动调用模型。

## 启动

解压下载的 ZIP，再解开其中的 tar.gz，进入含本文件的目录：

~~~bash
bash exploreos.sh start
~~~

脚本检查 SHA-256，加载与 IMAGE_ID.txt 一致的镜像，首次创建权限为 600 的私有 .env，再等待服务就绪。已有 .env 不会被覆盖，已有数据卷继续保留。不需要重新获取 npm 或 Python 依赖。

打开 **http://127.0.0.1:3001/api/v1/exploreos/ui**。在本机私人终端读取实例登录令牌：

~~~bash
bash exploreos.sh login
~~~

通过页面链接进入原 ClawInstitute 登录页，粘贴令牌后返回 ExploreOS。它与模型密钥用途不同。

## 第一次使用

在「使用指南」中打开零付费示例，创建后会保存一份访谈材料，点击「推进一轮」即可体验流程。演示是预设情景，不代表真实模型完成研究。

真实探索：登录后打开「模型设置」，在专用密码输入框保存 DeepSeek API 密钥，再在新课题中选择真实探索与共享预算。密钥只保存到服务器私有文件，不回显或写入浏览器存储。也可由私有 .env 的 DEEPSEEK_API_KEY 提供，更新后重新创建容器；环境变量提供时页面只读。创建、保存设置、安装、重启和查看记录均不会自动调用模型。

## 日常管理

~~~bash
bash exploreos.sh status
bash exploreos.sh stop
bash exploreos.sh start
bash exploreos.sh verify
~~~

status 检查服务与界面，不测试模型供应商。stop 保留命名卷；start 不自动恢复付费执行。未知调用需要先核对，预算历史不清零。

手动管理的等价入口为：

~~~bash
sha256sum -c SHA256SUMS
docker load -i exploreos-image.tar.gz
cp --no-clobber .env.example .env
chmod 600 .env
docker compose up --no-build -d --wait --wait-timeout 180
~~~

SOURCE_COMMIT.txt 是构建源码提交，IMAGE_ID.txt 是镜像内容标识。校验用于检查传输完整性，不替代对下载来源的信任。数据库和课题保存在命名卷中；保留要使用的数据卷，不执行 down --volumes。

服务器访问可使用 ssh -N -L 3001:127.0.0.1:3001 YOUR_USER@YOUR_SERVER 后从本机打开。当前仅发布 loopback 端口，不提供公共多租户托管。

## 文档与升级

按 SOURCE_COMMIT.txt 查阅对应版本的 [部署说明](https://github.com/XLi-hub/ExploreOS/blob/main/docs/deployment.md)、[第一次使用](https://github.com/XLi-hub/ExploreOS/blob/main/docs/getting-started.md) 和 [常见问题](https://github.com/XLi-hub/ExploreOS/blob/main/docs/faq.md)。

升级先做私有冷备。安装目录或 Compose 项目名改变会切换命名卷；迁移采用冷备恢复，保留预算与未知请求，不同时运行同一份预算历史的副本。已有实例占用 3001 时先优雅停止原服务。
