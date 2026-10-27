"""Author reviews of earlier findings. A response never verifies claim truth."""
from __future__ import annotations

import copy
import json

from .memory import terms

DECISIONS = ("retain", "revise", "withdraw", "undecided")
INACTIVE = ("superseded", "withdrawn")


def candidates(state, actor, question, revision, limit=6):
    """Own findings only: controls must not gain peer semantics via this path."""
    query = terms(question)
    entries = []
    for finding in state.get("knowledge", {}).values():
        if finding["actor"] != actor or finding["status"] in INACTIVE:
            continue
        challenges = finding.get("challenges", [])
        # Responses are attributed discussion, not resolutions of objections.
        unanswered = [c for c in challenges if not c.get("author_responses")]
        card = {key: copy.deepcopy(finding[key]) for key in
                ("post_id", "actor", "preview", "question_revision", "status", "evidence", "unresolved", "revisit_when")
                if key in finding}
        card.update(review_version=finding.get("review_version", 0),
                    challenges=copy.deepcopy((unanswered + [c for c in reversed(challenges) if c not in unanswered])[:6]),
                    unanswered_challenge_count=len(unanswered),
                    applicability_check_required=finding["question_revision"] != revision,
                    qualification="An objection and an author's response are not independent truth verification")
        score = (bool(unanswered), bool(challenges), finding["question_revision"] != revision,
                 len(query & terms(finding.get("preview", "") + " " + finding.get("unresolved", ""))))
        entries.append((score, len(entries), card))
    return [card for _, _, card in sorted(entries, key=lambda item: (item[0], item[1]), reverse=True)[:limit]]


def selection(output, request):
    review = output.get("review")
    if review is None:
        return None
    if not isinstance(review, dict) or not isinstance(review.get("reason"), str) or not review["reason"].strip():
        raise ValueError("A review action requires a target and a concrete reason")
    card = next((c for c in request.get("review_candidates", []) if c["post_id"] == review.get("target_post")), None)
    if card is None or card["actor"] != request["actor"]:
        raise ValueError("Review target was not an actually supplied own finding")
    return card


def context(client, state, card):
    """Read the chosen claim and the objections named in the plan snapshot."""
    original = client.request("GET", "/posts/" + card["post_id"])
    challenges = []
    for entry in card["challenges"]:
        post = client.request("GET", "/posts/" + entry["post_id"])
        challenges.append({"post_id": entry["post_id"], "reason": entry["reason"],
                           "author_type": entry.get("author_type", "historical_intervention"),
                           "source_id": entry.get("source_id"), "content": json.loads(post["content"])})
    note_ids = [call["id"] for call in state["calls"].values() if call.get("post_id") == card["post_id"]]
    # Objections live in the supplied list only. Duplicating the plan card's
    # challenges here both wastes context and makes omitted IDs look visible.
    target = {key: copy.deepcopy(value) for key, value in card.items() if key != "challenges"}
    return {"target": target, "original": json.loads(original["content"]),
            "challenges": challenges, "memory_note_ids": note_ids,
            "qualification": "Recheck applicability and evidence; replying does not settle an objection"}


def validate(output, request):
    review = output.get("review")
    chosen = request.get("review_context")
    if chosen is None:
        if review is not None:
            raise ValueError("Select a review in the plan before responding to an earlier finding")
        return
    if (not isinstance(review, dict) or review.get("target_post") != chosen["target"]["post_id"]
            or chosen["target"]["actor"] != request["actor"]
            or review.get("decision") not in DECISIONS
            or not isinstance(review.get("reason"), str) or not review["reason"].strip()):
        raise ValueError("A selected review needs an attributed retain/revise/withdraw/undecided response")
    addressed = review.get("addressed_challenges")
    allowed = {c["post_id"] for c in chosen["challenges"]}
    if (not isinstance(addressed, list) or any(not isinstance(c, str) or c not in allowed for c in addressed)
            or len(set(addressed)) != len(addressed)):
        raise ValueError("Review response refers to an objection that was not actually supplied")


def record(state, actor, call_id, post_id, output, request):
    """Called inside the same CAS commit that finalizes the response post."""
    review = output.get("review")
    if review is None:
        return
    observed = request["review_context"]["target"]
    target = state["knowledge"][review["target_post"]]
    current = target.get("review_version", 0)
    applied = current == observed["review_version"] and target["status"] not in INACTIVE
    entry = {"id": "review:" + call_id, "actor": actor, "target_post": review["target_post"],
             "response_post": post_id, "decision": review["decision"], "reason": review["reason"],
             "addressed_challenges": list(review["addressed_challenges"]),
             "question_revision": request["question_revision"], "observed_version": observed["review_version"],
             "actual_version": current, "status": "recorded" if applied else "stale",
             "evidence": copy.deepcopy(output.get("evidence")), "claim_truth_verified": False,
             "recalled_note_ids": [note["id"] for note in request["private_memory"].get("recalled_notes", [])
                                   if note["id"] in request["review_context"]["memory_note_ids"]],
             "qualification": "An author's response, not an independent resolution or validated replacement"}
    state.setdefault("reviews", []).append(entry)
    if not applied:
        return entry
    target["review_version"] = current + 1
    target.setdefault("reviews", []).append(entry["id"])
    for objection in target.get("challenges", []):
        if objection["post_id"] in review["addressed_challenges"]:
            objection.setdefault("author_responses", []).append(post_id)
    if review["decision"] == "revise":
        target.update(status="superseded", superseded_by=post_id)
        state["knowledge"][post_id]["revises"] = review["target_post"]
    elif review["decision"] == "withdraw":
        target.update(status="withdrawn", withdrawn_by=post_id)
    # retain and undecided never promote a contested claim to accepted truth.
    return entry


def critique_targets(request):
    visible = {entry["post_id"]: "qualified_memory_index" for entry in request.get("shared_memory", [])
               if entry["actor"] != request["actor"]}
    visible.update({entry["id"]: "full_post" for entry in request["peers"]
                    if entry["actor"] != request["actor"] and isinstance(entry.get("content"), dict)
                    and isinstance(entry["content"].get("finding"), str)})
    return visible


def validate_critique(output, request):
    critique = output.get("critique")
    if critique is None:
        return
    if (not request.get("peer_critique_enabled") or not isinstance(critique, dict)
            or not isinstance(critique.get("target_post"), str)
            or critique.get("target_post") not in critique_targets(request)
            or not isinstance(critique.get("reason"), str) or not critique["reason"].strip()):
        raise ValueError("A peer objection must target an actually supplied peer finding in collaborative mode")


def record_critique(state, actor, post_id, output, request):
    critique = output.get("critique")
    if critique is None:
        return None
    target = state["knowledge"][critique["target_post"]]
    if target["status"] not in INACTIVE:
        target["status"] = "contested"
    target["review_version"] = target.get("review_version", 0) + 1
    target.setdefault("challenges", []).append({"post_id": post_id, "reason": critique["reason"],
        "source_id": (output.get("evidence") or {}).get("source_id"), "author_type": "peer", "actor": actor,
        "question_revision": request["question_revision"],
        "basis_view": critique_targets(request)[critique["target_post"]],
        "qualification": "Peer objection, not an established refutation"})
    return critique["target_post"]
