"""Attributed source-support judgments; quote matching never verifies a claim."""
from __future__ import annotations

import copy
import hashlib
import json

VERDICTS = ("supports", "partial", "unsupported", "uncertain")
QUALIFICATION = "An attributed source-support judgment, not automatic truth verification or resolution of objections"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def packet(state, post_id, content, source):
    """Bind the review to the actual claim, material and observed question/feedback."""
    entry = next((p for p in state["posts"] if p["id"] == post_id and p["phase"] == "reflect"), None)
    if entry is None or post_id not in state.get("knowledge", {}):
        raise ValueError("Choose a finding in this project")
    finding = state["knowledge"][post_id]
    evidence = content.get("evidence")
    if evidence != finding.get("evidence"):
        raise ValueError("Finding evidence differs from its shared record")
    if evidence is not None:
        if source is None or evidence.get("source_id") != source["id"]:
            raise ValueError("The audit needs the finding's original material snapshot")
        actual = hashlib.sha256("\n".join(source["lines"]).encode()).hexdigest()
        expected = state["sources"][source["id"]]["sha256"]
        metadata = state["sources"][source["id"]]
        if (actual != expected or source["sha256"] != actual
                or any(source[key] != metadata[key] for key in ("id", "title", "path", "start_line"))
                or (evidence.get("source_sha256") and evidence["source_sha256"] != actual)):
            raise ValueError("Audit material differs from the finding's snapshot")
    elif source is not None:
        raise ValueError("A reasoning-only finding has no cited material")
    basis = {"post_id": post_id, "actor": entry["actor"], "round": entry["round"],
             "original_question": copy.deepcopy(state["question_revisions"][entry["question_revision"] - 1]),
             "current_question": copy.deepcopy(state["question_revisions"][-1]),
             "content": copy.deepcopy(content), "source": copy.deepcopy(source),
             "review_version": finding.get("review_version", 0),
             "challenges": copy.deepcopy(finding.get("challenges", []))}
    return {"kind": "source_audit_v1", "basis": basis, "basis_sha256": digest(basis),
            "finding_status": finding["status"],
            "assessments": [copy.deepcopy(a) for a in state.get("source_assessments", {}).values()
                            if a["target_post"] == post_id], "qualification": QUALIFICATION}


def judgment(audit, verdict, reason, reviewer, scope):
    if verdict not in VERDICTS:
        raise ValueError("Unknown source-support verdict")
    for label, value, limit in (("reason", reason, 2000), ("reviewer", reviewer, 80), ("scope", scope, 1000)):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f"Assessment {label} must contain 1–{limit} characters")
    if audit["basis"]["source"] is None and verdict != "uncertain":
        raise ValueError("Without cited material, source support must remain uncertain")
    return {"target_post": audit["basis"]["post_id"], "basis_sha256": audit["basis_sha256"],
            "verdict": verdict, "reason": reason.strip(), "reviewer": reviewer.strip(), "scope": scope.strip(),
            "question_revision": audit["basis"]["current_question"]["number"],
            "review_version": audit["basis"]["review_version"],
            "source_sha256": (audit["basis"]["source"] or {}).get("sha256"),
            "claim_truth_verified": False, "qualification": QUALIFICATION}


def view(state, finding, limit=3):
    """Keep the latest judgment per named reviewer and preserve disagreement."""
    latest = {}
    for entry in state.get("source_assessments", {}).values():
        if entry["target_post"] == finding["post_id"]:
            latest[entry["reviewer"]] = entry
    # A minority concern must not disappear behind several newer positive votes.
    entries = sorted(latest.values(), key=lambda a: (a["verdict"] != "supports", a["sequence"]), reverse=True)
    return [{**{key: copy.deepcopy(entry[key]) for key in
                ("id", "reviewer", "verdict", "question_revision", "review_version")},
             "reason": entry["reason"][:120], "scope": entry["scope"][:120],
             "reason_truncated": len(entry["reason"]) > 120, "scope_truncated": len(entry["scope"]) > 120,
             "omitted_reviewer_count": max(0, len(entries) - limit),
             "applicability_check_required": (entry["question_revision"] != state["question_revisions"][-1]["number"]
                                               or entry["resulting_review_version"] != finding.get("review_version", 0)),
             "qualification": QUALIFICATION} for entry in entries[:limit]]


def needs_attention(state, finding):
    return any(a["verdict"] != "supports" for a in view(state, finding))


def summary(state):
    """Explicit denominators; these are coverage counts, never quality scores."""
    findings = state.get("knowledge", {})
    records = list(state.get("source_assessments", {}).values())
    return {"finding_count": len(findings),
            "material_based_finding_count": sum(f.get("evidence") is not None for f in findings.values()),
            "assessed_finding_count": len({a["target_post"] for a in records}),
            "assessment_count": len(records),
            "verdict_counts_all_records": {v: sum(a["verdict"] == v for a in records) for v in VERDICTS},
            "qualification": "All findings are the denominator; historical and disagreeing judgments are retained. No quality or accuracy score is computed."}


def markdown(audit):
    basis = audit["basis"]
    content, source = basis["content"], basis["source"]
    lines = [f"# 来源核查：{basis['post_id']}", "", f"核查依据指纹：{audit['basis_sha256']}",
             f"原问题 v{basis['original_question']['number']}：{basis['original_question']['text']}",
             f"当前问题 v{basis['current_question']['number']}：{basis['current_question']['text']}",
             "", f"主张：{content['finding']}", f"认识状态：{audit['finding_status']}",
             f"类型（参与者自报）：{content.get('claim_kind', 'inference')}",
             f"未决：{content.get('unresolved', '')}", "", "## 原始材料快照", ""]
    if source:
        lines.extend([f"{source['id']}：{source['title']}；SHA-256：{source['sha256']}",
                      f"逐字引文：{content['evidence']['quote']}", ""])
        lines.extend(f"{source['start_line'] + i}: {line}" for i, line in enumerate(source["lines"]))
    else:
        lines.append("此步只做推理，没有引用外部材料；来源支持只能记为 uncertain。")
    lines.extend(["", "## 已有质疑", ""])
    lines.extend(f"- {c['post_id']}：{c['reason']}；作者回应：{c.get('author_responses', [])}"
                 for c in basis["challenges"])
    lines.extend(["", "## 核查历史", ""])
    lines.extend(f"- {a['id']}；{a['reviewer']}：{a['verdict']}；范围：{a['scope']}；理由：{a['reason']}"
                 for a in audit["assessments"])
    lines.extend(["", "核查应说明原文支持的范围、额外假设和缺失证据。署名判断不会自动验证主张，也不消除异议。", ""])
    return "\n".join(lines)
