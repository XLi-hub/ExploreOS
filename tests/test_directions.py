"""Adaptive direction mechanics on the owned service; no real-model calls."""
import copy
import unittest
import uuid

import requests

from explore.engine import Project
from explore.models import SimulatedBackend
from explore.store import Client


class DirectionTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()

    def project(self, *, material=False, **kwargs):
        return Project.create(self.client, "fork_" + uuid.uuid4().hex[:12],
            **({} if material else {"question": "Which alternative route should remain open?", "sources": []}), **kwargs)

    def test_single_agent_forks_a_new_route_then_reopens_its_own_paused_route(self):
        project = self.project(mode="single")
        class ForkAndReopen(SimulatedBackend):
            def call(self, call_id, messages, *args, **kwargs):
                request = messages[-1]
                output = super().call(call_id, messages, *args, **kwargs)
                if request["phase"] == "reflect":
                    if request["round"] == 1:
                        output["change"] = {"kind": "fork", "target": None, "title": "A new tentative explanation",
                                            "reason": "A reasoning-only alternative, not a verified correction", "influenced_by": []}
                    else:
                        target = next(d["id"] for d in request["directions"] if d["status"] == "paused")
                        output["change"] = {"kind": "reopen", "target": target,
                                            "reason": "Changed focus makes the earlier route worth another look", "influenced_by": []}
                return output
        backend = ForkAndReopen()
        project.advance(backend)
        state, _ = project.file.read()
        actor = next(iter(state["agents"]))
        original = state["directions"]["direction:" + actor]
        self.assertEqual(original["status"], "paused")
        new = next(d for d in state["directions"].values() if d["status"] == "active")
        self.assertEqual(new["title"], "A new tentative explanation")
        self.assertEqual(new["forked_from"], original["id"])
        self.assertEqual(new["basis_kind"], "reasoning_only")
        self.assertFalse(new["claim_truth_verified"])
        self.assertEqual(state["direction_history"][0]["before"][0]["members"], [actor])
        project.control("steer", "Now revisit the earlier explanation under changed assumptions")
        project.advance(backend)
        after, _ = project.file.read()
        self.assertEqual(after["agents"][actor]["direction"], original["id"])
        self.assertEqual(after["directions"][original["id"]]["title"], original["title"])
        self.assertEqual(after["directions"][new["id"]]["status"], "paused")
        self.assertEqual(len(after["direction_history"]), 2)
        self.assertEqual(len(after["question_revisions"]), 2)
        self.assertTrue(all(not k["claim_truth_verified"] for k in after["knowledge"].values()))

    def test_group_fork_requires_consent_and_preserves_a_stale_alternative(self):
        for stale in (False, True):
            with self.subTest(stale=stale):
                project = self.project(material=True, scenario="merge")
                project.advance(SimulatedBackend("merge"))
                first, _ = project.file.read()
                origin = next(d for d in first["directions"].values() if len(d["members"]) > 1)
                forker = origin["members"][0]
                class DeclinedFork(SimulatedBackend):
                    def call(self, call_id, messages, *args, **kwargs):
                        request = messages[-1]
                        output = super().call(call_id, messages, *args, **kwargs)
                        if request["phase"] == "reflect" and request["actor"] == forker:
                            output["change"] = {"kind": "fork", "target": None, "title": "A material-led alternative",
                                                "reason": "Check another scope suggested by the read material",
                                                "influenced_by": output["influenced_by"]}
                        if request["phase"] == "consent":
                            output = {"acknowledge": [], "reason": "Preserve the proposal pending more checking"}
                        return output
                project.advance(DeclinedFork())
                pending, _ = project.file.read()
                proposal = next(c for c in pending["changes"].values() if c["kind"] == "fork")
                self.assertEqual(proposal["status"], "pending")
                self.assertNotIn(proposal["target"], pending["directions"])
                self.assertEqual(set(proposal["affected"]), set(origin["members"]))
                if stale:
                    project.file.update("concurrent-direction-change", lambda s: s["directions"][origin["id"]].update(
                        version=s["directions"][origin["id"]]["version"] + 1))
                project.extend(1)
                project.advance(SimulatedBackend())
                after, _ = project.file.read()
                self.assertEqual(after["changes"][proposal["id"]]["status"], "stale" if stale else "applied")
                if stale:
                    self.assertNotIn(proposal["target"], after["directions"])
                else:
                    self.assertEqual(after["directions"][proposal["target"]]["basis_kind"], "material")
                    self.assertEqual(len(after["directions"]), len(first["directions"]) + 1)

    def test_lost_fork_publication_reconciles_without_redispatch_or_duplicate_directions(self):
        project = self.project(mode="single")
        class Fork(SimulatedBackend):
            calls = 0
            def call(self, call_id, messages, *args, **kwargs):
                self.calls += 1
                output = super().call(call_id, messages, *args, **kwargs)
                if messages[-1]["phase"] == "reflect":
                    output["change"] = {"kind": "fork", "target": None, "title": "An unverified alternative",
                                        "reason": "A distinct tentative route", "influenced_by": []}
                return output
        original = self.client.publish
        lost = []
        def publish(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[3] == "reflect" and not lost:
                lost.append(result)
                raise requests.ConnectionError("The fork post committed but its response was lost")
            return result
        backend = Fork()
        self.client.publish = publish
        with self.assertRaises(RuntimeError):
            project.advance(backend)
        self.client.publish = original
        before = backend.calls
        project.reconcile()
        project.reconcile()
        project.control("resume")
        project.advance(backend)
        state, _ = project.file.read()
        self.assertEqual(backend.calls, before)
        self.assertEqual(len(state["directions"]), 2)
        self.assertEqual(len(state["direction_history"]), 1)
        self.assertEqual(sum(p["id"] == lost[0] for p in state["posts"]), 1)

    def test_fixed_policy_and_fabricated_or_overwriting_forks_are_rejected(self):
        project = self.project(mode="single", semantic_policy={"direction_changes": False})
        project.advance(SimulatedBackend())
        state, _ = project.file.read()
        call = next(c for c in state["calls"].values() if c["phase"] == "reflect")
        output = copy.deepcopy(call["output"])
        output["change"] = {"kind": "fork", "target": None, "title": "new", "reason": "test", "influenced_by": []}
        with self.assertRaises(ValueError):
            project.validate(output, call["request"])
        request = copy.deepcopy(call["request"])
        request["semantic_policy"]["direction_changes"] = True
        legacy_request = copy.deepcopy(request)
        legacy_request.pop("direction_forks_enabled")
        with self.assertRaises(ValueError):
            project.validate(output, legacy_request)
        output["change"]["target"] = next(iter(state["directions"]))
        with self.assertRaises(ValueError):
            project.validate(output, request)
        output["change"]["target"] = None
        output["change"]["influenced_by"] = ["fabricated-peer-id"]
        with self.assertRaises(ValueError):
            project.validate(output, request)
        output["change"]["influenced_by"] = [{}]
        with self.assertRaises(ValueError):
            project.validate(output, request)


if __name__ == "__main__":
    unittest.main()
