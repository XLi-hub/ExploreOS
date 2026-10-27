"""An observed foreground plugin receipt, never an independently writable run state."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .models import PI_VERSION, PiBackend

PLUGIN_VERSION = "0.82.0"
TERMINAL = {"completed", "failed", "timed_out", "cancelled", "interrupted", "tool_budget_exhausted",
            "structured_output_failed", "acceptance_failed", "invalid_request", "unavailable_context", "duplicate_node"}


def reference(call_id):
    digest = hashlib.sha256(call_id.encode()).hexdigest()
    return {"kind": "pi-subagents-foreground-v1", "call_id": call_id,
            "requestId": "exploreos-" + digest[:32], "ownerRunId": call_id.split(":", 1)[0],
            "nodeId": call_id.split(":attempt", 1)[0], "receipt": f"delegations/{digest}/receipt.json"}


def read_receipt(directory, call_id):
    expected = reference(call_id)
    path = Path(directory) / expected["receipt"]
    if not path.resolve().is_relative_to(Path(directory).resolve()):
        raise ValueError("Delegation receipt escaped its invocation directory")
    if not path.exists():
        return None
    if path.stat().st_size > 100_000:
        raise ValueError("Delegation receipt exceeded its bounded format")
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError("Delegation receipt is incomplete") from error
    if (not isinstance(data, dict) or type(data.get("version")) is not int or data.get("version") != 1
            or data.get("backend") != "pi-subagents" or not isinstance(data.get("state"), str)
            or data["state"] not in {"preparing", "running", "terminal", "host_failed"}
            or type(data.get("emitted")) is not bool
            or data.get("pi_version") != PI_VERSION or data.get("plugin_version") != PLUGIN_VERSION
            or any(data.get(key) != expected[key] for key in ("call_id", "requestId", "ownerRunId", "nodeId"))
            or type(data.get("provider_requests")) is not int or not 0 <= data["provider_requests"] <= 1):
        raise ValueError("Delegation receipt does not match this invocation")
    response = data.get("response")
    if data["state"] != "terminal" and response is not None:
        raise ValueError("A nonterminal receipt cannot carry a terminal response")
    if data.get("state") == "terminal":
        if data["emitted"] is not True:
            raise ValueError("A terminal leaf must have been delegated")
        if (not isinstance(response, dict) or not isinstance(response.get("status"), str) or response["status"] not in TERMINAL
                or any(response.get(key) != expected[key] for key in ("requestId", "ownerRunId", "nodeId"))):
            raise ValueError("Delegation terminal response has an unknown identity or status")
        if response["status"] == "completed":
            profile = data.get("profile", {})
            result = response.get("result")
            usage = response.get("usage")
            if (data["provider_requests"] != 1 or not isinstance(response.get("runId"), str) or not response["runId"]
                    or response["runId"] != data.get("runId")
                    or response.get("launchContractDigest") != data.get("preflight_launch_digest")
                    or not isinstance(data.get("preflight_launch_digest"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", data["preflight_launch_digest"])
                    or not isinstance(profile, dict)
                    or profile.get("context") != "fresh" or profile.get("tools") != []
                    or any(profile.get(key) is not False for key in
                           ("inheritProjectContext", "inheritGlobalContext", "inheritSkills"))
                    or not isinstance(result, dict) or result.get("kind") != "text"
                    or not isinstance(result.get("text"), str)
                    or not isinstance(usage, dict) or usage.get("turns") != 1 or usage.get("toolCalls") != 0):
                raise ValueError("Completed plugin response lacks the bounded launch/result proof")
    return data


def terminal(data):
    return data is not None and data.get("state") == "terminal"


class SubagentsBackend(PiBackend):
    name = "pi-subagents"
    runtime_directory = "subagents"
    runner_script = "subagents_runner.mjs"
    setup_script = "setup_subagents.sh"
    extra_executor_metadata = {"pi_subagents": PLUGIN_VERSION, "pi_coding_agent": PI_VERSION}

    def __init__(self, root, gateway, timeout=95):
        super().__init__(root, gateway, timeout)
        modules = root / ".runtime/subagents/node_modules"
        for name, version in (("pi-subagents", PLUGIN_VERSION), ("@earendil-works/pi-coding-agent", PI_VERSION)):
            path = modules / name / "package.json"
            if not path.is_file() or json.loads(path.read_text())["version"] != version:
                raise RuntimeError("Install the pinned plugin host with bash scripts/cloud/setup_subagents.sh")

    def execution_reference(self, call_id, directory):
        return reference(call_id)

    def invocation_details(self, call_id, directory):
        ref = reference(call_id)
        path = directory / ref["receipt"]
        if path.exists():
            raise RuntimeError("A delegation receipt already exists; reconcile it instead of redispatching")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        return {"host_dir": str(path.parent / "host"), "receipt_path": str(path),
                "request_id": ref["requestId"], "owner_run_id": ref["ownerRunId"], "node_id": ref["nodeId"]}

    def receipt_metadata(self, result, call_id, directory):
        data = read_receipt(directory, call_id)
        if not terminal(data) or data["response"]["status"] != "completed":
            raise RuntimeError("Plugin completion needs its matching terminal receipt")
        response = data["response"]
        if result.get("plugin_version") != PLUGIN_VERSION or result.get("result") != response["result"]["text"]:
            raise RuntimeError("Plugin stdout and persisted result do not match")
        if result.get("delegation") != {key: response[key] for key in
                ("requestId", "ownerRunId", "nodeId", "runId", "status", "launchContractDigest")}:
            raise RuntimeError("Plugin stdout and persisted completion refer to different runs")
        return {**super().receipt_metadata(result, call_id, directory), "plugin_version": PLUGIN_VERSION,
                "delegation": result["delegation"], "execution_reference": reference(call_id)}
