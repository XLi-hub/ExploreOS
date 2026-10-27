'use strict';

// Real PGlite, isolated from the development service. Baseline mode deliberately
// pauses two reads at the same version; it does not invent a database response.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const pkg = path.join(root, '.runtime/clawinstitute/node_modules/clawinstitute');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'explore-m0-files-'));
delete process.env.DATABASE_URL;
process.env.CLAWINSTITUTE_DB_DIR = path.join(temporary, 'db');
process.env.CLAWINSTITUTE_CHECKPOINT_MS = '0';
process.env.CLAWINSTITUTE_ALLOW_EPHEMERAL = '1';
const db = require(path.join(pkg, 'src/db/client.js'));
const baseline = process.argv.includes('--baseline');
let fault = false;

async function main() {
  await require(path.join(pkg, 'src/db/migrate.js')).runMigrations();
  if (baseline) {
    const originalQuery = db.query;
    let arrivals = 0;
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    const timer = setTimeout(() => release(), 3000);
    db.query = async (sql, params) => {
      const result = await originalQuery(sql, params);
      if (/SELECT id, path, content, version, updated_by, updated_at/.test(sql)
          && result.rows[0]?.content === 'pending') {
        if (++arrivals === 2) {
          clearTimeout(timer);
          release();
        }
        await gate;
      }
      return result;
    };
  } else {
    assert.equal(typeof db.transaction, 'function', 'Apply the tracked patch first');
    const originalTransaction = db.transaction;
    db.transaction = fn => originalTransaction(query => fn(async (sql, params) => {
      if (fault && /UPDATE ws_workspace_files/.test(sql)) {
        fault = false;
        throw new Error('injected interruption before file update');
      }
      return query(sql, params);
    }));
  }
  const files = require(path.join(pkg, 'src/services/WorkspaceFileService.js'));
  const workspace = await require(path.join(pkg, 'src/services/WorkspaceService.js'))
    .create({ title: 'M0 isolated atomic file acceptance' });
  const id = workspace.id;
  await files.write(id, 'claim.md', 'pending', 'fixture', null);
  const results = await Promise.allSettled([
    files.write(id, 'claim.md', 'claimed A', 'A', 1),
    files.write(id, 'claim.md', 'claimed B', 'B', 1),
  ]);
  const winners = results.filter(result => result.status === 'fulfilled').length;
  if (baseline) {
    assert.equal(winners, 2, 'The forced two-reader interleaving should expose the upstream race');
    console.log('REPRODUCED: two claimants both succeeded from version 1 in the unpatched service.');
    return;
  }
  assert.equal(winners, 1);
  assert.equal(results.find(r => r.status === 'rejected').reason.statusCode, 409);
  let current = await files.read(id, 'claim.md');
  assert.equal(current.version, 2);
  assert.deepEqual((await files.history(id, 'claim.md')).map(x => x.version), [2, 1]);

  // Retransmitting the same bytes is harmless only with the current version;
  // a stale retry must still conflict rather than imply a new successful claim.
  await files.write(id, 'claim.md', current.content, 'retry', 2);
  assert.equal((await files.read(id, 'claim.md')).version, 2);
  await assert.rejects(files.write(id, 'claim.md', current.content, 'retry', 1), { statusCode: 409 });
  await assert.rejects(files.write(id, 'missing.md', 'unexpected', 'A', 7), { statusCode: 409 });
  const creates = await Promise.allSettled(Array.from({ length: 8 }, (_, i) =>
    files.write(id, 'create-only.md', `creator ${i}`, `A${i}`, 0)));
  assert.equal(creates.filter(r => r.status === 'fulfilled').length, 1);
  for (const r of creates.filter(r => r.status === 'rejected')) assert.equal(r.reason.statusCode, 409);

  await files.write(id, 'patch.md', '---\nstatus: pending\n---\nbody', 'fixture', null);
  const patches = await Promise.allSettled(Array.from({ length: 8 }, (_, i) =>
    files.patchFrontmatter(id, 'patch.md', { status: `claimed_${i}` }, `A${i}`, 1)));
  assert.equal(patches.filter(r => r.status === 'fulfilled').length, 1);
  for (const r of patches.filter(r => r.status === 'rejected')) assert.equal(r.reason.statusCode, 409);
  await Promise.all(Array.from({ length: 8 }, (_, i) =>
    files.patchFrontmatter(id, 'patch.md', { [`field${i}`]: i }, `A${i}`, null)));
  const merged = files.parseFrontmatter((await files.read(id, 'patch.md')).content).frontmatter;
  for (let i = 0; i < 8; i++) assert.equal(merged[`field${i}`], i);
  assert.deepEqual((await files.history(id, 'patch.md')).map(x => x.version), [10,9,8,7,6,5,4,3,2,1]);

  fault = true;
  await assert.rejects(files.write(id, 'claim.md', 'must roll back', 'A', 2), /injected interruption/);
  current = await files.read(id, 'claim.md');
  assert.equal(current.version, 2);
  assert.equal((await files.history(id, 'claim.md')).length, 2);
  await files.write(id, 'claim.md', 'after rollback', 'A', 2);
  assert.deepEqual((await files.history(id, 'claim.md')).map(x => x.version), [3,2,1]);
  console.log('PASS: concurrent claims, create-only races, PUT/PATCH stale retries, merged patches, full history and transaction rollback.');
}

main().catch(error => { console.error(error.message); process.exitCode = 1; })
  .finally(async () => { await db.close(); fs.rmSync(temporary, { recursive: true, force: true }); });
