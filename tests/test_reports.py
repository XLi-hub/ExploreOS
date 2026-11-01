"""Stage report provenance, reuse, invalidation and recovery on the owned shared store."""
import copy
from concurrent.futures import ThreadPoolExecutor
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from explore.engine import Project
from explore.models import SimulatedBackend
from explore.native import NativeService
from explore import reports
from explore.store import Client


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.service = NativeService(self.client)
        self.project = Project.create(self.client, "report_" + uuid.uuid4().hex[:12],
                                      mode="single", question="What should change when evidence is incomplete?",
                                      max_invocations_per_round=16)
        self.backend = SimulatedBackend()
        self.project.advance(self.backend)

    def test_report_is_attributed_idempotent_archivable_and_exported(self):
        project = self.project
        before = project.file.read()[0]
        post_id = project.generate_report(self.backend)
        current = project.file.read()[0]
        self.assertEqual(len(current["calls"]), len(before["calls"]) + 1)
        self.assertEqual(current["knowledge"], before["knowledge"])
        with patch.object(self.backend, "call", side_effect=AssertionError("No duplicate model request")):
            self.assertEqual(project.generate_report(self.backend), post_id)
        view = self.service.state(project)
        report = view["brief"]["reports"][0]
        self.assertTrue(report["current"])
        self.assertEqual(set(report["content"]["included_finding_ids"]), set(before["knowledge"]))
        self.assertIn("机械演示报告", view["brief"]["markdown"])
        project.archive_history(threshold=0)
        with patch.object(self.backend, "call", side_effect=AssertionError("Archived reports are reused")):
            self.assertEqual(project.generate_report(self.backend), post_id)
        with tempfile.TemporaryDirectory() as destination:
            from pathlib import Path
            exported = project.export(Path(destination))
            self.assertTrue(any(post["phase"] == "report" for post in exported["posts"]))
            self.assertIn("机械演示报告", (Path(destination) / "brief.md").read_text())

    def test_new_objection_and_changed_question_invalidate_report_without_rewriting_it(self):
        project = self.project
        project.generate_report(self.backend)
        before = self.service.state(project)["brief"]["reports"][0]["content"]
        target = next(iter(project.file.read()[0]["knowledge"]))
        project.challenge(target, "The finding does not cover a contradictory setting")
        self.assertFalse(self.service.state(project)["brief"]["reports"][0]["current"])
        with self.assertRaises(ValueError):
            project.generate_report(self.backend)
        project.control("steer", "What changes for a new user?")
        self.assertFalse(self.service.state(project)["brief"]["reports"][0]["current"])
        self.assertEqual(self.service.state(project)["brief"]["reports"][0]["content"], before)
        with self.assertRaises(ValueError):
            project.generate_report(self.backend)
        project.advance(self.backend)
        project.generate_report(self.backend)
        reports_view = self.service.state(project)["brief"]["reports"]
        self.assertEqual([item["current"] for item in reports_view], [False, True])

    def test_unknown_citations_and_memory_or_action_injection_are_rejected(self):
        project = self.project
        state = project.file.read()[0]
        actor = next(iter(state["agents"]))
        context = reports.request(project, state, actor, state["rounds"][-1])
        output = reports.fixture(context)
        invalid = copy.deepcopy(output)
        invalid["conclusions"][0]["basis"] = ["unseen-post"]
        with self.assertRaises(ValueError):
            reports.validate(invalid, context)
        for key in ("summary", "evidence", "review", "change"):
            invalid = {**copy.deepcopy(output), key: "unrequested"}
            with self.assertRaises(ValueError):
                reports.validate(invalid, context)
        reports.validate(output, context)
        self.assertEqual(output["report_basis_sha256"], reports.fingerprint(state))

    def test_frozen_evaluations_and_backend_mixing_cannot_add_report_calls(self):
        project = self.project
        before = len(project.file.read()[0]["calls"])
        class Other(SimulatedBackend):
            name = "pi"
        with self.assertRaises(ValueError):
            project.generate_report(Other())
        project.file.update("freeze-report-test", lambda state: state.update(evaluation_binding={"fixture": True}))
        with self.assertRaises(ValueError):
            project.generate_report(self.backend)
        self.assertEqual(len(project.file.read()[0]["calls"]), before)

    def test_concurrent_report_and_cancel_keep_completed_round_and_require_explicit_retry(self):
        project = self.project
        entered, release = threading.Event(), threading.Event()
        class Waiting(SimulatedBackend):
            def call(self, *args, **kwargs):
                entered.set()
                release.wait(timeout=10)
                return super().call(*args, **kwargs)
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(project.generate_report, Waiting())
            self.assertTrue(entered.wait(timeout=10))
            with self.assertRaises(RuntimeError):
                project.generate_report(self.backend)
            project.control("cancel")
            release.set()
            with self.assertRaises(TimeoutError):
                future.result(timeout=10)
        state = project.file.read()[0]
        self.assertEqual(state["status"], "paused")
        self.assertEqual(state["rounds"][-1]["status"], "completed")
        self.assertFalse(any(post["phase"] == "report" for post in state["posts"]))
        slot = next(key for key, call in state["calls"].items() if call["phase"] == "report")
        project.retry(slot, "Corrected explicit mechanical retry", expected_call_id=state["calls"][slot]["id"])
        project.generate_report(self.backend)
        self.assertEqual(len(project.file.read()[0]["retired_calls"]), 1)

    def test_committed_publication_with_lost_response_recovers_without_second_call(self):
        project = self.project
        original = self.client.publish
        lost = [False]
        def publish(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[3] == "report" and not lost[0]:
                lost[0] = True
                raise ConnectionError("Fixture lost response after committed report")
            return result
        with patch.object(self.client, "publish", side_effect=publish):
            with self.assertRaises(ConnectionError):
                project.generate_report(self.backend)
        with patch.object(self.backend, "call", side_effect=AssertionError("Recovery cannot call a model")):
            project.reconcile()
            project.control("resume")
            project.generate_report(self.backend)
        self.assertEqual(sum(post["phase"] == "report" for post in project.file.read()[0]["posts"]), 1)


if __name__ == "__main__":
    unittest.main()
