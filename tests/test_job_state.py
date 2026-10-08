import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from netmed.runtime.job_state import transition, TERMINAL_STATES
from netmed.runtime.jobs import change_state, worker, write_status


class JobStateTests(unittest.TestCase):
    def test_terminal_jobs_cannot_be_restarted_or_rewritten(self):
        for final in TERMINAL_STATES:
            with self.subTest(final=final), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                status = transition({}, "queued")
                status = transition(status, "running", pid=42)
                status = transition(status, final)
                write_status(path, status)
                before = (path / "status.json").read_bytes()
                for target in ("running", "failed", "cancelled"):
                    with self.assertRaisesRegex(ValueError, "Invalid job transition"):
                        transition(status, target)
                    self.assertEqual(change_state(path, target), status)
                self.assertEqual((path / "status.json").read_bytes(), before)

    def test_invalid_start_or_completion_is_rejected(self):
        with self.assertRaises(ValueError):
            transition({}, "running")
        with self.assertRaises(ValueError):
            transition({"state": "queued"}, "completed")

    def test_cancelled_worker_does_not_start_package(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_status(path, {"state": "cancelled", "arguments": ["demo", "run"]})
            with patch("netmed.runtime.python.invoke") as invoke:
                worker(path)
                invoke.assert_not_called()
            self.assertEqual(
                json.loads((path / "status.json").read_text())["state"], "cancelled"
            )
