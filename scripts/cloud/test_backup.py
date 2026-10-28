"""Offline backup integrity, refusal and rollback checks; no model/network calls."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

try:
    from . import backup
except ImportError:
    import backup


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="explore-backup-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source, self.target = self.base / "source", self.base / "target"
        for root in (self.source, self.target):
            (root / "cloud").mkdir(parents=True)
            for name in backup.PINS:
                (root / name).write_text('{"pinned":"test-only"}')
        self.write(".research/p/agents/a/memory/index.json", '{"condition":"仍需检查"}')
        self.write(".research/p/note.md", "original scope\n")
        self.write(".runtime/service/db/PG_VERSION", "17")
        self.write(".runtime/service/db/empty_table", "")
        self.write(".runtime/service/home/token", "fake-local-service-token")
        self.write(".runtime/secrets/deepseek-api-key", "fake-model-key-must-stay-out")
        self.write(".runtime/service/server.log", "private log not collected")
        self.write(".runtime/real-evaluation-readiness.json", '{"cases":168}')
        (self.source / ".runtime/service/db/empty_directory").mkdir()
        self.archive = self.base / "private.tar.gz"

    def write(self, relative, text):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_round_trip_keeps_bytes_empty_directories_and_private_modes(self):
        backup.create(self.source, self.archive)
        self.assertEqual(self.archive.stat().st_mode & 0o777, 0o600)
        manifest = backup.scan(self.archive)
        self.assertTrue(all(backup.allowed(r["path"]) for r in manifest["records"]))
        backup.restore(self.target, self.archive)
        for record in manifest["records"]:
            path = self.target / record["path"]
            self.assertTrue(path.exists())
            if record["kind"] == "file":
                self.assertEqual(path.read_bytes(), (self.source / record["path"]).read_bytes())
                self.assertEqual(path.stat().st_mode & 0o077, 0)
        self.assertTrue((self.target / ".runtime/service/db/empty_directory").is_dir())
        self.assertFalse((self.target / ".runtime/secrets/deepseek-api-key").exists())
        self.assertFalse((self.target / ".runtime/service/server.log").exists())
        self.assertFalse((self.target / ".runtime/service/process.json").exists())

    def test_running_service_and_existing_destination_are_refused(self):
        record = self.write(".runtime/service/process.json", json.dumps({"pid": os.getpid()}))
        with self.assertRaises(RuntimeError):
            backup.create(self.source, self.archive)
        self.assertFalse(self.archive.exists())
        record.unlink()
        backup.create(self.source, self.archive)
        before = self.archive.read_bytes()
        with self.assertRaises(FileExistsError):
            backup.create(self.source, self.archive)
        self.assertEqual(self.archive.read_bytes(), before)

    def test_source_symlinks_and_backups_inside_source_trees_are_refused(self):
        link = self.source / ".research/p/link"
        link.symlink_to(self.source / ".runtime/secrets/deepseek-api-key")
        with self.assertRaises(ValueError):
            backup.create(self.source, self.archive)
        self.assertFalse(self.archive.exists())
        link.unlink()
        with self.assertRaises(ValueError):
            backup.create(self.source, self.source / ".research/self.tar.gz")

    def test_live_project_process_is_refused_before_snapshot(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                   cwd=self.source / ".research/p")
        try:
            with self.assertRaises(RuntimeError):
                backup.no_controllers(self.source)
            with self.assertRaises(RuntimeError):
                backup.create(self.source, self.archive)
            self.assertFalse(self.archive.exists())
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_source_change_during_copy_never_publishes_partial_archive(self):
        original = tarfile.TarFile.addfile
        def change(archive, header, fileobj=None):
            result = original(archive, header, fileobj)
            if header.name == ".research/p/note.md":
                self.write(header.name, "changed while being snapshotted")
            return result
        with patch.object(tarfile.TarFile, "addfile", change):
            with self.assertRaises(RuntimeError):
                backup.create(self.source, self.archive)
        self.assertFalse(self.archive.exists())
        self.assertEqual(list(self.base.glob("*.part-*")), [])

    def malformed(self, extra=None, corrupt=False, duplicate=False):
        records = []
        with tarfile.open(self.archive, "w:gz") as archive:
            for name, payload in ((".research/p/note.md", b"original"),
                                  (".runtime/service/db/PG_VERSION", b"17"),
                                  (".runtime/service/home/token", b"fake-token")):
                header = tarfile.TarInfo(name)
                header.size = len(payload)
                archive.addfile(header, io.BytesIO(payload))
                records.append({"path": name, "kind": "file", "size": len(payload),
                                "sha256": "invalid" if corrupt else hashlib.sha256(payload).hexdigest()})
                if duplicate and name.endswith("note.md"):
                    archive.addfile(header, io.BytesIO(payload))
            if extra:
                archive.addfile(extra, io.BytesIO(b"x") if extra.isfile() else None)
            encoded = json.dumps({"kind": "exploreos_cold_backup_v1", "git_commit": None,
                                  "runtime_pins": backup.pins(self.source), "records": records}).encode()
            header = tarfile.TarInfo(backup.MANIFEST)
            header.size = len(encoded)
            archive.addfile(header, io.BytesIO(encoded))

    def test_path_traversal_links_duplicates_and_corruption_are_refused_before_write(self):
        traversal = tarfile.TarInfo("../escaped")
        traversal.size = 1
        link = tarfile.TarInfo(".research/p/link")
        link.type, link.linkname = tarfile.SYMTYPE, "/outside"
        for parameters in ({"extra": traversal}, {"extra": link}, {"duplicate": True}, {"corrupt": True}):
            with self.subTest(parameters=parameters):
                self.malformed(**parameters)
                with self.assertRaises(ValueError):
                    backup.restore(self.target, self.archive)
                self.assertFalse((self.target / ".research").exists())
                self.assertFalse((self.base / "escaped").exists())

    def test_restore_refuses_existing_data_and_mismatched_pins(self):
        backup.create(self.source, self.archive)
        (self.target / ".research").mkdir()
        marker = self.target / ".research/keep.txt"
        marker.write_text("existing user data")
        with self.assertRaises(FileExistsError):
            backup.restore(self.target, self.archive)
        self.assertEqual(marker.read_text(), "existing user data")
        marker.unlink()
        marker.parent.rmdir()
        (self.target / backup.PINS[0]).write_text("different runtime")
        with self.assertRaises(ValueError):
            backup.restore(self.target, self.archive)
        self.assertFalse((self.target / ".research").exists())

    def test_failed_install_rolls_back_and_can_be_retried_from_same_archive(self):
        backup.create(self.source, self.archive)
        original = os.rename
        def fail_second(source, destination):
            if Path(source).name == "db":
                raise OSError("Injected second data-tree installation failure")
            return original(source, destination)
        with patch.object(os, "rename", fail_second):
            with self.assertRaises(OSError):
                backup.restore(self.target, self.archive)
        self.assertFalse((self.target / ".research").exists())
        self.assertFalse((self.target / ".runtime/service/db").exists())
        backup.restore(self.target, self.archive)
        self.assertEqual((self.target / ".research/p/note.md").read_text(), "original scope\n")


if __name__ == "__main__":
    unittest.main()
