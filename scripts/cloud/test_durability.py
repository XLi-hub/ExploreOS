#!/usr/bin/env python3
"""Kill an isolated PGlite writer after CHECKPOINT; never touches service data."""
import os
import subprocess
import tempfile
import unittest

from runtime import ROOT

PACKAGE = ROOT / ".runtime/clawinstitute/node_modules/clawinstitute"
SCRIPT = r"""
const fs = require('node:fs');
const path = require('node:path');
const pkg = process.env.M0_PACKAGE;
const db = require(path.join(pkg, 'src/db/client.js'));
const files = require(path.join(pkg, 'src/services/WorkspaceFileService.js'));
(async () => {
  await require(path.join(pkg, 'src/db/migrate.js')).runMigrations();
  if (process.argv[1] === 'seed') {
    const ws = await require(path.join(pkg, 'src/services/WorkspaceService.js')).create({ title: 'isolated crash test' });
    await files.write(ws.id, 'checkpoint.md', 'version one', 'A', 0);
    await files.write(ws.id, 'checkpoint.md', 'version two', 'B', 1);
    await db.exec('CHECKPOINT');
    fs.writeFileSync(process.env.M0_METADATA, JSON.stringify({ id: ws.id }));
    console.log('M0_CHECKPOINT_READY');
    setInterval(() => {}, 1000);
  } else {
    const id = JSON.parse(fs.readFileSync(process.env.M0_METADATA)).id;
    const current = await files.read(id, 'checkpoint.md');
    const history = await files.history(id, 'checkpoint.md');
    if (current.content !== 'version two' || current.version !== 2 || history.length !== 2
        || history[1].content !== 'version one') throw new Error('checkpoint/history not recovered');
    await db.close();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
"""


class CheckpointRecoveryTests(unittest.TestCase):
    def test_sigkill_after_explicit_checkpoint(self):
        with tempfile.TemporaryDirectory(prefix="explore-m0-crash-") as directory:
            environment = os.environ.copy()
            environment.pop("DATABASE_URL", None)
            environment.update({"M0_PACKAGE": str(PACKAGE), "M0_METADATA": directory + "/metadata.json",
                                "CLAWINSTITUTE_DB_DIR": directory + "/db", "CLAWINSTITUTE_CHECKPOINT_MS": "0",
                                "CLAWINSTITUTE_ALLOW_EPHEMERAL": "1"})
            with tempfile.TemporaryFile(mode="w+") as output:
                process = subprocess.Popen(["node", "-e", SCRIPT, "seed"], env=environment,
                                           stdout=output, stderr=output)
                try:
                    import time
                    deadline = time.monotonic() + 20
                    ready = False
                    while time.monotonic() < deadline and process.poll() is None:
                        output.seek(0)
                        if "M0_CHECKPOINT_READY" in output.read():
                            ready = True
                            break
                        time.sleep(0.05)
                    self.assertTrue(ready, "Isolated child did not reach CHECKPOINT")
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
            subprocess.run(["node", "-e", SCRIPT, "verify"], env=environment,
                           capture_output=True, check=True, timeout=20)


if __name__ == "__main__":
    unittest.main()
