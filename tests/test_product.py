"""Product acceptance boundaries on actual shared records; no supplier traffic."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from explore.brief import build
from explore.models import SimulatedBackend
from explore.native import NativeService
from explore.store import Client


class ProductTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.service = NativeService(self.client)

    def project(self, **data):
        result = self.service.handle({"action": "create", "data": {
            "question": "Which disagreements should we revisit?", "mode": "single",
            "execution": {"backend": "simulated"}, **data}})
        return self.service.project(result["name"])

    def test_question_only_creation_and_saved_mode_survive_reload_without_model_setup(self):
        with patch("explore.native.model_key", side_effect=AssertionError("Demo must not read a model key")):
            project = self.project()
            self.assertRegex(project.directory.name, r"^q_[a-f0-9]{16}$")
            view = self.service.state(project)
            self.assertEqual(view["calls"], [])
            self.assertEqual(view["sources"], [])
            self.assertEqual(view["native_execution"], {"backend": "simulated"})
            self.service.handle({"action": "advance", "name": project.directory.name})
            reloaded = NativeService(self.client).state(project)
            self.assertEqual(reloaded["record_kind"], "mechanical_fixture")
            self.assertTrue(reloaded["brief"]["findings"])
            self.assertEqual(reloaded["brief"]["completed_rounds"], 1)
        before = project.file.read()[0]
        with self.assertRaises(ValueError):
            self.service.handle({"action": "advance", "name": project.directory.name, "data": {"backend": "pi"}})
        with patch.object(self.service, "budget_view", return_value=None):
            with self.assertRaises(ValueError):
                self.service.save_profile(project, {"backend": "pi", "budget_cny": 1})
        self.assertEqual(project.file.read()[0], before)

    def test_shared_budget_setup_is_read_only_and_rejects_reset_or_invalid_limits(self):
        with patch.object(self.service, "budget_view", return_value={"limit_cny": 7}):
            self.assertEqual(self.service.validate_profile({"backend": "pi"}), {"backend": "pi", "budget_cny": 7})
            with self.assertRaises(ValueError):
                self.service.validate_profile({"backend": "pi", "budget_cny": 8})
        with patch.object(self.service, "budget_view", return_value=None):
            for value in (None, True, 0, -1, float("nan"), float("inf"), "7"):
                with self.assertRaises(ValueError):
                    self.service.validate_profile({"backend": "pi", "budget_cny": value})

    def test_runtime_status_does_not_create_budget_or_expose_configured_secret(self):
        from explore import native
        with tempfile.TemporaryDirectory() as directory, patch.object(native, "ROOT", Path(directory)), patch.object(native, "model_key", return_value="fixture-private-secret"):
            response = self.service.runtime()
            self.assertEqual(response["credential"], "configured")
            self.assertFalse(response["pi_ready"])
            self.assertIsNone(response["budget"])
            self.assertNotIn("fixture-private-secret", json.dumps(response))
            self.assertFalse((Path(directory) / ".research").exists())

    def test_changed_focus_does_not_present_old_claim_as_current_and_keeps_objections(self):
        project = self.project()
        project.advance(SimulatedBackend())
        first = self.service.state(project)
        finding = first["brief"]["findings"][0]
        project.challenge(finding["post_id"], "A narrower setting could reverse this claim")
        project.control("steer", "What changes under a new setting?")
        view = self.service.state(project)
        brief = view["brief"]
        self.assertEqual(brief["findings"], [])
        self.assertTrue(brief["historical"])
        self.assertEqual(brief["historical"][0]["question_revision"], 1)
        self.assertTrue(any(q["kind"] == "challenge" for q in brief["questions"]))
        self.assertIn(finding["post_id"], brief["markdown"])
        self.assertEqual(view["calls"], self.service.state(project)["calls"])

    def test_withdrawals_and_stale_reviews_never_become_current_knowledge(self):
        project = self.project()
        project.advance(SimulatedBackend())
        view = self.service.state(project)
        post = view["brief"]["findings"][0]["post_id"]
        scenario = copy.deepcopy(view)
        scenario["knowledge"][post]["status"] = "withdrawn"
        scenario["knowledge"][post]["challenges"] = [{"reason": "Unresolved counterexample", "author_responses": ["response"]}]
        scenario["reviews"] = [{"status": "stale", "decision": "revise", "reason": "An outdated response", "target_post": post}]
        brief = build(scenario)
        self.assertFalse(any(f["post_id"] == post for f in brief["findings"]))
        self.assertTrue(any(f["post_id"] == post for f in brief["historical"]))
        self.assertEqual(brief["changes"], [])
        self.assertEqual(len(brief["stale_reviews"]), 1)
        self.assertTrue(next(q for q in brief["questions"] if q["kind"] == "challenge")["responded"])
        self.assertIn("异议仍保留", brief["markdown"])


if __name__ == "__main__":
    unittest.main()
