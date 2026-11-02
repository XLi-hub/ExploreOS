"""Owner-protected HTTP configuration on an isolated zero-model CI service."""
import json
import unittest
import requests

from explore.store import Client


class ProviderApiTests(unittest.TestCase):
    def test_instance_token_is_required_and_configuration_never_dispatches_a_model(self):
        client = Client()
        fixture_key = "sk-http-fixture-not-a-real-key"
        endpoint = client.base + "/exploreos"
        with requests.Session() as session:
            session.trust_env = False
            headers = {"Authorization": "Bearer " + client.token}
            before = session.get(endpoint + "/runtime", headers=headers, timeout=30).json()
            if before.get("credential_source") != "missing":
                self.skipTest("Preserve pre-existing user provider configuration")
            rejected = session.post(endpoint + "/provider", headers={"Authorization": "Bearer not-the-instance-token"},
                json={"operation": "save", "key": fixture_key, "expected_version": None, "owner_capability": True}, timeout=30)
            self.assertIn(rejected.status_code, (401, 403))
            saved = None
            try:
                response = session.post(endpoint + "/provider", headers=headers,
                    json={"operation": "save", "key": fixture_key, "expected_version": None}, timeout=30)
                self.assertEqual(response.status_code, 200)
                saved = response.json()["credential_version"]
                self.assertNotIn(fixture_key, response.text)
                observed = session.get(endpoint + "/runtime", headers=headers, timeout=30).json()
                self.assertTrue(observed["can_manage_provider"])
                self.assertEqual(observed["credential_source"], "local")
                self.assertEqual(observed["budget"], before["budget"])
                self.assertNotIn(fixture_key, json.dumps(observed))
                conflict = session.post(endpoint + "/provider", headers=headers,
                    json={"operation": "remove", "expected_version": None}, timeout=30)
                self.assertEqual(conflict.status_code, 409)
            finally:
                current = session.get(endpoint + "/runtime", headers=headers, timeout=30).json()
                if saved is not None and current.get("credential_version") == saved:
                    removed = session.post(endpoint + "/provider", headers=headers,
                        json={"operation": "remove", "expected_version": saved}, timeout=30)
                    self.assertEqual(removed.status_code, 200)
            after = session.get(endpoint + "/runtime", headers=headers, timeout=30).json()
            self.assertEqual(after["credential_source"], "missing")
            self.assertEqual(after["budget"], before["budget"])


if __name__ == "__main__":
    unittest.main()
