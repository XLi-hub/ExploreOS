"""Real Pi Agent runtime and relay, fake supplier only. No paid model calls."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

from explore.models import Gateway, PI_VERSION, PiBackend, SimulatedBackend
from explore.engine import Project
from explore.store import Budget, Client, JsonFile
from scripts.cloud.runtime import ROOT


def response(text='{"condition":"version matches atomically"}', tool=False):
    block = {"type": "tool_use", "id": "unexpected", "name": "bash", "input": {}} if tool else {"type": "text", "text": ""}
    events = [
        {"type": "message_start", "message": {"id": "fake-message", "type": "message", "role": "assistant",
            "model": "deepseek-flash", "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 20, "output_tokens": 0}}},
        {"type": "content_block_start", "index": 0, "content_block": block},
    ]
    if not tool:
        events.append({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}})
    events += [{"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use" if tool else "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 10}},
        {"type": "message_stop"}]
    data = "".join("event: " + e["type"] + "\ndata: " + json.dumps(e) + "\n\n" for e in events).encode()
    return SimpleNamespace(status_code=200, content=data, headers={"Content-Type": "text/event-stream"})


@unittest.skipUnless((ROOT / ".runtime/pi/node_modules/@earendil-works/pi-agent-core/package.json").exists(),
                     "Install the optional pinned Pi runtime with setup_pi.sh")
class PiTests(unittest.TestCase):
    def setUp(self):
        client = Client()
        workspace = client.request("POST", "/workspaces", {"title": "Pi fake supplier acceptance"})["id"]
        self.budget = Budget(JsonFile(client, workspace, "budget.json"), limit=1, prior=0)
        self.gateway = Gateway("fake-key-only-in-controller", self.budget)
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.gateway.close()
        self.temporary.cleanup()

    def test_pi_sdk_uses_one_bounded_request_and_keeps_contexts_separate(self):
        backend = PiBackend(ROOT, self.gateway)
        def supplier(*args, **kwargs):
            payload = json.loads(kwargs["data"])
            prompt = json.dumps(payload["messages"])
            return response(json.dumps({"context": "alpha" if "alpha-only" in prompt else "beta"}))
        with patch("explore.models.requests.post", side_effect=supplier) as remote:
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda name: backend.call("pi-" + name,
                    [{"question": name + "-only"}], self.directory / name), ("alpha", "beta")))
            self.assertEqual(results, [{"context": "alpha"}, {"context": "beta"}])
            self.assertEqual(remote.call_count, 2)
            prompts = []
            for call in remote.call_args_list:
                payload = json.loads(call.kwargs["data"])
                prompts.append(json.dumps(payload["messages"]))
                self.assertFalse(payload.get("tools"))
                self.assertEqual(payload["max_tokens"], 900)
                self.assertEqual(payload["thinking"], {"type": "disabled"})
            self.assertTrue(all(not ("alpha-only" in p and "beta-only" in p) for p in prompts))
        state, _ = self.budget.file.read()
        for record in state["requests"].values():
            self.assertEqual(record["state"], "received")
            self.assertEqual(record["request_metadata"]["backend"], "pi")
            self.assertEqual(record["pi_version"], PI_VERSION)
            self.assertNotIn("cli_version", record["request_metadata"])
            self.assertTrue(any(e["type"] == "agent_end" for e in record["pi_events"]))
        self.assertFalse(list(self.directory.rglob("auth.json")))

    def test_pi_sdk_does_not_retry_supplier_error(self):
        error = SimpleNamespace(status_code=500, content=b'{"type":"error","error":{"type":"api_error","message":"fixture"}}',
                                headers={"Content-Type": "application/json"})
        with patch("explore.models.requests.post", return_value=error) as remote:
            with self.assertRaises(RuntimeError):
                PiBackend(ROOT, self.gateway).call("pi-error", [{"question": "fixture"}], self.directory)
            self.assertEqual(remote.call_count, 1)
        record = self.budget.file.read()[0]["requests"]["pi-error"]
        self.assertEqual(record["state"], "unknown")
        self.assertNotIn("settled_cny", record)

    def test_controller_runs_three_pi_contexts_through_a_complete_round(self):
        project = Project.create(Client(), "pi_" + uuid.uuid4().hex[:12],
            question="Which assumptions should an open discussion keep revisiting?", question_author="evaluation_script")
        fixture = SimulatedBackend()
        def supplier(*args, **kwargs):
            payload = json.loads(kwargs["data"])
            text = "".join(block["text"] for message in payload["messages"] if message["role"] == "user"
                           for block in message["content"] if block["type"] == "text")
            request = json.loads(text)[0]
            output = fixture.call("fixture", [request], project.directory)
            return response(json.dumps(output))
        with patch("explore.models.requests.post", side_effect=supplier) as remote:
            project.advance(PiBackend(ROOT, self.gateway))
            self.assertEqual(remote.call_count, 9)
        state, _ = project.file.read()
        self.assertEqual(state["rounds"][0]["status"], "completed")
        self.assertEqual(len({c["actor"] for c in state["calls"].values()}), 3)
        self.assertTrue(all(c["backend"] == "pi" and c["status"] == "completed" for c in state["calls"].values()))
        self.assertEqual(len(state["knowledge"]), 3)
        self.assertTrue(all(not k["claim_truth_verified"] for k in state["knowledge"].values()))

    def test_pi_cancellation_stops_child_and_retains_inflight_reservation(self):
        entered, release, cancel = threading.Event(), threading.Event(), threading.Event()
        children = []
        def supplier(*args, **kwargs):
            entered.set()
            release.wait(timeout=10)
            return response()
        try:
            with patch("explore.models.requests.post", side_effect=supplier):
                with ThreadPoolExecutor(1) as pool:
                    future = pool.submit(PiBackend(ROOT, self.gateway).call, "pi-cancel", [{"question": "fixture"}],
                                         self.directory, cancelled=cancel.is_set, started=children.append)
                    self.assertTrue(entered.wait(timeout=10))
                    cancel.set()
                    with self.assertRaises(TimeoutError):
                        future.result(timeout=5)
                    self.assertIsNotNone(children[0].poll())
                    record = self.budget.file.read()[0]["requests"]["pi-cancel"]
                    self.assertEqual(record["state"], "unknown")
                    self.assertGreater(record["reserved_cny"], 0)
        finally:
            release.set()

    def test_unsolicited_tool_call_cannot_execute_or_start_another_request(self):
        with patch("explore.models.requests.post", return_value=response(tool=True)) as remote:
            with self.assertRaises(RuntimeError):
                PiBackend(ROOT, self.gateway).call("pi-tool", [{"question": "fixture"}], self.directory)
            self.assertEqual(remote.call_count, 1)
        self.assertEqual(self.budget.file.read()[0]["requests"]["pi-tool"]["state"], "received")
