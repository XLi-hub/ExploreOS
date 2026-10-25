#!/usr/bin/env python3
"""Zero-model mechanical demo of source -> objection -> review -> revised memory."""
import argparse
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from explore.engine import MODES, Project
from explore.models import SimulatedBackend
from explore.store import Client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="feedback_" + uuid.uuid4().hex[:10])
    parser.add_argument("--mode", choices=MODES, default="collaborative")
    args = parser.parse_args()
    project = Project.create(Client(), args.name, mode=args.mode, scenario="feedback",
        question="读书小组怎样在关注点改变后继续利用旧发现与分歧？",
        sources=[("initial", "合成初始情景", "examples/feedback/initial.md", 1, 80)],
        question_author="evaluation_script")
    backend = SimulatedBackend("feedback")
    project.advance(backend)
    state, _ = project.file.read()
    target = next(iter(state["knowledge"]))
    source = project.add_source("examples/feedback/counterexample.md", "合成反例情景")
    challenge = project.challenge(target, "初始片段没有覆盖关注点改变，原设想的适用范围需要复查", source,
                                  author_type="evaluation_script")
    project.control("steer", "检查新反例会怎样限制原设想，同时保留原始问题与分歧", author="evaluation_script")
    project.advance(backend)
    project.export(project.directory / "exports")
    result, _ = project.file.read()
    print(json.dumps({"project": args.name, "kind": "mechanical_fixture", "model_calls": 0,
                      "target_post": target, "challenge_post": challenge, "reviews": result["reviews"],
                      "brief": str(project.directory / "exports/brief.md"),
                      "qualification": "Scripted outputs verify mechanics, not the usefulness or truth of the revision"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
