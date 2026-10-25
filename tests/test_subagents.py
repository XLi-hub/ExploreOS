"""Real plugin host + public delegation + real shared ledger, fake supplier only."""
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from explore.engine import Project
from explore.models import Gateway, SimulatedBackend
from explore.store import Budget, Client, JsonFile
from explore.subagents import PLUGIN_VERSION, SubagentsBackend, read_receipt, reference
from scripts.cloud.runtime import ROOT
from test_pi import response


def fixture_supplier(*args, **kwargs):
    payload = json.loads(kwargs["data"])
    text = "".join(block["text"] for message in payload["messages"] if message["role"] == "user"
                   for block in message["content"] if block["type"] == "text")
    spec = json.loads(text.split("EXPLOREOS_TASK_BEGIN\n")[-1].split("\nEXPLOREOS_TASK_END")[0])[0]
    return response(json.dumps(SimulatedBackend().call("fixture", [spec], ROOT)))


@unittest.skipUnless((ROOT / ".runtime/subagents/node_modules/pi-subagents/package.json").exists(),
                     "Install the optional plugin host with setup_subagents.sh")
class SubagentTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        workspace = self.client.request("POST", "/workspaces", {"title": "Plugin fake-supplier acceptance"})["id"]
        self.budget = Budget(JsonFile(self.client, workspace, "budget.json"), limit=3, prior=0)
        self.gateway = Gateway("fake-provider-key-controller-only", self.budget)
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.gateway.close()
        self.temporary.cleanup()

    def project(self, mode="single"):
        return Project.create(self.client, "sub_" + uuid.uuid4().hex[:12], mode=mode,
            question="Which assumptions should this open discussion revisit?", question_author="evaluation_script")

    def test_public_delegation_receipt_and_replay_denial(self):
        call_id = "test-owner:r1.plan.actor"
        backend = SubagentsBackend(ROOT, self.gateway)
        with patch("explore.models.requests.post", return_value=response()) as supplier:
            result = backend.call(call_id, [{"question": "fixture"}], self.directory)
            self.assertIn("condition", result)
            receipt = read_receipt(self.directory, call_id)
            self.assertEqual(receipt["state"], "terminal")
            self.assertEqual(receipt["response"]["status"], "completed")
            self.assertEqual(receipt["profile"]["context"], "fresh")
            self.assertEqual(receipt["profile"]["tools"], [])
            self.assertEqual(receipt["response"]["launchContractDigest"], receipt["preflight_launch_digest"])
            self.assertTrue(receipt["response"]["runId"])
            self.assertEqual(receipt["provider_requests"], 1)
            with self.assertRaisesRegex(RuntimeError, "reconcile"):
                backend.call(call_id, [{"question": "must not redispatch"}], self.directory)
            self.assertEqual(supplier.call_count, 1)
        record = self.budget.file.read()[0]["requests"][call_id]
        self.assertEqual(record["request_metadata"]["pi_subagents"], PLUGIN_VERSION)
        self.assertEqual(record["delegation"]["runId"], receipt["response"]["runId"])

    def test_three_foreground_leaves_complete_the_controller_round_without_context_leakage(self):
        project = self.project(mode="independent")
        with patch("explore.models.requests.post", side_effect=fixture_supplier) as supplier:
            project.advance(SubagentsBackend(ROOT, self.gateway))
            self.assertEqual(supplier.call_count, 9)
            for call in supplier.call_args_list:
                self.assertFalse(json.loads(call.kwargs["data"]).get("tools"))
        state, _ = project.file.read()
        self.assertEqual(state["rounds"][0]["status"], "completed")
        self.assertEqual(len(state["posts"]), 9)
        self.assertEqual(len({c["actor"] for c in state["calls"].values()}), 3)
        for call in state["calls"].values():
            self.assertEqual(call["request"]["peers"], [])
            self.assertEqual(call["request"]["shared_memory"], [])
            self.assertEqual(call["execution_ref"]["call_id"], call["id"])
        observations = project.execution_status()
        self.assertTrue(all(o["plugin_status"] == "completed" for o in observations.values()))
        self.assertEqual(len({o["run_id"] for o in observations.values()}), 9)
        exported = project.export(project.directory / "exports")
        self.assertEqual(exported["execution_observations"], observations)

    def test_cancellation_ends_owned_host_and_keeps_unknown_supplier_reservation(self):
        entered, release, cancel = threading.Event(), threading.Event(), threading.Event()
        children = []
        def supplier(*args, **kwargs):
            entered.set()
            release.wait(timeout=15)
            return response()
        try:
            with patch("explore.models.requests.post", side_effect=supplier):
                with ThreadPoolExecutor(1) as pool:
                    future = pool.submit(SubagentsBackend(ROOT, self.gateway).call, "cancel-owner:node",
                        [{"question": "fixture"}], self.directory, cancelled=cancel.is_set, started=children.append)
                    self.assertTrue(entered.wait(timeout=12))
                    cancel.set()
                    with self.assertRaises(TimeoutError):
                        future.result(timeout=6)
                    self.assertIsNotNone(children[0].poll())
                    record = self.budget.file.read()[0]["requests"]["cancel-owner:node"]
                    self.assertEqual(record["state"], "unknown")
                    self.assertNotIn("settled_cny", record)
        finally:
            release.set()

    def test_supplier_text_without_plugin_receipt_cannot_be_promoted_or_retried(self):
        project = self.project()
        moved = []
        class LostReceipt(SubagentsBackend):
            def call(child, call_id, messages, directory, **kwargs):
                result = super().call(call_id, messages, directory, **kwargs)
                if not moved:
                    path = directory / reference(call_id)["receipt"]
                    backup = path.with_suffix(".retained")
                    path.rename(backup)
                    moved.append((path, backup))
                    raise RuntimeError("Host reply and its projected receipt became unavailable")
                return result
        backend = LostReceipt(ROOT, self.gateway)
        with patch("explore.models.requests.post", side_effect=fixture_supplier) as supplier:
            with self.assertRaises(RuntimeError):
                project.advance(backend)
            project.reconcile(self.budget)
            state, _ = project.file.read()
            slot, call = next(iter(state["calls"].items()))
            self.assertEqual(call["status"], "unknown")
            self.assertEqual(state["posts"], [])
            self.assertEqual(self.budget.file.read()[0]["requests"][call["id"]]["state"], "received")
            project.file.update("fixture-controller-exited", lambda s: s["calls"][slot].update(
                controller={"pid": 999999999, "start": "old", "boot": "old"}))
            with self.assertRaisesRegex(RuntimeError, "Plugin outcome is unknown"):
                project.retry(slot, "A lost plugin result must not cause another paid attempt", self.budget)
            moved[0][1].rename(moved[0][0])
            project.reconcile(self.budget)
            self.assertEqual(project.file.read()[0]["calls"][slot]["status"], "completed")
            project.control("resume")
            project.advance(backend)
            self.assertEqual(supplier.call_count, 3)

    def test_failed_plugin_status_does_not_become_a_finding_from_valid_provider_text(self):
        project = self.project()
        class FailedStatus(SubagentsBackend):
            def call(child, call_id, messages, directory, **kwargs):
                super().call(call_id, messages, directory, **kwargs)
                path = directory / reference(call_id)["receipt"]
                data = json.loads(path.read_text())
                data["response"]["status"] = "failed"  # mechanical protocol-failure injection
                path.write_text(json.dumps(data))
                raise RuntimeError("Plugin protocol failed after receiving provider text")
        with patch("explore.models.requests.post", side_effect=fixture_supplier) as supplier:
            with self.assertRaises(RuntimeError):
                project.advance(FailedStatus(ROOT, self.gateway))
            project.reconcile(self.budget)
            state, _ = project.file.read()
            slot, call = next(iter(state["calls"].items()))
            self.assertEqual(call["status"], "failed")
            self.assertEqual(state["posts"], [])
            project.retry(slot, "Explicit retry after a known failed terminal plugin receipt", self.budget)
            self.assertIn(call["id"], project.file.read()[0]["retired_calls"])
            self.assertEqual(supplier.call_count, 1)

    def test_tool_request_is_blocked_and_does_not_start_a_second_supplier_request(self):
        with patch("explore.models.requests.post", return_value=response(tool=True)) as supplier:
            with self.assertRaises(RuntimeError):
                SubagentsBackend(ROOT, self.gateway).call("tool-owner:node", [{"question": "fixture"}], self.directory)
            self.assertEqual(supplier.call_count, 1)
        data = read_receipt(self.directory, "tool-owner:node")
        self.assertNotEqual((data or {}).get("response", {}).get("status"), "completed")

    def test_foreign_receipt_identity_is_rejected(self):
        call_id = "identity-owner:node"
        with patch("explore.models.requests.post", return_value=response()):
            SubagentsBackend(ROOT, self.gateway).call(call_id, [{"question": "fixture"}], self.directory)
        path = self.directory / reference(call_id)["receipt"]
        data = json.loads(path.read_text())
        data["response"]["requestId"] = "some-other-attempt"
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            read_receipt(self.directory, call_id)

    def test_project_context_and_extensions_do_not_enter_the_leaf(self):
        marker = "EXTERNAL_PROJECT_CONTEXT_MUST_NOT_ENTER_LEAF"
        (self.directory / "AGENTS.md").write_text(marker)
        extensions = self.directory / ".pi/extensions"
        extensions.mkdir(parents=True)
        sentinel = self.directory / "unexpected-extension-ran"
        (extensions / "poison.mjs").write_text(
            "import fs from 'node:fs'; fs.writeFileSync(" + json.dumps(str(sentinel)) + ", 'unexpected'); export default () => {};\n")
        with patch("explore.models.requests.post", return_value=response()) as supplier:
            SubagentsBackend(ROOT, self.gateway).call("isolation-owner:node", [{"question": "fixture"}], self.directory)
            self.assertNotIn(marker, supplier.call_args.kwargs["data"].decode())
        self.assertFalse(sentinel.exists())

    def test_plugin_error_does_not_enable_sdk_or_supplier_retries(self):
        error = SimpleNamespace(status_code=500,
            content=b'{"type":"error","error":{"type":"api_error","message":"fixture"}}',
            headers={"Content-Type": "application/json"})
        with patch("explore.models.requests.post", return_value=error) as supplier:
            with self.assertRaises(RuntimeError):
                SubagentsBackend(ROOT, self.gateway).call("failed-owner:node", [{"question": "fixture"}], self.directory)
            self.assertEqual(supplier.call_count, 1)
        receipt = read_receipt(self.directory, "failed-owner:node")
        self.assertEqual(receipt["response"]["status"], "failed")
        record = self.budget.file.read()[0]["requests"]["failed-owner:node"]
        self.assertEqual(record["state"], "unknown")
        self.assertNotIn("settled_cny", record)

    def test_sigkill_after_plugin_receipt_recovers_without_replaying_the_leaf(self):
        project = self.project()
        code = '''
import os, signal, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path.cwd() / "tests"))
from test_subagents import fixture_supplier
from explore.engine import Project
from explore.models import Gateway
from explore.store import Budget, Client, JsonFile
from explore.subagents import SubagentsBackend
from scripts.cloud.runtime import ROOT
c = Client()
b = Budget(JsonFile(c, sys.argv[2], "budget.json"), limit=3, prior=0)
g = Gateway("fake-provider-key-controller-only", b)
class DieAfterReceipt(SubagentsBackend):
    def call(self, *args, **kwargs):
        super().call(*args, **kwargs)
        os.kill(os.getpid(), signal.SIGKILL)
with patch("explore.models.requests.post", side_effect=fixture_supplier):
    Project(c, Path(sys.argv[1])).advance(DieAfterReceipt(ROOT, g))
'''
        result = subprocess.run([sys.executable, "-c", code, str(project.directory), self.budget.file.workspace],
                                cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, -9, result.stderr)
        before, _ = project.file.read()
        slot, original = next(iter(before["calls"].items()))
        self.assertEqual(original["status"], "running")
        project.reconcile(self.budget)
        self.assertEqual(project.file.read()[0]["calls"][slot]["status"], "completed")
        with patch("explore.models.requests.post", side_effect=fixture_supplier) as supplier:
            project.advance(SubagentsBackend(ROOT, self.gateway))
            self.assertEqual(supplier.call_count, 2)
        after, _ = project.file.read()
        self.assertEqual(after["calls"][slot]["id"], original["id"])
        self.assertEqual(after["rounds"][0]["status"], "completed")
        self.assertEqual(len(self.budget.file.read()[0]["requests"]), 3)


if __name__ == "__main__":
    unittest.main()
