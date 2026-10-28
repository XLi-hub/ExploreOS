#!/usr/bin/env python3
"""Apply the audited release patch, or check it, without accepting unknown files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "cloud/patches/clawinstitute-0.1.3-atomic-files.patch"
MANIFEST = ROOT / "cloud/patches/manifest.json"
PACKAGE = ROOT / ".runtime/clawinstitute/node_modules/clawinstitute"


def apply_set(manifest_path, patch, *, check):
    manifest = json.loads(manifest_path.read_text())
    package = json.loads((PACKAGE / "package.json").read_text())
    if package["name"] != manifest["package"] or package["version"] != manifest["version"]:
        raise RuntimeError("Patch target differs from the audited release.")
    states = []
    for name, hashes in manifest["files"].items():
        target = PACKAGE / name
        digest = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        if digest == hashes["after_sha256"]:
            states.append("patched")
        elif digest == hashes["before_sha256"]:
            states.append("original")
        else:
            raise RuntimeError(f"Unexpected upstream edits in {name}; preserve and inspect them.")
    if all(state == "patched" for state in states):
        return
    if check or not all(state == "original" for state in states):
        raise RuntimeError("Atomic file patch is missing or partially applied; run patch_upstream.py.")
    command = ["git", "apply", f"--directory={PACKAGE.relative_to(ROOT)}"]
    subprocess.run([*command, "--check", str(patch)], cwd=ROOT, check=True)
    subprocess.run([*command, str(patch)], cwd=ROOT, check=True)
    apply_set(manifest_path, patch, check=True)


def check_or_apply(*, check: bool = False) -> None:
    apply_set(MANIFEST, PATCH, check=check)
    apply_set(ROOT / "cloud/patches/idempotent-posts.json",
              ROOT / "cloud/patches/idempotent-posts.patch", check=check)
    apply_set(ROOT / "cloud/patches/native-exploration.json",
              ROOT / "cloud/patches/native-exploration.patch", check=check)
    apply_set(ROOT / "cloud/patches/native-admin-login.json",
              ROOT / "cloud/patches/native-admin-login.patch", check=check)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    check_or_apply(check=args.check)
    print("PASS: audited ClawInstitute atomic-file, idempotent-publication, native-exploration and admin-login patches.")
