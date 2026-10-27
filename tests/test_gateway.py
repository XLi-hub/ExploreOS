"""Native protocol boundary, with a fake supplier and real admission storage."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request

from explore.models import Gateway, OUTPUT_TOKENS
from explore.store import AdmissionError, Budget, Client, JsonFile
from scripts.probe_native import session_budget


class GatewayTests(unittest.TestCase):
    def test_existing_pool_reuses_its_authorized_limit_without_reset(self):
        client = Client()
        with tempfile.TemporaryDirectory() as directory, patch("scripts.probe_native.ROOT", Path(directory)):
            with self.assertRaises(RuntimeError):
                session_budget(client)
            pool = session_budget(client, limit=1)
            pool.admit("retained-unknown", 10, 10)
            restored = session_budget(client)
            state, _ = restored.file.read()
            self.assertEqual(state["limit_cny"], 1)
            self.assertEqual(state["requests"]["retained-unknown"]["state"], "unknown")
            with self.assertRaises(AdmissionError):
                session_budget(client, limit=5)

    def test_paid_retry_and_tools_are_denied_without_second_supplier_call(self):
        client = Client()
        workspace = client.request("POST", "/workspaces", {"title": "gateway mechanical acceptance"})["id"]
        budget = Budget(JsonFile(client, workspace, "budget.json"), limit=1, prior=0, max_calls=4)
        gateway = Gateway("fake-key-never-forwarded-to-a-real-server", budget)
        gateway.allowed.update({"call1", "tools"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def request(call_id, tools=None):
            body = {"model": "irrelevant", "max_tokens": 999999, "messages": [{"role": "user", "content": "fixture"}]}
            if tools:
                body["tools"] = tools
            req = urllib.request.Request(f"http://127.0.0.1:{gateway.server.server_port}/{call_id}/v1/messages?beta=true",
                data=json.dumps(body).encode(), headers={"x-api-key": gateway.token, "Content-Type": "application/json"})
            try:
                with opener.open(req, timeout=5) as response:
                    return response.status
            except urllib.error.HTTPError as error:
                return error.code
        result = {"content": [{"type": "text", "text": '{"fixture":true}'}],
                  "usage": {"input_tokens": 20, "output_tokens": 10}}
        fake = SimpleNamespace(status_code=200, content=json.dumps(result).encode(), headers={"Content-Type": "application/json"})
        try:
            with patch("explore.models.requests.post", return_value=fake) as supplier:
                self.assertEqual(request("call1"), 200)
                self.assertEqual(request("call1"), 429)
                self.assertEqual(request("tools", [{"name": "Bash"}]), 403)
                self.assertEqual(supplier.call_count, 1)
                sent = json.loads(supplier.call_args.kwargs["data"])
                self.assertEqual(sent["max_tokens"], OUTPUT_TOKENS)
                self.assertEqual(sent["thinking"], {"type": "disabled"})
                self.assertEqual(sent["model"], "deepseek-flash")
            state, _ = budget.file.read()
            self.assertEqual(len(state["requests"]), 1)
            self.assertEqual(state["requests"]["call1"]["state"], "received")
        finally:
            gateway.close()


if __name__ == "__main__":
    unittest.main()
