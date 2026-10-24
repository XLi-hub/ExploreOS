"""Admission and uncertain-outcome tests; no supplier or model calls."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest

import requests

from m0_live import Ledger, invoke


class ModelAdmissionTests(unittest.TestCase):
    def test_concurrent_reservations_do_not_overissue(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory), 0.15)

            def reserve(_):
                try:
                    ledger.reserve("actor", [{"role": "user", "content": "fixture"}])
                    return True
                except RuntimeError:
                    return False

            with ThreadPoolExecutor(8) as pool:
                admitted = sum(pool.map(reserve, range(20)))
            self.assertGreater(admitted, 0)
            self.assertLess(admitted, 20)
            self.assertLessEqual(sum(r["reserved_cny"] for r in ledger.records), 0.15)
            saved = json.loads(ledger.path.read_text())
            self.assertEqual(len(saved["calls"]), admitted)

    def test_timeout_or_cancel_keeps_reservation_and_blocks_fresh_restart(self):
        for failure in [requests.Timeout, KeyboardInterrupt]:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                ledger = Ledger(Path(directory), 1)
                calls = []

                def uncertain(key, messages):
                    calls.append(1)
                    raise failure()

                with self.assertRaises(failure):
                    invoke(ledger, "A", "fixture-key", [], transport=uncertain)
                self.assertEqual(len(calls), 1)
                saved = json.loads(ledger.path.read_text())
                self.assertEqual(saved["calls"][0]["state"], "unknown")
                self.assertGreater(saved["calls"][0]["reserved_cny"], 0)
                self.assertNotIn("fixture-key", ledger.path.read_text())
                with self.assertRaisesRegex(RuntimeError, "already exists"):
                    Ledger(Path(directory), 1)

    def test_truncated_response_is_recorded_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory), 1)
            calls = []

            def truncated(key, messages):
                calls.append(1)
                return {"usage": {"completion_tokens": 700}, "choices": [{"finish_reason": "length"}]}

            with self.assertRaisesRegex(RuntimeError, "Truncated"):
                invoke(ledger, "A", "fixture-key", [], transport=truncated)
            self.assertEqual(len(calls), 1)
            saved = json.loads(ledger.path.read_text())
            self.assertEqual(saved["calls"][0]["usage"]["completion_tokens"], 700)
            self.assertGreater(saved["calls"][0]["reserved_cny"], 0)

    def test_zero_budget_does_not_create_a_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                Ledger(Path(directory), 0)
            self.assertFalse((Path(directory) / "ledger.json").exists())


if __name__ == "__main__":
    unittest.main()
