# 发布 ExploreOS

用户要求全部完成后再发 release。正式发布前必须完成 [v0.1.0 草稿](releases/v0.1.0.md) 的真实验收事项；当前仍有缺口，不创建版本标签或公开正式 release。

`.release/acceptance.json` 记录人工核对结果和证据引用，执行指纹复用原冻结评测的 runtime_manifest。它是人工验收记录，不会自动证明主张真实，也不能用随意填写状态替代实际测试。密钥、研究材料、供应商原始回复和私人报告不进入发布附件或验收文件。

可在本机检查发布阻塞项（不调用供应商或创建 release）：

~~~bash
.venv/bin/python scripts/cloud/release_gate.py --tag v0.1.0
~~~

未完成时返回非零并列出缺口。正常开发 CI 运行发布条件的单元检查，不触发正式发布。所有实际验收完成且发布说明已经更新后，将变更合入 main，等待该提交的 `ExploreOS cloud checks` 和 `ExploreOS product container` 全部成功。确认安装包存在后，使用已经通过检查的完整提交 SHA：

~~~bash
git tag -a v0.1.0 VERIFIED_MAIN_COMMIT_SHA -m "ExploreOS v0.1.0"
git push origin refs/tags/v0.1.0
~~~

标签触发正式发布流程，依次核对验收记录与执行指纹、标签/提交对应、main 分支上的同提交 CI、未过期且来自该产品运行的唯一附件，以及包内源码提交和 SHA-256。通过后先创建未公开的 GitHub Release 草稿，上传版本化 Linux 安装包和外部 SHA256SUMS，核对远端附件名称/大小后才正式公开。上传失败保留未公开草稿。已有同名 release 不覆盖，发布失败应检查具体原因后修正，不强推已有标签或删除历史失败记录。

当前 GitHub 连接器没有创建 Release 的直接工具，当前终端的 `gh api` 访问也被拒绝；发布使用仓库内标准 GitHub Actions 的受限工作流令牌，不把个人令牌或模型密钥交给 CI。本次仅准备流程，不触发标签，不将未验收版本发布为正式版。
