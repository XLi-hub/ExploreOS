"""Finite local wakeups; Project owns all model execution and recovery state."""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from pathlib import Path

from scripts.cloud.runtime import ROOT
from .engine import Project, alive, process_identity
from .models import REAL_BACKENDS, SimulatedBackend
from .store import Client, Conflict


def configure(project, interval_seconds, *, backend="simulated", additional_rounds=0, now=None):
    if type(interval_seconds) is not int or not 60 <= interval_seconds <= 604800:
        raise ValueError("Choose an interval between one minute and seven days")
    if backend not in ("simulated", *REAL_BACKENDS) or type(additional_rounds) is not int or not 0 <= additional_rounds <= 20:
        raise ValueError("Choose a documented backend and authorize at most 20 additional rounds")
    due = int(time.time() if now is None else now) + interval_seconds
    operation = "configure-schedule:" + uuid.uuid4().hex
    def change(state):
        if state.get("controller") and alive(state["controller"]["process"]):
            raise Conflict("Pause and drain the current controller before reconfiguring wakeups")
        prior = state.get("schedule", {})
        state["max_rounds"] += additional_rounds
        state["schedule"] = {"enabled": False, "generation": prior.get("generation", 0) + 1,
            "interval_seconds": interval_seconds, "next_due": due, "backend": backend,
            "end_round": state["max_rounds"], "notification_channel": "local_project_records_only"}
        project.event(state, "schedule_configured", interval_seconds=interval_seconds,
                      additional_rounds=additional_rounds, qualification="Disabled until explicitly enabled; supplier budget is unchanged")
        return state["schedule"]
    return project.file.update(operation, change)


def enable(project, budget=None):
    def change(state):
        schedule = state.get("schedule")
        if schedule is None:
            raise ValueError("Configure a finite schedule before enabling it")
        if schedule["backend"] in REAL_BACKENDS and budget is None:
            raise ValueError("A real-model schedule requires the existing explicit shared budget")
        if budget:
            schedule["budget_workspace"] = budget.file.workspace
        schedule["enabled"] = True
        project.event(state, "schedule_enabled", generation=schedule["generation"])
        return True
    return project.file.update("enable-schedule:" + uuid.uuid4().hex, change)


def disable(project, *, cancel=False):
    def change(state):
        schedule = state.get("schedule")
        if schedule:
            schedule["enabled"] = False
            schedule["generation"] += 1
        # Stop new dispatch immediately in the same CAS. Owned calls can drain.
        running = any(c["status"] in ("starting", "running") for c in state["calls"].values())
        state["status"] = "cancelling" if cancel and running else "paused"
        if cancel and not running and state["rounds"] and state["rounds"][-1]["status"] == "active":
            state["rounds"][-1]["status"] = "cancelled"
        project.event(state, "schedule_disabled", current_calls="cancel" if cancel else "drain")
        return True
    return project.file.update("disable-schedule:" + uuid.uuid4().hex, change)


def tick(project, backend, *, budget=None, now=None):
    observed_time = int(time.time() if now is None else now)
    owner = process_identity()
    def claim(state):
        schedule = state.get("schedule", {})
        if not schedule.get("enabled") or observed_time < schedule["next_due"] or state["status"] != "active":
            return None
        if schedule["backend"] != backend.name:
            raise Conflict("Wakeup backend differs from the configured profile")
        if backend.name in REAL_BACKENDS and (budget is None or budget.file.workspace != schedule.get("budget_workspace")):
            raise Conflict("Wakeup is not bound to its authorized shared budget")
        completed = bool(state["rounds"] and state["rounds"][-1]["status"] in ("completed", "cancelled"))
        target = len(state["rounds"]) + (1 if not state["rounds"] or completed else 0)
        pending = schedule.get("trigger")
        if pending and pending["generation"] == schedule["generation"] and not pending.get("handled"):
            if alive(pending.get("process")):
                return None
            target = pending["round_target"]
            recovered = {**pending, "process": owner}
            schedule["trigger"] = recovered
            return recovered
        if pending and pending["generation"] == schedule["generation"] and pending.get("outcome") != "completed":
            target = pending["round_target"]
        if target > schedule["end_round"]:
            schedule["enabled"] = False
            project.event(state, "schedule_round_limit_reached", end_round=schedule["end_round"])
            return None
        attempt = pending.get("attempt", 0) + 1 if pending else 1
        trigger = {"id": f"wake:{schedule['generation']}:{schedule['next_due']}:{attempt}", "attempt": attempt,
                   "generation": schedule["generation"], "round_target": target,
                   "process": owner, "handled": False,
                   "findings_before": len(state.get("knowledge", {})), "changes_before": len(state["direction_history"])}
        schedule["trigger"] = trigger
        return trigger
    trigger = project.file.update("wake-claim:" + uuid.uuid4().hex, claim)
    if trigger is None:
        return {"action": "idle"}
    outcome = "completed"
    try:
        state, _ = project.file.read()
        target = trigger["round_target"]
        if not (len(state["rounds"]) >= target and state["rounds"][target - 1]["status"] == "completed"):
            project.reconcile(budget)
            state, _ = project.file.read()
            if any(c["status"] in ("unknown", "failed", "failed_before_dispatch", "invalid_output") for c in state["calls"].values()):
                raise RuntimeError("Inspect existing failed or unknown outcomes before another scheduled dispatch")
            project.advance(backend, trigger=trigger)
        state, _ = project.file.read()
        if len(state["rounds"]) < target or state["rounds"][target - 1]["status"] != "completed":
            outcome = "paused_or_incomplete"
    except Exception:
        outcome = "needs_attention"
        raise
    finally:
        def finish(state):
            schedule = state.get("schedule", {})
            current = schedule.get("trigger", {})
            if current.get("id") != trigger["id"]:
                return False
            current.update(handled=True, outcome=outcome)
            if outcome == "completed":
                while schedule["next_due"] <= observed_time:
                    schedule["next_due"] += schedule["interval_seconds"]
                if trigger["round_target"] >= schedule["end_round"]:
                    schedule["enabled"] = False
            if (outcome != "completed" or len(state.get("knowledge", {})) > trigger["findings_before"]
                    or len(state["direction_history"]) > trigger["changes_before"]):
                state.setdefault("schedule_notifications", []).append({"id": trigger["id"], "outcome": outcome,
                    "round": trigger["round_target"], "qualification": "Local stage/error notice; new records are not proof of useful or true findings"})
            project.event(state, "schedule_wakeup_observed", trigger_id=trigger["id"], outcome=outcome)
            return True
        project.file.update("wake-finish:" + trigger["id"], finish)
    return {"action": outcome, "round": trigger["round_target"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("configure", "enable", "disable", "tick", "watch", "status"))
    parser.add_argument("name")
    parser.add_argument("--interval-seconds", type=int, default=86400)
    parser.add_argument("--additional-rounds", type=int, default=0)
    parser.add_argument("--backend", choices=("simulated", *REAL_BACKENDS), default="simulated")
    parser.add_argument("--budget-cny", type=float)
    parser.add_argument("--cancel", action="store_true")
    args = parser.parse_args()
    from .evaluation import identifier
    identifier(args.name)
    client = Client()
    project = Project(client, ROOT / ".research" / args.name)
    state, _ = project.file.read()
    profile = state.get("schedule", {}).get("backend", "simulated")
    gateway, budget = None, None
    if args.command in ("enable", "tick", "watch") and profile in REAL_BACKENDS:
        from scripts.probe_native import session_budget
        budget = session_budget(client, limit=args.budget_cny)
        if not os.environ.get("DEEPSEEK_API_KEY"):
            raise RuntimeError("Configure DEEPSEEK_API_KEY for real scheduled execution")
        if args.command in ("tick", "watch"):
            from .models import ClaudeBackend, Gateway, PiBackend
            from .subagents import SubagentsBackend
            gateway = Gateway(os.environ["DEEPSEEK_API_KEY"], budget)
            backend = {"pi": PiBackend, "claude": ClaudeBackend, "pi-subagents": SubagentsBackend}[profile](ROOT, gateway)
    else:
        backend = SimulatedBackend(state["scenario"])
    try:
        if args.command == "configure":
            print(configure(project, args.interval_seconds, backend=args.backend, additional_rounds=args.additional_rounds))
        elif args.command == "enable":
            print(enable(project, budget))
        elif args.command == "disable":
            print(disable(project, cancel=args.cancel))
        elif args.command in ("tick", "watch"):
            while True:
                print(json.dumps(tick(project, backend, budget=budget)), flush=True)
                if args.command == "tick" or not project.file.read()[0].get("schedule", {}).get("enabled"):
                    break
                time.sleep(5)
        else:
            print(json.dumps({"schedule": state.get("schedule"), "notices": state.get("schedule_notifications", [])}, ensure_ascii=False, indent=2))
    finally:
        if gateway:
            gateway.close()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        raise SystemExit(f"Stopped: {error}")
