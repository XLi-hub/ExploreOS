"""Finite exploration protocol over the upstream identities, posts and files."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from scripts.cloud.runtime import ROOT
from .bootstrap import launch
from .memory import Memory, select_shared_memory
from . import assessments, cross_memory, policy, reviews
from .subagents import read_receipt, terminal as plugin_terminal
from .models import REAL_BACKENDS, parse_json_output
from .store import Conflict, JsonFile, atomic_local

MODES = ("single", "multiple_perspectives", "independent", "collaborative")
PERSPECTIVES = ["澄清假设、竞争解释与缺失材料；可以自行更换视角",
                "寻找反例、适用边界与被忽略的替代路线；可以自行更换视角",
                "联系实际情境、人的需求变化与可继续的问题；可以自行更换视角"]
SOURCE_SPECS = [("product", "产品目标与交互", "docs/product-design.md", 11, 55),
                ("architecture", "状态、并发与执行边界", "docs/architecture.md", 94, 140),
                ("evaluation", "反例、对照与协作收益", "docs/evaluation.md", 9, 43)]


def source_snapshot(source_id, title, relative, start, end):
    path = (ROOT / relative).resolve()
    # Only controller-supplied paths enter this function; model actions select IDs.
    if not path.is_file() or path.stat().st_size > 256_000:
        raise ValueError("Configured source must be a regular text file below 256 KB")
    lines = path.read_text().splitlines()[start - 1:end]
    if not lines or len("\n".join(lines).encode()) > 12_000:
        raise ValueError("Select a smaller nonempty source slice before starting model calls")
    return {"id": source_id, "title": title, "path": relative, "start_line": start, "lines": lines,
            "sha256": hashlib.sha256("\n".join(lines).encode()).hexdigest()}


def process_identity(pid=None):
    pid = pid or os.getpid()
    try:
        start = Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()[19]
        return {"pid": pid, "start": start, "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}
    except FileNotFoundError:
        return None


def alive(identity):
    if not identity or process_identity(identity["pid"]) != identity:
        return False
    try:
        return not Path(f"/proc/{identity['pid']}/stat").read_text().split(") ", 1)[1].startswith("Z")
    except FileNotFoundError:
        return False


class Project:
    def __init__(self, client, directory):
        self.client, self.directory = client, Path(directory)
        self.metadata = json.loads((self.directory / "run_metadata.json").read_text())
        self.file = JsonFile(client, self.metadata["workspace_id"], "exploration/state.json")

    @classmethod
    def create(cls, client, name, *, mode="collaborative", scenario="split", max_rounds=2, question=None, sources=None, question_author="user", semantic_policy=None, max_invocations_per_round=None, participants=3, max_concurrency=2):
        if mode not in MODES:
            raise ValueError("Unknown evaluation mode")
        semantic_policy = policy.normalize(semantic_policy)
        if type(participants) is not int or not 1 <= participants <= 8 or type(max_concurrency) is not int or not 1 <= max_concurrency <= 8:
            raise ValueError("Configure 1–8 participants and 1–8 concurrent calls")
        max_invocations_per_round = max_invocations_per_round if max_invocations_per_round is not None else max(12, participants * 4)
        if type(max_rounds) is not int or not 1 <= max_rounds <= 20:
            raise ValueError("Configure 1–20 finite rounds")
        if type(max_invocations_per_round) is not int or not 3 <= max_invocations_per_round <= 40:
            raise ValueError("Round invocation ceiling must be 3–40")
        if mode not in ("single", "multiple_perspectives") and max_invocations_per_round < participants * 3:
            raise ValueError("Invocation ceiling must allow each participant's three baseline phases")
        directory, metadata = launch(client, name, question, participants=participants)
        project = cls(client, directory)
        actors = metadata["agents"][:1] if mode in ("single", "multiple_perspectives") else metadata["agents"]
        snapshots = {}
        selected_sources = sources if sources is not None else ([] if question else SOURCE_SPECS)
        for spec in selected_sources:
            source = source_snapshot(*spec)
            path = f"sources/{source['id']}.json"
            client.request("PUT", f"/workspaces/{metadata['workspace_id']}/files/{path}",
                           {"content": json.dumps(source, ensure_ascii=False)}, version=0)
            snapshots[source["id"]] = {key: value for key, value in source.items() if key != "lines"}
        project.file.create({"kind": "open_exploration_v1", "name": name, "mode": mode, "scenario": scenario,
            "status": "active", "max_rounds": max_rounds, "max_invocations_per_round": max_invocations_per_round,
            "semantic_policy": semantic_policy,
            "max_concurrency": max_concurrency,
            "question_revisions": [{"number": 1, "text": question or "如何让本项目从多智能体演示走向可持续、可核对的开放探索？", "author": question_author if question else "user_fixture"}],
            "agents": {actor: {"direction": None, "cursor": 0, "perspective": PERSPECTIVES[i % len(PERSPECTIVES)]} for i, actor in enumerate(actors)},
            "directions": {}, "changes": {}, "direction_history": [], "sources": snapshots, "rounds": [],
            "calls": {}, "posts": [], "knowledge": {}, "reviews": [], "events": []})
        return project

    def add_source(self, path, title=None):
        source_id = "source_" + uuid.uuid4().hex[:12]
        source = source_snapshot(source_id, title or Path(path).name, str(path), 1, 80)
        self.client.request("PUT", f"/workspaces/{self.file.workspace}/files/sources/{source_id}.json",
                            {"content": json.dumps(source, ensure_ascii=False)}, version=0)
        def add(state):
            state["sources"][source_id] = {key: value for key, value in source.items() if key != "lines"}
            self.event(state, "source_added", source_id=source_id, sha256=source["sha256"])
            return source_id
        return self.file.update("source:" + source_id, add)

    def event(self, state, kind, **values):
        state["events"].append({"sequence": len(state["events"]) + 1, "kind": kind, "time_ns": time.time_ns(), **values})

    def status(self):
        state, version = self.file.read()
        return {"name": state["name"], "mode": state["mode"], "status": state["status"], "version": version,
                "rounds": state["rounds"], "calls": {key: value["status"] for key, value in state["calls"].items()},
                "directions": state["directions"], "changes": state["changes"],
                "review_count": len(state.get("reviews", [])),
                "source_assessment_summary": assessments.summary(state),
                "unanswered_challenges": sum(not c.get("author_responses") for k in state.get("knowledge", {}).values()
                                             for c in k.get("challenges", []))}

    def control(self, command, question=None, author="user"):
        def change(state):
            if command in ("pause", "cancel"):
                state["status"] = "paused" if command == "pause" else "cancelling"
                if command == "cancel" and not any(c["status"] in ("starting", "running") for c in state["calls"].values()):
                    state["status"] = "paused"
                    if state["rounds"] and state["rounds"][-1]["status"] == "active":
                        state["rounds"][-1]["status"] = "cancelled"
            elif command == "resume":
                if any(call["status"] in ("starting", "running", "unknown") for call in state["calls"].values()):
                    raise RuntimeError("Reconcile outstanding invocations before resuming")
                state["status"] = "active"
            elif command == "steer":
                if not question or not question.strip():
                    raise ValueError("A new user focus is required")
                state["question_revisions"].append({"number": len(state["question_revisions"]) + 1,
                                                     "text": question, "author": author})
            self.event(state, command, question_revision=len(state["question_revisions"]))
            return True
        return self.file.update("control:" + uuid.uuid4().hex, change)

    def extend(self, rounds=1):
        if type(rounds) is not int or not 1 <= rounds <= 20:
            raise ValueError("Authorize 1–20 additional finite rounds at a time")
        def change(state):
            state["max_rounds"] += rounds
            self.event(state, "round_allowance_extended", additional_rounds=rounds,
                       qualification="Supplier budget is unchanged")
            return state["max_rounds"]
        return self.file.update("extend:" + uuid.uuid4().hex, change)

    def retry(self, slot, reason, budget=None):
        if not reason or not reason.strip():
            raise ValueError("An explicit correction/retry reason is required")
        ledger = budget.file.read()[0]["requests"] if budget else {}
        observed, _ = self.file.read()
        observed_call = observed["calls"][slot]
        plugin_receipt = None
        if observed_call["backend"] == "pi-subagents":
            plugin_receipt = read_receipt(self.directory / "agents" / observed_call["actor"], observed_call["id"])
        def change(state):
            if state.get("controller") and alive(state["controller"]["process"]):
                raise RuntimeError("Stop the current controller before authorizing a retry")
            call = state["calls"][slot]
            if call["id"] != observed_call["id"]:
                raise RuntimeError("The invocation changed while authorizing its retry")
            if alive(call.get("child")) or (call["status"] == "unknown" and alive(call.get("controller"))):
                raise RuntimeError("The original process is still alive; do not duplicate its work")
            record = ledger.get(call["id"])
            if call["backend"] in REAL_BACKENDS:
                if budget is None or (record is not None and record["state"] != "received"):
                    raise RuntimeError("Unknown supplier outcome; retain the reservation and reconcile first")
            if call["backend"] == "pi-subagents":
                unsent = (record is None and (call["status"] == "failed_before_dispatch" or
                          (plugin_receipt is not None and plugin_receipt.get("emitted") is False)))
                if not unsent and not plugin_terminal(plugin_receipt):
                    raise RuntimeError("Plugin outcome is unknown; missing receipts do not authorize redispatch")
                if (plugin_terminal(plugin_receipt) and plugin_receipt["response"]["status"] == "completed"
                        and call["status"] != "invalid_output"):
                    raise RuntimeError("Reconcile the completed plugin result instead of starting another paid attempt")
            if call["status"] not in ("failed", "failed_before_dispatch", "invalid_output", "unknown"):
                raise RuntimeError("Only terminal failed or verified unsent attempts can be retried")
            if any(c["status"] in ("starting", "running", "unknown") and key != slot for key, c in state["calls"].items()):
                raise RuntimeError("Reconcile other outstanding calls before retrying")
            state.setdefault("retired_calls", {})[call["id"]] = call
            state.setdefault("attempt_numbers", {})[slot] = state.get("attempt_numbers", {}).get(slot, 1) + 1
            state.setdefault("retry_feedback", {})[slot] = {"reason": reason, "previous_attempt": call["id"],
                                                            "rejected_output": call.get("output")}
            del state["calls"][slot]
            state["status"] = "active"
            self.event(state, "retry_authorized", previous_attempt=call["id"], reason=reason)
            return True
        return self.file.update("retry:" + uuid.uuid4().hex, change)

    def challenge(self, target_post, reason, source_id=None, author_type="user"):
        state, _ = self.file.read()
        entry = next((p for p in state["posts"] if p["id"] == target_post and p["phase"] == "reflect"), None)
        if not entry or not reason or not reason.strip():
            raise ValueError("Choose a finding in this project and provide a concrete challenge")
        if source_id is not None and source_id not in state["sources"]:
            raise ValueError("Challenge source is not in this project's material index")
        if author_type not in ("user", "assistant_review", "evaluation_script"):
            raise ValueError("Identify the challenge author as user, assistant_review or evaluation_script")
        author = {"user": "user_", "assistant_review": "review_", "evaluation_script": "script_"}[author_type] + state["name"][:20]
        self.client.request("POST", "/agents/register", {"name": author, "description": author_type + " intervention record"})
        operation = "challenge:" + uuid.uuid4().hex
        body = {"target_post": target_post, "reason": reason, "source_id": source_id,
                "question_revision": len(state["question_revisions"]), "author_type": author_type,
                "round": len(state["rounds"]),
                "qualification": "A challenge is not an automatically proven refutation"}
        self.file.update("intent:" + operation, lambda s: s.setdefault("pending_challenges", {}).update(
            {operation: {"actor": author, "body": body, "target_entry": entry}}))
        return self.complete_challenge(operation, {"actor": author, "body": body, "target_entry": entry})

    def complete_challenge(self, operation, intent):
        author, body, entry = intent["actor"], intent["body"], intent["target_entry"]
        target_post, reason, source_id = body["target_post"], body["reason"], body["source_id"]
        published = self.client.publish(self.metadata["workshop"], author, operation, "challenge", body)
        def change(state):
            knowledge = state.setdefault("knowledge", {}).setdefault(target_post, {"post_id": target_post,
                "actor": entry["actor"], "question_revision": entry["question_revision"],
                "claim_truth_verified": False})
            if knowledge.get("status") not in reviews.INACTIVE:
                knowledge["status"] = "contested"
            knowledge["review_version"] = knowledge.get("review_version", 0) + 1
            knowledge.setdefault("challenges", []).append({"post_id": published, "reason": reason, "source_id": source_id,
                "author_type": body["author_type"], "question_revision": body["question_revision"]})
            state["posts"].append({"id": published, "actor": author, "phase": "challenge", "round": body["round"],
                                   "question_revision": body["question_revision"]})
            self.event(state, "finding_challenged", target_post=target_post, challenge_post=published)
            state.get("pending_challenges", {}).pop(operation, None)
            return published
        return self.file.update(operation, change)

    def read_source(self, source_id):
        state, _ = self.file.read()
        source = json.loads(self.client.request("GET", f"/workspaces/{self.file.workspace}/files/sources/{source_id}.json")["content"])
        digest = hashlib.sha256("\n".join(source["lines"]).encode()).hexdigest()
        if digest != state["sources"][source_id]["sha256"]:
            raise RuntimeError("Material changed after its project snapshot")
        return source

    def call_details(self, call):
        archive = call.get("archive")
        if archive is None:
            return call
        record = json.loads(self.client.request("GET",
            f"/workspaces/{self.file.workspace}/files/{archive['path']}")["content"])
        if assessments.digest(record) != archive["sha256"] or record["call"]["id"] != call["id"]:
            raise RuntimeError("Archived invocation differs from its immutable reference")
        return {**record["call"], **call}

    def archive_history(self, *, threshold=450_000):
        """Move completed payloads to immutable upstream files before 1 MB writes.

        Live/unknown attempts stay inline. Metadata, execution ownership and the
        single content authority are unchanged; this is not another database.
        """
        state, _ = self.file.read()
        if len(json.dumps({"content": json.dumps(state)}).encode()) <= threshold:
            return 0
        archived = {}
        for group in ("calls", "retired_calls"):
            for slot, call in state.get(group, {}).items():
                if call.get("archive") or (group == "calls" and call["status"] != "completed"):
                    continue
                record = {"kind": "archived_invocation_v1", "call": call}
                fingerprint = assessments.digest(record)
                path = "execution/archive/" + hashlib.sha256(call["id"].encode()).hexdigest() + ".json"
                endpoint = f"/workspaces/{self.file.workspace}/files/{path}"
                try:
                    self.client.request("PUT", endpoint, {"content": json.dumps(record, ensure_ascii=False)}, version=0)
                except Conflict:
                    if assessments.digest(json.loads(self.client.request("GET", endpoint)["content"])) != fingerprint:
                        raise Conflict("Existing invocation archive differs from its fingerprint")
                archived[(group, slot)] = (fingerprint, path, call)
        if not archived:
            return 0
        def compact(current):
            count = 0
            for (group, slot), (fingerprint, path, observed) in archived.items():
                actual = current.get(group, {}).get(slot)
                if actual != observed:
                    continue
                actual["archive"] = {"path": path, "sha256": fingerprint}
                for field in ("request", "output", "publication_payload"):
                    actual.pop(field, None)
                # Preserve all proven peer-read IDs before retiring full inputs.
                actor = current["agents"].get(actual["actor"])
                if actor is not None:
                    provided = observed.get("request", {})
                    actor["read_posts"] = sorted(set(actor.get("read_posts", [])) |
                        {p["id"] for p in provided.get("peers", [])} | set(provided.get("contribution_views", {})))
                count += 1
            self.event(current, "invocation_payloads_archived", count=count)
            return count
        return self.file.update("archive-invocations:" + uuid.uuid4().hex, compact)

    def audit_source(self, post_id):
        state, _ = self.file.read()
        if not any(p["id"] == post_id and p["phase"] == "reflect" for p in state["posts"]):
            raise ValueError("Choose a finding in this project")
        content = json.loads(self.client.request("GET", f"/posts/{post_id}")["content"])
        evidence = content.get("evidence")
        source = self.read_source(evidence["source_id"]) if evidence else None
        return assessments.packet(state, post_id, content, source)

    def assess_source(self, post_id, basis_sha256, verdict, reason, reviewer, scope, assessment_id=None):
        assessment_id = assessment_id or uuid.uuid4().hex
        if (not isinstance(assessment_id, str) or not 1 <= len(assessment_id) <= 64
                or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in assessment_id)):
            raise ValueError("Assessment ID must be 1–64 letters, digits, underscores or hyphens")
        if any(not isinstance(value, str) for value in (reason, reviewer, scope)):
            raise ValueError("Assessment reason, reviewer and scope must be text")
        supplied = dict(target_post=post_id, basis_sha256=basis_sha256, verdict=verdict,
                        reason=reason.strip(), reviewer=reviewer.strip(), scope=scope.strip())
        def existing(state):
            old = state.get("source_assessments", {}).get(assessment_id)
            if old is not None and any(old[k] != v for k, v in supplied.items()):
                raise Conflict("Assessment ID already belongs to a different judgment")
            return old
        state, _ = self.file.read()
        if existing(state) is not None:
            return assessment_id
        audit = self.audit_source(post_id)
        if audit["basis_sha256"] != basis_sha256:
            raise Conflict("Audit basis changed; inspect a fresh source-audit before assessing")
        record = assessments.judgment(audit, verdict, reason, reviewer, scope)
        basis_path = f"exploration/source-audits/{basis_sha256}.json"
        archived = {"kind": "source_audit_basis_v1", "basis": audit["basis"], "basis_sha256": basis_sha256}
        endpoint = f"/workspaces/{self.file.workspace}/files/{basis_path}"
        try:
            self.client.request("PUT", endpoint, {"content": json.dumps(archived, ensure_ascii=False)}, version=0)
        except Conflict:
            if json.loads(self.client.request("GET", endpoint)["content"]) != archived:
                raise Conflict("Stored audit basis differs from its fingerprint")
        record.update(id=assessment_id, basis_path=basis_path, created_ns=time.time_ns())
        def change(state):
            if existing(state) is not None:
                return assessment_id
            current = assessments.packet(state, post_id, audit["basis"]["content"], audit["basis"]["source"])
            if current["basis_sha256"] != basis_sha256:
                raise Conflict("Question or feedback changed during assessment; inspect a fresh source-audit")
            records = state.setdefault("source_assessments", {})
            finding = state["knowledge"][post_id]
            finding["review_version"] = finding.get("review_version", 0) + 1
            records[assessment_id] = {**record, "sequence": len(records) + 1,
                                      "resulting_review_version": finding["review_version"]}
            self.event(state, "source_support_assessed", assessment_id=assessment_id, target_post=post_id,
                       verdict=verdict, reviewer=reviewer)
            return assessment_id
        return self.file.update("source-assessment:" + assessment_id + ":" + assessments.digest(supplied), change)

    def request_for(self, state, actor, phase, round_record):
        semantic_policy = policy.normalize(state.get("semantic_policy"))
        review_context = None
        if phase == "reflect":
            planned = self.call_details(state["calls"][f"r{round_record['number']}.plan.{actor}"])
            chosen = reviews.selection(planned["output"], planned["request"])
            if chosen is not None:
                review_context = reviews.context(self.client, state, chosen)
        peers = []
        if state["mode"] == "collaborative" and phase != "propose":
            for entry in state["posts"][-18:]:
                if entry["actor"] != actor:
                    post = self.client.request("GET", f"/posts/{entry['id']}")
                    peers.append({"id": post["id"], "actor": entry["actor"], "content": json.loads(post["content"])})
        memory_store = Memory(self.directory / "agents" / actor / "memory")
        remembered = {note["id"] for note in memory_store.index()["notes"]}
        # Recover indexed private notes from immutable completed attempt outputs,
        # including projects created before the indexed-memory implementation.
        for call in state["calls"].values():
            if call["actor"] != actor or call["status"] != "completed" or call["id"] in remembered:
                continue
            result = self.call_details(call).get("output", {})
            if result.get("summary"):
                memory_store.remember(call["id"], summary=result["summary"], question_revision=call["question_revision"],
                    source_ids=[result["evidence"]["source_id"]] if result.get("evidence") else [],
                    unresolved=result.get("unresolved", ""), peer_posts=result.get("influenced_by", []), review=result.get("review"))
        memory = memory_store.recall(state["question_revisions"][round_record["question_revision"] - 1]["text"],
                                    preferred_ids=review_context["memory_note_ids"] if review_context else (),
                                    include_execution_failures=semantic_policy["execution_failure_memory"])
        prior_findings = {call["id"]: state.get("knowledge", {}).get(call.get("post_id")) for call in state["calls"].values()}
        for note in memory.get("recalled_notes", []):
            finding = prior_findings.get(note["id"])
            if finding:
                note["current_finding"] = {key: finding[key] for key in
                    ("post_id", "status", "question_revision", "superseded_by", "withdrawn_by") if key in finding}
        directions = list(state["directions"].values())
        if state["mode"] != "collaborative":
            directions = [d for d in directions if actor in d["members"]]
        pending = [c for c in state["changes"].values() if c["status"] == "pending"] if peers else []
        request = {"phase": phase, "actor": actor, "round": round_record["number"],
                   "question_revision": round_record["question_revision"],
                   "question": state["question_revisions"][round_record["question_revision"] - 1]["text"],
                   "initial_perspective": PERSPECTIVES if state["mode"] == "multiple_perspectives" else state["agents"][actor]["perspective"],
                   "private_memory": memory, "peers": peers, "directions": directions, "pending_changes": pending,
                   "sources": [{"id": s["id"], "title": s["title"]} for s in state["sources"].values()]}
        previously_read = set(state["agents"][actor].get("read_posts", []))
        if state["mode"] == "collaborative":
            for call in state["calls"].values():
                if call["actor"] == actor and call["status"] == "completed":
                    previously_read.update(p["id"] for p in call.get("request", {}).get("peers", []))
        else:
            previously_read.clear()
        recalled_links = {link for note in memory.get("recalled_notes", []) for link in note.get("peer_posts", [])}
        priority_links = sorted(recalled_links & previously_read)
        request["previously_read_peer_ids"] = (priority_links + sorted(previously_read - recalled_links))[:100]
        request["index_cursor"] = len(state["posts"]) if phase != "propose" else state["agents"][actor]["cursor"]
        request["shared_memory"] = select_shared_memory(state, actor, phase, request["question"], request["question_revision"])
        request["review_candidates"] = reviews.candidates(state, actor, request["question"], request["question_revision"]) if phase == "plan" else []
        request["review_context"] = review_context
        request["peer_critique_enabled"] = state["mode"] == "collaborative" and phase == "reflect" and semantic_policy["peer_critique"]
        request["semantic_policy"] = semantic_policy
        request["cross_project_memory"] = cross_memory.recall(self.client, state) if phase != "propose" else []
        if phase == "propose":
            request["contract"] = {"direction": "一个暂定探索方向，避免声称已验证", "reason": "方向理由", "summary": "私有工作摘要"}
        elif phase == "plan":
            request["contract"] = {"source_id": "选择实际读取的一份来源ID；本次只推理可为null，无资料时必须为null", "purpose": "检查什么假设，考虑质疑和重复工作",
                                   "review": "null，或{target_post:review_candidates中自己的旧发现ID,reason:为什么复查}；可选择新材料检查，不要求每次复查",
                                   "influenced_by": ["实际影响行动的同伴帖子ID，没有则为空"],
                                   "acknowledge": ["只能来自本次pending_changes列表；该列表为空必须给空数组，不要复制同伴对旧提案的确认"]}
        elif phase == "consent":
            request["contract"] = {"acknowledge": ["你明确同意的待处理变更ID；不同意或依据不足时留空"],
                                   "reason": "确认或保留意见的依据，不要为了完成流程而同意"}
        else:
            plan = self.call_details(state["calls"][f"r{round_record['number']}.plan.{actor}"])["output"]
            request["tool_result"] = self.read_source(plan["source_id"]) if plan["source_id"] is not None else None
            request["prior_action"] = plan
            request["contract"] = {"finding": "读完材料后，说明认识或行动如何变化，保留竞争解释",
                "evidence": {"source_id": "本次材料ID", "line": "可省略，由执行器按唯一逐字引文定位", "quote": "某一行内的足够具体、可唯一定位的逐字原文"},
                "influenced_by": ["实际影响你的同伴帖子ID；没有则为空"],
                "summary": "下一轮私有摘要", "unresolved": "尚未核对的问题",
                "claim_kind": "fact/inference/hypothesis/idea之一；引用原文不自动验证推断",
                "revisit_when": "什么新材料、反例或关注点变化会使本发现需要重开，最多50字",
                "change": "可为null；或{kind:join或reopen,target:已有方向ID,reason:材料或交流给出的变更/重开理由,influenced_by:[实际同伴帖子ID]}；reopen只针对paused方向，不必为了流程而调整"}
            if request["tool_result"] is None:
                request["contract"]["evidence"] = None
                request["contract"]["claim_kind"] = "inference/hypothesis/idea之一；本次没有外部材料，禁止把主张标为fact"
            request["contract"]["review"] = ("{target_post:本次复查目标ID,decision:retain/revise/withdraw/undecided之一,reason:结合实际检查的理由,addressed_challenges:[实际回应的review_context质疑ID]}；revise时finding写新主张；允许保留分歧，回应不等于质疑已解决"
                                               if review_context else "null；本次未在plan选择复查，不能改写旧发现")
            request["contract"]["critique"] = ("null，或{target_post:本次peers或shared_memory中他人的发现ID,reason:具体质疑}；仅有索引时只能指出待查问题，不能声称读过全文；质疑不自动推翻主张"
                                                 if request["peer_critique_enabled"] else "null；本配置不提供同伴质疑通道")
            if not semantic_policy["direction_changes"]:
                request["contract"]["change"] = "null；本次固定方向与成员，保留讨论和发现但不应用重组"
        request["instructions"] = "严格输出JSON对象，键与contract一致，每个文字字段最多100字。视角提示可自行拒绝或修订，不是固定研究分工。不得编造来源或同伴ID，不用多数同意代替证据。方向与分工由你根据证据判断，程序不要求必定改向。source_assessments为署名的来源支持判断，不是新证据或事实认证；检查其范围、问题版本及分歧。"
        omitted = {"peers": 0, "shared_memory": 0, "private_notes": 0, "review_candidates": 0, "cross_project_memory": 0,
                   "review_challenges": 0}
        request["context_omissions"] = omitted
        if review_context:
            review_context["omitted_challenge_ids"] = []
            review_context["qualification"] += "; omitted objections were not supplied and cannot be claimed as addressed"
        def size():
            request["contribution_views"] = {entry["post_id"]: "qualified_memory_index" for entry in request["shared_memory"] if entry["actor"] != actor}
            request["contribution_views"].update({entry["post_id"]: "change_proposal" for entry in request["pending_changes"] if entry["actor"] != actor})
            request["contribution_views"].update({entry["id"]: "full_post" for entry in request["peers"]})
            return len(json.dumps(request, ensure_ascii=False).encode())
        while size() > 22000 and request["peers"]:
            request["peers"].pop(0)
            omitted["peers"] += 1
        while size() > 22000 and request["shared_memory"]:
            request["shared_memory"].pop()
            omitted["shared_memory"] += 1
        while size() > 22000 and request["private_memory"].get("recalled_notes"):
            request["private_memory"]["recalled_notes"].pop()
            omitted["private_notes"] += 1
        while size() > 22000 and request["cross_project_memory"]:
            request["cross_project_memory"].pop()
            omitted["cross_project_memory"] += 1
        while size() > 22000 and request["review_candidates"]:
            request["review_candidates"].pop()
            omitted["review_candidates"] += 1
        while size() > 22000 and review_context and review_context["challenges"]:
            entry = review_context["challenges"].pop()
            review_context["omitted_challenge_ids"].append(entry["post_id"])
            omitted["review_challenges"] += 1
        if size() > 22000:
            raise ValueError("Question or material slice exceeds the bounded context; provide a smaller focus or slice")
        return request

    def validate(self, output, request):
        if not isinstance(output, dict):
            raise ValueError("Participant returned a non-object")
        phase = request["phase"]
        if phase not in ("plan", "reflect") and output.get("review") is not None:
            raise ValueError("Review actions belong in plan/reflect, not other phases")
        if phase != "reflect" and output.get("critique") is not None:
            raise ValueError("Peer objections belong in a finding's reflect output")
        strings = {"propose": ("direction", "reason", "summary"), "plan": ("purpose",), "consent": ("reason",),
                   "reflect": ("finding", "summary", "unresolved")}[phase]
        if any(not isinstance(output.get(key), str) or not output[key].strip() for key in strings):
            raise ValueError("Participant output has missing text fields")
        peer_ids = {p["id"] for p in request["peers"]} | set(request.get("previously_read_peer_ids", [])) | set(request.get("contribution_views", {}))
        if phase not in ("propose", "consent"):
            links = output.get("influenced_by")
            if not isinstance(links, list) or any(link not in peer_ids for link in links):
                raise ValueError("Influence link was not in the actually provided peer context")
        if phase in ("plan", "consent"):
            acks = output.get("acknowledge")
            if not isinstance(acks, list):
                raise ValueError("Acknowledgement refers to an unseen proposal")
            pending_ids = {c["id"] for c in request["pending_changes"]}
            obsolete = [ack for ack in acks if ack not in pending_ids]
            if obsolete:
                current, _ = self.file.read()
                shown = json.dumps(request["peers"])
                if any(not isinstance(ack, str) or ack not in shown or
                       current["changes"].get(ack, {}).get("status") not in ("applied", "stale") for ack in obsolete):
                    raise ValueError("Acknowledgement refers to an unseen proposal")
                output["ignored_obsolete_acknowledgements"] = obsolete
                output["acknowledge"] = [ack for ack in acks if ack in pending_ids]
        if phase == "plan":
            reviews.selection(output, request)
            if "source_id" not in output or (output["source_id"] is not None and
                    output["source_id"] not in {source["id"] for source in request["sources"]}):
                raise ValueError("Source outside read allowlist")
        if phase == "reflect":
            reviews.validate(output, request)
            reviews.validate_critique(output, request)
            if output.get("claim_kind", "inference") not in ("fact", "inference", "hypothesis", "idea"):
                raise ValueError("Claim kind must distinguish fact, inference, hypothesis and idea")
            evidence = output.get("evidence")
            source = request["tool_result"]
            if source is None:
                if evidence is not None or output.get("claim_kind") == "fact":
                    raise ValueError("A reasoning-only step cannot invent external evidence or verify facts")
            else:
                if not isinstance(evidence, dict):
                    raise ValueError("A material-based finding must identify its actual source")
                line, quote = evidence.get("line"), evidence.get("quote")
                if (evidence.get("source_id") != source["id"] or not isinstance(quote, str) or not quote.strip()):
                    raise ValueError("Evidence does not match the actual read result")
                matches = [i + 1 for i, text in enumerate(source["lines"]) if quote in text]
                if len(matches) != 1:
                    raise ValueError("Quoted evidence is absent or ambiguous in the actual read result")
                evidence.update(model_reported_line=line, line=matches[0],
                                original_line=source["start_line"] + matches[0] - 1,
                                location_method="unique_exact_quote", source_sha256=source["sha256"])
            change = output.get("change")
            if change is not None:
                if not request.get("semantic_policy", policy.DEFAULT)["direction_changes"]:
                    raise ValueError("Direction changes are disabled in this frozen configuration")
                if (not isinstance(change, dict) or change.get("kind") not in ("join", "reopen")
                        or change.get("target") not in {d["id"] for d in request["directions"]}
                        or not isinstance(change.get("reason"), str) or not change["reason"].strip()
                        or not isinstance(change.get("influenced_by"), list) or not change["influenced_by"]
                        or any(link not in peer_ids for link in change["influenced_by"])):
                    raise ValueError("Direction change has no valid target or peer basis")
                target = next(d for d in request["directions"] if d["id"] == change["target"])
                if change["kind"] == "reopen" and target["status"] != "paused":
                    raise ValueError("Reopening requires a previously paused direction")

    def apply_changes(self, state):
        for proposal in state["changes"].values():
            if proposal["status"] != "pending" or not set(proposal["affected"]) <= set(proposal["acks"]):
                continue
            target = state["directions"][proposal["target"]]
            origin = state["directions"][proposal["origin"]]
            if (origin["version"], target["version"]) != tuple(proposal["base_versions"]):
                proposal["status"] = "stale"
                continue
            before = json.loads(json.dumps([origin, target]))
            actor = proposal["actor"]
            origin["members"].remove(actor)
            target["members"].append(actor)
            target["status"] = "active"
            origin["version"] += 1
            target["version"] += 1
            if not origin["members"]:
                origin["status"] = "paused"
            state["agents"][actor]["direction"] = target["id"]
            proposal["status"] = "applied"
            state["direction_history"].append({"proposal_id": proposal["id"], "before": before,
                                                "after": json.loads(json.dumps([origin, target]))})
            self.event(state, "direction_change_applied", proposal_id=proposal["id"])

    def finalize(self, slot, actor, phase, output, request):
        public = {key: value for key, value in output.items() if key != "summary"}
        state, _ = self.file.read()
        call_id = state["calls"][slot]["id"]
        self.file.update("publication-intent:" + call_id,
                         lambda s: s["calls"][slot].setdefault("publication_payload", public))
        public = self.file.read()[0]["calls"][slot]["publication_payload"]
        post_id = self.client.publish(self.metadata["workshop"], actor, call_id, phase, public)
        if "summary" in output:
            Memory(self.directory / "agents" / actor / "memory").remember(call_id,
                summary=output["summary"], question_revision=request["question_revision"],
                source_ids=[output["evidence"]["source_id"]] if output.get("evidence") else [],
                unresolved=output.get("unresolved", ""), peer_posts=output.get("influenced_by", []), review=output.get("review"))
            atomic_local(self.directory / "agents" / actor / "memory/exploration.json",
                         {"summary": output["summary"], "question_revision": request["question_revision"], "last_call": call_id})

        def change(state):
            call = state["calls"][slot]
            call.update(status="completed", post_id=post_id)
            state["posts"].append({"id": post_id, "actor": actor, "phase": phase, "round": request["round"],
                                   "question_revision": request["question_revision"]})
            state["agents"][actor]["cursor"] = max(state["agents"][actor]["cursor"], request.get("index_cursor", 0))
            state["agents"][actor]["read_posts"] = sorted(set(state["agents"][actor].get("read_posts", [])) |
                {post["id"] for post in request["peers"]} | set(request.get("previously_read_peer_ids", [])))
            state["agents"][actor]["read_posts"] = sorted(set(state["agents"][actor]["read_posts"]) | set(request.get("contribution_views", {})))
            if phase == "propose" and state["agents"][actor]["direction"] is None:
                direction_id = "direction:" + actor
                state["directions"][direction_id] = {"id": direction_id, "title": output["direction"],
                    "members": [actor], "version": 1, "status": "active", "proposal_post": post_id}
                state["agents"][actor]["direction"] = direction_id
            if phase in ("plan", "consent"):
                for proposal_id in output["acknowledge"]:
                    proposal = state["changes"][proposal_id]
                    if actor in proposal["affected"]:
                        proposal["acks"][actor] = post_id
                self.apply_changes(state)
                if phase == "plan":
                    source_id = output["source_id"]
                    call["read_source"] = {"id": source_id, "sha256": state["sources"][source_id]["sha256"] if source_id is not None else None}
                    chosen = reviews.selection(output, request)
                    if chosen:
                        call["review_target"] = {"post_id": chosen["post_id"], "version": chosen["review_version"]}
            if phase == "reflect" and output.get("change"):
                proposed = output["change"]
                origin_id = state["agents"][actor]["direction"]
                if proposed["target"] != origin_id:
                    origin, target = state["directions"][origin_id], state["directions"][proposed["target"]]
                    observed = {direction["id"]: direction for direction in request["directions"]}
                    observed_origin, observed_target = observed[origin_id], observed[proposed["target"]]
                    base_versions = [observed_origin["version"], observed_target["version"]]
                    proposal_id = "change:" + call_id
                    state["changes"][proposal_id] = {**proposed, "id": proposal_id, "actor": actor,
                        "origin": origin_id, "post_id": post_id,
                        "status": "pending" if base_versions == [origin["version"], target["version"]] else "stale",
                        "base_versions": base_versions,
                        "affected": sorted(set(observed_origin["members"] + observed_target["members"])), "acks": {actor: post_id}}
                    self.apply_changes(state)
            if phase == "reflect":
                state.setdefault("knowledge", {})[post_id] = {"post_id": post_id, "actor": actor,
                    "question_revision": request["question_revision"], "preview": output["finding"][:120],
                    "claim_kind": output.get("claim_kind", "inference"), "status": "provisional",
                    "evidence": output["evidence"], "unresolved": output["unresolved"],
                    "revisit_when": output.get("revisit_when", "Recheck when question, material or assumptions change"),
                    "source_quote_verified": output.get("evidence") is not None, "claim_truth_verified": False}
                review = reviews.record(state, actor, call_id, post_id, output, request)
                if review:
                    self.event(state, "finding_reviewed", review_id=review["id"], status=review["status"])
                challenged = reviews.record_critique(state, actor, post_id, output, request)
                if challenged:
                    self.event(state, "peer_challenged_finding", target_post=challenged, challenge_post=post_id)
            self.event(state, "call_completed", call_id=call_id, post_id=post_id,
                       question_revision=request["question_revision"])
            return post_id
        return self.file.update("finalize:" + call_id, change)

    def perform(self, actor, phase, round_record, backend, owner):
        slot = f"r{round_record['number']}.{phase}.{actor}"
        prior, _ = self.file.read()
        attempt_number = prior.get("attempt_numbers", {}).get(slot, 1)
        call_id = self.metadata["run_id"] + ":" + slot + (f":attempt{attempt_number}" if attempt_number > 1 else "")
        def claim(state):
            if slot in state["calls"]:
                return False
            if state["status"] != "active":
                raise RuntimeError("Project is paused or cancelling")
            trigger = round_record.get("schedule_trigger")
            if trigger and (not state.get("schedule", {}).get("enabled") or
                            state["schedule"]["generation"] != trigger["generation"]):
                raise RuntimeError("Scheduled dispatch was disabled or superseded")
            number = sum(c["round"] == round_record["number"] for c in
                         [*state["calls"].values(), *state.get("retired_calls", {}).values()])
            if number >= state["max_invocations_per_round"]:
                raise RuntimeError("Round invocation limit exhausted")
            state["calls"][slot] = {"id": call_id, "status": "starting", "actor": actor, "phase": phase,
                "round": round_record["number"], "question_revision": round_record["question_revision"],
                "owner": owner, "controller": process_identity(), "started_ns": time.time_ns(), "backend": backend.name}
            self.event(state, "call_claimed", call_id=call_id)
            return True
        self.file.update("claim:" + slot + ":" + owner, claim)
        state, _ = self.file.read()
        call = state["calls"][slot]
        if call["status"] == "completed":
            return call["post_id"]
        if call["status"] == "received":
            self.validate(call["output"], call["request"])
            return self.finalize(slot, actor, phase, call["output"], call["request"])
        if call["owner"] != owner or call["status"] != "starting":
            raise RuntimeError("Invocation already claimed; reconcile it instead of retrying")
        try:
            request = self.request_for(state, actor, phase, round_record)
            if slot in state.get("retry_feedback", {}):
                request["correction_feedback"] = state["retry_feedback"][slot]
        except Exception as error:
            self.file.update("prepare-error:" + call_id, lambda s: s["calls"][slot].update(
                status="failed_before_dispatch", error_type=type(error).__name__, ended_ns=time.time_ns(),
                failure={"scope": "context assembly and allowlisted material read", "observed": type(error).__name__,
                         "retry_when": "repair the material/context and explicitly reconcile; no supplier request was dispatched"}))
            raise
        execution_ref = backend.execution_reference(call_id, self.directory / "agents" / actor) if hasattr(backend, "execution_reference") else None
        self.file.update("request:" + call_id, lambda s: s["calls"][slot].update(request=request, execution_ref=execution_ref))

        def started(process):
            self.file.update("started:" + call_id,
                             lambda s: s["calls"][slot].update(status="running", child=process_identity(process.pid)))
        last_check = [0, False]
        def cancelled():
            if time.monotonic() - last_check[0] > 0.4:
                current, _ = self.file.read()
                last_check[:] = [time.monotonic(), current["status"] == "cancelling"]
            return last_check[1]
        try:
            output = backend.call(call_id, [request], self.directory / "agents" / actor,
                                  cancelled=cancelled, started=started)
            self.file.update("received:" + call_id, lambda s: s["calls"][slot].update(
                status="received", output=output, ended_ns=time.time_ns()))
            self.validate(output, request)
            return self.finalize(slot, actor, phase, output, request)
        except BaseException as error:
            current, _ = self.file.read()
            known_output = current["calls"][slot].get("output") is not None
            status = ("invalid_output" if isinstance(error, ValueError) else "received") if known_output else (
                "unknown" if backend.name in REAL_BACKENDS else "failed")
            failure = {"scope": f"{phase} at question revision {request['question_revision']}",
                       "observed": type(error).__name__, "classification": "execution_observation_not_rejected_hypothesis",
                       "retry_when": "known outcomes may be reconciled; unknown supplier requests retain their reservation"}
            self.file.update("error:" + call_id,
                lambda s: s["calls"][slot].update(status=status, failure=failure,
                                                 error_type=type(error).__name__, ended_ns=time.time_ns()))
            Memory(self.directory / "agents" / actor / "memory").remember("failure:" + call_id,
                summary=f"Execution {phase} encountered {type(error).__name__}; this does not disprove the task hypothesis",
                question_revision=request["question_revision"], unresolved="Inspect the original attempt before retrying",
                failure=failure)
            raise

    def advance(self, backend, *, trigger=None):
        owner = uuid.uuid4().hex
        def own(state):
            current = state.get("controller")
            if current and alive(current["process"]):
                raise RuntimeError("Another live controller owns this project")
            state["controller"] = {"owner": owner, "process": process_identity()}
            return True
        self.file.update("controller:" + owner, own)
        try:
            return self._advance_owned(backend, owner, trigger=trigger)
        finally:
            def release(state):
                if state.get("controller", {}).get("owner") == owner:
                    state.pop("controller", None)
                return True
            self.file.update("release:" + owner, release)

    def _advance_owned(self, backend, owner, *, trigger=None):
        def start(state):
            if state["status"] != "active":
                raise RuntimeError("Project is paused or blocked; inspect status first")
            if trigger is not None:
                schedule = state.get("schedule", {})
                if (not schedule.get("enabled") or schedule["generation"] != trigger["generation"]
                        or schedule.get("trigger", {}).get("id") != trigger["id"]):
                    raise RuntimeError("The scheduled wakeup was disabled or replaced")
                actual = len(state["rounds"]) + (1 if not state["rounds"] or state["rounds"][-1]["status"] in ("completed", "cancelled") else 0)
                if actual != trigger["round_target"]:
                    raise Conflict("The scheduled target round already changed; do not start another round")
            previous_backends = {c["backend"] for c in
                                 [*state["calls"].values(), *state.get("retired_calls", {}).values()]}
            if previous_backends and previous_backends != {backend.name}:
                raise RuntimeError("Use a separate project for another backend; simulated results cannot fill a real-model case")
            if state["rounds"] and state["rounds"][-1]["status"] not in ("completed", "cancelled"):
                if trigger is None and state["rounds"][-1].pop("schedule_trigger", None):
                    self.event(state, "scheduled_round_taken_over_manually", round=state["rounds"][-1]["number"])
                return state["rounds"][-1]
            if len(state["rounds"]) >= state["max_rounds"]:
                raise RuntimeError("All configured rounds have completed")
            record = {"number": len(state["rounds"]) + 1, "question_revision": len(state["question_revisions"]),
                      "status": "active", "phase": "propose"}
            if trigger:
                record["schedule_trigger"] = {"id": trigger["id"], "generation": trigger["generation"]}
            state["rounds"].append(record)
            self.event(state, "round_started", round=record["number"], question_revision=record["question_revision"])
            return record
        round_record = self.file.update("round-start:" + owner, start)
        for phase in ("propose", "plan", "reflect", "consent"):
            self.archive_history()
            state, _ = self.file.read()
            # Reserve room for a complete bounded phase before any paid call.
            # The upstream API accepts 1 MB JSON bodies. If the compact index
            # itself is full, preserve it and require an explicit continuation.
            if len(json.dumps({"content": json.dumps(state)}).encode()) > 450_000:
                self.file.update("storage-boundary:" + owner, lambda s: s.update(
                    status="blocked", last_errors=["storage_capacity"],
                    continuation_required="Export this project and explicitly link relevant qualified memory into a new project"))
                raise RuntimeError("Project audit index reached its bounded capacity; export and create an explicit linked continuation before more calls")
            if state["status"] != "active":
                return
            actors = list(state["agents"])
            if phase == "consent":
                pending = [c for c in state["changes"].values() if c["status"] == "pending"]
                actors = [actor for actor in actors if any(actor in c["affected"] and actor not in c["acks"] for c in pending)]
                if not actors:
                    continue
            errors = []
            with ThreadPoolExecutor(max_workers=state.get("max_concurrency", 2)) as pool:
                futures = [pool.submit(self.perform, actor, phase, round_record, backend, owner) for actor in actors]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as error:
                        errors.append(type(error).__name__)
            current, _ = self.file.read()
            if current["status"] == "cancelling":
                def cancelled(state):
                    state["status"] = "paused"
                    state["rounds"][-1]["status"] = "cancelled"
                    self.event(state, "round_cancelled", round=round_record["number"])
                    return True
                self.file.update("cancelled:" + owner, cancelled)
                return
            if current["status"] == "paused":
                return
            if errors:
                self.file.update("blocked:" + owner, lambda s: s.update(status="blocked", last_errors=errors))
                raise RuntimeError("A participant failed; all settled peer results were retained. Inspect/reconcile before retry.")
            self.file.update(f"phase:{round_record['number']}:{phase}",
                             lambda s: s["rounds"][-1].update(phase=phase))
        self.archive_history()
        self.file.update("round-complete:" + str(round_record["number"]),
                         lambda s: s["rounds"][-1].update(status="completed"))

    def reconcile(self, budget=None):
        state, _ = self.file.read()
        for operation, intent in state.get("pending_challenges", {}).items():
            self.complete_challenge(operation, intent)
        ledger = budget.file.read()[0]["requests"] if budget else {}
        def mark_orphan(slot, call, status):
            def change(current):
                live = current.get("controller", {})
                actual = current["calls"][slot]
                if (actual["id"] != call["id"] or actual["status"] == "completed"
                        or (live.get("owner") == actual["owner"] and alive(live.get("process")))
                        or alive(actual.get("child"))):
                    return False
                actual.update(status=status, ended_ns=time.time_ns(),
                    failure={"scope": "controller exited before local completion",
                             "observed": status, "classification": "execution_observation_not_rejected_hypothesis",
                             "retry_when": "explicit retry only after a known supplier outcome or verified absence of dispatch"})
                self.event(current, "orphan_reconciled", call_id=actual["id"], status=status)
                return True
            self.file.update("orphan:" + call["id"] + ":" + status, change)
        for slot, call in state["calls"].items():
            owner = state.get("controller", {})
            driving = owner.get("owner") == call["owner"] and alive(owner.get("process"))
            if call["status"] == "completed" or driving or alive(call.get("child")):
                continue
            if call.get("output") is not None:
                try:
                    self.validate(call["output"], call["request"])
                    self.finalize(slot, call["actor"], call["phase"], call["output"], call["request"])
                except ValueError:
                    mark_orphan(slot, call, "invalid_output")
                    continue
            else:
                record = ledger.get(call["id"], {})
                if call["backend"] == "pi-subagents":
                    if call["status"] == "failed_before_dispatch":
                        continue
                    try:
                        receipt = read_receipt(self.directory / "agents" / call["actor"], call["id"])
                    except ValueError:
                        mark_orphan(slot, call, "unknown")
                        continue
                    if not plugin_terminal(receipt):
                        unsent = receipt is not None and receipt.get("emitted") is False and not record
                        mark_orphan(slot, call, "failed_before_dispatch" if unsent else "unknown")
                        continue
                    if receipt["response"]["status"] != "completed":
                        mark_orphan(slot, call, "failed")
                        continue
                    if record.get("state") != "received":
                        mark_orphan(slot, call, "unknown")
                        continue
                    # Plugin completion is required; supplier text alone is not a terminal leaf result.
                    record = {**record, "output": receipt["response"]["result"]["text"]}
                if record.get("output"):
                    try:
                        output = parse_json_output(record["output"])
                        self.validate(output, call["request"])
                    except (ValueError, KeyError):
                        mark_orphan(slot, call, "invalid_output")
                        continue
                    self.file.update("recovered:" + call["id"], lambda s, k=slot, v=output: s["calls"][k].update(status="received", output=v))
                    self.finalize(slot, call["actor"], call["phase"], output, call["request"])
                elif call["status"] in ("starting", "running", "unknown"):
                    status = "failed" if call["backend"] not in REAL_BACKENDS else (
                        "failed_before_dispatch" if budget is not None and not record else (
                            "invalid_output" if record.get("state") == "received" else "unknown"))
                    mark_orphan(slot, call, status)
        return self.status()

    def execution_status(self):
        state, _ = self.file.read()
        observations = {}
        attempts = [*state["calls"].items(), *(("retired:" + key, call) for key, call in state.get("retired_calls", {}).items())]
        for slot, call in attempts:
            if call["backend"] != "pi-subagents":
                continue
            item = {"call_id": call["id"], "controller_status": call["status"], "reference": call.get("execution_ref")}
            try:
                receipt = read_receipt(self.directory / "agents" / call["actor"], call["id"])
                response = (receipt or {}).get("response", {})
                item.update(receipt_phase=(receipt or {}).get("state", "missing"),
                            plugin_status=response.get("status", "unknown"), run_id=response.get("runId"),
                            launch_contract=response.get("launchContractDigest"),
                            parent_session=(receipt or {}).get("parent_session_id"))
            except ValueError:
                item.update(receipt_phase="invalid", plugin_status="unknown")
            observations[slot] = item
        return observations

    def export(self, destination):
        state, version = self.file.read()
        for group in ("calls", "retired_calls"):
            state[group] = {slot: self.call_details(call) for slot, call in state.get(group, {}).items()}
        posts = [{**entry, "post": self.client.request("GET", f"/posts/{entry['id']}")} for entry in state["posts"]]
        attempts = [*state["calls"].values(), *state.get("retired_calls", {}).values()]
        kind = "not_run" if not attempts else (
            "mechanical_fixture" if all(c["backend"] == "simulated" for c in attempts) else (
                "real_model_case" if any(c["backend"] in REAL_BACKENDS and c["status"] == "completed" for c in attempts)
                else "incomplete_execution_case"))
        snapshot = {"state": state, "file_version": version, "posts": posts,
                    "execution_observations": self.execution_status(),
                    "sources": [self.read_source(source_id) for source_id in state["sources"]],
                    "kind": kind}
        snapshot["source_assessment_summary"] = assessments.summary(state)
        sources = {source["id"]: source for source in snapshot["sources"]}
        snapshot["source_audits"] = []
        for item in posts:
            if item["phase"] == "reflect":
                content = json.loads(item["post"]["content"])
                source = sources.get((content.get("evidence") or {}).get("source_id"))
                snapshot["source_audits"].append(assessments.packet(state, item["id"], content, source))
        snapshot["source_assessment_bases"] = {}
        for entry in state.get("source_assessments", {}).values():
            fingerprint = entry["basis_sha256"]
            if fingerprint not in snapshot["source_assessment_bases"]:
                archived = json.loads(self.client.request("GET",
                    f"/workspaces/{self.file.workspace}/files/{entry['basis_path']}")["content"])
                if archived.get("basis_sha256") != fingerprint or assessments.digest(archived["basis"]) != fingerprint:
                    raise RuntimeError("Archived audit basis differs from its fingerprint")
                snapshot["source_assessment_bases"][fingerprint] = archived
        atomic_local(destination / "export.json", snapshot)
        lines = [f"# {state['name']} 阶段简报", "", f"模式：{state['mode']}；状态：{state['status']}；轮数：{len(state['rounds'])}",
                 "", f"记录性质：{snapshot['kind']}；模拟运行不验证探索质量。", "", "## 问题版本", ""]
        lines.extend(f"- v{q['number']}（{q['author']}）：{q['text']}" for q in state["question_revisions"])
        lines.extend(["", "## 当前方向", ""])
        lines.extend(f"- {d['title']}（{d['status']}，{', '.join(d['members']) or '无当前成员'}）" for d in state["directions"].values())
        lines.extend(["", "## 发现与未决问题", ""])
        for item in posts:
            content = json.loads(item["post"]["content"])
            if item["phase"] == "reflect":
                evidence = content["evidence"]
                citation = "无外部材料；此步不能验证事实"
                if evidence:
                    location = (f"原始文件第 {evidence['original_line']} 行" if 'original_line' in evidence
                                else f"材料片段第 {evidence.get('line','?')} 行")
                    citation = f"{evidence['source_id']}，{location}：{evidence['quote']}"
                lines.extend([f"- {content['finding']}", f"  - 出处：{citation}；帖子：{item['id']}",
                              f"  - 未决：{content['unresolved']}；影响链接：{content['influenced_by']}",
                              f"  - 类型（参与者自报）：{content.get('claim_kind','inference')}；认识状态：{state.get('knowledge',{}).get(item['id'],{}).get('status','provisional')}；重开条件：{content.get('revisit_when','问题、资料或假设变化时复查')}"])
        lines.extend(["", "## 质疑与适用边界", ""])
        for item in posts:
            if item["phase"] == "challenge":
                content = json.loads(item["post"]["content"])
                lines.append(f"- 对 {content['target_post']} 的 {content['author_type']} 质疑：{content['reason']}；来源：{content['source_id']}")
        for finding in state.get("knowledge", {}).values():
            for challenge in finding.get("challenges", []):
                if challenge.get("author_type") == "peer":
                    lines.append(f"- {challenge['actor']} 对 {finding['post_id']} 的同伴质疑：{challenge['reason']}；记录：{challenge['post_id']}；所见：{challenge['basis_view']}")
        lines.extend(["", "## 旧认识复查", ""])
        for review in state.get("reviews", []):
            lines.extend([f"- {review['actor']} 对 {review['target_post']} → {review['response_post']}：{review['decision']}（{review['status']}）",
                          f"  - 理由：{review['reason']}；实际回应的质疑：{review['addressed_challenges']}",
                          f"  - 取回的原笔记：{review['recalled_note_ids']}；实际材料：{(review.get('evidence') or {}).get('source_id', '无外部材料')}"])
        unanswered = sum(not c.get("author_responses") for k in state.get("knowledge", {}).values() for c in k.get("challenges", []))
        lines.append(f"尚无当前版本作者回应的质疑：{unanswered}。有回应也不等于异议已解决；修订后的主张仍待核查，过期复查不改变旧认识状态。")
        counts = snapshot["source_assessment_summary"]
        lines.extend(["", "## 来源支持核查", "",
                      f"已核查发现：{counts['assessed_finding_count']}/{counts['finding_count']}；其中全部材料型发现：{counts['material_based_finding_count']}；核查记录：{counts['assessment_count']}。",
                      "分母包含全部历史发现；同一发现可有重复核查和不同判断，不计算正确率。核查署名由提交者提供，未经身份认证。", ""])
        for assessment in state.get("source_assessments", {}).values():
            lines.extend([f"- {assessment['target_post']}；{assessment['reviewer']}：{assessment['verdict']}（问题 v{assessment['question_revision']}）",
                          f"  - 范围：{assessment['scope']}；理由：{assessment['reason']}；记录：{assessment['id']}",
                          f"  - 核查依据：{assessment['basis_sha256']}；判断不自动验证主张或消除异议。"])
        lines.extend(["", "## 运行与变更", "", f"已完成调用：{sum(c['status']=='completed' for c in state['calls'].values())}/{len(state['calls'])}",
                      f"已应用方向/成员变更：{len(state['direction_history'])}；待确认：{sum(c['status']=='pending' for c in state['changes'].values())}；过期未生效：{sum(c['status']=='stale' for c in state['changes'].values())}",
                      f"保留的历史失败尝试：{len(state.get('retired_calls',{}))}；重试仍计入调用限额与费用预留。",
                      "共享记录和同伴赞同不构成独立外部证据；本简报为确定性导出，未追加模型调用。"])
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        (destination / "brief.md").write_text("\n".join(lines) + "\n")
        return snapshot
