import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = {path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
             for path in (ROOT / ".github/workflows").glob("*.yml")}
if os.name == "nt":
    BASH = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
    BASH = str(BASH) if BASH.is_file() else None
else:
    BASH = shutil.which("bash")


class WorkflowTests(unittest.TestCase):
    def test_release_writes_are_scoped_to_publication_and_cleanup(self):
        for filename, workflow in WORKFLOWS.items():
            self.assertEqual(workflow["permissions"], {"contents": "read"})
            for job_name, job in workflow["jobs"].items():
                if job.get("permissions", {}).get("contents") == "write":
                    self.assertIn(job_name, {"aggregate-release", "cleanup"})
        self.assertEqual(WORKFLOWS["build.yml"]["jobs"]["notify"]["permissions"], {})

    def test_cleanup_and_build_share_the_same_lock(self):
        locks = [workflow["concurrency"] for workflow in WORKFLOWS.values()]
        self.assertEqual(locks[0], locks[1])
        self.assertFalse(locks[0]["cancel-in-progress"])

    def test_actions_are_pinned_and_checkout_does_not_persist_tokens(self):
        for workflow in WORKFLOWS.values():
            for job in workflow["jobs"].values():
                for step in job["steps"]:
                    if "uses" in step:
                        self.assertRegex(step["uses"], r"@[0-9a-f]{40}$")
                    if step.get("uses", "").startswith("actions/checkout@"):
                        self.assertFalse(step["with"]["persist-credentials"])

    def test_scripts_do_not_interpolate_actions_expressions(self):
        for workflow in WORKFLOWS.values():
            for job in workflow["jobs"].values():
                for step in job["steps"]:
                    self.assertNotIn("${{", step.get("run", ""), step.get("name", "run"))

    @unittest.skipUnless(BASH, "Bash is required for shell syntax checks")
    def test_all_shell_steps_parse(self):
        for filename, workflow in WORKFLOWS.items():
            for job in workflow["jobs"].values():
                for step in job["steps"]:
                    if "run" in step:
                        with self.subTest(workflow=filename, step=step.get("name")):
                            result = subprocess.run([BASH, "-n"], input=step["run"], text=True, encoding="utf-8",
                                                    capture_output=True)
                            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(BASH, "Bash is required for the injection regression check")
    def test_external_tag_is_data_and_cannot_escape_the_output_filename(self):
        step = next(step for step in WORKFLOWS["build.yml"]["jobs"]["build"]["steps"]
                    if step.get("name") == "Nomear APK")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "app-morphe.apk").write_bytes(b"apk")
            env = {**os.environ, "APP_DISPLAY_NAME": "App", "APP_VERSION": "1",
                   "PATCHES_VERSION": "v1$(touch injected);../[a]\nvalue", "OUTPUT_NAME": "app",
                   "GITHUB_ENV": (root / "env").as_posix()}
            result = subprocess.run([BASH, "--noprofile", "--norc", "-c", step["run"]],
                                    cwd=root, env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / "injected").exists())
            assets = list(root.glob("*.apk"))
            self.assertEqual(len(assets), 1)
            self.assertTrue(re.fullmatch(r"[A-Za-z0-9._-]+\.apk", assets[0].name))
            self.assertEqual(assets[0].read_bytes(), b"apk")
            self.assertEqual((root / "env").read_text().count("\n"), 1)


if __name__ == "__main__":
    unittest.main()
