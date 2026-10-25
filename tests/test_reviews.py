"""Real collaboration API checks; model outputs are explicit mechanical fixtures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import uuid

import requests

from explore.engine import Project
from explore.memory import Memory
from explore.models import SimulatedBackend
from explore.store import Client


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()

    def project(self, mode="single", sources=None):
        return Project.create(self.client, "r_" + uuid.uuid4().hex[:12], mode=mode,
            scenario="feedback", question="How can changing questions preserve useful disagreement?",
            sources=sources, question_author="evaluation_script")

    def first_finding(self, project):
        project.advance(SimulatedBackend("feedback"))
        state, _ = project.file.read()
        return next(iter(state["knowledge"]))

    def test_new_material_changes_action_and_preserves_original_and_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / "initial.md"
            old.write_text("Synthetic fixture: preserve competing explanations.\n")
            new = Path(directory) / "counterexample.md"
            new.write_text("Synthetic counterexample: changed needs can invalidate a former recommendation.\n")
            project = self.project(mode="collaborative", sources=[("initial", "initial fixture", str(old), 1, 1)])
            target = self.first_finding(project)
            state, _ = project.file.read()
            original = self.client.request("GET", "/posts/" + target)["content"]
            actor = state["knowledge"][target]["actor"]
            old_call = next(c for c in state["calls"].values() if c.get("post_id") == target)
            memory = Memory(project.directory / "agents" / actor / "memory")
            note_path = next(n["file"] for n in memory.index()["notes"] if n["id"] == old_call["id"])
            original_note = (memory.directory / note_path).read_bytes()
            for i in range(15):
                memory.remember(f"newer-unrelated-{i}", summary="Unrelated recent administrative note",
                                question_revision=1, unresolved="No relevant question")
            source_id = project.add_source(str(new))
            challenge_id = project.challenge(target, "Recheck the earlier finding under changed needs", source_id,
                                             author_type="evaluation_script")
            project.control("steer", "Which earlier advice still applies after needs change?", author="evaluation_script")
            project.advance(SimulatedBackend("feedback"))
            after, _ = project.file.read()
            self.assertEqual(len(after["reviews"]), 1)
            review = after["reviews"][0]
            self.assertEqual(review["status"], "recorded")
            self.assertEqual(review["addressed_challenges"], [challenge_id])
            self.assertIn(old_call["id"], review["recalled_note_ids"])
            self.assertEqual(review["evidence"]["source_id"], source_id)
            self.assertEqual(review["evidence"]["source_sha256"], project.read_source(source_id)["sha256"])
            self.assertEqual(after["knowledge"][target]["status"], "superseded")
            replacement = after["knowledge"][review["response_post"]]
            self.assertEqual(replacement["revises"], target)
            self.assertFalse(replacement["claim_truth_verified"])
            self.assertEqual(replacement["status"], "provisional")
            self.assertEqual(self.client.request("GET", "/posts/" + target)["content"], original)
            self.assertEqual((memory.directory / note_path).read_bytes(), original_note)
            request = next(c["request"] for c in after["calls"].values() if c.get("post_id") == review["response_post"])
            self.assertEqual(request["prior_action"]["source_id"], source_id)
            self.assertEqual(request["review_context"]["original"], json.loads(original))
            self.assertTrue(any(n["id"] == old_call["id"] and n["current_finding"]["status"] == "contested"
                                for n in request["private_memory"]["recalled_notes"]))
            project.export(project.directory / "exports")
            self.assertIn("旧认识复查", (project.directory / "exports/brief.md").read_text())

    def test_retain_undecided_and_withdraw_never_turn_response_into_truth(self):
        for decision, status in (("retain", "contested"), ("undecided", "contested"), ("withdraw", "withdrawn")):
            with self.subTest(decision=decision):
                project = self.project()
                target = self.first_finding(project)
                project.challenge(target, "The reasoning has an untested assumption")
                class Responding(SimulatedBackend):
                    def call(self, *args, **kwargs):
                        output = super().call(*args, **kwargs)
                        if output.get("review") and "decision" in output["review"]:
                            output["review"]["decision"] = decision
                        return output
                project.advance(Responding("feedback"))
                after, _ = project.file.read()
                finding = after["knowledge"][target]
                self.assertEqual(finding["status"], status)
                self.assertFalse(finding["claim_truth_verified"])
                self.assertEqual(len(finding["challenges"]), 1)
                self.assertEqual(len(finding["challenges"][0]["author_responses"]), 1)
                self.assertNotIn("resolved", finding["challenges"][0])
                self.assertIsNone(after["reviews"][0]["evidence"])
                if decision == "withdraw":
                    project.challenge(target, "Another objection to the historical finding")
                    self.assertEqual(project.file.read()[0]["knowledge"][target]["status"], "withdrawn")

    def test_new_objection_during_review_makes_old_response_stale(self):
        project = self.project()
        target = self.first_finding(project)
        first = project.challenge(target, "First objection")
        second = []
        class ConcurrentObjection(SimulatedBackend):
            def call(self, call_id, messages, *args, **kwargs):
                request = messages[-1]
                if request["phase"] == "reflect":
                    second.append(project.challenge(target, "New objection after the review snapshot"))
                return super().call(call_id, messages, *args, **kwargs)
        project.advance(ConcurrentObjection("feedback"))
        state, _ = project.file.read()
        self.assertEqual(state["reviews"][0]["status"], "stale")
        self.assertEqual(state["reviews"][0]["addressed_challenges"], [first])
        self.assertNotIn(second[0], state["reviews"][0]["addressed_challenges"])
        self.assertEqual(state["knowledge"][target]["status"], "contested")
        self.assertNotIn("superseded_by", state["knowledge"][target])
        self.assertTrue(all(not c.get("author_responses") for c in state["knowledge"][target]["challenges"]))

    def test_independent_mode_only_supplies_own_findings_and_objections(self):
        project = self.project(mode="independent")
        target = self.first_finding(project)
        project.challenge(target, "This agent should revisit its own conclusion")
        project.advance(SimulatedBackend("feedback"))
        state, _ = project.file.read()
        self.assertEqual(len(state["reviews"]), 1)
        for call in state["calls"].values():
            request = call["request"]
            self.assertEqual(request["peers"], [])
            self.assertEqual(call["output"].get("influenced_by", []), [])
            self.assertTrue(all(c["actor"] == call["actor"] for c in request.get("review_candidates", [])))
            if request.get("review_context"):
                self.assertEqual(request["review_context"]["target"]["actor"], call["actor"])

    def test_lost_response_publication_reconciles_without_duplicate_review_or_calls(self):
        project = self.project()
        target = self.first_finding(project)
        project.challenge(target, "Keep the original and the response")
        original_publish = project.client.publish
        lost = []
        class Counting(SimulatedBackend):
            calls = 0
            def call(self, *args, **kwargs):
                self.calls += 1
                return super().call(*args, **kwargs)
        backend = Counting("feedback")
        def publish(*args, **kwargs):
            post_id = original_publish(*args, **kwargs)
            if args[3] == "reflect" and args[4].get("review") and not lost:
                lost.append(post_id)
                raise requests.ConnectionError("The service committed but the response was lost")
            return post_id
        project.client.publish = publish
        with self.assertRaises(RuntimeError):
            project.advance(backend)
        self.assertEqual(project.file.read()[0]["reviews"], [])
        project.client.publish = original_publish
        calls_before = backend.calls
        project.reconcile()
        project.reconcile()
        project.control("resume")
        project.advance(backend)
        state, _ = project.file.read()
        self.assertEqual(backend.calls, calls_before)
        self.assertEqual(len(state["reviews"]), 1)
        self.assertEqual(state["reviews"][0]["response_post"], lost[0])
        self.assertEqual(sum(p["id"] == lost[0] for p in state["posts"]), 1)

    def test_peer_targets_unsolicited_reviews_and_fabricated_objections_are_rejected(self):
        project = self.project(mode="independent")
        target = self.first_finding(project)
        state, _ = project.file.read()
        actor = state["knowledge"][target]["actor"]
        other = next(k["post_id"] for k in state["knowledge"].values() if k["actor"] != actor)
        round_record = {"number": 2, "question_revision": 1}
        request = project.request_for(state, actor, "plan", round_record)
        output = SimulatedBackend().call("fixture", [request], project.directory)
        output["review"] = {"target_post": other, "reason": "Must not read or revise a peer in a control"}
        with self.assertRaises(ValueError):
            project.validate(output, request)
        original = next(c for c in state["calls"].values() if c.get("post_id") == target)
        bad = copy.deepcopy(original["output"])
        bad["review"] = {"target_post": target, "decision": "revise", "reason": "Unselected", "addressed_challenges": []}
        with self.assertRaises(ValueError):
            project.validate(bad, original["request"])
        project.challenge(target, "Actual objection")
        project.advance(SimulatedBackend("feedback"))
        response = next(c for c in project.file.read()[0]["calls"].values() if (c.get("output", {}).get("review") or {}).get("decision"))
        bad = copy.deepcopy(response["output"])
        bad["review"]["addressed_challenges"] = ["not-supplied"]
        with self.assertRaises(ValueError):
            project.validate(bad, response["request"])
        bad = copy.deepcopy(original["output"])
        bad["critique"] = {"target_post": other, "reason": "A control must not acquire peer semantics"}
        with self.assertRaises(ValueError):
            project.validate(bad, original["request"])

    def test_peer_objection_survives_unknown_publication_and_guides_later_author_review(self):
        project = self.project(mode="collaborative")
        self.first_finding(project)
        state, _ = project.file.read()
        target = next(k["post_id"] for k in state["knowledge"].values() if k["actor"].endswith("0"))
        original = self.client.request("GET", "/posts/" + target)["content"]
        class Peer(SimulatedBackend):
            def call(self, call_id, messages, *args, **kwargs):
                output = super().call(call_id, messages, *args, **kwargs)
                request = messages[-1]
                if request["phase"] == "reflect" and request["round"] == 2 and request["actor"].endswith("1"):
                    output["critique"] = {"target_post": target, "reason": "Mechanical peer objection: the earlier inference needs a scope check"}
                return output
        original_publish = project.client.publish
        lost = []
        def publish(*args, **kwargs):
            post_id = original_publish(*args, **kwargs)
            if args[3] == "reflect" and args[4].get("critique") and not lost:
                lost.append(post_id)
                raise requests.ConnectionError("Peer objection committed but publication response lost")
            return post_id
        project.client.publish = publish
        with self.assertRaises(RuntimeError):
            project.advance(Peer("feedback"))
        project.client.publish = original_publish
        project.reconcile()
        project.reconcile()
        project.control("resume")
        project.advance(Peer("feedback"))
        after, _ = project.file.read()
        finding = after["knowledge"][target]
        self.assertEqual(finding["status"], "contested")
        self.assertEqual(len(finding["challenges"]), 1)
        self.assertEqual(finding["challenges"][0]["author_type"], "peer")
        self.assertEqual(finding["challenges"][0]["post_id"], lost[0])
        self.assertEqual(finding["review_version"], 1)
        self.assertEqual(after["reviews"], [])
        project.extend(1)
        project.advance(SimulatedBackend("feedback"))
        final, _ = project.file.read()
        self.assertEqual(len(final["reviews"]), 1)
        self.assertEqual(final["reviews"][0]["target_post"], target)
        self.assertEqual(final["reviews"][0]["addressed_challenges"], lost)
        self.assertTrue(final["reviews"][0]["actor"].endswith("0"))
        self.assertEqual(final["knowledge"][target]["status"], "superseded")
        self.assertEqual(self.client.request("GET", "/posts/" + target)["content"], original)
        self.assertTrue(all(not k["claim_truth_verified"] for k in final["knowledge"].values()))

    def test_review_is_optional_and_visible_candidates_do_not_force_a_revision(self):
        project = self.project()
        self.first_finding(project)
        project.advance(SimulatedBackend("feedback"))
        state, _ = project.file.read()
        self.assertEqual(state["reviews"], [])
        self.assertTrue(all(k["status"] == "provisional" for k in state["knowledge"].values()))


if __name__ == "__main__":
    unittest.main()
