"""Provider setup without network/model calls, using only temporary private directories."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from explore import credentials
from explore.native import NativeService
from explore.store import Conflict


KEY_A = "sk-fixture-provider-alpha-not-real"
KEY_B = "sk-fixture-provider-beta-not-real"


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.root_patch = patch.object(credentials, "ROOT", self.root)
        self.environment_patch = patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""})
        self.root_patch.start()
        self.environment_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.environment_patch.stop)

    def save(self, value=KEY_A, expected=None):
        return credentials.configure({"operation": "save", "key": value, "expected_version": expected})

    def test_passive_status_creates_nothing_and_save_is_private_without_value_disclosure(self):
        self.assertIsNone(credentials.model_key())
        self.assertEqual(credentials.public_configuration()["credential_source"], "missing")
        self.assertFalse((self.root / ".runtime").exists())
        result = self.save()
        self.assertEqual(result["credential_source"], "local")
        self.assertRegex(result["credential_version"], r"^[a-f0-9]{32}$")
        self.assertNotIn(KEY_A, json.dumps(result))
        target = self.root / credentials.RELATIVE
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(credentials.model_key(), KEY_A)

    def test_stale_tabs_and_concurrent_first_writes_cannot_overwrite_each_other(self):
        def attempt(value):
            try:
                return self.save(value)
            except Conflict:
                return None
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(attempt, (KEY_A, KEY_B)))
        self.assertEqual(sum(value is not None for value in results), 1)
        current = credentials.public_configuration()
        with self.assertRaises(Conflict):
            self.save("sk-fixture-stale-tab-value", expected=None)
        after = self.save(KEY_B, expected=current["credential_version"])
        self.assertNotEqual(after["credential_version"], current["credential_version"])
        with self.assertRaises(Conflict):
            credentials.configure({"operation": "remove", "expected_version": current["credential_version"]})
        self.assertEqual(credentials.model_key(), KEY_B)

    def test_environment_configuration_cannot_be_replaced_or_removed_from_ui(self):
        initial = self.save()
        before = (self.root / credentials.RELATIVE).read_bytes()
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": KEY_B}):
            self.assertEqual(credentials.model_key(), KEY_B)
            self.assertFalse(credentials.public_configuration()["credential_editable"])
            for operation in ("save", "remove"):
                with self.assertRaises(ValueError):
                    credentials.configure({"operation": operation, "key": KEY_A,
                                           "expected_version": initial["credential_version"]})
        self.assertEqual((self.root / credentials.RELATIVE).read_bytes(), before)
        self.assertEqual(credentials.model_key(), KEY_A)

    def test_legacy_configuration_is_preserved_and_remove_only_removes_ui_owned_key(self):
        legacy = self.root / ".runtime/secrets/deepseek-api-key"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(KEY_A)
        legacy.chmod(0o600)
        self.assertEqual(credentials.model_key(), KEY_A)
        saved = self.save(KEY_B)
        self.assertEqual(credentials.model_key(), KEY_B)
        result = credentials.configure({"operation": "remove", "expected_version": saved["credential_version"]})
        self.assertEqual(result["credential_source"], "legacy")
        self.assertEqual(credentials.model_key(), KEY_A)
        self.assertEqual(legacy.read_text(), KEY_A)

    def test_corrupt_or_symlinked_files_are_refused_without_echoing_values(self):
        target = self.root / credentials.RELATIVE
        target.parent.mkdir(parents=True, mode=0o700)
        target.write_text('{"api_key":"' + KEY_A)
        target.chmod(0o600)
        with self.assertRaises(RuntimeError) as error:
            credentials.model_key()
        self.assertNotIn(KEY_A, str(error.exception))
        target.unlink()
        outside = self.root / "outside"
        outside.write_text(KEY_A)
        target.symlink_to(outside)
        with self.assertRaises(RuntimeError):
            credentials.model_key()
        with self.assertRaises(RuntimeError):
            self.save()
        self.assertEqual(outside.read_text(), KEY_A)
        target.unlink()
        target.parent.rmdir()
        target.parent.symlink_to(self.root)
        with self.assertRaises(RuntimeError):
            self.save()

    def test_setup_cannot_invoke_models_or_change_existing_budget_records(self):
        research = self.root / ".research"
        research.mkdir()
        marker = research / "existing-budget-reference.json"
        marker.write_text('{"prior_exposure":1.5,"unknown":2}')
        service = NativeService(client=object())
        pool = {"limit_cny": 5, "remaining_cny": 3.5, "unknown_requests": 2}
        with patch.object(service, "budget_view", return_value=pool), patch("explore.models.Gateway",
                side_effect=AssertionError("Saving configuration must not invoke models")):
            result = service.handle({"action": "configure-provider", "data": {
                "operation": "save", "key": KEY_A, "expected_version": None}})
        self.assertEqual(result["credential"], "configured")
        self.assertEqual(result["budget"], pool)
        self.assertNotIn(KEY_A, json.dumps(result))
        self.assertEqual(marker.read_text(), '{"prior_exposure":1.5,"unknown":2}')

    def test_invalid_input_and_missing_revision_do_not_create_configuration(self):
        for data in ({"operation": "save", "key": KEY_A},
                     {"operation": "save", "key": "bad\\nheader", "expected_version": None},
                     {"operation": "save", "key": KEY_A, "expected_version": True}):
            with self.assertRaises(ValueError):
                credentials.configure(data)
        self.assertFalse((self.root / credentials.RELATIVE).exists())


if __name__ == "__main__":
    unittest.main()
