import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import psutil
from netmed.runtime import processes
from netmed.runtime.jobs import launch, active, kill


class ProcessTests(unittest.TestCase):
    def test_detached_worker_filters_environment_and_keeps_native_overrides(self):
        with (
            patch.dict(
                os.environ, {"UNRELATED_API_KEY": "dummy", "NETMED_UV": "/explicit/uv"}
            ),
            patch.object(processes.subprocess, "Popen") as launch,
        ):
            launch.return_value.pid = 123
            processes.start_worker(Path("/temporary/job"), None)
            environment = launch.call_args.kwargs["env"]
            self.assertNotIn("UNRELATED_API_KEY", environment)
            self.assertEqual(environment["NETMED_UV"], "/explicit/uv")

    def test_windows_external_setup_is_explicit_and_environment_has_no_side_effect(
        self,
    ):
        import ctypes

        windll = Mock()
        with (
            patch.object(processes.sys, "platform", "win32"),
            patch.object(processes.sys, "frozen", True, create=True),
            patch.object(ctypes, "windll", windll, create=True),
        ):
            processes.process_environment()
            windll.kernel32.SetDllDirectoryW.assert_not_called()
            processes.prepare_external_process()
            windll.kernel32.SetDllDirectoryW.assert_called_once_with(None)

    def test_detachment_uses_detected_platform(self):
        with patch.object(processes.sys, "platform", "win32"):
            self.assertTrue(processes._windows())
            self.assertEqual(processes.detached_options(), {"creationflags": 0x208})
        with patch.object(processes.sys, "platform", "darwin"):
            self.assertFalse(processes._windows())
            self.assertEqual(processes.detached_options(), {"start_new_session": True})

    def test_windows_inspection_and_tree_termination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            process = Mock()
            process.cmdline.return_value = [
                "python",
                "-m",
                "netmed",
                "_job-worker",
                str(root),
            ]
            process.is_running.return_value = True
            process.status.return_value = psutil.STATUS_RUNNING
            child = Mock()
            process.children.return_value = [child]
            with (
                patch.object(processes, "_windows", return_value=True),
                patch.object(processes.psutil, "Process", return_value=process),
                patch.object(processes.subprocess, "run") as stop,
                patch.object(
                    processes.psutil, "wait_procs", return_value=([process, child], [])
                ) as wait,
            ):
                self.assertTrue(processes.worker_is_active(123, root))
                stop.return_value.returncode = 0
                processes.stop_worker(123, root)
                self.assertEqual(
                    stop.call_args.args[0], ["taskkill", "/PID", "123", "/T", "/F"]
                )
                wait.assert_called_once_with([process, child], timeout=5)
                process.cmdline.return_value = ["python", "-m", "unrelated", str(root)]
                self.assertFalse(processes.worker_is_active(123, root))
                with self.assertRaises(ValueError):
                    processes.stop_worker(123, root)
                self.assertEqual(stop.call_count, 1)

    def test_failed_stop_does_not_mark_job_cancelled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ("a" * 32)
            root.mkdir()
            status = {"tool": "demo", "state": "running", "pid": 123}
            (root / "status.json").write_text(json.dumps(status))
            with patch(
                "netmed.runtime.jobs.stop_worker", side_effect=RuntimeError("denied")
            ):
                with self.assertRaises(RuntimeError):
                    kill(root.parent, root.name)
            self.assertEqual(json.loads((root / "status.json").read_text()), status)

    def test_jobs_delegate_active_and_kill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ("a" * 32)
            root.mkdir()
            (root / "status.json").write_text(
                json.dumps(
                    {
                        "tool": "demo",
                        "state": "running",
                        "pid": 123,
                        "created_at": "2026-10-07T09:00:00+00:00",
                    }
                )
            )
            with (
                patch(
                    "netmed.runtime.jobs.worker_is_active", return_value=True
                ) as probe,
                patch("netmed.runtime.jobs.stop_worker") as stop,
            ):
                self.assertEqual(active(root.parent)[0]["tool"], "demo")
                probe.assert_called_once_with(123, root)
                self.assertEqual(kill(root.parent, root.name)["state"], "cancelled")
                stop.assert_called_once_with(123, root.resolve())

    @unittest.skipUnless(
        os.environ.get("NETMED_PROCESS_TESTS") == "1",
        "Enable real process tests explicitly or in CI",
    )
    def test_real_detached_job_and_child_are_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.json"
            catalog.write_text(
                json.dumps({"sources": {"demo": {"kind": "python", "module": "demo"}}})
            )
            # Fake scientific worker spawns a child and blocks, with no API calls.
            (root / "worker.py").write_text(
                'import subprocess, sys, time\np = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\nprint(p.pid, flush=True)\ntime.sleep(60)\n'
            )
            environment = {
                "id": "test",
                "directory": str(root),
                "python": sys.executable,
                "worker": str(root / "worker.py"),
            }
            with patch(
                "netmed.runtime.environments.UvEnvironmentManager.ensure",
                return_value=environment,
            ):
                job = launch(catalog, ["demo", "wait"], root / "jobs")
            output = Path(job["directory"]) / "result.txt"
            child = None
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if output.exists() and output.read_text().strip():
                        child = psutil.Process(int(output.read_text().strip()))
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(child, "Tool child did not start")
                self.assertTrue(
                    any(item["id"] == job["id"] for item in active(root / "jobs"))
                )
                self.assertEqual(kill(root / "jobs", job["id"])["state"], "cancelled")
                _, alive = psutil.wait_procs([child], timeout=5)
                self.assertFalse(
                    [p for p in alive if p.status() != psutil.STATUS_ZOMBIE]
                )
                self.assertEqual(active(root / "jobs"), [])
                self.assertTrue(output.exists())
            finally:
                # Keep a failed integration check from leaking test processes.
                for pid in [job["pid"], child.pid if child else None]:
                    if pid:
                        try:
                            psutil.Process(pid).kill()
                        except psutil.Error:
                            pass

    def test_unrelated_pid_and_zombie_are_not_active(self):
        with tempfile.TemporaryDirectory() as directory:
            process = Mock()
            process.cmdline.return_value = ["python", "-m", "unrelated", directory]
            with patch.object(processes.psutil, "Process", return_value=process):
                self.assertFalse(processes.worker_is_active(123, directory))
                process.cmdline.return_value = [
                    "python",
                    "-m",
                    "netmed",
                    "_job-worker",
                    str(Path(directory).resolve()),
                ]
                process.is_running.return_value = True
                process.status.return_value = psutil.STATUS_ZOMBIE
                self.assertFalse(processes.worker_is_active(123, directory))

    @unittest.skipUnless(os.name == "posix", "POSIX group termination")
    def test_posix_stop_waits_and_rejects_wrong_group(self):
        with tempfile.TemporaryDirectory() as directory:
            process = Mock()
            child = Mock()
            process.cmdline.return_value = [
                "python",
                "-m",
                "netmed",
                "_job-worker",
                str(Path(directory).resolve()),
            ]
            process.is_running.return_value = True
            process.status.return_value = psutil.STATUS_RUNNING
            process.children.return_value = [child]
            with (
                patch.object(processes, "_windows", return_value=False),
                patch.object(processes.psutil, "Process", return_value=process),
                patch.object(processes.os, "getpgid", return_value=456),
                patch.object(processes.os, "killpg") as stop,
                patch.object(
                    processes.psutil, "wait_procs", return_value=([process, child], [])
                ) as wait,
            ):
                with self.assertRaisesRegex(ValueError, "group leader"):
                    processes.stop_worker(123, directory)
                stop.assert_not_called()
                wait.assert_not_called()
                processes.os.getpgid.return_value = 123
                processes.stop_worker(123, directory)
                stop.assert_called_once()
                wait.assert_called_once_with([process, child], timeout=5)

    def test_unconfirmed_stop_raises_error(self):
        with tempfile.TemporaryDirectory() as directory:
            process = Mock()
            process.cmdline.return_value = [
                "python",
                "-m",
                "netmed",
                "_job-worker",
                str(Path(directory).resolve()),
            ]
            process.is_running.return_value = True
            process.status.return_value = psutil.STATUS_RUNNING
            process.children.return_value = []
            with (
                patch.object(processes, "_windows", return_value=True),
                patch.object(processes.psutil, "Process", return_value=process),
                patch.object(processes.subprocess, "run") as stop,
                patch.object(
                    processes.psutil, "wait_procs", return_value=([], [process])
                ),
            ):
                stop.return_value.returncode = 0
                with self.assertRaisesRegex(ValueError, "not confirmed"):
                    processes.stop_worker(123, directory)
