#!/usr/bin/env python3
"""M0 API acceptance and portable fixture export; never invokes a model."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import threading
import uuid

import requests

from runtime import STATE, RECORD, TOKEN, api, private_write

RESULT = STATE / "m0-api.json"
EXPORT = STATE / "m0-api-export.json"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def race(method, path, version, bodies, actors, header_name="If-Match"):
    """Start requests together; inspect HTTP status without printing response secrets."""
    barrier = threading.Barrier(len(bodies))
    port = int(json.loads(RECORD.read_text())["port"])
    token = TOKEN.read_text().strip()

    def request(item):
        index, body = item
        with requests.Session() as session:
            session.trust_env = False  # loopback service only
            barrier.wait(timeout=10)
            response = session.request(
                method, f"http://127.0.0.1:{port}/api/v1{path}", json=body,
                headers={"Authorization": "Bearer " + token, header_name: str(version),
                         "X-Agent-Name": actors[index % len(actors)]}, timeout=15,
            )
            return response.status_code

    with ThreadPoolExecutor(len(bodies)) as pool:
        statuses = list(pool.map(request, enumerate(bodies)))
    require(statuses.count(200) == 1 and statuses.count(409) == len(bodies) - 1,
            f"Expected one winner and only version conflicts, got {statuses}")
    return statuses


def seed():
    suffix = uuid.uuid4().hex[:10]
    workshop = "m0_" + suffix
    actors = [f"m0_{suffix}_{i}" for i in range(3)]
    api("POST", "/workshops", {"name": workshop, "display_name": "M0 API acceptance"})
    for actor in actors:
        first = api("POST", "/agents/register", {"name": actor})["agent"]
        second = api("POST", "/agents/register", {"name": actor})["agent"]
        require(first["id"] == second["id"], "Repeated registration changed identity")
        api("POST", f"/workshops/{workshop}/subscribe", {}, actor=actor)
    workspace = api("POST", "/workspaces", {"title": workshop, "workshop": workshop})
    base = f"/workspaces/{workspace['id']}/files/"
    api("PUT", base + "claim.md", {"content": "pending"})
    put = race("PUT", base + "claim.md", 1,
               [{"content": f"claim {i}"} for i in range(8)], actors)
    claim = api("GET", base + "claim.md")
    api("PUT", base + "claim.md", {"content": claim["content"]}, headers={"If-Match": "2"})
    require(api("GET", base + "claim.md")["version"] == 2, "Exact retry created a revision")
    api("PUT", base + "claim.md", {"content": claim["content"]},
        headers={"If-Match": "1"}, expected=409)
    api("PUT", base + "absent.md", {"content": "must not create"},
        headers={"If-Match": "7"}, expected=409)
    create = race("PUT", base + "created.md", 0,
                  [{"content": f"creator {i}"} for i in range(8)], actors)
    native_create = race("PUT", base + "native-lock.md", "*",
                         [{"content": f"holder {i}"} for i in range(8)], actors,
                         header_name="If-None-Match")
    api("PUT", base + "native-lock.md", {"content": "invalid"},
        headers={"If-None-Match": "*", "If-Match": "1"}, expected=400)
    api("PUT", base + "patch.md", {"content": "---\nstate: pending\n---\naction"})
    patch = race("PATCH", base + "patch.md", 1,
                 [{"frontmatter": {"state": f"claimed_{i}"}} for i in range(8)], actors)
    api("PATCH", base + "patch.md", {"frontmatter": {"state": "stale"}},
        headers={"If-Match": "1"}, expected=409)
    history = api("GET", base + "claim.md/history")["history"]
    require([entry["version"] for entry in history] == [2, 1], "Claim history has a gap")
    # No server-side operation-id facility: verify the gap instead of auto-retrying POST.
    body = {"workshop": workshop, "title": "[FIXTURE] duplicate submission probe",
            "content": "Identical requests intentionally sent twice; no model content."}
    posts = [api("POST", "/posts", body, actor=actors[0])["post"] for _ in range(2)]
    require(posts[0]["id"] != posts[1]["id"], "Duplicate POST behavior changed; review idempotency")
    comment = api("POST", f"/posts/{posts[0]['id']}/comments",
                  {"content": "Deterministic peer reply"}, actor=actors[1])["comment"]
    snapshots = {name: api("GET", base + name) for name in ["claim.md", "created.md", "native-lock.md", "patch.md"]}
    result = {"kind": "m0_api_mechanics_no_model_calls", "workshop": workshop,
              "workspace_id": workspace["id"], "actors": actors,
              "post_ids": [post["id"] for post in posts], "comment_id": comment["id"],
              "files": snapshots, "race_statuses": {"put": put, "patch": patch, "create": create, "native_create": native_create},
              "duplicate_posts_deduplicated": False}
    private_write(RESULT, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    export_fixture()
    print("PASS: HTTP PUT/PATCH/create races (1 success, 7 conflicts each), stale retries, identity reuse, history and export.")
    print("KNOWN GAP: identical POST submissions create different posts; automatic POST retries are unsafe.")


def export_fixture():
    result = json.loads(RESULT.read_text())
    base = f"/workspaces/{result['workspace_id']}/files/"
    payload = {"kind": result["kind"], "workshop": result["workshop"],
               "workspace_id": result["workspace_id"], "files": {}, "posts": []}
    for name, saved in result["files"].items():
        current = api("GET", base + name)
        require(current["version"] == saved["version"] and current["content"] == saved["content"],
                f"Saved fixture differs: {name}")
        payload["files"][name] = {"file": current, "history": api("GET", base + name + "/history")}
    for post_id in result["post_ids"]:
        post = api("GET", f"/posts/{post_id}")
        comments = api("GET", f"/posts/{post_id}/comments")["comments"]
        payload["posts"].append({"post": post, "comments": comments})
    require(result["comment_id"] in {c["id"] for p in payload["posts"] for c in p["comments"]},
            "Saved reply missing")
    for actor in result["actors"]:
        api("GET", f"/agents/by-name/{actor}")
    # Export only an allowlist. Registration responses contain the shared API token.
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    require(TOKEN.read_text().strip() not in encoded, "Service token must not enter an export")
    private_write(EXPORT, encoded)
    return hashlib.sha256(encoded.encode()).hexdigest()


def verify():
    before = hashlib.sha256(EXPORT.read_bytes()).hexdigest()
    after = export_fixture()
    require(before == after, "Quiescent export changed across restart")
    print("PASS: restart preserved identities, files, complete histories, posts and reply; export hash unchanged.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["seed", "verify", "export"])
    args = parser.parse_args()
    try:
        {"seed": seed, "verify": verify, "export": export_fixture}[args.command]()
    except (OSError, ValueError, RuntimeError, KeyError, requests.RequestException) as error:
        # Requests exceptions may include details; do not serialize headers or bodies.
        print(f"ERROR: M0 acceptance failed ({type(error).__name__}).")
        raise SystemExit(1)
