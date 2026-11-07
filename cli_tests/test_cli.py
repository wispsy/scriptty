import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SELECT = ["--provider", "scriptty-test", "--select", "text.normalize", "--select", "text.report", "--catalog-version", "v1"]


class InstalledCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.outside = Path(self.temporary.name)
        self.receipt = self.outside / "receipt.txt"
        self.inputs = self.outside / "inputs.json"
        self.inputs.write_text(json.dumps({"schema": 1, "inputs": {"text": " HéLLo   🌍 "}}), encoding="utf-8")
        self.workflow = str(ROOT / "examples" / "text.json")
        self.options = ["--inputs", str(self.inputs), *SELECT]
        self.environment = {**os.environ, "SCRIPTTY_TEST_RECEIPT": str(self.receipt), "PYTHONIOENCODING": "cp1252"}

    def call(self, *arguments, console=False):
        executable = Path(sys.executable).with_name("scriptty.exe" if sys.platform == "win32" else "scriptty")
        prefix = [str(executable)] if console else [sys.executable, "-I", "-m", "scriptty"]
        return subprocess.run([*prefix, *arguments], cwd=self.outside, env=self.environment, capture_output=True)

    def payload(self, result):
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        return json.loads(result.stdout.decode("utf-8"))

    def test_inspect_is_passive_list_is_selected_and_console_runs_unicode(self):
        inspected = self.call("inspect", self.workflow)
        self.assertEqual(self.payload(inspected)["status"], "inspected")
        self.assertEqual(inspected.stderr, b"")
        listed = self.payload(self.call("list", *SELECT))
        self.assertEqual([item["name"] for item in listed["capabilities"]], ["text.normalize", "text.report"])
        run = self.call("run", self.workflow, *self.options, console=True)
        self.assertEqual(self.payload(run)["outputs"], {"report": {"text": "héllo 🌍"}})
        self.assertIn(b"normalizing", run.stderr)
        self.assertEqual(self.receipt.read_text().splitlines(), ["normalize", "report"])

    def test_errors_are_versioned_json_on_stderr_before_effects(self):
        self.inputs.write_text('{"schema":1,"inputs":{"text":2}}')
        result = self.call("run", self.workflow, *self.options)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        error = json.loads(result.stderr.decode("utf-8").splitlines()[-1])
        self.assertEqual((error["schema"], error["status"]), (1, "error"))
        self.assertFalse(self.receipt.exists())
        missing = self.call("run", self.workflow)
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(json.loads(missing.stderr.splitlines()[-1])["error"], "UsageError")

    @unittest.skipUnless(importlib.util.find_spec("func_seq"), "sequence profile is optional")
    def test_durable_pause_resume_mismatch_and_explicit_recovery(self):
        checkpoint = str(self.outside / "progress.json")
        first = self.payload(self.call("run", self.workflow, *self.options, "--checkpoint", checkpoint, "--pace", "function"))
        self.assertEqual(first["status"], "paused")
        self.assertEqual(first["completed"], ["normalize"])
        self.assertNotEqual(self.call("run", self.workflow, *self.options, "--checkpoint", checkpoint).returncode, 0)
        altered = ["v2" if item == "v1" else item for item in self.options]
        mismatch = self.call("resume", self.workflow, *altered, "--checkpoint", checkpoint)
        self.assertIn(b"DefinitionMismatchError", mismatch.stderr)
        resumed = self.payload(self.call("resume", self.workflow, *self.options, "--checkpoint", checkpoint))
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed["run_id"], first["run_id"])
        self.assertEqual(self.receipt.read_text().splitlines(), ["normalize", "report"])
        self.payload(self.call("resume", self.workflow, *self.options, "--checkpoint", checkpoint))
        self.assertEqual(self.receipt.read_text().splitlines(), ["normalize", "report"])

        self.receipt.unlink()
        self.environment["SCRIPTTY_TEST_FAIL"] = "1"
        failed_checkpoint = str(self.outside / "failed.json")
        failed = self.call("run", self.workflow, *self.options, "--checkpoint", failed_checkpoint)
        self.assertIn(b"StepFailedError", failed.stderr)
        refused = self.call("resume", self.workflow, *self.options, "--checkpoint", failed_checkpoint)
        self.assertIn(b"RecoveryRequiredError", refused.stderr)
        self.payload(self.call("resume", self.workflow, *self.options, "--checkpoint", failed_checkpoint, "--retry"))
        self.assertEqual(self.receipt.read_text().splitlines(), ["normalize", "report", "report"])
