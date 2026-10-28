"""Native Claw controls use existing Project operations; suppliers stay simulated."""
import unittest
from unittest.mock import patch
import uuid

from explore.engine import Project
from explore.models import SimulatedBackend
from explore.native import NativeService
from explore.store import Budget, Client, Conflict, JsonFile


class NativeControlTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.service = NativeService(self.client)

    def project(self, **parameters):
        name = "nc_" + uuid.uuid4().hex[:12]
        self.service.handle({"action": "create", "data": {"name": name, "question": "Which assumptions should remain open?", **parameters}})
        return self.service.project(name)

    def action(self, project, action, **data):
        return self.service.handle({"action": action, "name": project.directory.name, "data": data})

    def test_native_creation_keeps_configured_participants_and_no_unrelated_sources(self):
        project = self.project(participants=4, concurrency=3)
        state = self.service.state(project)
        self.assertEqual(state["participant_count"], 4)
        self.assertEqual(state["max_concurrency"], 3)
        self.assertEqual(state["max_rounds"], 2)
        self.assertEqual(state["sources"], [])
        self.assertEqual(state["calls"], [])
        for values in ({"participants": 9}, {"concurrency": 0}):
            with self.assertRaises(ValueError):
                self.project(**values)

    def test_native_material_and_memory_controls_cannot_change_frozen_evaluation_inputs(self):
        from explore.evaluation import Campaign, freeze_pack
        from scripts.cloud.runtime import ROOT
        campaign = Campaign.prepare(self.client, "nc_eval_" + uuid.uuid4().hex[:12],
            freeze_pack(ROOT / "examples/evaluation/pilot.json", repeats=1, variants=["single"]))
        state, _ = campaign.file.read()
        project, _ = campaign.project(state, state["cases"][0])
        origin = self.project(mode="single")
        origin.advance(SimulatedBackend())
        finding = next(p for p in self.service.state(origin)["posts"] if p["phase"] == "reflect")
        for action, data in (("add-source", {"title": "not frozen", "text": "new semantic input"}),
                             ("extend", {"rounds": 1}),
                             ("link-memory", {"origin_name": origin.directory.name, "post_id": finding["id"],
                                              "conditions": "limited", "reason": "new input"})):
            with self.assertRaises(ValueError):
                self.action(project, action, **data)
        self.assertFalse((project.directory / "materials").exists())
        self.assertEqual(self.service.state(project)["calls"], [])

    def test_material_ingestion_uses_existing_shared_snapshot_and_rejects_truncation(self):
        project = self.project(mode="single")
        text = "第一条原始观察。\r\n第二条保留限制。\n"
        self.client.request("POST", f"/exploreos/project/{project.directory.name}/add-source",
            {"title": "我的原文", "text": text, "path": "/etc/passwd"})
        state = self.service.state(project)
        self.assertEqual(len(state["sources"]), 1)
        self.assertEqual(state["sources"][0]["lines"], ["第一条原始观察。", "第二条保留限制。"])
        self.assertEqual(state["sources"][0]["title"], "我的原文")
        saved = list((project.directory / "materials").glob("user_*.md"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].stat().st_mode & 0o777, 0o600)
        for content in ("\n".join(["line"] * 81), "界" * 4001, "", "abc\x00def"):
            with self.assertRaises(ValueError):
                self.action(project, "add-source", title="bad", text=content)
        self.assertEqual(len(self.service.state(project)["sources"]), 1)
        self.assertEqual(len(list((project.directory / "materials").glob("*"))), 1)
        self.assertEqual(self.service.state(project)["calls"], [])
        escaped = "\\" * 11900
        self.client.request("POST", f"/exploreos/project/{project.directory.name}/add-source",
            {"title": "转义字符片段", "text": escaped})
        self.assertEqual(self.service.state(project)["sources"][-1]["lines"], [escaped])

    def test_finite_extension_does_not_dispatch_and_can_continue_after_limit(self):
        project = self.project(mode="single")
        for _ in range(2):
            project.advance(SimulatedBackend())
        before = self.service.state(project)
        self.action(project, "extend", rounds=1)
        after = self.service.state(project)
        self.assertEqual(after["max_rounds"], 3)
        self.assertEqual(after["calls"], before["calls"])
        for rounds in (0, 21, True):
            with self.assertRaises(ValueError):
                self.action(project, "extend", rounds=rounds)
        self.action(project, "advance", backend="simulated")
        self.assertEqual(len(self.service.state(project)["rounds"]), 3)
        self.assertEqual(self.service.state(project)["record_kind"], "mechanical_fixture")

    def test_known_failure_recovery_requires_current_attempt_and_never_dispatches(self):
        project = self.project(mode="single")
        class Failed(SimulatedBackend):
            def call(self, *args, **kwargs):
                raise TimeoutError("Explicit known mechanical failure")
        with self.assertRaises(RuntimeError):
            project.advance(Failed())
        call = self.service.state(project)["calls"][0]
        self.action(project, "reconcile")
        with self.assertRaises(Conflict):
            self.action(project, "retry", slot=call["slot"], call_id="stale-invocation", reason="corrected")
        self.assertEqual(len(self.service.state(project)["calls"]), 1)
        self.action(project, "retry", slot=call["slot"], call_id=call["id"], reason="The mechanical fixture is corrected")
        state, _ = project.file.read()
        self.assertEqual(state["calls"], {})
        self.assertIn(call["id"], state["retired_calls"])
        view = self.service.state(project)
        self.assertEqual(view["record_kind"], "mechanical_fixture")
        self.assertEqual(view["retired_calls"][0]["id"], call["id"])
        project.advance(SimulatedBackend())
        self.assertEqual(project.file.read()[0]["rounds"][0]["status"], "completed")

    def test_unknown_supplier_recovery_retains_exposure_and_refuses_retry(self):
        project = self.project(mode="single")
        workspace = self.client.request("POST", "/workspaces", {"title": "Native recovery fake supplier ledger"})["id"]
        budget = Budget(JsonFile(self.client, workspace, "budget.json"), limit=1, prior=0)
        class Unknown:
            name = "pi"
            def call(self, call_id, *args, **kwargs):
                budget.admit(call_id, 100, 900)
                raise TimeoutError("Explicit fake supplier: missing receipt")
        with self.assertRaises(RuntimeError):
            project.advance(Unknown())
        call = self.service.state(project)["calls"][0]
        before = budget.file.read()[0]
        with patch("scripts.probe_native.session_budget", return_value=budget):
            self.action(project, "reconcile")
            with self.assertRaises(RuntimeError):
                self.action(project, "retry", slot=call["slot"], call_id=call["id"], reason="Must remain unknown")
        self.assertEqual(budget.file.read()[0], before)
        self.assertGreater(budget.exposure(before), 0)
        self.assertEqual(self.service.state(project)["calls"][0]["status"], "unknown")

    def test_cross_project_reference_rechecks_original_objections(self):
        origin, target = self.project(mode="single"), self.project(mode="single")
        origin.advance(SimulatedBackend())
        finding = next(p for p in self.service.state(origin)["posts"] if p["phase"] == "reflect")
        self.client.request("POST", f"/exploreos/project/{target.directory.name}/link-memory", {
            "origin_name": origin.directory.name, "post_id": finding["id"],
            "conditions": "Only the original limited conditions", "reason": "Check a competing explanation"})
        before = self.service.state(target)
        card = before["linked_memory_observations"][0]
        self.assertFalse(card["claim_truth_verified"])
        self.assertEqual(before["sources"], [])
        self.action(origin, "challenge", post_id=finding["id"], reason="A new objection about scope")
        after = self.service.state(target)["linked_memory_observations"][0]
        self.assertEqual(after["origin_status"], "contested")
        self.assertTrue(after["historical_basis_changed"])
        self.assertTrue(after["applicability_check_required"])


if __name__ == "__main__":
    unittest.main()
