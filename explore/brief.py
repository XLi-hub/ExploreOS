"""Readable, attributed projections of existing records; no model or truth inference."""


def build(view):
    revision = view["question_revisions"][-1]
    findings, historical, questions = [], [], []
    for post in view["posts"]:
        if post["phase"] != "reflect":
            continue
        content = post["content"]
        knowledge = (view.get("knowledge") or {}).get(post["id"], {})
        item = {"post_id": post["id"], "actor": post.get("actor"), "round": post["round"],
                "question_revision": post["question_revision"], "text": content["finding"],
                "status": knowledge.get("status", "provisional"),
                "claim_kind": content.get("claim_kind", "inference"),
                "evidence": content.get("evidence"), "influenced_by": content.get("influenced_by", [])}
        current = post["question_revision"] == revision["number"] and item["status"] not in ("withdrawn", "superseded")
        (findings if current else historical).append(item)
        if current and content.get("unresolved"):
            questions.append({"post_id": post["id"], "text": content["unresolved"], "kind": "unresolved"})
        # A response does not resolve an objection. Preserve historical objections too.
        for objection in knowledge.get("challenges", []):
            questions.append({"post_id": post["id"], "text": objection["reason"], "kind": "challenge",
                              "question_revision": post["question_revision"],
                              "responded": bool(objection.get("author_responses"))})
    review_fields = ("actor", "target_post", "response_post", "decision", "reason", "status")
    changes = [{key: entry.get(key) for key in review_fields}
               for entry in view.get("reviews", []) if entry["status"] == "recorded"]
    stale_reviews = [{key: entry.get(key) for key in review_fields}
                     for entry in view.get("reviews", []) if entry["status"] != "recorded"]
    calls = view["calls"]
    outstanding = [call for call in calls if call["status"] in ("starting", "running", "received", "unknown", "cancelling")]
    failed = [call for call in calls if call["status"] in ("failed", "failed_before_dispatch", "invalid_output", "timed_out")]
    rounds = view["rounds"]
    exhausted = len(rounds) >= view["max_rounds"] and rounds[-1]["status"] in ("completed", "cancelled")
    if view.get("evaluation_binding"):
        next_step = "这是固定评测案例，请从原评测流程继续，保留冻结输入。"
    elif view.get("continuation_required"):
        next_step = "导出完整记录，再以带适用条件的引用建立接续课题。"
    elif outstanding or failed or view["status"] == "blocked":
        next_step = "查看运行状态；中断或未知请求先核对，已知失败经修正后再授权重试。"
    elif view["status"] in ("paused", "cancelling"):
        next_step = "检查当前材料与关注点，准备好后继续探索。"
    elif exhausted:
        next_step = "阅读本轮成果；可补充材料或修改关注点，再追加有限轮次继续。"
    elif not calls:
        next_step = "可先添加相关材料，然后开始第一轮探索。"
    else:
        next_step = "检查未决问题和质疑，补充材料或调整关注点，再推进一轮。"
    result = {"question": revision, "findings": findings, "historical": historical,
              "questions": questions, "changes": changes, "stale_reviews": stale_reviews, "next_step": next_step,
              "completed_rounds": sum(r["status"] == "completed" for r in rounds),
              "completed_calls": sum(c["status"] == "completed" for c in calls),
              "outstanding_calls": len(outstanding), "failed_calls": len(failed)}
    lines = [f"# {revision['text']}", "", f"项目：{view['name']} · 问题 v{revision['number']} · {view['record_kind']}",
             "", "本简报从已保存记录整理，未追加模型调用。发现保留参与者署名与暂定状态，材料引用和同伴赞同不自动验证主张。",
             "", "## 当前发现", ""]
    for item in findings:
        evidence = item["evidence"]
        lines.extend([f"- {item['text']}", f"  - {item['actor']} · 第 {item['round']} 轮 · {item['status']} · {item['claim_kind']} · 记录 {item['post_id']}"])
        lines.append(f"  - 材料：{evidence['source_id']}，第 {evidence.get('original_line', evidence.get('line', '?'))} 行：{evidence['quote']}" if evidence else "  - 仅有推理，无外部材料支持。")
    if not findings:
        lines.append("当前关注点下尚无可展示的新发现。历史发现保留其原问题版本。")
    lines.extend(["", "## 认识变化（署名回应，保留争议）", ""])
    lines.extend(f"- {c['decision']}：{c['reason']} · {c['target_post']} → {c['response_post']} · {c['status']}" for c in changes)
    if stale_reviews:
        lines.append(f"另保留 {len(stale_reviews)} 条未生效的历史复查回应，可在完整记录中查看。")
    lines.extend(["", "## 未决问题与质疑", ""])
    for item in questions:
        suffix = "（已有回应，异议仍保留）" if item.get("responded") else ""
        lines.append(f"- {item['text']}{suffix} · 记录 {item['post_id']}")
    lines.extend(["", "## 下一步", "", next_step, "", "## 历史发现（沿用前须复查）", ""])
    lines.extend(f"- {item['text']} · 问题 v{item['question_revision']} · {item['status']} · 记录 {item['post_id']}" for item in historical)
    result["markdown"] = "\n".join(lines) + "\n"
    return result
