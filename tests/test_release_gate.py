"""Publication fails closed when acceptance, runtime or build evidence is missing."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.cloud import release_gate as gate


class ReleaseGateTests(unittest.TestCase):
    def accepted(self):
        # Fabricated metadata for gate tests, never a real acceptance declaration.
        return {"version": "v0.1.0", "runtime_sha256": "fixture-runtime",
                "acceptance": {name: {"status": "accepted", "evidence": "Synthetic gate-test evidence only"}
                               for name in gate.REQUIRED_ACCEPTANCE}}

    def builds(self):
        sha = "a" * 40
        runs = [{"id": i + 1, "name": name, "head_sha": sha, "head_branch": "main", "event": "push",
                 "status": "completed", "conclusion": "success"}
                for i, name in enumerate(gate.REQUIRED_WORKFLOWS)]
        artifacts = [{"name": "exploreos-linux-amd64-" + sha, "expired": False,
                      "workflow_run": {"head_sha": sha, "id": 2}}]
        return runs, artifacts, sha

    def test_current_pending_acceptance_stops_before_any_remote_operation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".release").mkdir()
            (root / "docs/releases").mkdir(parents=True)
            pending = self.accepted()
            pending["runtime_sha256"] = gate.digest({"fixture": "runtime"})
            for entry in pending["acceptance"].values():
                entry["status"] = "pending"
            (root / ".release/acceptance.json").write_text(json.dumps(pending))
            (root / "docs/releases/v0.1.0.md").write_text("状态：待验收")
            with patch("sys.argv", ["release_gate", "--github-checks"]), patch.object(gate, "ROOT", root), patch.object(gate, "runtime_manifest", return_value={"fixture": "runtime"}), patch.object(gate, "github") as remote:
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(gate.main(), 1)
                remote.assert_not_called()
                self.assertIn('"publishable": false', output.getvalue())
                for name in gate.REQUIRED_ACCEPTANCE:
                    self.assertIn("Acceptance pending: " + name, output.getvalue())

    def test_recorded_acceptance_requires_actual_evidence_and_current_runtime(self):
        record = self.accepted()
        self.assertEqual(gate.acceptance_errors(record, "fixture-runtime", "v0.1.0", "状态：发布就绪"), [])
        for name in gate.REQUIRED_ACCEPTANCE:
            invalid = copy.deepcopy(record)
            invalid["acceptance"][name]["evidence"] = " "
            self.assertTrue(gate.acceptance_errors(invalid, "fixture-runtime", "v0.1.0", "状态：发布就绪"))
        self.assertTrue(gate.acceptance_errors(record, "changed-runtime", "v0.1.0", "状态：发布就绪"))
        self.assertTrue(gate.acceptance_errors(record, "fixture-runtime", "v0.1.0", "状态：待验收"))
        self.assertTrue(gate.acceptance_errors(record, "fixture-runtime", "v0.1.1", "状态：发布就绪"))

    def test_failed_or_pending_latest_build_cannot_be_hidden_by_an_older_success(self):
        runs, artifacts, sha = self.builds()
        for status, conclusion in (("completed", "failure"), ("in_progress", None)):
            newer = {**runs[0], "id": 3, "status": status, "conclusion": conclusion}
            with self.assertRaisesRegex(ValueError, "Latest same-commit"):
                gate.select_verified_artifact([*runs, newer], artifacts, sha)

    def test_other_commits_branches_and_pull_request_builds_cannot_authorize_release(self):
        runs, artifacts, sha = self.builds()
        for mismatch in ({"head_sha": "b" * 40}, {"head_branch": "codex/test"}, {"event": "pull_request"}):
            changed = [{**r, **mismatch} for r in runs]
            with self.assertRaisesRegex(ValueError, "Missing main CI"):
                gate.select_verified_artifact(changed, artifacts, sha)

    def test_expired_duplicate_or_foreign_artifact_is_refused(self):
        runs, artifacts, sha = self.builds()
        for changed in ([{**artifacts[0], "expired": True}], artifacts * 2,
                        [{**artifacts[0], "workflow_run": {"head_sha": sha, "id": 99}}],
                        [{**artifacts[0], "workflow_run": {"head_sha": "b" * 40, "id": 2}}]):
            with self.assertRaisesRegex(ValueError, "Require one unexpired"):
                gate.select_verified_artifact(runs, changed, sha)

    def test_matching_build_and_artifact_select_the_exact_product_run(self):
        runs, artifacts, sha = self.builds()
        self.assertEqual(gate.select_verified_artifact(runs, artifacts, sha), (2, "exploreos-linux-amd64-" + sha))


if __name__ == "__main__":
    unittest.main()
