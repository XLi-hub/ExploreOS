"""CLI for bounded open exploration. Default commands never invoke paid models."""
import argparse
import getpass
import json
import os
from pathlib import Path

from scripts.cloud.runtime import ROOT
from scripts.probe_native import session_budget
from .engine import MODES, Project
from .models import ClaudeBackend, Gateway, PiBackend, SimulatedBackend
from .store import Client, atomic_local
from .subagents import SubagentsBackend
from . import assessments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("name")
    create.add_argument("--mode", choices=MODES, default="collaborative")
    create.add_argument("--scenario", choices=("split", "merge", "feedback"), default="split")
    create.add_argument("--question", help="Any open question; no metric or dataset required")
    create.add_argument("--participants", type=int, default=3)
    create.add_argument("--concurrency", type=int, default=2)
    create.add_argument("--source", action="append", default=[], help="Explicitly allowed UTF-8 material path; repeat for more materials")
    for name in ("advance", "status", "pause", "resume", "cancel", "reconcile", "export", "steer", "add-source", "memory", "reviews", "executions", "extend", "challenge", "retry", "source-audit", "assess-source", "link-memory"):
        command = sub.add_parser(name)
        command.add_argument("name")
        if name == "advance":
            command.add_argument("--backend", choices=("simulated", "pi", "claude", "pi-subagents"), default="simulated")
            command.add_argument("--budget-cny", type=float, help="Explicit budget for first paid run; existing pools are never reset")
        if name == "steer":
            command.add_argument("question")
        if name == "add-source":
            command.add_argument("path")
            command.add_argument("--title")
        if name == "extend":
            command.add_argument("--rounds", type=int, default=1)
        if name == "challenge":
            command.add_argument("post_id")
            command.add_argument("reason")
            command.add_argument("--source-id")
        if name == "retry":
            command.add_argument("slot")
            command.add_argument("reason")
        if name in ("source-audit", "assess-source"):
            command.add_argument("post_id")
        if name == "assess-source":
            command.add_argument("--basis-sha256", required=True, help="Fingerprint from the source-audit you inspected")
            command.add_argument("--verdict", choices=assessments.VERDICTS, required=True)
            command.add_argument("--reason", required=True)
            command.add_argument("--scope", required=True, help="What the cited material does and does not support")
            command.add_argument("--reviewer", default="user", help="Self-reported attribution, not authenticated identity")
            command.add_argument("--assessment-id", help="Stable ID to safely repeat a submission after an unknown response")
        if name == "link-memory":
            command.add_argument("origin_name")
            command.add_argument("post_id")
            command.add_argument("--conditions", required=True)
            command.add_argument("--reason", required=True)
    args = parser.parse_args()
    client = Client()
    if args.command == "create":
        sources = [(f"source{i}", Path(path).name, path, 1, 80) for i, path in enumerate(args.source)]
        project = Project.create(client, args.name, mode=args.mode, scenario=args.scenario,
                                 question=args.question, sources=sources or None, participants=args.participants,
                                 max_concurrency=args.concurrency)
    else:
        directory = (ROOT / ".research" / args.name).resolve()
        if directory.parent != (ROOT / ".research").resolve():
            raise ValueError("Project name must resolve directly below .research")
        project = Project(client, directory)
        if args.command == "advance":
            if args.backend in ("pi", "claude", "pi-subagents"):
                key = os.environ.get("DEEPSEEK_API_KEY") or getpass.getpass("DeepSeek API key (hidden): ")
                gateway = Gateway(key, session_budget(client, limit=args.budget_cny))
                try:
                    backend = {"pi": PiBackend, "claude": ClaudeBackend, "pi-subagents": SubagentsBackend}[args.backend]
                    project.advance(backend(ROOT, gateway))
                finally:
                    gateway.close()
            else:
                project.advance(SimulatedBackend(project.file.read()[0]["scenario"]))
        elif args.command == "reconcile":
            project.reconcile(session_budget(client) if (ROOT / ".research/session-budget.json").exists() else None)
        elif args.command == "export":
            project.export(project.directory / "exports")
        elif args.command == "add-source":
            print("Added material:", project.add_source(args.path, args.title))
        elif args.command == "extend":
            project.extend(args.rounds)
        elif args.command == "challenge":
            print("Published user challenge:", project.challenge(args.post_id, args.reason, args.source_id))
        elif args.command == "retry":
            pool = session_budget(client) if (ROOT / ".research/session-budget.json").exists() else None
            project.retry(args.slot, args.reason, pool)
        elif args.command == "source-audit":
            audit = project.audit_source(args.post_id)
            destination = project.directory / "audits" / audit["basis_sha256"]
            atomic_local(destination / "audit.json", audit)
            (destination / "audit.md").write_text(assessments.markdown(audit), encoding="utf-8")
            print(json.dumps({"audit": str(destination / "audit.md"), **audit}, ensure_ascii=False, indent=2))
        elif args.command == "assess-source":
            print("Recorded source assessment:", project.assess_source(args.post_id, args.basis_sha256,
                args.verdict, args.reason, args.reviewer, args.scope, args.assessment_id))
        elif args.command == "link-memory":
            from . import cross_memory
            origin_directory = (ROOT / ".research" / args.origin_name).resolve()
            if origin_directory.parent != (ROOT / ".research").resolve():
                raise ValueError("Choose a local project name")
            origin = Project(client, origin_directory)
            print("Linked qualified memory:", cross_memory.link(project, origin, args.post_id, args.conditions, args.reason))
        elif args.command == "memory":
            from .memory import Memory
            state, _ = project.file.read()
            print(json.dumps({actor: Memory(project.directory / "agents" / actor / "memory").index()
                              for actor in state["agents"]}, ensure_ascii=False, indent=2))
        elif args.command == "reviews":
            state, _ = project.file.read()
            print(json.dumps({"findings": list(state.get("knowledge", {}).values()),
                              "reviews": state.get("reviews", []),
                              "source_assessments": list(state.get("source_assessments", {}).values()),
                              "qualification": "Author responses preserve objections; no claim has been automatically verified"},
                             ensure_ascii=False, indent=2))
        elif args.command == "executions":
            print(json.dumps(project.execution_status(), ensure_ascii=False, indent=2))
        elif args.command in ("pause", "resume", "cancel", "steer"):
            project.control(args.command, getattr(args, "question", None))
    print(json.dumps(project.status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        raise SystemExit(f"Stopped: {error}")
