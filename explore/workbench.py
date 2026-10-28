"""Loopback exploration views and controls over the existing ClawInstitute state."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit

from scripts.cloud.runtime import ROOT
from .engine import Project
from .models import SimulatedBackend
from .store import Client, Conflict

WEB = Path(__file__).with_name("web")


class Workbench(ThreadingHTTPServer):
    def __init__(self, address, client=None):
        if address[0] != "127.0.0.1":
            raise ValueError("The development workbench binds only to loopback")
        super().__init__(address, Handler)
        self.client = client or Client()
        self.session = secrets.token_hex(32)
        self.workers = ThreadPoolExecutor(max_workers=2)
        self.observations = {}

    def project(self, name):
        if re.fullmatch(r"[a-z0-9_]{1,24}", name) is None:
            raise ValueError("Unknown project name")
        return Project(self.client, ROOT / ".research" / name)

    def advance(self, project, backend, budget_cny):
        gateway = None
        try:
            if backend == "simulated":
                adapter = SimulatedBackend(project.file.read()[0]["scenario"])
            else:
                from scripts.probe_native import session_budget
                from .models import ClaudeBackend, Gateway, PiBackend
                from .subagents import SubagentsBackend
                key = os.environ.get("DEEPSEEK_API_KEY")
                if not key:
                    raise RuntimeError("Configure DEEPSEEK_API_KEY before starting a real-model run")
                gateway = Gateway(key, session_budget(self.client, limit=budget_cny))
                adapter = {"pi": PiBackend, "claude": ClaudeBackend, "pi-subagents": SubagentsBackend}[backend](ROOT, gateway)
            project.advance(adapter)
            self.observations.pop(project.directory.name, None)
        except Exception as error:
            self.observations[project.directory.name] = {"error_type": type(error).__name__, "detail": str(error)}
        finally:
            if gateway:
                gateway.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, value, content_type="application/json; charset=utf-8", extra=None):
        data = json.dumps(value, ensure_ascii=False).encode() if content_type.startswith("application/json") else value
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        for key, val in (extra or {}).items():
            self.send_header(key, val)
        self.end_headers()
        self.wfile.write(data)

    def checked(self, mutation=False):
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected:
            self.send(403, {"error": "Open the workbench using its printed loopback address"})
            return False
        if self.path.startswith("/api/") and self.headers.get("X-ExploreOS-Session") != self.server.session:
            self.send(403, {"error": "Reload the workbench session"})
            return False
        if mutation and self.headers.get("Origin") != "http://" + expected:
            self.send(403, {"error": "Cross-origin controls are disabled"})
            return False
        return True

    def do_GET(self):
        if not self.checked():
            return
        try:
            path = urlsplit(self.path).path
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path in assets:
                name, mime = assets[path]
                data = (WEB / name).read_bytes().replace(b"__SESSION__", self.server.session.encode())
                self.send(200, data, mime)
                return
            if path == "/api/projects":
                projects = []
                for metadata in sorted((ROOT / ".research").glob("*/run_metadata.json")):
                    try:
                        project = self.server.project(metadata.parent.name)
                        state, _ = project.file.read()
                        if state.get("evaluation_binding"):
                            continue
                        projects.append({"name": state["name"], "status": state["status"], "mode": state["mode"],
                                         "question": state["question_revisions"][-1]["text"], "rounds": len(state["rounds"])})
                    except (OSError, RuntimeError, ValueError):
                        projects.append({"name": metadata.parent.name, "status": "unavailable", "question": "项目记录暂不可读"})
                self.send(200, {"projects": projects})
                return
            match = re.fullmatch(r"/api/project/([a-z0-9_]+)/([a-z-]+)(?:/([a-zA-Z0-9_-]+))?", path)
            if not match:
                self.send(404, {"error": "Unknown view"})
                return
            name, view, target = match.groups()
            project = self.server.project(name)
            if view == "export":
                self.send(200, project.export(project.directory / "exports"),
                          extra={"Content-Disposition": f'attachment; filename="{name}-export.json"'})
            elif view == "audit" and target:
                self.send(200, project.audit_source(target))
            elif view == "state":
                state, version = project.file.read()
                result = {key: state.get(key) for key in ("name", "status", "mode", "question_revisions", "directions",
                    "changes", "direction_history", "knowledge", "reviews", "source_assessments", "rounds", "schedule", "schedule_notifications", "cross_project_memory", "last_errors", "continuation_required")}
                result.update(version=version, posts=[{**entry, "content": json.loads(self.server.client.request(
                    "GET", "/posts/" + entry["id"])["content"])} for entry in state["posts"]],
                    calls=[{k: call.get(k) for k in ("id", "actor", "phase", "status", "round", "failure")} for call in state["calls"].values()],
                    events=state["events"][-100:], sources=[project.read_source(s) for s in state["sources"]],
                    observation=self.server.observations.get(name), workshop=project.metadata["workshop"],
                    native_workspace_url=f"http://127.0.0.1:{os.environ.get('EXPLORE_FRONTEND_PORT', '3001')}/m/{project.metadata['workshop']}",
                    record_kind=("not_run" if not state["calls"] else "mechanical_fixture" if all(
                        c["backend"] == "simulated" for c in state["calls"].values()) else "real_model_execution"))
                self.send(200, result)
            else:
                self.send(404, {"error": "Unknown view"})
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            self.send(409 if isinstance(error, Conflict) else 400, {"error": str(error)})

    def do_POST(self):
        if not self.checked(mutation=True):
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 16000 or not self.headers.get("Content-Type", "").startswith("application/json"):
                raise ValueError("Use a bounded JSON control request")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Control parameters must be an object")
            path = urlsplit(self.path).path
            if path == "/api/projects":
                question = data.get("question", "")
                if not isinstance(question, str) or not 1 <= len(question.strip()) <= 3000:
                    raise ValueError("Enter a question of 1–3000 characters")
                project = Project.create(self.server.client, data["name"], question=question, mode=data.get("mode", "collaborative"))
                self.send(201, project.status())
                return
            match = re.fullmatch(r"/api/project/([a-z0-9_]+)/([a-z-]+)", path)
            if not match:
                raise ValueError("Unknown control")
            name, action = match.groups()
            project = self.server.project(name)
            if action in ("pause", "resume", "cancel", "steer"):
                project.control(action, data.get("question"))
            elif action == "challenge":
                project.challenge(data["post_id"], data["reason"], data.get("source_id"))
            elif action == "reconcile":
                from scripts.probe_native import session_budget
                budget = session_budget(self.server.client) if (ROOT / ".research/session-budget.json").exists() else None
                project.reconcile(budget)
            elif action == "extend":
                project.extend(data.get("rounds", 1))
            elif action == "assess":
                project.assess_source(data["post_id"], data["basis_sha256"], data["verdict"],
                    data["reason"], data.get("reviewer", "user"), data["scope"], data["assessment_id"])
            elif action == "advance":
                backend = data.get("backend", "simulated")
                if backend not in ("simulated", "pi", "pi-subagents", "claude"):
                    raise ValueError("Unknown execution backend")
                self.server.workers.submit(self.server.advance, project, backend, data.get("budget_cny"))
                self.send(202, {"accepted": True, "qualification": "Project state and execution claims determine actual progress"})
                return
            else:
                raise ValueError("Unknown control")
            self.send(200, project.status())
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            self.send(409 if isinstance(error, Conflict) else 400, {"error": str(error)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=3388)
    args = parser.parse_args()
    server = Workbench(("127.0.0.1", args.port))
    print(f"ExploreOS workbench: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.workers.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    main()
