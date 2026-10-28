"""JSON controller bridge hosted by ClawInstitute's authenticated API."""
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from .credentials import model_key
from scripts.cloud.runtime import ROOT
from .engine import Project
from .models import SimulatedBackend
from .store import Client


class NativeService:
    def __init__(self, client=None):
        self.client = client or Client()

    def project(self, name):
        if not isinstance(name, str) or re.fullmatch(r"[a-z0-9_]{1,24}", name) is None:
            raise ValueError("Unknown project name")
        return Project(self.client, ROOT / ".research" / name)

    def projects(self):
        def read(metadata):
            try:
                project = self.project(metadata.parent.name)
                state, _ = project.file.read()
                if state.get("evaluation_binding"):
                    return None
                return {"name": state["name"], "status": state["status"], "mode": state["mode"],
                        "question": state["question_revisions"][-1]["text"], "rounds": len(state["rounds"])}
            except (OSError, RuntimeError, ValueError):
                return {"name": metadata.parent.name, "status": "unavailable", "question": "项目记录暂不可读"}
        # Each response is still read from ClawInstitute, with bounded read concurrency.
        with ThreadPoolExecutor(max_workers=8) as readers:
            result = readers.map(read, sorted((ROOT / ".research").glob("*/run_metadata.json")))
            return {"projects": [entry for entry in result if entry is not None]}

    def state(self, project):
        state, version = project.file.read()
        result = {key: state.get(key) for key in ("name", "status", "mode", "question_revisions", "directions",
            "changes", "direction_history", "knowledge", "reviews", "source_assessments", "rounds", "schedule",
            "schedule_notifications", "cross_project_memory", "last_errors", "continuation_required")}
        result.update(version=version, posts=[{**entry, "content": json.loads(self.client.request(
            "GET", "/posts/" + entry["id"])["content"])} for entry in state["posts"]],
            calls=[{key: call.get(key) for key in ("id", "actor", "phase", "status", "round", "failure")}
                   for call in state["calls"].values()], events=state["events"][-100:],
            sources=[project.read_source(source) for source in state["sources"]],
            observation=state.get("runtime_observation"), workshop=project.metadata["workshop"],
            native_workspace_url="/m/" + project.metadata["workshop"],
            native_files_url="/workspace/" + project.metadata["workspace_id"],
            record_kind=("not_run" if not state["calls"] else "mechanical_fixture" if all(
                call["backend"] == "simulated" for call in state["calls"].values()) else "real_model_execution"))
        return result

    def advance(self, project, data):
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
        if action == "create":
            question = data.get("question", "")
            if not isinstance(question, str) or not 1 <= len(question.strip()) <= 3000:
                raise ValueError("Enter a question of 1–3000 characters")
            project = Project.create(self.client, data["name"], question=question, mode=data.get("mode", "collaborative"),
                                     participants=data.get("participants", 3), max_concurrency=data.get("concurrency", 2))
            return project.status()
        project = self.project(request.get("name"))
        if action == "state":
            return self.state(project)
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
        elif action == "reconcile":
            from scripts.probe_native import session_budget
            budget = session_budget(self.client) if (ROOT / ".research/session-budget.json").exists() else None
            project.reconcile(budget)
        elif action == "extend":
            project.extend(data.get("rounds", 1))
        elif action == "advance":
            return self.advance(project, data)
        else:
            raise ValueError("Unknown native action")
        return project.status()


def main():
    try:
        raw = sys.stdin.buffer.read(16001)
        if len(raw) > 16000:
            raise ValueError("Native control payload exceeds its bound")
        result = NativeService().handle(json.loads(raw))
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)[:1000], "error_type": type(error).__name__}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
