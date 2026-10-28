#!/usr/bin/env python3
"""Private, offline snapshots of the existing ClawInstitute instance and project files."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import uuid

try:
    from .runtime import ROOT, alive
except ImportError:
    from runtime import ROOT, alive

MANIFEST = "exploreos-backup.json"
TREES = (".research", ".runtime/service/db")
EXTRAS = (".runtime/service/home/token", ".runtime/real-evaluation-readiness.json")
PINS = ("cloud/versions.json", "cloud/package-lock.json")
MAX_FILES, MAX_BYTES = 200000, 64 * 1024**3


def digest_file(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def allowed(name):
    path = PurePosixPath(name)
    return (name == path.as_posix() and not path.is_absolute() and ".." not in path.parts
            and (name in EXTRAS or any(name == root or name.startswith(root + "/") for root in TREES)))


def pins(root):
    return {name: digest_file(root / name) for name in PINS}


def no_links(root, relative):
    current = root
    for component in PurePosixPath(relative).parts:
        current /= component
        if current.is_symlink():
            raise ValueError("Snapshot paths cannot traverse symbolic links")


@contextmanager
def offline(root):
    no_links(root, ".runtime/service")
    service = root / ".runtime/service"
    service.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (service / "manager.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = service / "process.json"
        if record.exists() and alive(int(json.loads(record.read_text())["pid"])):
            raise RuntimeError("Stop the owned service before snapshot or restore")
        no_controllers(root)
        yield


def no_controllers(root):
    for process in Path("/proc").iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            working = (process / "cwd").resolve(strict=True)
            if not working.is_relative_to(root):
                continue
            args = (process / "cmdline").read_bytes().split(b"\0")
            modules = {b"explore", b"explore.native", b"explore.evaluation", b"explore.schedule"}
            controller = b"-m" in args and any(value in modules for value in args)
            runners = {b"pi_runner.mjs", b"subagents_runner.mjs", b"probe_native.py", b"acceptance_m1.py"}
            controller |= any(value.rsplit(b"/", 1)[-1] in runners for value in args)
            if working.is_relative_to(root / ".research") or controller:
                raise RuntimeError("Stop project controllers and wakeup watchers before snapshot or restore")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue


def source_paths(root):
    result = []
    for relative in (*TREES, *EXTRAS):
        path = root / relative
        no_links(root, relative)
        if not path.exists():
            if relative in (".runtime/service/db", ".runtime/service/home/token"):
                raise ValueError("The source has no existing ClawInstitute database/token")
            continue
        candidates = [path, *sorted(path.rglob("*"))] if path.is_dir() else [path]
        for candidate in candidates:
            info = candidate.lstat()
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise ValueError("Snapshot supports regular files/directories only; inspect links or special files first")
            result.append((candidate.relative_to(root).as_posix(), info))
    if len(result) > MAX_FILES or sum(info.st_size for _, info in result if stat.S_ISREG(info.st_mode)) > MAX_BYTES:
        raise ValueError("Snapshot exceeds the supported file/byte bounds")
    return result


def signature(info):
    return info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode


class HashReader:
    def __init__(self, source):
        self.source, self.digest = source, hashlib.sha256()

    def read(self, amount):
        block = self.source.read(amount)
        self.digest.update(block)
        return block


def create(root, destination):
    root, destination = Path(root).resolve(), Path(destination).absolute()
    destination = destination.parent.resolve() / destination.name
    if any(destination.is_relative_to(root / tree) for tree in TREES) or destination in [root / name for name in EXTRAS]:
        raise ValueError("Store the backup outside the snapshotted data trees")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Backup destination already exists")
    temporary = destination.with_name(destination.name + ".part-" + uuid.uuid4().hex)
    try:
        with offline(root):
            paths = source_paths(root)
            runtime_pins = pins(root)
            records = []
            with open(temporary, "xb", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
                with tarfile.open(fileobj=output, mode="w:gz", compresslevel=3) as archive:
                    for name, before in paths:
                        path = root / name
                        header = tarfile.TarInfo(name)
                        header.mode, header.mtime = 0o700 if stat.S_ISDIR(before.st_mode) else 0o600 | (before.st_mode & 0o100), int(before.st_mtime)
                        if stat.S_ISDIR(before.st_mode):
                            header.type = tarfile.DIRTYPE
                            archive.addfile(header)
                            records.append({"path": name, "kind": "directory", "size": 0})
                        else:
                            header.size = before.st_size
                            with open(path, "rb", opener=lambda p, flags: os.open(p, flags | os.O_NOFOLLOW)) as source:
                                reader = HashReader(source)
                                archive.addfile(header, reader)
                                if signature(os.fstat(source.fileno())) != signature(before):
                                    raise RuntimeError("Source changed during snapshot; no backup was published")
                            records.append({"path": name, "kind": "file", "size": header.size,
                                            "sha256": reader.digest.hexdigest()})
                    if [(name, signature(info)) for name, info in paths] != [(name, signature(info)) for name, info in source_paths(root)]:
                        raise RuntimeError("Source tree changed during snapshot; no backup was published")
                    if runtime_pins != pins(root):
                        raise RuntimeError("Runtime pins changed during snapshot")
                    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], text=True, capture_output=True)
                    manifest = {"kind": "exploreos_cold_backup_v1", "created_ns": time.time_ns(),
                                "git_commit": commit.stdout.strip() if commit.returncode == 0 else None,
                                "runtime_pins": runtime_pins, "records": records,
                                "scope": "ClawInstitute DB, project files and local service token; no standalone model-secret configuration, logs or runtime dependencies"}
                    encoded = json.dumps(manifest, ensure_ascii=False).encode()
                    header = tarfile.TarInfo(MANIFEST)
                    header.size, header.mode = len(encoded), 0o600
                    archive.addfile(header, io.BytesIO(encoded))
                output.flush()
                os.fsync(output.fileno())
            os.link(temporary, destination)  # Never replace an existing archive.
            descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return {"archive": str(destination), "entries": len(records),
                "data_bytes": sum(r["size"] for r in records), "model_requests": 0}
    finally:
        temporary.unlink(missing_ok=True)


def scan(path, destination=None, expected=None):
    records, seen, manifest, total = [], set(), None, 0
    with tarfile.open(path, "r|gz") as archive:
        for member in archive:
            name = member.name.rstrip("/")
            if name in seen or len(seen) >= MAX_FILES + 1:
                raise ValueError("Duplicate archive entries or too many entries")
            seen.add(name)
            if name == MANIFEST:
                if not member.isfile() or member.size > 64 * 1024**2:
                    raise ValueError("Invalid backup manifest")
                manifest = json.loads(archive.extractfile(member).read())
                continue
            if (manifest is not None or not allowed(name) or not (member.isfile() or member.isdir())
                    or (member.isdir() and member.size != 0)):
                raise ValueError("Unsupported archive path, link or entry type")
            total += member.size
            if total > MAX_BYTES or member.size < 0:
                raise ValueError("Archive exceeds the supported byte bound")
            item = {"path": name, "kind": "file" if member.isfile() else "directory", "size": member.size}
            target = destination / name if destination else None
            if member.isdir():
                if target:
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
            else:
                result = hashlib.sha256()
                if target:
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    output = open(target, "xb", opener=lambda p, flags: os.open(p, flags, 0o600 | (member.mode & 0o100)))
                else:
                    output = None
                try:
                    source = archive.extractfile(member)
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        result.update(block)
                        if output:
                            output.write(block)
                finally:
                    if output:
                        output.close()
                item["sha256"] = result.hexdigest()
            records.append(item)
    if (not manifest or manifest.get("kind") != "exploreos_cold_backup_v1" or manifest.get("records") != records
            or not any(r["path"].startswith(".runtime/service/db/") for r in records)
            or not any(r["path"] == ".runtime/service/home/token" for r in records)):
        raise ValueError("Backup manifest or payload checksum differs")
    if expected is not None and manifest != expected:
        raise ValueError("Archive changed between validation and restore")
    return manifest


def restore(root, archive):
    root = Path(root).resolve()
    manifest = scan(archive)
    if manifest["runtime_pins"] != pins(root):
        raise ValueError("Restore into a checkout with matching ClawInstitute/runtime pins")
    with offline(root):
        targets = [root / name for name in (*TREES, *EXTRAS)]
        for name in (*TREES, *EXTRAS):
            no_links(root, name)
        if any(path.exists() for path in targets):
            raise FileExistsError("Restore requires empty target data; existing research, DB, tokens and readiness records are never replaced")
        stage = root / ".runtime" / ("restore-" + uuid.uuid4().hex)
        stage.mkdir(mode=0o700)
        moved, rollback_failed = [], False
        try:
            scan(archive, stage, manifest)
            for target in targets:
                source = stage / target.relative_to(root)
                if source.exists():
                    if target.exists() or target.is_symlink():
                        raise FileExistsError("Target data appeared during restore")
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    os.rename(source, target)
                    moved.append((source, target))
        except BaseException:
            for source, target in reversed(moved):
                try:
                    source.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    os.rename(target, source)
                except OSError:
                    rollback_failed = True
            if rollback_failed:
                raise RuntimeError("Restore rollback could not finish; preserve the private restore staging directory for manual recovery")
            raise
        finally:
            if not rollback_failed:
                shutil.rmtree(stage)
    return {"restored": True, "entries": len(manifest["records"]), "git_commit": manifest["git_commit"],
            "model_requests": 0, "service_started": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "inspect", "restore"))
    parser.add_argument("archive", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.command == "create":
        result = create(args.root, args.archive)
    elif args.command == "restore":
        result = restore(args.root, args.archive)
    else:
        result = scan(args.archive)
        result = {"kind": result["kind"], "entries": len(result["records"]), "git_commit": result["git_commit"],
                  "data_bytes": sum(r["size"] for r in result["records"])}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError, tarfile.TarError) as error:
        raise SystemExit("Backup stopped: " + str(error))
