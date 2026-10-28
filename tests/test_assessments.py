"""Offline protocol checks with an explicit in-memory CAS API, never model calls.

The real upstream service remains covered separately by cloud acceptance checks.
"""
import copy
import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import requests

from explore import assessments
from explore.engine import Project
from explore.memory import select_shared_memory
from explore.models import SimulatedBackend
from explore.store import Conflict


class MemoryAPI:
    """Only the file CAS and idempotent post seams used by these offline cases."""
    def __init__(self):
        self.files, self.posts, self.operations = {}, {}, {}
        self.lock = threading.RLock()
        self.lose_response = None

    def request(self, method, path, body=None, *, actor=None, version=None):
        with self.lock:
            if path.startswith("/posts/") and method == "GET":
                return copy.deepcopy(self.posts[path.rsplit("/", 1)[-1]])
            if method == "POST" and path == "/agents/register":
                return {"name": body["name"]}
            if "/files/" not in path:
                raise AssertionError((method, path))
            old = self.files.get(path)
            if method == "GET":
                return copy.deepcopy(old)
            if method != "PUT":
                raise AssertionError((method, path))
            if version != (old["version"] if old else 0):
                raise Conflict("Fixture CAS conflict")
            self.files[path] = {"content": body["content"], "version": version + 1}
            if self.lose_response and self.lose_response(path, body):
                self.lose_response = None
                raise requests.ConnectionError("Fixture: commit succeeded, response lost")
            return copy.deepcopy(self.files[path])

    def publish(self, workshop, actor, operation, kind, content):
        with self.lock:
            encoded = json.dumps(content, ensure_ascii=False)
            if operation in self.operations:
                post = self.posts[self.operations[operation]]
                if post["content"] != encoded:
                    raise Conflict("Fixture publication conflict")
                return post["id"]
            post_id = "post" + str(len(self.posts) + 1)
            self.posts[post_id] = {"id": post_id, "content": encoded}
            self.operations[operation] = post_id
            return post_id


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.client = MemoryAPI()

    def project(self, mode="single", material=True):
        parent = self.directory / ".research"
        parent.mkdir(exist_ok=True)
        directory = parent / (mode + str(len(list(parent.iterdir()))))
        directory.mkdir()
        metadata = {"workspace_id": directory.name, "workshop": "fixture", "run_id": directory.name,
                    "agents": ["agent0", "agent1", "agent2"]}
        (directory / "run_metadata.json").write_text(json.dumps(metadata))
        source = self.directory / "material.md"
        source.write_text("Header outside snapshot\nSynthetic observation supports a limited case.\nOther explanations remain open.\n")
        with patch("explore.engine.launch", return_value=(directory, metadata)):
            project = Project.create(self.client, "fixture", mode=mode,
                question="How should a limited observation change a decision?",
                sources=[("material", "Synthetic fixture", str(source), 2, 3)] if material else [])
        project.advance(SimulatedBackend())
        return project, next(iter(project.file.read()[0]["knowledge"]))

    def assess(self, project, target, *, verdict="partial", reviewer="reviewer1", assessment_id="stable", basis=None):
        basis = basis or project.audit_source(target)["basis_sha256"]
        return project.assess_source(target, basis, verdict, "Only one situation was observed", reviewer,
                                     "The observation does not establish general usefulness", assessment_id)

    def test_audit_uses_original_snapshot_with_line_numbers_and_question_versions(self):
        project, target = self.project()
        before, _ = project.file.read()
        (self.directory / "material.md").write_text("The local file was replaced after the exploration.\n")
        project.control("steer", "Which observations still apply after a changed need?")
        audit = project.audit_source(target)
        self.assertEqual(audit["basis"]["original_question"]["number"], 1)
        self.assertEqual(audit["basis"]["current_question"]["number"], 2)
        self.assertEqual(audit["basis_sha256"], assessments.digest(audit["basis"]))
        rendered = assessments.markdown(audit)
        self.assertIn("2: Synthetic observation", rendered)
        self.assertNotIn("local file was replaced", rendered)
        after, _ = project.file.read()
        self.assertEqual(before["calls"], after["calls"])
        self.assertEqual(before["posts"], after["posts"])
        damaged = copy.deepcopy(audit["basis"]["source"])
        damaged["lines"][0] = "Silent snapshot mutation"
        with self.assertRaises(ValueError):
            assessments.packet(after, target, audit["basis"]["content"], damaged)
        with self.assertRaises(ValueError):
            project.audit_source("a-finding-from-another-project")

    def test_assessment_is_attributed_retains_claim_and_is_recalled_in_the_next_round(self):
        project, target = self.project()
        original = self.client.request("GET", "/posts/" + target)
        self.assess(project, target)
        state, _ = project.file.read()
        finding = state["knowledge"][target]
        self.assertEqual(finding["status"], "provisional")
        self.assertFalse(finding["claim_truth_verified"])
        self.assertEqual(finding["review_version"], 1)
        self.assertEqual(self.client.request("GET", "/posts/" + target), original)
        self.assertFalse(assessments.view(state, finding)[0]["applicability_check_required"])
        project = Project(self.client, project.directory)
        project.advance(SimulatedBackend())
        after, _ = project.file.read()
        plan = next(c["request"] for c in after["calls"].values() if c["round"] == 2 and c["phase"] == "plan")
        card = next(c for c in plan["review_candidates"] if c["post_id"] == target)
        self.assertEqual(card["source_assessments"][0]["verdict"], "partial")
        self.assertEqual(card["source_assessments"][0]["scope"], "The observation does not establish general usefulness")
        self.assertIn(target, [f["post_id"] for f in plan["shared_memory"] if f["source_assessments"]])

    def test_reasoning_only_cannot_be_marked_as_source_supported(self):
        project, target = self.project(material=False)
        for verdict in ("supports", "partial", "unsupported"):
            with self.subTest(verdict=verdict), self.assertRaises(ValueError):
                self.assess(project, target, verdict=verdict)
        self.assess(project, target, verdict="uncertain")
        self.assertEqual(assessments.summary(project.file.read()[0])["material_based_finding_count"], 0)

    def test_concurrent_duplicate_submissions_commit_once_and_conflicting_replay_fails(self):
        project, target = self.project()
        basis = project.audit_source(target)["basis_sha256"]
        with ThreadPoolExecutor(8) as pool:
            results = list(pool.map(lambda _: self.assess(project, target, basis=basis), range(8)))
        self.assertEqual(results, ["stable"] * 8)
        state, _ = project.file.read()
        self.assertEqual(len(state["source_assessments"]), 1)
        self.assertEqual(state["knowledge"][target]["review_version"], 1)
        self.assertEqual(sum(e["kind"] == "source_support_assessed" for e in state["events"]), 1)
        with self.assertRaises(Conflict):
            self.assess(project, target, verdict="supports", basis=basis)
        project.control("steer", "A different focus after the recorded assessment")
        self.assertEqual(self.assess(project, target, basis=basis), "stable")

    def test_lost_archive_and_state_responses_resume_without_duplicate_assessments(self):
        for stage in ("archive", "state"):
            with self.subTest(stage=stage):
                project, target = self.project()
                basis = project.audit_source(target)["basis_sha256"]
                self.client.lose_response = lambda path, body: (
                    "/source-audits/" in path if stage == "archive" else
                    path.endswith("state.json") and bool(json.loads(body["content"]).get("source_assessments")))
                if stage == "archive":
                    with self.assertRaises(requests.ConnectionError):
                        self.assess(project, target, basis=basis)
                else:
                    self.assess(project, target, basis=basis)
                reloaded = Project(self.client, project.directory)
                self.assess(reloaded, target, basis=basis)
                self.assertEqual(len(reloaded.file.read()[0]["source_assessments"]), 1)

    def test_changed_focus_or_feedback_rejects_stale_basis_and_concurrent_commit(self):
        for change in ("focus", "feedback", "during_commit"):
            with self.subTest(change=change):
                project, target = self.project()
                basis = project.audit_source(target)["basis_sha256"]
                if change == "focus":
                    project.control("steer", "Changed focus")
                elif change == "feedback":
                    project.challenge(target, "New objection after the audit")
                else:
                    original = project.file.update
                    def update(operation, mutate):
                        if operation.startswith("source-assessment:"):
                            project.challenge(target, "Feedback arrived during the assessment")
                        return original(operation, mutate)
                    project.file.update = update
                with self.assertRaises(Conflict):
                    self.assess(project, target, basis=basis)
                self.assertFalse(project.file.read()[0].get("source_assessments"))

    def test_assessment_arriving_during_author_review_makes_response_stale(self):
        project, target = self.project()
        project.challenge(target, "The scope is too broad")
        test = self
        class AssessWhileReflecting(SimulatedBackend):
            def call(self, call_id, messages, *args, **kwargs):
                if messages[-1]["phase"] == "reflect":
                    test.assess(project, target)
                return super().call(call_id, messages, *args, **kwargs)
        project.advance(AssessWhileReflecting("feedback"))
        state, _ = project.file.read()
        self.assertEqual(state["reviews"][0]["status"], "stale")
        self.assertEqual(state["knowledge"][target]["status"], "contested")
        self.assertNotIn("superseded_by", state["knowledge"][target])

    def test_disagreement_and_superseding_judgments_keep_explicit_denominators(self):
        project, target = self.project()
        self.assess(project, target)
        self.assess(project, target, verdict="supports", reviewer="reviewer2", assessment_id="second")
        state, _ = project.file.read()
        views = assessments.view(state, state["knowledge"][target])
        self.assertEqual({v["verdict"] for v in views}, {"partial", "supports"})
        self.assess(project, target, verdict="supports", assessment_id="third")
        state, _ = project.file.read()
        self.assertEqual({v["verdict"] for v in assessments.view(state, state["knowledge"][target])}, {"supports"})
        counts = assessments.summary(state)
        self.assertEqual(counts["assessed_finding_count"], 1)
        self.assertEqual(counts["finding_count"], 1)
        self.assertEqual(counts["assessment_count"], 3)
        self.assertEqual(counts["verdict_counts_all_records"]["partial"], 1)

    def test_independent_and_propose_contexts_hide_peer_assessments(self):
        for mode in ("independent", "collaborative"):
            with self.subTest(mode=mode):
                project, target = self.project(mode=mode)
                self.assess(project, target)
                state, _ = project.file.read()
                actor = next(a for a in state["agents"] if a != state["knowledge"][target]["actor"])
                for phase in ("propose", "plan"):
                    request = project.request_for(state, actor, phase, {"number": 2, "question_revision": 1})
                    assessments_seen = [a for f in request["shared_memory"] for a in f["source_assessments"]]
                    if mode == "independent" or phase == "propose":
                        self.assertEqual(assessments_seen, [])
                    else:
                        self.assertEqual(assessments_seen[0]["id"], "stable")
                    self.assertTrue(all(c["actor"] == actor for c in request["review_candidates"]))

    def test_long_judgments_are_bounded_and_minority_concerns_survive(self):
        project, target = self.project()
        for i, verdict in enumerate(("partial", "supports", "supports", "supports", "supports")):
            basis = project.audit_source(target)["basis_sha256"]
            project.assess_source(target, basis, verdict, "理" * 2000, "reviewer" + str(i), "限" * 1000, str(i))
        state, _ = project.file.read()
        views = assessments.view(state, state["knowledge"][target])
        self.assertEqual(len(views), 3)
        self.assertEqual(views[0]["verdict"], "partial")
        self.assertTrue(views[0]["reason_truncated"])
        self.assertEqual(views[0]["omitted_reviewer_count"], 2)
        self.assertLess(len(json.dumps(views, ensure_ascii=False).encode()), 5000)
        self.assertTrue(assessments.needs_attention(state, state["knowledge"][target]))
        audit = project.audit_source(target)
        self.assertEqual(len(audit["assessments"][0]["reason"]), 2000)
        request = project.request_for(state, "agent0", "plan", {"number": 2, "question_revision": 1})
        self.assertLessEqual(len(json.dumps(request, ensure_ascii=False).encode()), 22000)
        large = self.directory / "large.md"
        large.write_text("Synthetic observation requiring a scope check.\n" + "x" * 11800 + "\n")
        source_id = project.add_source(str(large))
        project.challenge(target, "Use the larger material while retaining the attributed concerns", source_id)
        project.advance(SimulatedBackend("feedback"))
        after, _ = project.file.read()
        response = next(c for c in after["calls"].values() if c["phase"] == "reflect" and c["round"] == 2)
        self.assertLessEqual(len(json.dumps(response["request"], ensure_ascii=False).encode()), 22000)
        self.assertEqual(len(response["request"]["review_context"]["target"]["source_assessments"]), 3)

    def test_invalid_judgments_and_changed_snapshot_metadata_are_rejected(self):
        project, target = self.project()
        audit = project.audit_source(target)
        for reason, reviewer, scope in (("", "user", "scope"), ("reason", " ", "scope"),
                                        ("reason", "user", ""), ("x" * 2001, "user", "scope")):
            with self.subTest(reason_length=len(reason)), self.assertRaises(ValueError):
                project.assess_source(target, audit["basis_sha256"], "partial", reason, reviewer, scope)
        damaged = copy.deepcopy(audit["basis"]["source"])
        damaged["start_line"] += 10
        with self.assertRaises(ValueError):
            assessments.packet(project.file.read()[0], target, audit["basis"]["content"], damaged)

    def test_export_contains_offline_material_and_historical_audit_basis(self):
        project, target = self.project()
        self.assess(project, target)
        project.control("steer", "Now inspect a different need")
        before = copy.deepcopy(project.file.read()[0]["calls"])
        exported = project.export(project.directory / "exports")
        self.assertEqual(exported["source_assessment_summary"]["assessed_finding_count"], 1)
        basis = next(iter(exported["source_assessment_bases"].values()))
        self.assertEqual(basis["basis"]["current_question"]["number"], 1)
        self.assertEqual(exported["source_audits"][0]["basis"]["current_question"]["number"], 2)
        self.assertEqual(exported["state"]["calls"], before)
        self.assertIn("来源支持核查", (project.directory / "exports/brief.md").read_text())
        self.assertIn("Synthetic observation", json.dumps(exported))
        self.assertFalse(exported["state"]["knowledge"][target]["claim_truth_verified"])

    def test_cli_writes_readable_audit_and_records_a_judgment(self):
        from explore.__main__ import main
        project, target = self.project()
        with patch("explore.__main__.ROOT", self.directory), patch("explore.__main__.Client", return_value=self.client):
            with patch("sys.argv", ["explore", "source-audit", project.directory.name, target]), contextlib.redirect_stdout(io.StringIO()):
                main()
            markdown = next((project.directory / "audits").glob("*/audit.md"))
            self.assertIn("Synthetic observation", markdown.read_text())
            audit = json.loads(markdown.with_name("audit.json").read_text())
            argv = ["explore", "assess-source", project.directory.name, target,
                    "--basis-sha256", audit["basis_sha256"], "--verdict", "partial",
                    "--scope", "Only the observed case", "--reason", "No comparison was made",
                    "--assessment-id", "cli-record"]
            with patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
                main()
        self.assertEqual(project.status()["source_assessment_summary"]["assessment_count"], 1)


if __name__ == "__main__":
    unittest.main()
