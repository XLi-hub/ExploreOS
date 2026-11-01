"""Installation-helper behavior with a fake Docker CLI, no daemon or model calls."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.bundle = Path(self.temporary.name)
        shutil.copyfile(ROOT / "scripts/distribution/exploreos.sh", self.bundle / "exploreos.sh")
        for name, text in {
            "compose.yaml": "services: {}\n",
            ".env.example": "DEEPSEEK_API_KEY=\n",
            "IMAGE_ID.txt": "sha256:expected\n",
            "SOURCE_COMMIT.txt": "a" * 40 + "\n",
            "exploreos-image.tar.gz": "fixture image",
        }.items():
            (self.bundle / name).write_text(text)
        checksums = []
        for name in ("compose.yaml", ".env.example", "IMAGE_ID.txt", "SOURCE_COMMIT.txt",
                     "exploreos-image.tar.gz", "exploreos.sh"):
            checksums.append(hashlib.sha256((self.bundle / name).read_bytes()).hexdigest() + "  " + name)
        (self.bundle / "SHA256SUMS").write_text("\n".join(checksums) + "\n")
        cli = self.bundle / "bin"
        cli.mkdir()
        docker = cli / "docker"
        docker.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ["EXPLOREOS_HELPER_TEST_ROOT"])
with (root / "commands.jsonl").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["image", "inspect"]:
    loaded = (root / "loaded").exists()
    print("sha256:expected" if loaded and not os.environ.get("EXPLOREOS_HELPER_BAD_LOAD") else "sha256:other")
elif sys.argv[1] == "load":
    (root / "loaded").touch()
""")
        docker.chmod(0o700)
        self.environment = {**os.environ, "PATH": str(cli) + os.pathsep + os.environ["PATH"],
                            "EXPLOREOS_HELPER_TEST_ROOT": str(self.bundle)}

    def run_helper(self, command, expected=0):
        result = subprocess.run(["bash", str(self.bundle / "exploreos.sh"), command],
                                cwd="/", env=self.environment, text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def commands(self):
        path = self.bundle / "commands.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_start_loads_exact_image_and_creates_private_configuration(self):
        self.run_helper("start")
        self.assertEqual((self.bundle / ".env").stat().st_mode & 0o777, 0o600)
        self.assertIn(["load", "-i", "exploreos-image.tar.gz"], self.commands())
        self.assertIn(["compose", "up", "--no-build", "-d", "--wait", "--wait-timeout", "180"], self.commands())
        self.assertFalse(any("down" in command or "--volumes" in command for command in self.commands()))

    def test_start_preserves_user_configuration(self):
        (self.bundle / ".env").write_text("PRIVATE_CONFIG=retained\n")
        self.run_helper("start")
        self.assertEqual((self.bundle / ".env").read_text(), "PRIVATE_CONFIG=retained\n")

    def test_changed_bundle_and_wrong_loaded_image_cannot_start(self):
        (self.bundle / "compose.yaml").write_text("tampered")
        self.run_helper("start", expected=1)
        self.assertEqual(self.commands(), [])
        (self.bundle / "compose.yaml").write_text("services: {}\n")
        self.environment["EXPLOREOS_HELPER_BAD_LOAD"] = "1"
        self.run_helper("start", expected=1)
        self.assertFalse(any(command[:2] == ["compose", "up"] for command in self.commands()))

    def test_verify_and_help_are_offline_and_stop_retains_volumes(self):
        self.run_helper("verify")
        self.run_helper("help")
        self.assertEqual(self.commands(), [])
        self.run_helper("stop")
        self.assertIn(["compose", "stop"], self.commands())
        self.assertFalse(any("down" in command or "--volumes" in command for command in self.commands()))


if __name__ == "__main__":
    unittest.main()
