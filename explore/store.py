"""Versioned state and execution admission, with ClawInstitute as sole authority."""
from __future__ import annotations

import copy
import json
import math
import time
import uuid
from pathlib import Path

import requests

from scripts.cloud.runtime import RECORD, TOKEN


class Conflict(RuntimeError):
    pass


class AdmissionError(RuntimeError):
    pass


class Client:
    def __init__(self):
        try:
            record = json.loads(RECORD.read_text())
        except FileNotFoundError:
            raise RuntimeError("Start this checkout's service with scripts/cloud/runtime.py start") from None
        self.base = f"http://127.0.0.1:{int(record['port'])}/api/v1"
        self.token = TOKEN.read_text().strip()

    def request(self, method, path, body=None, *, actor=None, version=None):
        headers = {"Authorization": "Bearer " + self.token}
        if actor:
            headers["X-Agent-Name"] = actor
        if version is not None:
            headers["If-Match"] = str(version)
        with requests.Session() as session:
            session.trust_env = False  # Only the loopback collaboration service.
            response = session.request(method, self.base + path, json=body, headers=headers, timeout=15)
        if response.status_code == 409:
            raise Conflict("Shared version or publication operation conflicts")
        if not response.ok:
            raise RuntimeError(f"Collaboration API {method} {path}: HTTP {response.status_code}")
        return response.json() if response.content else None

    def publish(self, workshop, actor, operation, kind, content):
        body = {"workshop": workshop, "operation_id": operation,
                "title": f"[{kind.upper()}] {actor}", "content": json.dumps(content, ensure_ascii=False)}
        # The service transaction deduplicates this exact operation and content.
        for attempt in range(2):
            try:
                return self.request("POST", "/posts", body, actor=actor)["post"]["id"]
            except (requests.Timeout, requests.ConnectionError):
                if attempt:
                    raise


class JsonFile:
    def __init__(self, client, workspace, path):
        self.client, self.workspace, self.path = client, workspace, path
        self.endpoint = f"/workspaces/{workspace}/files/{path}"

    def create(self, initial):
        initial = copy.deepcopy(initial)
        initial.setdefault("_operations", {})
        try:
            self.client.request("PUT", self.endpoint, {"content": json.dumps(initial)}, version=0)
        except Conflict:
            existing, _ = self.read()
            if existing.get("kind") != initial.get("kind"):
                raise RuntimeError("Existing shared file has another schema")

    def read(self):
        file = self.client.request("GET", self.endpoint)
        return json.loads(file["content"]), file["version"]

    def update(self, operation, mutate):
        """Only pure state changes inside mutate; external effects follow commit."""
        for attempt in range(40):
            state, version = self.read()
            if operation in state["_operations"]:
                return state["_operations"][operation]
            result = mutate(state)
            state["_operations"][operation] = result
            try:
                self.client.request("PUT", self.endpoint, {"content": json.dumps(state)}, version=version)
                return result
            except (Conflict, requests.Timeout, requests.ConnectionError):
                # Stable operation keys reconcile an unknown PUT before any replay.
                time.sleep(min(attempt * 0.002, 0.03))
        raise Conflict("Shared file remained busy; no external action was dispatched")


class Budget:
    """One shared pool across projects, native CLI requests and direct adapters."""
    def __init__(self, file, limit=5, prior=2.10214, max_calls=64):
        if (isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(limit) or limit <= 0
                or isinstance(prior, bool) or not isinstance(prior, (int, float)) or not math.isfinite(prior)
                or not 0 <= prior <= limit or type(max_calls) is not int or not 1 <= max_calls <= 10000):
            raise AdmissionError("Budget and prior exposure must be finite, nonnegative and within the authorized limit")
        self.file = file
        file.create({"kind": "execution_budget_v1", "limit_cny": limit, "prior_cny": prior,
                     "max_calls": max_calls, "requests": {}})
        state, _ = file.read()
        if (state["limit_cny"], state["prior_cny"], state["max_calls"]) != (limit, prior, max_calls):
            raise AdmissionError("Budget configuration differs from the existing authorized pool")

    @staticmethod
    def exposure(state):
        return state["prior_cny"] + sum(r.get("settled_cny", r["reserved_cny"]) for r in state["requests"].values())

    def admit(self, call_id, input_bytes, output_tokens, metadata=None):
        if type(input_bytes) is not int or input_bytes < 0 or type(output_tokens) is not int or output_tokens <= 0:
            raise AdmissionError("Token admission bounds must be nonnegative integer sizes")
        # Admission is byte-bounded at deliberately conservative CNY token prices.
        ceiling = ((input_bytes + 512) * 20 + output_tokens * 80) / 1_000_000

        def change(state):
            if call_id in state["requests"]:
                raise AdmissionError("Supplier outcome already exists or is unknown; automatic retry denied")
            if len(state["requests"]) >= state["max_calls"] or self.exposure(state) + ceiling > state["limit_cny"]:
                raise AdmissionError("Authorized supplier budget exhausted")
            state["requests"][call_id] = {"reserved_cny": ceiling, "state": "unknown", "started_ns": time.time_ns()}
            state["requests"][call_id].update(input_bytes=input_bytes, max_output_tokens=output_tokens,
                                               request_metadata=metadata or {})
            return True

        # A fresh HTTP request cannot replay an earlier admission operation.
        self.file.update("admit:" + call_id + ":" + uuid.uuid4().hex, change)
        return ceiling

    def settle(self, call_id, usage, *, received=True, output=None, metadata=None):
        def change(state):
            record = state["requests"][call_id]
            record.update(ended_ns=time.time_ns(), usage=usage, state="received" if received else "unknown")
            if output is not None:
                record["output"] = output
            if metadata:
                record["response_metadata"] = metadata
            keys = ("input_tokens", "output_tokens")
            if all(type(usage.get(key)) is int and usage[key] >= 0 for key in keys):
                amount = (usage["input_tokens"] * 20 + usage["output_tokens"] * 80) / 1_000_000
                # Never interpret an inconsistent supplier report as more allowance.
                if amount <= record["reserved_cny"]:
                    record["settled_cny"] = amount
            return True
        self.file.update("settle:" + call_id, change)


def atomic_local(path: Path, value):
    """Private context/reference projection; never an alternative shared database."""
    import os
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".pending")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory_fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
