#!/usr/bin/env python3
"""Restore a cold snapshot into an isolated PGlite instance; never calls a model."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.cloud import backup
from scripts.cloud.runtime import ROOT, RECORD, start, stop
from explore.store import Budget, Client, JsonFile, atomic_local

SCRIPT = r"""
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const root=process.env.BACKUP_CHECK_ROOT;
const record=JSON.parse(fs.readFileSync(path.join(root,process.env.BACKUP_CHECK_RECORD),'utf8'));
const pkg=process.env.BACKUP_CHECK_PACKAGE;
const db=require(path.join(pkg,'src/db/client.js'));
const files=require(path.join(pkg,'src/services/WorkspaceFileService.js'));
const digest=text=>crypto.createHash('sha256').update(text).digest('hex');
(async()=>{
 try{
  for(const item of record.files){
   const file=await files.read(item.workspace_id,item.path);
   assert.equal(digest(file.content),item.sha256,'Restored content differs');
   assert.equal(file.version,item.version,'Restored file version differs');
  }
  const history=await files.history(record.workspace_id,'materials/probe.md');
  assert.deepEqual(history.map(item=>({version:item.version,sha256:digest(item.content)})),record.history);
  for(const item of record.posts){
   const row=(await db.query('SELECT content FROM posts WHERE id=$1',[item.id])).rows[0];
   assert.equal(digest(row.content),item.sha256,'Restored post differs');
  }
  for(const item of record.comments){
   const row=(await db.query('SELECT content FROM comments WHERE id=$1',[item.id])).rows[0];
   assert.equal(digest(row.content),item.sha256,'Restored reply differs');
  }
  for(const name of record.actors){
   assert.equal((await db.query('SELECT name FROM agents WHERE name=$1',[name])).rows[0].name,name);
  }
  const ledger=JSON.parse((await files.read(record.workspace_id,'execution/backup-test-budget.json')).content);
  assert.equal(ledger.limit_cny,1);
  assert.equal(ledger.requests[record.unknown_request].state,'unknown');
  assert(ledger.requests[record.unknown_request].reserved_cny>0);
  assert(!fs.existsSync(path.join(root,'.runtime/secrets/deepseek-api-key')));
  console.log('PASS: isolated restored PGlite preserves materials, full history, identities, posts/replies, project state and budget exposure.');
 }finally{await db.close()}
})().catch(error=>{console.error(error.message);process.exitCode=1});
"""


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def seed():
    client, suffix = Client(), uuid.uuid4().hex[:12]
    workshop = "bk_" + suffix
    actors = [workshop + "_a", workshop + "_b"]
    client.request("POST", "/workshops", {"name": workshop, "display_name": "Zero-model backup verification"})
    for actor in actors:
        client.request("POST", "/agents/register", {"name": actor, "description": "Deterministic backup fixture"})
        client.request("POST", f"/workshops/{workshop}/subscribe", {}, actor=actor)
    workspace = client.request("POST", "/workspaces", {"title": workshop, "workshop": workshop})["id"]
    endpoint = f"/workspaces/{workspace}/files/materials/probe.md"
    first = client.request("PUT", endpoint, {"content": "早期材料：仍需检查适用条件。"}, actor=actors[0], version=0)
    client.request("PUT", endpoint, {"content": "后续材料：保留原范围和未决异议。"}, actor=actors[1], version=first["version"])
    post = client.request("POST", "/posts", {"workshop": workshop, "title": "[FIXTURE] Backup integrity",
        "content": "Deterministic persistence fixture; no supplier request or quality claim."}, actor=actors[0])["post"]
    comment = client.request("POST", f"/posts/{post['id']}/comments", {"content": "Keep the original unresolved condition."}, actor=actors[1])["comment"]
    budget = Budget(JsonFile(client, workspace, "execution/backup-test-budget.json"), limit=1, prior=0)
    unknown = "backup-fixture-" + suffix
    budget.admit(unknown, 100, 900, metadata={"fixture": "No supplier was contacted; restore must retain this synthetic unknown reservation"})
    references = [(workspace, "materials/probe.md"), (workspace, "execution/backup-test-budget.json")]
    pool = ROOT / ".research/session-budget.json"
    if pool.exists():
        references.append((json.loads(pool.read_text())["workspace_id"], "execution/session-budget.json"))
    sample = ROOT / ".research/workbench_demo/run_metadata.json"
    if sample.exists():
        references.append((json.loads(sample.read_text())["workspace_id"], "exploration/state.json"))
    files = []
    for workspace_id, path in references:
        file = client.request("GET", f"/workspaces/{workspace_id}/files/{path}")
        files.append({"workspace_id": workspace_id, "path": path, "version": file["version"], "sha256": sha(file["content"])})
    history = client.request("GET", endpoint + "/history")["history"]
    record = {"kind": "deterministic_backup_fixture_no_model_calls", "workspace_id": workspace,
              "actors": actors, "files": files, "unknown_request": unknown,
              "history": [{"version": item["version"], "sha256": sha(item["content"])} for item in history],
              "posts": [{"id": post["id"], "sha256": sha(post["content"])}],
              "comments": [{"id": comment["id"], "sha256": sha(comment["content"])}]}
    relative = ".research/backup_checks/" + suffix + ".json"
    atomic_local(ROOT / relative, record)
    return relative


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="New private archive to retain; existing destinations are never overwritten")
    args = parser.parse_args()
    if not RECORD.exists():
        raise RuntimeError("Start the owned service before running backup verification")
    archive = args.archive or ROOT / ".runtime/backups" / ("verified-" + uuid.uuid4().hex + ".tar.gz")
    backup.no_controllers(ROOT)
    record = seed()
    backup.no_controllers(ROOT)
    stop()
    try:
        summary = backup.create(ROOT, archive)
        with tempfile.TemporaryDirectory(prefix="backup-restore-check-", dir=ROOT / ".runtime") as temporary:
            target = Path(temporary)
            for name in backup.PINS:
                (target / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target / name)
            backup.restore(target, archive)
            environment = os.environ.copy()
            environment.pop("DATABASE_URL", None)
            environment.update({"BACKUP_CHECK_ROOT": str(target), "BACKUP_CHECK_RECORD": record,
                "BACKUP_CHECK_PACKAGE": str(ROOT / ".runtime/clawinstitute/node_modules/clawinstitute"),
                "CLAWINSTITUTE_DB_DIR": str(target / ".runtime/service/db"), "CLAWINSTITUTE_CHECKPOINT_MS": "0"})
            result = subprocess.run(["node", "-e", SCRIPT], env=environment, text=True, capture_output=True, timeout=120)
            if result.returncode:
                raise RuntimeError("Isolated restored database verification failed: " + result.stderr[-1000:])
            print(result.stdout.strip())
        print(json.dumps(summary))
    finally:
        start()  # Only the collaboration service; never starts exploration/watchers.


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        raise SystemExit("Backup verification stopped: " + str(error))
