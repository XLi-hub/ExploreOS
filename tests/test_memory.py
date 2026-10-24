import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from explore.memory import Memory, select_shared_memory


class MemoryTests(unittest.TestCase):
    def test_old_relevant_failure_is_recalled_after_newer_unrelated_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = Memory(Path(directory))
            memory.remember("old-failure", summary="用户改向后旧结论的适用范围需要重查", question_revision=1,
                unresolved="旧结论不能无条件复用", source_ids=["source-v1"],
                failure={"scope": "原问题与旧资料", "retry_when": "出现新材料或用户改变关注点"})
            for i in range(12):
                memory.remember(f"later-{i}", summary=f"unrelated compilation note {i}", question_revision=1)
            reads = []
            original = Path.read_text
            def read(path, *args, **kwargs):
                if path.name.startswith("note_"):
                    reads.append(path.name)
                return original(path, *args, **kwargs)
            with patch.object(Path, "read_text", read):
                recalled = Memory(Path(directory)).recall("用户改向后如何核查旧结论的适用范围？")
            self.assertEqual(recalled["index_size"], 13)
            self.assertIn("old-failure", [note["id"] for note in recalled["recalled_notes"]])
            self.assertLessEqual(len(recalled["recalled_notes"]), 6)
            self.assertLessEqual(len(reads), 6)
            note = next(n for n in recalled["recalled_notes"] if n["id"] == "old-failure")
            self.assertEqual(note["failure"]["retry_when"], "出现新材料或用户改变关注点")
            self.assertIn("not_external_evidence", note["epistemic_status"])

    def test_replaying_completed_call_does_not_duplicate_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = Memory(Path(directory))
            for _ in range(3):
                memory.remember("stable-call", summary="one immutable note", question_revision=1)
            self.assertEqual(len(memory.index()["notes"]), 1)
            self.assertTrue((Path(directory) / "MEMORY.md").exists())

    def test_old_contested_finding_survives_recent_window_without_leaking_into_controls(self):
        entries = {"old": {"post_id": "old", "actor": "A", "status": "contested", "question_revision": 1,
                           "preview": "旧解释的适用范围受到新材料质疑", "unresolved": "需要复查"}}
        entries.update({f"new{i}": {"post_id": f"new{i}", "actor": "B", "status": "provisional", "question_revision": 2,
                                   "preview": f"recent unrelated note {i}"} for i in range(20)})
        state = {"mode": "collaborative", "knowledge": entries}
        shared = select_shared_memory(state, "B", "plan", "用户改向后复查旧解释", 2)
        old = next(entry for entry in shared if entry["post_id"] == "old")
        self.assertTrue(old["applicability_check_required"])
        self.assertLessEqual(len(shared), 8)
        state["mode"] = "independent"
        isolated = select_shared_memory(state, "B", "plan", "用户改向后复查旧解释", 2)
        self.assertTrue(all(entry["actor"] == "B" for entry in isolated))


if __name__ == "__main__":
    unittest.main()
