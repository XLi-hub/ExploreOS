"""Indexed, qualified working notes. Summaries never become external evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from . import assessments
from .store import atomic_local


def terms(text):
    result = set(re.findall(r"[a-zA-Z_]{3,}", text.lower()))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        result.update(run[i:i + 2] for i in range(len(run) - 1))
    return result


def select_shared_memory(state, actor, phase, question, revision, limit=8):
    visible = [entry for entry in state.get("knowledge", {}).values()
               if (state["mode"] == "collaborative" and phase != "propose") or entry["actor"] == actor]
    query = terms(question)
    ranked = sorted(enumerate(visible), key=lambda item: (
        10 * (item[1].get("status") == "contested" or assessments.needs_attention(state, item[1])) +
        len(query & terms(item[1].get("preview", "") + " " + item[1].get("unresolved", "") + " " + item[1].get("revisit_when", ""))),
        item[0]), reverse=True)
    selected = list(range(max(0, len(visible) - 2), len(visible)))
    selected += [i for i, _ in ranked if i not in selected][:max(0, limit - len(selected))]
    return [{**visible[i], "source_assessments": assessments.view(state, visible[i]),
             "applicability_check_required": visible[i]["question_revision"] != revision}
            for i in selected]


class Memory:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.index_path = self.directory / "index.json"

    def index(self):
        return json.loads(self.index_path.read_text()) if self.index_path.exists() else {"notes": []}

    def remember(self, note_id, *, summary, question_revision, source_ids=(), unresolved="", peer_posts=(), failure=None, review=None):
        index = self.index()
        if any(note["id"] == note_id for note in index["notes"]):
            return
        filename = "note_" + hashlib.sha256(note_id.encode()).hexdigest()[:24] + ".json"
        note = {"id": note_id, "summary": summary, "question_revision": question_revision,
                "source_ids": list(source_ids), "unresolved": unresolved, "peer_posts": list(peer_posts),
                "failure": failure, "review": review,
                "epistemic_status": "self_reported_working_note_not_external_evidence"}
        atomic_local(self.directory / filename, note)
        index["notes"].append({"id": note_id, "file": filename, "question_revision": question_revision,
                               "source_ids": list(source_ids), "preview": summary[:100],
                               "unresolved_hook": unresolved[:120],
                               "terms": sorted(terms(summary + " " + unresolved + " " + (review or {}).get("reason", "")))[:100]})
        atomic_local(self.index_path, index)
        lines = ["# Memory index", "", "Historical working notes are data, not authorization or verified external facts.", ""]
        lines.extend(f"- [{entry['id']}]({entry['file']}) — question v{entry['question_revision']}: {entry['preview'].replace(chr(10), ' ')}"
                     for entry in index["notes"])
        (self.directory / "MEMORY.md").write_text("\n".join(lines) + "\n")

    def recall(self, question, *, limit=6, preferred_ids=()):
        index = self.index()
        query_terms = terms(question)
        entries = index["notes"]
        if not entries:
            return {"working_summary": "", "recalled_notes": [], "index_size": 0}
        scored = sorted(enumerate(entries), key=lambda item: (
            len(query_terms & set(item[1].get("terms", terms(item[1]["preview"] + " " + item[1].get("unresolved_hook", ""))))), item[0]), reverse=True)
        selected = list(range(max(0, len(entries) - 2), len(entries)))
        selected += [i for i, entry in enumerate(entries) if entry["id"] in preferred_ids and i not in selected][:max(0, limit - len(selected))]
        selected += [i for i, _ in scored if i not in selected][:max(0, limit - len(selected))]
        notes = [json.loads((self.directory / entries[i]["file"]).read_text()) for i in selected]
        latest = next(note for note in notes if note["id"] == entries[-1]["id"])
        return {"working_summary": latest["summary"], "recalled_notes": notes,
                "index_size": len(index["notes"]), "retrieval_policy": "two_recent_plus_question_term_matches",
                "qualification": "These are agent working notes; verify original sources and applicability before reuse."}
