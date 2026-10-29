"""JSON controller bridge hosted by ClawInstitute's authenticated API."""
import json
import math
import os
from pathlib import Path
import re
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

from .credentials import model_key
from scripts.cloud.runtime import ROOT
from .engine import Project
from .models import SimulatedBackend
from .store import Budget, Client, JsonFile

MAX_CONTROL_BYTES = 96000  # Fits a 12 KB source even when JSON escapes each byte.

class NativeService:
    def __init__(self, client=None):
        self.client = client or Client()

    def project(self, name):
        if not isinstance(name, str) or re.fullmatch(r"[a-z0-9_]{1,24}", name) is None:
            raise ValueError("Unknown project name")
        return Project(self.client, ROOT / ".research" / name)

    def budget_view(self):
        reference = ROOT / ".research/session-budget.json"
        if not reference.exists():
            return None
        workspace = json.loads(reference.read_text())["workspace_id"]
        state, _ = JsonFile(self.client, workspace, "execution/session-budget.json").read()
        exposure = Budget.exposure(state)
        return {"limit_cny": state["limit_cny"], "exposure_cny": exposure,
                "remaining_cny": max(0, state["limit_cny"] - exposure),
                "requests": len(state["requests"]), "max_calls": state["max_calls"],
                "unknown_requests": sum(r["state"] == "unknown" for r in state["requests"].values())}

    def runtime(self):
        """Passive setup information only; never creates a pool or contacts a model."""
        from .models import PI_VERSION
        try:
            credential = "configured" if model_key() else "missing"
        except (OSError, RuntimeError):
            credential = "invalid"
        pi_ready = True
        for name in ("pi-agent-core", "pi-ai"):
            path = ROOT / ".runtime/pi/node_modules/@earendil-works" / name / "package.json"
            try:
                pi_ready = pi_ready and json.loads(path.read_text())["version"] == PI_VERSION
            except (OSError, ValueError, KeyError):
                pi_ready = False
        policy = "unknown"
        try:
            snapshot = json.loads(Path("/etc/codex/network-policy.json").read_text())
            network = snapshot.get("http_network_policy", {})
            if (snapshot.get("version") == 1 and network.get("type") == "restricted"
                    and not any(r.get("host") == "api.deepseek.com" for r in network.get("egress_rules", []))):
                policy = "not_allowed_at_startup"
        except (OSError, ValueError):
            pass
        return {"credential": credential, "pi_ready": pi_ready, "budget": self.budget_view(),
                "network": policy, "model": "DeepSeek", "network_checked": False}

    def validate_profile(self, data):
        if not isinstance(data, dict) or data.get("backend") not in ("simulated", "pi", "pi-subagents", "claude"):
            raise ValueError("Choose a supported exploration mode")
        profile = {"backend": data["backend"]}
        if data["backend"] != "simulated":
            budget = self.budget_view()
            limit = data.get("budget_cny", budget["limit_cny"] if budget else None)
            if isinstance(limit, bool) or not isinstance(limit, (float, int)) or not math.isfinite(limit) or limit <= 0:
                raise ValueError("Set a positive shared model budget before real exploration")
            if budget and limit != budget["limit_cny"]:
                raise ValueError("The existing shared model budget cannot be reset or increased here")
            profile["budget_cny"] = limit
        return profile

    def save_profile(self, project, data):
        profile = self.validate_profile(data)
        def save(state):
            project.assert_input_change_allowed(state)
            attempts = [*state["calls"].values(), *state.get("retired_calls", {}).values()]
            if any(call["backend"] != profile["backend"] for call in attempts):
                raise ValueError("This project already has another execution mode; create a new project to keep results separate")
            state["native_execution"] = profile
            project.event(state, "native_execution_configured", backend=profile["backend"])
        project.file.update("native-profile:" + uuid.uuid4().hex, save)
        return profile

    def projects(self):
        def read(metadata):
            try:
                project = self.project(metadata.parent.name)
                state, _ = project.file.read()
                if state.get("evaluation_binding"):
                    return None
                return {"name": state["name"], "status": state["status"], "mode": state["mode"],
                        "question": state["question_revisions"][-1]["text"], "rounds": len(state["rounds"]),
                        "last_activity_ns": (state["events"][-1]["time_ns"] if state["events"] else metadata.stat().st_mtime_ns)}
            except (OSError, RuntimeError, ValueError):
                return {"name": metadata.parent.name, "status": "unavailable", "question": "项目记录暂不可读"}
        # Each response is still read from ClawInstitute, with bounded read concurrency.
        with ThreadPoolExecutor(max_workers=8) as readers:
            result = readers.map(read, sorted((ROOT / ".research").glob("*/run_metadata.json")))
            return {"projects": sorted((entry for entry in result if entry is not None),
                                       key=lambda entry: entry.get("last_activity_ns", 0), reverse=True)}

    def state(self, project):
        state, version = project.file.read()
        attempts = [*state["calls"].values(), *state.get("retired_calls", {}).values()]
        fields = ("id", "actor", "phase", "status", "round", "failure", "backend")
        result = {key: state.get(key) for key in ("name", "status", "mode", "question_revisions", "directions",
            "changes", "direction_history", "knowledge", "reviews", "source_assessments", "rounds", "schedule",
            "schedule_notifications", "cross_project_memory", "last_errors", "continuation_required",
            "max_rounds", "max_concurrency", "evaluation_binding")}
        result["native_execution"] = state.get("native_execution")
        result.update(version=version, posts=[{**entry, "content": json.loads(self.client.request(
            "GET", "/posts/" + entry["id"])["content"])} for entry in state["posts"]],
            calls=[{"slot": slot, **{key: call.get(key) for key in fields}}
                   for slot, call in state["calls"].items()], events=state["events"][-100:],
            retired_calls=[{key: call.get(key) for key in fields} for call in state.get("retired_calls", {}).values()],
            participant_count=len(state["agents"]),
            sources=[project.read_source(source) for source in state["sources"]],
            observation=state.get("runtime_observation"), workshop=project.metadata["workshop"],
            native_workspace_url="/m/" + project.metadata["workshop"],
            native_files_url="/workspace/" + project.metadata["workspace_id"],
            record_kind=("not_run" if not attempts else "mechanical_fixture" if all(
                call["backend"] == "simulated" for call in attempts) else "real_model_execution" if any(
                call["backend"] != "simulated" and call["status"] == "completed" for call in attempts)
                else "incomplete_execution_case"))
        from .cross_memory import recall
        result["linked_memory_observations"] = recall(self.client, state)
        from .brief import build
        result["brief"] = build(result)
        return result

    def add_source(self, project, data):
        title, text = data.get("title"), data.get("text")
        if (not isinstance(title, str) or not 1 <= len(title.strip()) <= 160
                or not isinstance(text, str) or not text.strip() or "\x00" in text
                or len(text.encode("utf-8")) > 12000 or len(text.splitlines()) > 80):
            raise ValueError("Supply a title (1–160 characters) and nonempty UTF-8 material of at most 80 lines / 12000 bytes")
        project.assert_input_change_allowed(project.file.read()[0])
        folder = project.directory / "materials"
        folder.mkdir(exist_ok=True, mode=0o700)
        destination = folder / ("user_" + uuid.uuid4().hex + ".md")
        with open(destination, "x", encoding="utf-8", opener=lambda name, flags: os.open(name, flags, 0o600)) as output:
            output.write(text)
        return project.add_source(destination, title.strip())

    def advance(self, project, data):
        saved = project.file.read()[0].get("native_execution") or {}
        if saved and data.get("backend", saved["backend"]) != saved["backend"]:
            raise ValueError("Execution differs from this project's saved exploration settings")
        data = {**saved, **data}
        backend = data.get("backend", "simulated")
        if backend not in ("simulated", "pi", "pi-subagents", "claude"):
            raise ValueError("Unknown execution backend")
        gateway = None
        try:
            if backend == "simulated":
                adapter = SimulatedBackend(project.file.read()[0]["scenario"])
            else:
                from scripts.probe_native import session_budget
                from .models import ClaudeBackend, Gateway, PiBackend
                from .subagents import SubagentsBackend
                key = model_key()
                if not key:
                    raise RuntimeError("Current runtime has no DEEPSEEK_API_KEY; ClawInstitute login credentials are separate")
                gateway = Gateway(key, session_budget(self.client, limit=data.get("budget_cny")))
                adapter = {"pi": PiBackend, "claude": ClaudeBackend, "pi-subagents": SubagentsBackend}[backend](ROOT, gateway)
            project.advance(adapter)
            project.file.update("native-done:" + os.urandom(12).hex(), lambda s: s.pop("runtime_observation", None))
        except Exception as error:
            def record(state):
                state["runtime_observation"] = {"error_type": type(error).__name__, "detail": str(error)[:1000]}
                project.event(state, "native_controller_action_failed", error_type=type(error).__name__)
            project.file.update("native-error:" + os.urandom(12).hex(), record)
            raise
        finally:
            if gateway:
                gateway.close()
        return project.status()

    def handle(self, request):
        if not isinstance(request, dict) or not isinstance(request.get("action"), str):
            raise ValueError("Use an explicit native action")
        action, data = request["action"], request.get("data", {})
        if not isinstance(data, dict):
            raise ValueError("Control parameters must be an object")
        if action == "projects":
            return self.projects()
        if action == "runtime":
            return self.runtime()
        if action == "create":
            question = data.get("question", "")
            if not isinstance(question, str) or not 1 <= len(question.strip()) <= 3000:
                raise ValueError("Enter a question of 1–3000 characters")
            profile = self.validate_profile(data["execution"]) if "execution" in data else None
            name = data.get("name") or "q_" + uuid.uuid4().hex[:16]
            project = Project.create(self.client, name, question=question, mode=data.get("mode", "collaborative"),
                                     participants=data.get("participants", 3), max_concurrency=data.get("concurrency", 2))
            if profile:
                self.save_profile(project, profile)
            return project.status()
        project = self.project(request.get("name"))
        if action == "state":
            return self.state(project)
        if action == "brief":
            return self.state(project)["brief"]
        if action == "export":
            return project.export(project.directory / "exports")
        if action == "audit":
            return project.audit_source(request["target"])
        if action in ("pause", "resume", "cancel", "steer"):
            project.control(action, data.get("question"))
        elif action == "challenge":
            project.challenge(data["post_id"], data["reason"], data.get("source_id"))
        elif action == "assess":
            project.assess_source(data["post_id"], data["basis_sha256"], data["verdict"], data["reason"],
                                  data.get("reviewer", "user"), data["scope"], data["assessment_id"])
        elif action in ("reconcile", "retry"):
            from scripts.probe_native import session_budget
            budget = session_budget(self.client) if (ROOT / ".research/session-budget.json").exists() else None
            if action == "reconcile":
                project.reconcile(budget)
            else:
                if not isinstance(data.get("call_id"), str) or not data["call_id"]:
                    raise ValueError("Choose the actual failed invocation before authorizing retry")
                project.retry(data["slot"], data["reason"], budget, expected_call_id=data["call_id"])
        elif action == "add-source":
            self.add_source(project, data)
        elif action == "link-memory":
            from .cross_memory import link
            link(project, self.project(data["origin_name"]), data["post_id"], data["conditions"], data["reason"])
        elif action == "extend":
            project.extend(data.get("rounds", 1))
        elif action == "advance":
            return self.advance(project, data)
        elif action == "configure-execution":
            self.save_profile(project, data)
        else:
            raise ValueError("Unknown native action")
        return project.status()


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_CONTROL_BYTES + 1)
        if len(raw) > MAX_CONTROL_BYTES:
            raise ValueError("Native control payload exceeds its bound")
        result = NativeService().handle(json.loads(raw))
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)[:1000], "error_type": type(error).__name__}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
