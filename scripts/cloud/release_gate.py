#!/usr/bin/env python3
"""Verify recorded product acceptance and same-commit CI before publishing."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from explore.assessments import digest
from explore.evaluation import runtime_manifest

REQUIRED_ACCEPTANCE = ("m1_quality_review", "m2_repeated_evaluation", "persistent_deployment")
REQUIRED_WORKFLOWS = ("ExploreOS cloud checks", "ExploreOS product container")
VERSION_PATTERN = r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"


def acceptance_errors(record, fingerprint, tag, notes):
    errors = []
    if not re.fullmatch(VERSION_PATTERN, tag):
        errors.append("Use an explicit stable version vMAJOR.MINOR.PATCH")
    if record.get("version") != tag:
        errors.append("Acceptance record does not match the requested release version")
    if record.get("runtime_sha256") != fingerprint:
        errors.append("Recorded acceptance belongs to a different exploration runtime")
    for name in REQUIRED_ACCEPTANCE:
        entry = record.get("acceptance", {}).get(name, {})
        evidence = entry.get("evidence")
        if entry.get("status") != "accepted" or not isinstance(evidence, str) or not evidence.strip():
            errors.append(f"Acceptance pending: {name}")
    if "状态：发布就绪" not in notes.splitlines():
        errors.append("Release notes are still a draft")
    return errors


def select_verified_artifact(runs, artifacts, sha):
    selected = {}
    for name in REQUIRED_WORKFLOWS:
        candidates = [r for r in runs if r.get("name") == name and r.get("head_sha") == sha
                      and r.get("head_branch") == "main" and r.get("event") == "push"]
        if not candidates:
            raise ValueError("Missing main CI for this exact commit: " + name)
        latest = max(candidates, key=lambda r: r["id"])
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            raise ValueError("Latest same-commit main CI has not passed: " + name)
        selected[name] = latest
    expected = "exploreos-linux-amd64-" + sha
    matches = [a for a in artifacts if a.get("name") == expected and not a.get("expired")
               and a.get("workflow_run", {}).get("head_sha") == sha
               and a.get("workflow_run", {}).get("id") == selected[REQUIRED_WORKFLOWS[-1]]["id"]]
    if len(matches) != 1:
        raise ValueError("Require one unexpired product artifact from the verified main run")
    return selected[REQUIRED_WORKFLOWS[-1]]["id"], matches[0]["name"]


def github(path):
    return json.loads(subprocess.check_output(["gh", "api", path], text=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="v0.1.0")
    parser.add_argument("--repository", default="XLi-hub/ExploreOS")
    parser.add_argument("--github-checks", action="store_true")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    record = json.loads((ROOT / ".release/acceptance.json").read_text())
    if not re.fullmatch(VERSION_PATTERN, args.tag):
        raise ValueError("Use an explicit stable release version before selecting notes")
    notes = (ROOT / "docs/releases" / (args.tag + ".md")).read_text()
    errors = acceptance_errors(record, digest(runtime_manifest()), args.tag, notes)
    if errors:
        print(json.dumps({"publishable": False, "blockers": errors}, ensure_ascii=False))
        return 1
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if args.github_checks:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
            raise ValueError("Invalid repository")
        ref = subprocess.check_output(["git", "rev-parse", args.tag + "^{commit}"], cwd=ROOT, text=True).strip()
        if ref != sha:
            raise ValueError("The release tag does not identify the checked-out commit")
        subprocess.run(["git", "merge-base", "--is-ancestor", sha, "origin/main"], cwd=ROOT, check=True)
        prefix = "repos/" + args.repository + "/actions/"
        runs = github(prefix + "runs?head_sha=" + sha + "&event=push&branch=main&per_page=100")["workflow_runs"]
        product_runs = [r for r in runs if r.get("name") == REQUIRED_WORKFLOWS[-1]]
        if not product_runs:
            raise ValueError("No product build for this commit")
        run_id = max(product_runs, key=lambda r: r["id"])["id"]
        artifacts = github(prefix + f"runs/{run_id}/artifacts")["artifacts"]
        run_id, name = select_verified_artifact(runs, artifacts, sha)
        if args.github_output:
            with args.github_output.open("a") as output:
                output.write(f"run_id={run_id}\nartifact_name={name}\n")
    print(json.dumps({"acceptance_record_passed": True, "github_checks_passed": args.github_checks,
                      "commit": sha, "qualification": "Recorded acceptance and CI do not independently prove claim truth"}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit("Release blocked: " + str(error))
