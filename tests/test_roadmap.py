"""Roadmap integration checks on the owned API; no paid models or external jobs."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

import requests

from explore import cross_memory, policy, schedule
from explore.engine import Project
from explore.evaluation import Campaign, DIMENSIONS, freeze_pack, validate_frozen
from explore.memory import Memory
from explore.models import SimulatedBackend
from explore.store import Budget, Client, Conflict, JsonFile
from explore.workbench import Workbench
from scripts.cloud.runtime import ROOT


def name(prefix):
    return prefix + uuid.uuid4().hex[:12]


class FrozenProtocolTests(unittest.TestCase):
    def test_fixed_pack_has_eight_tasks_and_reproducible_materials(self):
        pack = ROOT / "examples/evaluation/pilot.json"
        first = freeze_pack(pack, seed="fixed-seed")
        self.assertEqual(len(first["protocol"]["tasks"]), 8)
        self.assertGreaterEqual(sum(t["kind"] == "open" for t in first["protocol"]["tasks"]), 4)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "pack"
            shutil.copytree(pack.parent, destination)
            self.assertEqual(first, freeze_pack(destination / pack.name, seed="fixed-seed"))
        changed = copy.deepcopy(first)
        changed["protocol"]["rounds"] += 1
        with self.assertRaises(ValueError):
            validate_frozen(changed)
        for repeats in (0, True, 11):
            with self.assertRaises(ValueError):
                freeze_pack(pack, repeats=repeats)
        with self.assertRaises(ValueError):
            freeze_pack(pack, variants=["single", "single"])

    def test_material_escape_and_missing_closed_task_expectations_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "pack"
            shutil.copytree(ROOT / "examples/evaluation", directory)
            path = directory / "pilot.json"
            raw = json.loads(path.read_text())
            raw["tasks"][0]["sources"][0]["path"] = "../outside.md"
            path.write_text(json.dumps(raw))
            with self.assertRaises(ValueError):
                freeze_pack(path)
            raw = json.loads((ROOT / "examples/evaluation/pilot.json").read_text())
            del raw["tasks"][-1]["expected_checks"]
            path.write_text(json.dumps(raw))
            with self.assertRaises(ValueError):
                freeze_pack(path)


class RoadmapIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()

    def project(self, mode="single", **kwargs):
        return Project.create(self.client, name("road_"), mode=mode,
                              question="Which assumptions should an open discussion revisit?", sources=[], **kwargs)

    def test_campaign_restarts_without_repeating_completed_cases_and_retains_blind_reviews(self):
        frozen = freeze_pack(ROOT / "examples/evaluation/pilot.json", repeats=1,
                             variants=["single", "collaborative"], seed="test-seed")
        campaign = Campaign.prepare(self.client, name("eval_"), frozen)
        class Counting(SimulatedBackend):
            count = 0
            def call(self, *args, **kwargs):
                self.count += 1
                return super().call(*args, **kwargs)
        backend = Counting()
        first = campaign.advance(backend, maximum_cases=1)
        self.assertEqual(backend.count, 6)
        campaign = Campaign(self.client, campaign.directory)
        self.assertEqual(campaign.advance(backend, case_id=first[0]), [])
        self.assertEqual(backend.count, 6)
        report = campaign.export(campaign.directory / "test-export")
        self.assertEqual(report["case_status_counts"]["completed"], 1)
        self.assertEqual(report["case_status_counts"]["not_started"], 15)
        packet = json.loads((campaign.directory / "test-export/review-packet.json").read_text())
        view = packet["cases"][0]
        self.assertNotIn("mode", view)
        self.assertNotIn("variant", view)
        self.assertTrue(view["sampled_finding_indexes"])
        self.assertLessEqual(len(view["sampled_finding_indexes"]), 5)
        ratings = {d: "uncertain" for d in DIMENSIONS}
        campaign.review(view["case_id"], "reviewer A", ratings, "The synthetic mechanics do not establish quality", "same-id")
        campaign.review(view["case_id"], "reviewer A", ratings, "The synthetic mechanics do not establish quality", "same-id")
        with self.assertRaises(Conflict):
            campaign.review(view["case_id"], "reviewer B", ratings, "Another judgment", "same-id")
        after = campaign.export(campaign.directory / "test-export")
        self.assertEqual(len(after["human_reviews"]), 1)

    def test_semantic_ablations_preserve_recording_and_reject_disabled_operations(self):
        project = self.project(mode="collaborative", semantic_policy={"peer_critique": False, "direction_changes": False})
        project.advance(SimulatedBackend("merge"))
        state, _ = project.file.read()
        self.assertEqual(len(state["calls"]), 9)
        self.assertEqual(state["direction_history"], [])
        call = next(c for c in state["calls"].values() if c["phase"] == "reflect")
        self.assertFalse(call["request"]["peer_critique_enabled"])
        output = copy.deepcopy(call["output"])
        peer = next(k["post_id"] for k in state["knowledge"].values() if k["actor"] != call["actor"])
        output["critique"] = {"target_post": peer, "reason": "Forbidden in this ablation"}
        with self.assertRaises(ValueError):
            project.validate(output, call["request"])
        memory = Memory(project.directory / "agents" / call["actor"] / "memory")
        memory.remember("failure:fixture", summary="Execution failed; not a rejected hypothesis", question_revision=1,
                        failure={"scope": "fixture", "retry_when": "explicit reconciliation"})
        observed = memory.recall("execution", include_execution_failures=False)
        self.assertNotIn("failure:fixture", [n["id"] for n in observed["recalled_notes"]])
        self.assertEqual(observed["execution_failure_notes_hidden"], 1)
        self.assertIn("failure:fixture", [n["id"] for n in memory.index()["notes"]])
        with self.assertRaises(ValueError):
            policy.normalize({"direction_changes": 1})

    def test_participant_count_uses_upstream_roster_and_preserves_budget_ceiling(self):
        project = self.project(mode="independent", participants=4, max_concurrency=2)
        project.advance(SimulatedBackend())
        state, _ = project.file.read()
        self.assertEqual(len(project.metadata["agents"]), 4)
        self.assertEqual(len(state["agents"]), 4)
        self.assertEqual(len(state["calls"]), 12)
        self.assertEqual(state["max_invocations_per_round"], 16)
        self.assertTrue(all(c["request"]["peers"] == [] for c in state["calls"].values()))
        with self.assertRaises(ValueError):
            self.project(mode="collaborative", participants=8, max_invocations_per_round=12)

    def test_concurrent_create_does_not_overwrite_a_partial_or_completed_project(self):
        project_name = name("create_")
        def create(_):
            try:
                return Project.create(self.client, project_name, question="Concurrent creation fixture", sources=[])
            except RuntimeError:
                return None
        with ThreadPoolExecutor(2) as pool:
            projects = [p for p in pool.map(create, range(2)) if p is not None]
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].file.read()[0]["calls"], {})
        self.assertEqual(len(projects[0].metadata["agents"]), 3)

    def test_cross_project_memory_rechecks_origin_and_never_becomes_external_evidence(self):
        origin, target = self.project(), self.project()
        origin.advance(SimulatedBackend())
        state, _ = origin.file.read()
        finding = next(iter(state["knowledge"]))
        card_id = cross_memory.link(target, origin, finding, "Only under the original assumptions", "Revisit this analogy")
        target_state, _ = target.file.read()
        recalled = cross_memory.recall(self.client, target_state)
        self.assertEqual(recalled[0]["id"], card_id)
        self.assertFalse(recalled[0]["claim_truth_verified"])
        self.assertTrue(recalled[0]["applicability_check_required"])
        origin.challenge(finding, "The source project's scope is disputed")
        new_view = cross_memory.recall(self.client, target_state)[0]
        self.assertEqual(new_view["origin_status"], "contested")
        self.assertTrue(new_view["historical_basis_changed"])
        target.advance(SimulatedBackend())
        after, _ = target.file.read()
        reflect = next(c for c in after["calls"].values() if c["phase"] == "reflect")
        self.assertEqual(reflect["request"]["cross_project_memory"][0]["id"], card_id)
        self.assertIsNone(reflect["output"]["evidence"])
        with self.assertRaises(ValueError):
            cross_memory.link(target, target, finding, "conditions", "reason")

    def test_concurrent_wakeups_dispatch_one_round_and_disable_stops_future_rounds(self):
        project = self.project()
        schedule.configure(project, 60, now=1000)
        schedule.enable(project)
        with ThreadPoolExecutor(5) as pool:
            results = list(pool.map(lambda _: schedule.tick(project, SimulatedBackend(), now=1060), range(5)))
        self.assertEqual(sum(r["action"] == "completed" for r in results), 1)
        state, _ = project.file.read()
        self.assertEqual(len(state["calls"]), 3)
        self.assertEqual(len(state["schedule_notifications"]), 1)
        self.assertEqual(schedule.tick(project, SimulatedBackend(), now=1060)["action"], "idle")
        schedule.disable(project)
        self.assertEqual(schedule.tick(project, SimulatedBackend(), now=2000)["action"], "idle")
        self.assertEqual(len(project.file.read()[0]["rounds"]), 1)

    def test_restart_after_round_completion_does_not_reexecute_and_round_limit_disables(self):
        project = self.project()
        project.advance(SimulatedBackend())
        schedule.configure(project, 60, now=1000)
        schedule.enable(project)
        def crash_fixture(state):
            state["schedule"]["trigger"] = {"id": "recovered-wakeup", "generation": state["schedule"]["generation"],
                "round_target": 1, "process": {"pid": 999999999, "start": "old", "boot": "old"}, "handled": False,
                "findings_before": 0, "changes_before": 0}
        project.file.update("crash-fixture", crash_fixture)
        reloaded = Project(self.client, project.directory)
        self.assertEqual(schedule.tick(reloaded, SimulatedBackend(), now=1060)["action"], "completed")
        self.assertEqual(len(reloaded.file.read()[0]["calls"]), 3)
        self.assertEqual(schedule.tick(reloaded, SimulatedBackend(), now=1120)["round"], 2)
        state, _ = reloaded.file.read()
        self.assertFalse(state["schedule"]["enabled"])
        self.assertEqual(len(state["calls"]), 6)

    def test_disabled_wakeup_between_claim_and_dispatch_cannot_start_models(self):
        project = self.project()
        schedule.configure(project, 60, now=1000)
        schedule.enable(project)
        original = project.advance
        def disable_before_start(backend, **kwargs):
            schedule.disable(project)
            return original(backend, **kwargs)
        with patch.object(project, "advance", side_effect=disable_before_start):
            with self.assertRaises(RuntimeError):
                schedule.tick(project, SimulatedBackend(), now=1060)
        self.assertEqual(project.file.read()[0]["calls"], {})
        paid = self.project()
        schedule.configure(paid, 60, backend="pi", now=1000)
        with self.assertRaises(ValueError):
            schedule.enable(paid)

    def test_sigkill_after_scheduled_round_recovers_without_repeating_execution(self):
        project = self.project()
        schedule.configure(project, 60, now=1000)
        schedule.enable(project)
        code = '''
import os, signal, sys
from explore.engine import Project
from explore.models import SimulatedBackend
from explore.schedule import tick
from explore.store import Client
p=Project(Client(),sys.argv[1])
original=p.advance
def die_after_completion(*args,**kwargs):
    original(*args,**kwargs)
    os.kill(os.getpid(),signal.SIGKILL)
p.advance=die_after_completion
tick(p,SimulatedBackend(),now=1060)
'''
        result = subprocess.run([sys.executable, "-c", code, str(project.directory)], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, -9, result.stderr)
        state, _ = project.file.read()
        self.assertEqual(len(state["calls"]), 3)
        self.assertFalse(state["schedule"]["trigger"]["handled"])
        schedule.tick(Project(self.client, project.directory), SimulatedBackend(), now=1060)
        after, _ = project.file.read()
        self.assertEqual(len(after["calls"]), 3)
        self.assertEqual(len(after["schedule_notifications"]), 1)

    def test_unknown_scheduled_supplier_keeps_reservation_and_never_retries(self):
        project = self.project()
        workspace = self.client.request("POST", "/workspaces", {"title": "Scheduled unknown-result fixture"})["id"]
        budget = Budget(JsonFile(self.client, workspace, "budget.json"), limit=1, prior=0)
        class UnknownSupplier:
            name = "pi"
            def call(self, call_id, *args, **kwargs):
                budget.admit(call_id, 100, 900)
                raise TimeoutError("Explicit fake supplier: result is unknown")
        schedule.configure(project, 60, backend="pi", now=1000)
        schedule.enable(project, budget)
        with self.assertRaises(RuntimeError):
            schedule.tick(project, UnknownSupplier(), budget=budget, now=1060)
        pool, _ = budget.file.read()
        self.assertEqual(len(pool["requests"]), 1)
        self.assertGreater(budget.exposure(pool), 0)
        self.assertEqual(schedule.tick(project, UnknownSupplier(), budget=budget, now=1120)["action"], "idle")
        self.assertEqual(len(budget.file.read()[0]["requests"]), 1)

    def test_manual_completion_of_failed_wakeup_is_observed_before_another_round(self):
        project = self.project()
        schedule.configure(project, 60, now=1000)
        schedule.enable(project)
        class Failure(SimulatedBackend):
            def call(self, *args, **kwargs):
                raise TimeoutError("Known simulated failure, no supplier")
        with self.assertRaises(RuntimeError):
            schedule.tick(project, Failure(), now=1060)
        state, _ = project.file.read()
        slot = next(iter(state["calls"]))
        project.retry(slot, "Explicit recovery of a known simulated failure")
        project.advance(SimulatedBackend())
        self.assertEqual(schedule.tick(project, SimulatedBackend(), now=1060)["round"], 1)
        self.assertEqual(len(project.file.read()[0]["rounds"]), 1)
        self.assertEqual(schedule.tick(project, SimulatedBackend(), now=1120)["round"], 2)
        schedule.disable(project, cancel=True)
        self.assertEqual(project.file.read()[0]["status"], "paused")

    def test_workbench_controls_are_same_origin_and_preserve_question_history(self):
        project = self.project()
        server = Workbench(("127.0.0.1", 0), self.client)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: server.workers.shutdown(wait=True, cancel_futures=True))
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        with requests.Session() as browser:
            browser.trust_env = False
            page = browser.get(base)
            self.assertEqual(page.status_code, 200)
            self.assertIn("ExploreOS", page.text)
            self.assertIn("frame-ancestors 'none'", page.headers["Content-Security-Policy"])
            route = base + f"/api/project/{project.directory.name}/steer"
            self.assertEqual(browser.post(route, json={"question": "new"}).status_code, 403)
            headers = {"X-ExploreOS-Session": server.session, "Origin": "https://another-origin.invalid"}
            self.assertEqual(browser.post(route, json={"question": "new"}, headers=headers).status_code, 403)
            headers["Origin"] = base
            result = browser.post(route, json={"question": "Now consider changed assumptions"}, headers=headers)
            self.assertEqual(result.status_code, 200, result.text)
            state = browser.get(base + f"/api/project/{project.directory.name}/state", headers=headers).json()
            self.assertEqual(len(state["question_revisions"]), 2)
            self.assertNotIn("token", json.dumps(state))
            self.assertEqual(browser.get(base, headers={"Host": "another-origin.invalid"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
