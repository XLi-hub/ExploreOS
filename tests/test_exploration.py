"""Real upstream API mechanical acceptance. Requires the checkout-owned service."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
import unittest
import uuid
import tempfile
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from explore.engine import Project
from explore.models import SimulatedBackend
from explore.store import AdmissionError, Budget, Client, Conflict, JsonFile


def name(prefix):
    return prefix + uuid.uuid4().hex[:10]


class ExplorationTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()

    def test_two_rounds_change_focus_pause_and_resume(self):
        project = Project.create(self.client, name("t_merge_"), scenario="merge")
        project.advance(SimulatedBackend("merge"))
        project.control("pause")
        with self.assertRaises(RuntimeError):
            project.advance(SimulatedBackend("merge"))
        project.control("steer", "Focus on evidence validity and long-term user redirection")
        reloaded = Project(self.client, project.directory)
        reloaded.control("resume")
        reloaded.advance(SimulatedBackend("merge"))
        state, _ = reloaded.file.read()
        self.assertEqual([r["question_revision"] for r in state["rounds"]], [1, 2])
        self.assertEqual(len(state["direction_history"]), 1)
        self.assertGreaterEqual(len(state["calls"]), 18)
        self.assertLessEqual(len(state["calls"]), 24)
        self.assertTrue(all(c["status"] == "completed" for c in state["calls"].values()))
        self.assertTrue(all(c["question_revision"] == c["request"]["question_revision"] for c in state["calls"].values()))
        self.assertEqual(len(state["posts"]), len(state["calls"]))
        export = reloaded.export(project.directory / "exports")
        self.assertEqual(export["kind"], "mechanical_fixture")

    def test_no_communication_mode_hides_all_peer_semantics(self):
        project = Project.create(self.client, name("t_indep_"), mode="independent")
        project.advance(SimulatedBackend())
        state, _ = project.file.read()
        self.assertEqual(len(state["calls"]), 9)
        for call in state["calls"].values():
            self.assertEqual(call["request"]["peers"], [])
            self.assertEqual(call["request"].get("previously_read_peer_ids", []), [])
            self.assertEqual(call["request"]["pending_changes"], [])
            self.assertTrue(all(call["actor"] in d["members"] for d in call["request"]["directions"]))

    def test_different_fixture_scenarios_have_different_reorganization(self):
        project = Project.create(self.client, name("t_split_"), scenario="split")
        for _ in range(2):
            project.advance(SimulatedBackend("split"))
        state, _ = project.file.read()
        self.assertEqual(len(state["direction_history"]), 0)
        self.assertEqual(len(state["directions"]), 3)

    def test_concurrent_publication_is_idempotent_and_rejects_new_content(self):
        project = Project.create(self.client, name("t_post_"))
        actor = next(iter(project.file.read()[0]["agents"]))
        def publish(_):
            return self.client.publish(project.metadata["workshop"], actor, "test:one", "finding", {"content": "one"})
        with ThreadPoolExecutor(8) as pool:
            posts = list(pool.map(publish, range(8)))
        self.assertEqual(len(set(posts)), 1)
        with self.assertRaises(Conflict):
            self.client.publish(project.metadata["workshop"], actor, "test:one", "finding", {"content": "different"})

    def test_concurrent_budget_and_duplicate_supplier_requests(self):
        workspace = self.client.request("POST", "/workspaces", {"title": "budget test"})["id"]
        budget = Budget(JsonFile(self.client, workspace, "budget.json"), limit=0.25, prior=0, max_calls=10)
        def admit(index):
            try:
                budget.admit("call" + str(index), 500, 900)
                return True
            except AdmissionError:
                return False
        with ThreadPoolExecutor(8) as pool:
            accepted = sum(pool.map(admit, range(20)))
        state, _ = budget.file.read()
        self.assertLess(accepted, 20)
        self.assertGreater(accepted, 0)
        self.assertLessEqual(Budget.exposure(state), 0.25)
        key = next(iter(state["requests"]))
        with self.assertRaises(AdmissionError):
            budget.admit(key, 500, 900)

    def test_one_participant_fails_without_losing_successful_peer_results(self):
        class Failing(SimulatedBackend):
            def call(self, call_id, messages, *args, **kwargs):
                if messages[-1]["actor"].endswith("1"):
                    raise TimeoutError("fixture timeout")
                return super().call(call_id, messages, *args, **kwargs)
        project = Project.create(self.client, name("t_fail_"))
        with self.assertRaises(RuntimeError):
            project.advance(Failing())
        state, _ = project.file.read()
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(len(state["posts"]), 2)
        self.assertEqual(sum(c["status"] == "completed" for c in state["calls"].values()), 2)
        self.assertEqual(sum(c["status"] == "failed" for c in state["calls"].values()), 1)
        slot = next(key for key, call in state["calls"].items() if call["status"] == "failed")
        original = state["calls"][slot]["id"]
        project.retry(slot, "Fixture failure was terminal; explicitly authorize a new attempt")
        project.advance(SimulatedBackend())
        after, _ = project.file.read()
        self.assertEqual(after["calls"][slot]["status"], "completed")
        self.assertNotEqual(after["calls"][slot]["id"], original)
        self.assertIn(original, after["retired_calls"])
        self.assertEqual(len(after["posts"]), 9)

    def test_unknown_supplier_attempt_keeps_budget_and_cannot_be_retried(self):
        project = Project.create(self.client, name("t_unknown_"), mode="single")
        workspace = self.client.request("POST", "/workspaces", {"title": "unknown attempt budget"})["id"]
        budget = Budget(JsonFile(self.client, workspace, "budget.json"), limit=1, prior=0)
        class UnknownSupplier:
            name = "claude"
            def call(self, call_id, *args, **kwargs):
                budget.admit(call_id, 100, 900)
                raise TimeoutError("No supplier result was observed")
        with self.assertRaises(RuntimeError):
            project.advance(UnknownSupplier())
        state, _ = project.file.read()
        slot = next(iter(state["calls"]))
        project.file.update("simulate-controller-exit", lambda s: s["calls"][slot].update(
            controller={"pid": 999999999, "start": "old", "boot": "old"}))
        with self.assertRaises(RuntimeError):
            project.retry(slot, "Must not duplicate an unknown supplier request", budget)
        pool, _ = budget.file.read()
        self.assertGreater(budget.exposure(pool), 0)
        self.assertEqual(len(pool["requests"]), 1)

    def test_sigkill_controller_reconciles_unsent_and_unknown_attempts(self):
        for sent in (False, True):
            with self.subTest(supplier_admitted=sent):
                project = Project.create(self.client, name("t_crash_"), mode="single")
                workspace = self.client.request("POST", "/workspaces", {"title": "controller crash budget"})["id"]
                budget = Budget(JsonFile(self.client, workspace, "budget.json"), limit=1, prior=0)
                code = '''
import os, signal, sys
from pathlib import Path
from explore.engine import Project
from explore.store import Budget, Client, JsonFile
client = Client()
pool = Budget(JsonFile(client, sys.argv[2], "budget.json"), limit=1, prior=0)
class Crashed:
    name = "claude"
    def call(self, call_id, *args, **kwargs):
        if sys.argv[3] == "sent":
            pool.admit(call_id, 100, 900)
        os.kill(os.getpid(), signal.SIGKILL)
Project(client, Path(sys.argv[1])).advance(Crashed())
'''
                result = subprocess.run([sys.executable, "-c", code, str(project.directory),
                                         workspace, "sent" if sent else "unsent"], timeout=15,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, -9, result.stderr)
                project.reconcile(budget)
                state, _ = project.file.read()
                slot, call = next(iter(state["calls"].items()))
                self.assertEqual(call["status"], "unknown" if sent else "failed_before_dispatch")
                if sent:
                    with self.assertRaises(RuntimeError):
                        project.retry(slot, "Unknown supplier result cannot be retried", budget)
                    self.assertGreater(budget.exposure(budget.file.read()[0]), 0)
                else:
                    project.retry(slot, "Controller died before supplier admission", budget)
                    self.assertNotIn(slot, project.file.read()[0]["calls"])

    def test_concurrent_claims_dispatch_at_most_once(self):
        project = Project.create(self.client, name("t_claim_"))
        actor = next(iter(project.file.read()[0]["agents"]))
        class Counting(SimulatedBackend):
            def __init__(self):
                self.calls = 0
                self.lock = threading.Lock()
                super().__init__()
            def call(self, *args, **kwargs):
                with self.lock:
                    self.calls += 1
                time.sleep(0.1)
                return super().call(*args, **kwargs)
        backend = Counting()
        def perform(_):
            try:
                project.perform(actor, "propose", {"number": 1, "question_revision": 1}, backend, uuid.uuid4().hex)
            except RuntimeError:
                pass
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(perform, range(2)))
        self.assertEqual(backend.calls, 1)

    def test_open_non_scientific_question_and_explicit_material(self):
        question = "个人知识系统怎样支持经常改变的问题？"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "personal_notes.md"
            source.write_text("旧结论的适用范围需要随关注点变化重新核查。\n保留未决问题比覆盖旧笔记更有用。\n")
            project = Project.create(self.client, name("t_open_"), question=question,
                sources=[("personal", "个人知识系统笔记", str(source), 1, 2)])
            project.advance(SimulatedBackend())
            state, _ = project.file.read()
            self.assertEqual(state["question_revisions"][0]["text"], question)
            self.assertEqual(state["question_revisions"][0]["author"], "user")
            self.assertFalse((project.directory / "champion").exists())
            self.assertFalse((project.directory / "repo").exists())
            self.assertEqual(len(state["knowledge"]), 3)
            self.assertTrue(all(not k["claim_truth_verified"] for k in state["knowledge"].values()))
            first = project.read_source("personal")
            source.write_text("新增材料不应静默覆盖前轮来源。\n")
            new_id = project.add_source(str(source))
            self.assertEqual(project.read_source("personal"), first)
            self.assertNotEqual(project.read_source(new_id)["sha256"], first["sha256"])
            target = next(p["id"] for p in state["posts"] if p["phase"] == "reflect")
            project.challenge(target, "The cited material does not yet establish general usefulness", new_id)
            updated, _ = project.file.read()
            self.assertEqual(updated["knowledge"][target]["status"], "contested")
            self.assertFalse(updated["knowledge"][target]["claim_truth_verified"])
            self.assertEqual(self.client.request("GET", f"/posts/{target}")["id"], target)

    def test_pause_drains_current_calls_and_resume_does_not_repeat_them(self):
        project = Project.create(self.client, name("t_pause_"))
        entered = threading.Event()
        release = threading.Event()
        class Blocking(SimulatedBackend):
            def __init__(self):
                self.count = 0
                self.lock = threading.Lock()
                super().__init__()
            def call(self, *args, **kwargs):
                with self.lock:
                    self.count += 1
                    if self.count == 2:
                        entered.set()
                if not release.wait(timeout=10):
                    raise TimeoutError("fixture release missing")
                return super().call(*args, **kwargs)
        backend = Blocking()
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(project.advance, backend)
            self.assertTrue(entered.wait(timeout=10))
            project.control("pause")
            release.set()
            future.result(timeout=10)
        state, _ = project.file.read()
        self.assertEqual(state["status"], "paused")
        self.assertEqual(backend.count, 2)
        project.control("resume")
        project.advance(backend)
        self.assertEqual(backend.count, 9)

    def test_cancel_marks_round_terminal_and_never_reuses_attempts(self):
        project = Project.create(self.client, name("t_cancel_"))
        entered = threading.Event()
        count = [0]
        lock = threading.Lock()
        class Cancellable(SimulatedBackend):
            def call(self, call_id, messages, directory, cancelled=lambda: False, **kwargs):
                with lock:
                    count[0] += 1
                    if count[0] == 2:
                        entered.set()
                deadline = time.monotonic() + 10
                while not cancelled() and time.monotonic() < deadline:
                    time.sleep(0.01)
                raise TimeoutError("fixture cancellation")
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(project.advance, Cancellable())
            self.assertTrue(entered.wait(timeout=10))
            project.control("cancel")
            future.result(timeout=10)
        state, _ = project.file.read()
        self.assertEqual(state["status"], "paused")
        self.assertEqual(state["rounds"][0]["status"], "cancelled")
        self.assertEqual(count[0], 2)
        original_ids = {c["id"] for c in state["calls"].values()}
        project.control("resume")
        project.advance(SimulatedBackend())
        current, _ = project.file.read()
        self.assertEqual(current["rounds"][1]["status"], "completed")
        later_ids = {c["id"] for c in current["calls"].values() if c["round"] == 2}
        self.assertFalse(original_ids & later_ids)

    def test_open_reasoning_without_materials_does_not_invent_evidence(self):
        project = Project.create(self.client, name("t_ideas_"), question="一个创意讨论怎样保留有用分歧，而不急着得出唯一答案？")
        project.advance(SimulatedBackend())
        state, _ = project.file.read()
        self.assertEqual(state["sources"], {})
        self.assertTrue(state["knowledge"])
        self.assertTrue(all(not item["source_quote_verified"] and not item["claim_truth_verified"] for item in state["knowledge"].values()))
        self.assertTrue(all(call["output"]["evidence"] is None for call in state["calls"].values() if call["phase"] == "reflect"))

    def test_unknown_challenge_publication_reconciles_without_duplicate_feedback(self):
        project = Project.create(self.client, name("t_feedback_"))
        project.advance(SimulatedBackend())
        state, _ = project.file.read()
        target = next(item["id"] for item in state["posts"] if item["phase"] == "reflect")
        publish = self.client.publish
        created = []
        def committed_without_response(*args, **kwargs):
            created.append(publish(*args, **kwargs))
            raise TimeoutError("The server committed but the response was lost")
        with patch.object(self.client, "publish", committed_without_response):
            with self.assertRaises(TimeoutError):
                project.challenge(target, "Keep the original claim and inspect its source scope")
        project.reconcile()
        project.reconcile()
        after, _ = project.file.read()
        feedback = [post for post in after["posts"] if post["phase"] == "challenge"]
        self.assertEqual([post["id"] for post in feedback], created)
        self.assertEqual(after["pending_challenges"], {})
        self.assertEqual(after["knowledge"][target]["status"], "contested")


if __name__ == "__main__":
    unittest.main()
