"""Explicit cross-project references with qualified, revision-aware recall."""
from __future__ import annotations

import copy
import json
import uuid

from .assessments import digest
from .store import JsonFile


def link(target, origin, post_id, conditions, reason):
    target.assert_input_change_allowed(target.file.read()[0])
    if target.file.workspace == origin.file.workspace:
        raise ValueError("Choose another project as the memory origin")
    if any(not isinstance(v, str) or not v.strip() or len(v) > 500 for v in (conditions, reason)):
        raise ValueError("Supply 1–500 character applicability conditions and transfer reasoning")
    audit = origin.audit_source(post_id)
    basis = audit["basis"]
    card_id = "memory:" + uuid.uuid4().hex
    card = {"id": card_id, "origin_workspace": origin.file.workspace, "origin_project": origin.directory.name,
            "origin_post": post_id, "origin_question": basis["original_question"],
            "observed_review_version": basis["review_version"], "observed_question_revision": basis["current_question"]["number"],
            "content_sha256": digest(basis["content"]), "preview": basis["content"]["finding"][:300],
            "claim_kind": basis["content"].get("claim_kind", "inference"),
            "conditions": conditions.strip(), "transfer_reason": reason.strip(),
            "claim_truth_verified": False,
            "qualification": "An explicitly linked historical claim, not a cross-project fact or independent evidence"}
    def save(state):
        target.assert_input_change_allowed(state)
        state.setdefault("cross_project_memory", {})[card_id] = copy.deepcopy(card)
        target.event(state, "cross_project_memory_linked", card_id=card_id, origin_post=post_id)
        return card_id
    return target.file.update("link-memory:" + card_id, save)


def recall(client, state, limit=3):
    result = []
    stored = list(state.get("cross_project_memory", {}).values())
    for card in reversed(stored[-limit:]):
        view = copy.deepcopy(card)
        try:
            origin, _ = JsonFile(client, card["origin_workspace"], "exploration/state.json").read()
            finding = origin.get("knowledge", {}).get(card["origin_post"])
            content = json.loads(client.request("GET", "/posts/" + card["origin_post"])["content"])
            if finding is None or digest(content) != card["content_sha256"]:
                view.update(origin_status="changed_or_unavailable", applicability_check_required=True)
            else:
                view.update(origin_status=finding["status"],
                    current_review_version=finding.get("review_version", 0),
                    origin_question_changed=len(origin["question_revisions"]) != card["observed_question_revision"],
                    applicability_check_required=True,
                    historical_basis_changed=(finding.get("review_version", 0) != card["observed_review_version"]
                                              or len(origin["question_revisions"]) != card["observed_question_revision"]),
                    withdrawal_or_revision=finding.get("withdrawn_by") or finding.get("superseded_by"))
        except (RuntimeError, OSError, ValueError, KeyError):
            view.update(origin_status="unavailable", applicability_check_required=True)
        view["omitted_card_count"] = max(0, len(stored) - limit)
        result.append(view)
    return result
