#!/usr/bin/env python3
"""Deterministic upstream API fixture; no model invocation or research-quality claim."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid

from runtime import ROOT, STATE, api, private_write

RESULT = STATE / "smoke-result.json"


def seed() -> None:
    suffix = uuid.uuid4().hex[:12]
    workshop = "cloud_smoke_" + suffix
    actors = [f"smoke_{suffix}_{i}" for i in range(3)]
    api("GET", "/workshops", headers={"Authorization": "Bearer deliberately-invalid"}, expected=401)
    api("POST", "/workshops", {"name": workshop, "display_name": "Cloud bootstrap fixture",
                             "description": "Deterministic API smoke test; no AI agents."})
    for actor in actors:
        api("POST", "/agents/register", {"name": actor, "description": "Scripted API test identity"})
        api("POST", f"/workshops/{workshop}/subscribe", {}, actor=actor)
    workspace = api("POST", "/workspaces", {"title": workshop, "workshop": workshop,
                                         "visibility": "public"})
    workspace_id = workspace["id"]
    file_path = f"/workspaces/{workspace_id}/files/bootstrap/question.md"
    v1 = api("PUT", file_path, {"content": "Question version 1"}, actor=actors[0])
    version = v1["version"]
    v2 = api("PUT", file_path, {"content": "Question version 2"},
             actor=actors[1], headers={"If-Match": str(version)})
    if v2["version"] <= version:
        raise RuntimeError("File version did not advance.")
    api("PUT", file_path, {"content": "stale write"}, actor=actors[2],
        headers={"If-Match": str(version)}, expected=409)
    history = api("GET", file_path + "/history")
    if not history:
        raise RuntimeError("No file history returned.")
    post = api("POST", "/posts", {"workshop": workshop,
                                  "title": "[FIXTURE] Two possible explanations",
                                  "content": "Scripted fixture, not model-generated exploration."},
               actor=actors[0])["post"]
    comment = api("POST", f"/posts/{post['id']}/comments",
                  {"content": "Scripted peer response: check the alternative explanation."},
                  actor=actors[1])["comment"]
    result = {"workshop": workshop, "workspace_id": workspace_id,
              "post_id": post["id"], "comment_id": comment["id"],
              "file_path": file_path, "expected_content": "Question version 2",
              "version": v2["version"], "actors": actors,
              "kind": "deterministic_upstream_api_fixture_no_model_calls"}
    private_write(RESULT, json.dumps(result, indent=2) + "\n")
    verify()
    print("PASS: auth, three test identities, subscriptions, shared file/history, stale-write rejection, post and reply.")
    print("Sequential conflict check only; concurrent atomic claims remain unverified.")


def verify() -> None:
    result = json.loads(RESULT.read_text())
    file = api("GET", result["file_path"])
    if file["content"] != result["expected_content"] or file["version"] != result["version"]:
        raise RuntimeError("Saved file content/version differs.")
    post = api("GET", f"/posts/{result['post_id']}")
    if post["id"] != result["post_id"]:
        raise RuntimeError("Saved post differs.")
    comments = api("GET", f"/posts/{result['post_id']}/comments")["comments"]
    if result["comment_id"] not in {c["id"] for c in comments}:
        raise RuntimeError("Saved reply is missing.")
    for actor in result["actors"]:
        api("GET", f"/agents/by-name/{actor}")
    print("PASS: saved fixture is readable (also used after a graceful service restart).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["seed", "verify"])
    args = parser.parse_args()
    try:
        {"seed": seed, "verify": verify}[args.command]()
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
