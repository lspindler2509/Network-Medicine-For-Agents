import json
import os
from datetime import datetime, timezone
import tempfile
import time
import unittest
import sys
from unittest.mock import patch
from pathlib import Path
from netmed.catalog import build
from netmed.runtime.jobs import (
    launch,
    clean,
    active,
    kill,
    list_jobs,
    inspect_job,
    directory_for,
)
from netmed.runtime.environments import UvEnvironmentManager
from netmed.runtime.layout import data_directory
from netmed.runtime.processes import process_environment
from netmed.runtime import processes


class JobTests(unittest.TestCase):
    def test_cleanup_reports_locked_worker_log_without_crashing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identity = "a" * 32
            job = root / identity
            job.mkdir()
            (job / "status.json").write_text('{"state":"completed","tool":"demo"}')
            with patch(
                "netmed.runtime.jobs.shutil.rmtree",
                side_effect=PermissionError("file in use"),
            ):
                result = clean(root, identity)
            self.assertEqual(result["removed"], [])
            self.assertEqual(result["skipped"][0]["id"], identity)
            self.assertTrue(job.exists())

    def test_native_results_are_not_read_back_and_saved_ids_are_recorded(self):
        from netmed.runtime.jobs import worker

        for save in (False, True):
            with self.subTest(save=save), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                args = ["demo", "query"] + (["--save-object", "data"] if save else [])
                (root / "status.json").write_text(
                    json.dumps({"tool": "demo", "arguments": args, "state": "queued"})
                )
                (root / "execution.json").write_text(
                    json.dumps(
                        {"sources": {"demo": {"kind": "python", "module": "demo"}}}
                    )
                )
                (root / "environment.json").write_text("{}")

                def invoke(*args, **kwargs):
                    kwargs["stdout"].write(
                        json.dumps({"saved_objects": [{"id": "a" * 32}]})
                    )
                    return 0

                original_read = Path.read_text
                reads = []

                def read(path, *args, **kwargs):
                    reads.append(path.name)
                    return original_read(path, *args, **kwargs)

                with (
                    patch("netmed.runtime.python.invoke", side_effect=invoke),
                    patch.object(Path, "read_text", read),
                ):
                    worker(root)
                self.assertEqual("result.txt" in reads, save)
                status = json.loads((root / "status.json").read_text())
                self.assertEqual(status["state"], "completed")
                self.assertEqual(status.get("objects", []), ["a" * 32] if save else [])

    def test_one_data_directory_controls_jobs_logs_environments_and_worker_settings(
        self,
    ):
        from netmed.runtime.command_log import record_command

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
        ):
            root = Path(directory).resolve()
            self.assertEqual(data_directory(), root)
            self.assertEqual(directory_for(), root / "jobs")
            self.assertEqual(UvEnvironmentManager().root, root)
            self.assertEqual(record_command(["--help"]), root / "logs.txt")
            self.assertEqual(process_environment()["NETMED_DATA_DIR"], directory)

    def test_detached_job_completes_and_stores_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "sources.toml"
            config.write_text(
                '[sources.demo]\nkind="python"\nmodule="json"\ndiscovery="lazy"\n'
            )
            catalog = root / "catalog.json"
            build(config, catalog)
            (root / "worker.py").write_text(
                'import json, sys; print(json.load(sys.stdin)["arguments"])'
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
                job = launch(
                    catalog, ["demo", "dumps", '{"gene":"EGFR"}'], root / "jobs"
                )
            # Terminal status is written before the detached interpreter exits.
            # Wait for our own Popen handle so Windows releases worker.log before
            # TemporaryDirectory cleanup, also when an assertion fails.
            worker_process = next(p for p in processes._workers if p.pid == job["pid"])
            try:
                # A later catalog edit must not affect this job.
                catalog.write_text("{}")
                status_path = Path(job["directory"]) / "status.json"
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    state = json.loads(status_path.read_text())
                    if state["state"] in ("completed", "failed"):
                        break
                    time.sleep(0.05)
                self.assertFalse((status_path.parent / "catalog.json").exists())
                self.assertEqual(
                    json.loads((status_path.parent / "execution.json").read_text()),
                    {"sources": {"demo": {"kind": "python", "module": "json"}}},
                )
                self.assertEqual(state["tool"], "demo")
                self.assertIn("created_at", state)
                self.assertEqual(
                    state["arguments"], ["demo", "dumps", '{"gene":"EGFR"}']
                )
                self.assertEqual(
                    state["state"],
                    "completed",
                    (Path(job["directory"]) / "stderr.txt").read_text(),
                )
                self.assertIn(
                    "EGFR", (Path(job["directory"]) / "result.txt").read_text()
                )
            finally:
                worker_process.wait(timeout=15)

    @unittest.skipUnless(
        os.name == "posix", "Symlink fixture requires POSIX permissions"
    )
    def test_cleanup_preserves_active_unknown_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "jobs"
            root.mkdir()
            ids = [str(i) * 32 for i in range(1, 8)]
            for job, state in zip(
                ids, ["completed", "failed", "queued", "running", "unknown"]
            ):
                path = root / job
                path.mkdir()
                (path / "status.json").write_text(
                    json.dumps({"state": state, "tool": "demo"})
                )
                (path / "result.txt").write_text("result")
            external = Path(directory) / "external"
            external.mkdir()
            (external / "status.json").write_text('{"state":"completed"}')
            (root / ids[5]).symlink_to(external, target_is_directory=True)
            (root / ids[6]).mkdir()
            (root / ids[6] / "status.json").write_text("invalid json")
            self.assertEqual(
                [j["id"] for j in clean(root, dry_run=True)["would_remove"]], ids[:2]
            )
            self.assertTrue((root / ids[0] / "result.txt").exists())
            self.assertEqual(
                [j["id"] for j in clean(root, job=ids[0])["removed"]], [ids[0]]
            )
            self.assertTrue((root / ids[1]).exists())
            removed = clean(root)
            self.assertEqual([j["id"] for j in removed["removed"]], [ids[1]])
            self.assertEqual([j["id"] for j in removed["skipped"]], ids[2:])
            self.assertTrue((external / "status.json").exists())
            for job in ids[2:]:
                self.assertTrue((root / job).exists())
            with self.assertRaises(ValueError):
                clean(root, "../external")

    def test_cleanup_missing_directory_is_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(clean(Path(directory) / "missing")["removed"], [])

    def test_multiple_ids_and_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ids = ["a" * 32, "b" * 32, "c" * 32]
            for job in ids:
                path = root / job
                path.mkdir()
                (path / "status.json").write_text(
                    json.dumps(
                        {
                            "state": "completed",
                            "tool": "nedrex",
                            "arguments": ["nedrex", "core", "get_edges", "--limit=3"],
                        }
                    )
                )
                (path / "result.txt").write_text("abc")
            preview = clean(root, ids[:2], dry_run=True)
            self.assertEqual([j["id"] for j in preview["would_remove"]], ids[:2])
            self.assertEqual(
                preview["would_remove"][0], {"id": ids[0], "tool": "nedrex"}
            )
            with self.assertRaises(ValueError):
                clean(root, [ids[0], "../invalid"])
            self.assertTrue((root / ids[0]).exists())
            self.assertEqual(len(clean(root, [*ids[:2], ids[0]])["removed"]), 2)
            self.assertTrue((root / ids[2]).exists())

    def test_api_job_keeps_only_backend_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.json"
            selected = {
                "version": "2.3.0",
                "config": "/restish/config.json",
                "cache": "/restish/cache",
                "source": "api",
            }
            catalog.write_text(
                json.dumps(
                    {
                        "sources": {
                            "api": {
                                "kind": "openapi",
                                "base_url": "https://example.org",
                                "description": "discard",
                                "restish": selected,
                                "operation_count": 100,
                            },
                            "unrelated": {"kind": "python", "module": "json"},
                        }
                    }
                )
            )
            with (
                patch("netmed.runtime.jobs.start_worker", return_value=123),
                patch("netmed.runtime.restish_binary.ensure"),
            ):
                job = launch(catalog, ["api", "version"], root / "jobs")
            path = Path(job["directory"])
            saved = json.loads((path / "execution.json").read_text())
            self.assertEqual(
                saved, {"sources": {"api": {"kind": "openapi", "restish": selected}}}
            )
            self.assertEqual(
                json.loads((path / "status.json").read_text())["tool"], "api"
            )
            self.assertFalse((path / "catalog.json").exists())

    def test_active_checks_processes_without_modifying_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, state in enumerate(
                ["running", "running", "completed", "queued", "running"], 1
            ):
                path = root / (str(index) * 32)
                path.mkdir()
                status = {
                    "tool": "nedrex",
                    "state": state,
                    "created_at": "2026-10-07T09:00:00+00:00",
                }
                if state != "queued":
                    status["pid"] = index
                (path / "status.json").write_text(json.dumps(status))
            before = {p: p.read_bytes() for p in root.glob("*/status.json")}

            def probe(pid, path):
                return pid == 1

            with (
                patch("netmed.runtime.jobs.worker_is_active", side_effect=probe),
                patch("netmed.runtime.jobs.datetime", wraps=datetime) as clock,
            ):
                clock.now.return_value = datetime(
                    2026, 10, 7, 9, 1, 30, tzinfo=timezone.utc
                )
                result = active(root)
            self.assertEqual(len(result), 1)
            entry = result[0]
            self.assertEqual((entry["id"], entry["tool"]), ("1" * 32, "nedrex"))
            self.assertNotIn("pid", entry)
            self.assertEqual(entry["runtime"], "00:01:30")
            self.assertEqual(
                entry["started_at"],
                datetime(2026, 10, 7, 9, tzinfo=timezone.utc)
                .astimezone()
                .strftime("%Y-%m-%d %H:%M"),
            )
            self.assertEqual(
                before, {p: p.read_bytes() for p in root.glob("*/status.json")}
            )

    def test_kill_verifies_worker_and_preserves_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job = "a" * 32
            path = root / job
            path.mkdir()
            status = path / "status.json"
            original = {"tool": "demo", "state": "running", "pid": 12345}
            status.write_text(json.dumps(original))
            (path / "result.txt").write_text("partial result")
            with patch("netmed.runtime.jobs.stop_worker") as stop:
                stop.side_effect = ValueError("No matching job worker found")
                with self.assertRaises(ValueError):
                    kill(root, job)
                self.assertEqual(json.loads(status.read_text()), original)
                stop.side_effect = None
                self.assertEqual(
                    kill(root, job), {"id": job, "tool": "demo", "state": "cancelled"}
                )
                stop.assert_called_with(12345, path.resolve())
                self.assertEqual(json.loads(status.read_text())["state"], "cancelled")
                self.assertEqual((path / "result.txt").read_text(), "partial result")
                calls = stop.call_count
                kill(root, job)
                self.assertEqual(stop.call_count, calls)
            self.assertEqual(
                clean(root, dry_run=True)["would_remove"], [{"id": job, "tool": "demo"}]
            )

    def test_failed_start_is_saved_and_can_be_cleaned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "sources": {
                            "api": {
                                "kind": "openapi",
                                "base_url": "https://example.org",
                                "restish": {
                                    "version": "2.3.0",
                                    "config": "/config",
                                    "cache": "/cache",
                                    "source": "api",
                                },
                            }
                        }
                    }
                )
            )
            with (
                patch(
                    "netmed.runtime.jobs.start_worker",
                    side_effect=OSError("spawn failed"),
                ),
                patch("netmed.runtime.restish_binary.ensure"),
            ):
                with self.assertRaisesRegex(ValueError, "marked failed"):
                    launch(catalog, ["api", "query"], root / "jobs")
            entries = list_jobs(root / "jobs")
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["state"], "failed")
            details = inspect_job(root / "jobs", entries[0]["id"])
            self.assertEqual(details["arguments"], ["api", "query"])
            self.assertEqual(len(clean(root / "jobs")["removed"]), 1)
