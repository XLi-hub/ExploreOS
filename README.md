<div align="center">

# ✳ ExploreOS

### 让问题越探越清楚。

面向开放问题的多智能体探索工作空间。<br>
从不同解释出发，用材料与质疑推进认识，把可继续的记忆留下来。

[![Cloud checks](https://github.com/XLi-hub/ExploreOS/actions/workflows/cloud-bootstrap.yml/badge.svg?branch=main)](https://github.com/XLi-hub/ExploreOS/actions/workflows/cloud-bootstrap.yml)
[![Product container](https://github.com/XLi-hub/ExploreOS/actions/workflows/product-container.yml/badge.svg?branch=main)](https://github.com/XLi-hub/ExploreOS/actions/workflows/product-container.yml)
![Platform](https://img.shields.io/badge/Linux-amd64-738568)
![Deployment](https://img.shields.io/badge/部署-自托管-396b4d)

[快速开始](#快速开始) · [使用指南](docs/getting-started.md) · [安装与备份](docs/deployment.md) · [产品设计](docs/product-core.md) · [参与开发](CONTRIBUTING.md)

</div>

---

**一个问题，多种可能。** ExploreOS 适合那些还没有标准答案、需要反复比较和修订的问题：产品机会、工作方式、机制分析、创意判断或研究设想。提出问题，添加材料，让具有独立上下文的参与者提出方向、互相质疑；检查发现与原文，补上反例，下一轮继续。

> **当前为产品预览，面向 Linux amd64 上的个人或单一可信使用者。** 已有原生界面、真实模型路径、预算与恢复控制、可校验安装包。正式稳定版仍受真实质量评阅、重复评测和长期部署验收约束；详见 [交付状态](docs/product-delivery.md) 与 [发布条件](docs/releasing.md)。零付费示例使用预设情景，有明确标记。

## 你会得到什么

| 能力 | 使用时的意义 |
| --- | --- |
| **多条探索路线** | 默认三个独立上下文；参与者可以提出竞争解释，并基于记录调整方向或分工。 |
| **可以检查的发现** | 主张保留作者、问题版本、原文行号、材料指纹与质疑，不把同伴一致当作事实。 |
| **留住分歧** | 反例、未答问题、撤回与修订继续可见；旧关注点下的结论进入历史。 |
| **接着上次继续** | 关闭页面、重启服务后读取原记录；补材料、改向或追加有限轮次。 |
| **有条件的记忆** | 跨课题引用保留出处与适用条件，取回时重新检查来源状态。 |
| **可控的运行** | 模型预算跨项目共享；暂停停止新派发，未知请求保留额度并先核对。 |
| **可带走的成果** | 下载 Markdown 阶段简报，或导出含原始记录的 JSON；导出无需模型。 |

界面提供浅色与深色外观、问题模板、零付费示例、来源材料计数和键盘导航。浏览器使用预览随 [cloud checks 的成功运行](https://github.com/XLi-hub/ExploreOS/actions/workflows/cloud-bootstrap.yml) 保存为 `exploreos-browser-previews-*` 附件。

## 快速开始

### 使用预构建安装包

1. 打开 [产品构建](https://github.com/XLi-hub/ExploreOS/actions/workflows/product-container.yml)，选择 **main 分支的成功运行**，在 Artifacts 下载 `exploreos-linux-amd64-*`。
2. 解压下载的 ZIP，再解开其中的 `exploreos-linux-amd64.tar.gz`。
3. 在解压目录运行：

~~~bash
bash exploreos.sh start
~~~

需要 Docker Engine 与 Docker Compose v2。启动脚本校验包内容，加载与包内标识一致的镜像，创建私有配置，再等待服务就绪；不会启动探索或调用模型。Actions 附件通常需要登录 GitHub，保留 14 天。

打开 **http://127.0.0.1:3001/api/v1/exploreos/ui**。在安装主机的私人终端读取实例登录令牌：

~~~bash
bash exploreos.sh login
~~~

粘贴到页面链接指向的 ClawInstitute 原登录页，回到 ExploreOS 即可使用。登录令牌与模型 API 密钥用途不同。

### 从源码安装

~~~bash
git clone https://github.com/XLi-hub/ExploreOS.git
cd ExploreOS
cp .env.example .env
chmod 600 .env
docker compose up --build -d --wait --wait-timeout 180
~~~

同样打开上面的地址。源码安装读取登录令牌：

~~~bash
docker compose exec -T exploreos cat .runtime/service/home/token
~~~

服务器通过 [SSH 私有访问](docs/deployment.md)；源码开发环境见 [CLOUD.md](CLOUD.md)。

## 第一次探索

**先体验流程：** 点击「使用指南 → 打开零付费示例」，创建后已有一份访谈片段。点击「推进一轮」，检查「阶段成果」「发现与分歧」和「来源材料」；然后修改关注点，继续下一轮。示例结果来自预设情景，不是真实模型的研究结论。

**开始自己的问题：**

1. 新建探索，写下你想弄清楚的问题。可直接修改首页的示例问题。
2. 添加笔记、访谈或原文片段。每份最多 80 行 / 12,000 UTF-8 字节，界面显示用量，超出会拒绝保存。
3. 选择执行方式并明确推进一轮。没有材料时只做推理，发现会保留这一限制。
4. 查看不同路线、原文与未决质疑；需要时补材料、修改关注点，再继续。
5. 下载阶段简报，或在运行控制中导出全部记录。

启用真实探索：登录后打开右上角[模型设置](docs/provider-setup.md)，在专用密码输入框保存 DeepSeek API 密钥，再确认真实探索方式和共享预算。密钥只保存在服务器私有文件中，不回显或写入浏览器存储。保存不调用模型。也可继续使用安装主机的私有 `.env` 配置 `DEEPSEEK_API_KEY`；环境变量提供时页面只读。

支持的主执行路径是 **Pi + DeepSeek**；Pi 前台子代理与历史 Claude 路径为高级选项。界面中的配置状态不代替实际供应商连通验证。真实与演示项目分别保存，运行后不混换后端。

完成一轮后可显式[生成综合报告](docs/stage-reports.md)，得到带发现引用的阶段判断、竞争解释、适用限制与下一步。真实生成计入共享预算；输入变化后旧报告标为历史，重复查看和导出不再调用模型。

## 日常使用

~~~bash
bash exploreos.sh status  # 服务与界面健康状态，不调用模型
bash exploreos.sh stop    # 优雅停止，保留卷
bash exploreos.sh start   # 重新打开已有数据，不自动推进探索
bash exploreos.sh verify  # 仅检查安装包完整性
~~~

以上脚本位于预构建安装包。源码安装使用 `docker compose stop` / `docker compose up -d`。

数据保存在命名卷中；升级先做私有冷备。服务健康不代表探索质量或供应商可用。备份归档包含私人材料与实例登录令牌，应另存受控位置；不要对需要保留的实例执行 `down --volumes`。详见 [部署](docs/deployment.md)、[备份恢复](docs/backup-restore.md) 和 [常见问题](docs/faq.md)。

## 它怎样工作

~~~mermaid
flowchart LR
    Q[问题与关注点] --> A[独立视角提出方向]
    A --> S[共享提案、发现与质疑]
    S --> C[查材料、检验解释]
    C --> M[带出处和限制的记忆]
    M --> N[阶段成果与下一轮]
    N --> S
~~~

ExploreOS 复用 **AutoScientists 的任务/身份布局、ClawInstitute 的共享内容与认证、Pi 的模型执行能力**。原生探索界面直接扩展现有 ClawInstitute API；共享内容只有一套权威存储。确定性控制层管理预算、认领和恢复，参与者提出研究方向。

协作是否比单代理更有用，仍需在同材料和预算下评估；现有配置对照与消融入口见 [评测说明](docs/evaluation-pilot.md)。运行成功、影响链接和报告长度不能单独证明质量收益。

## 文档

| 从这里开始 | 深入使用与开发 |
| --- | --- |
| [第一次使用](docs/getting-started.md) | [架构与状态所有权](docs/architecture.md) |
| [安装与持久运行](docs/deployment.md) | [上游复用与边界](docs/upstream-reuse.md) |
| [探索工作台](docs/workbench.md) | [来源支持核查](docs/source-support.md) |
| [常见问题](docs/faq.md) | [记忆复查](docs/memory-feedback.md) |
| [备份与恢复](docs/backup-restore.md) | [固定对照评测](docs/evaluation-pilot.md) |
| [验收指南](docs/acceptance-guide.md) | [真实案例与限制](docs/m1-validation.md) |
| [更新记录](CHANGELOG.md) | [路线图](docs/roadmap.md) |
| [发布条件](docs/releasing.md) | [开发环境](CLOUD.md) |

欢迎提交可复现问题和有材料依据的改进建议。开始前阅读 [贡献指南](CONTRIBUTING.md)，报告问题时移除 API 密钥、登录令牌与私人材料。
