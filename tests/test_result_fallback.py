"""Real pinned-Fire worker contract tests using an explicitly selected interpreter."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from unittest.mock import patch
import unittest


FIXTURE = """
from pathlib import Path

class Exportable:
    def to_json(self):
        return '{"genes": ["EGFR"]}'

class Listable:
    def tolist(self):
        return [1, 2]

class Snapshot:
    def __init__(self):
        self.genes = ["EGFR"]
    def to_csv(self, index=True):
        return "index,gene;0,EGFR" if index else "gene;EGFR"

class BrokenExport(Snapshot):
    def to_json(self):
        raise ValueError("broken export")

class InvalidExport(Snapshot):
    def to_json(self):
        return "not JSON"

class RecoverableExport(Listable):
    def to_json(self):
        raise ValueError("broken first exporter")

class RecoverableInvalidExport(Listable):
    def to_json(self):
        return "not JSON"

class Unpicklable:
    def __reduce__(self):
        raise TypeError("cannot pickle")

class Text:
    def __str__(self):
        return "native text"
    def to_json(self):
        raise AssertionError("native output must bypass the exporter")

def result(kind, counter):
    path = Path(counter)
    path.write_text(str(int(path.read_text()) + 1 if path.exists() else 1))
    return {"json": Exportable, "listable": Listable, "snapshot": Snapshot, "broken": BrokenExport,
            "invalid": InvalidExport, "recoverable": RecoverableExport,
            "recoverable_invalid": RecoverableInvalidExport,
            "unpicklable": Unpicklable, "text": Text}[kind]()

def bundle():
    return {"z_score": Snapshot(), "other": Exportable()}

def values(kind):
    if kind == "list": return [1, 2]
    if kind == "dict": return {"gene": "EGFR"}
    if kind == "none": return None
    if kind == "generator": return (x for x in [1, 2])
"""


@unittest.skipUnless(
    os.environ.get("NETMED_WORKER_PYTHON"),
    "Set NETMED_WORKER_PYTHON to an interpreter with pinned Fire",
)
class ResultFallbackTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "fixture.py").write_text(FIXTURE)
        self.worker = Path(__file__).resolve().parents[1] / "src/netmed/worker/entry.py"
        self.python = os.environ["NETMED_WORKER_PYTHON"]
        self.driver = "import sys,runpy;sys.path.insert(0,sys.argv[1]);runpy.run_path(sys.argv[2],run_name='__main__')"

    def request(self, arguments, options=None):
        return {
            "module": "fixture",
            "name": "netmed fixture",
            "arguments": arguments,
            "original_arguments": arguments,
            "object_options": options or {},
            "objects_root": str(self.root / "objects"),
            "environment_id": "fixture",
        }

    def run_worker(self, arguments, options=None, file_output=False):
        command = [self.python, "-c", self.driver, str(self.root), str(self.worker)]
        request = json.dumps(self.request(arguments, options))
        if file_output:
            with (
                (self.root / "result.txt").open("w") as output,
                (self.root / "stderr.txt").open("w") as errors,
            ):
                result = subprocess.run(
                    command,
                    input=request,
                    text=True,
                    stdout=output,
                    stderr=errors,
                    timeout=20,
                )
            return (
                result.returncode,
                (self.root / "result.txt").read_text(),
                (self.root / "stderr.txt").read_text(),
            )
        result = subprocess.run(
            command, input=request, text=True, capture_output=True, timeout=20
        )
        return result.returncode, result.stdout, result.stderr

    def test_json_export_runs_operation_once_without_snapshot(self):
        code, output, errors = self.run_worker(
            ["result", "json", str(self.root / "counter")]
        )
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output), {"genes": ["EGFR"]})
        self.assertEqual(errors, "")
        self.assertFalse((self.root / "objects").exists())
        self.assertEqual((self.root / "counter").read_text(), "1")

    def test_list_export_is_json_without_snapshot(self):
        code, output, errors = self.run_worker(
            ["result", "listable", str(self.root / "counter")]
        )
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output), [1, 2])
        self.assertEqual(errors, "")
        self.assertFalse((self.root / "objects").exists())
        self.assertEqual((self.root / "counter").read_text(), "1")

    def test_snapshot_export_failure_and_file_output_are_recoverable(self):
        for kind in ("snapshot", "broken", "invalid"):
            with self.subTest(kind=kind):
                counter = self.root / ("counter-" + kind)
                code, output, errors = self.run_worker(
                    ["result", kind, str(counter)], file_output=True
                )
                self.assertEqual(code, 0, errors)
                saved = json.loads(output)
                self.assertEqual(saved["output_format"], "pickle")
                self.assertIn(
                    "No native text representation (__str__)", saved["reason"]
                )
                if kind == "snapshot":
                    self.assertIn("supported JSON exporter", saved["reason"])
                else:
                    self.assertIn("to_json export failed", saved["reason"])
                identity = saved["saved_objects"][0]["id"]
                self.assertTrue(
                    (self.root / "objects" / identity / "object.pkl").exists()
                )
                self.assertEqual(counter.read_text(), "1")
                # Load it in the original interpreter; the core never unpickles.
                check = subprocess.run(
                    [
                        self.python,
                        "-c",
                        "import sys,pickle;sys.path.insert(0,sys.argv[1]);v=pickle.load(open(sys.argv[2],'rb'));assert v.genes==['EGFR']",
                        str(self.root),
                        str(self.root / "objects" / identity / "object.pkl"),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(check.returncode, 0, check.stderr)

    def test_failed_json_export_tries_next_exporter_without_repeating_operation(self):
        for kind in ("recoverable", "recoverable_invalid"):
            with self.subTest(kind=kind):
                counter = self.root / ("counter-" + kind)
                code, output, errors = self.run_worker(
                    ["result", kind, str(counter)], file_output=True
                )
                self.assertEqual(code, 0, errors)
                self.assertEqual(json.loads(output), [1, 2])
                self.assertFalse((self.root / "objects").exists())
                self.assertEqual(counter.read_text(), "1")

    def test_save_failure_is_nonzero_without_published_snapshot(self):
        code, output, errors = self.run_worker(
            ["result", "unpicklable", str(self.root / "counter")]
        )
        self.assertNotEqual(code, 0)
        self.assertIn("Cannot save object", errors)
        self.assertNotIn('"saved_objects"', output)
        self.assertEqual(list((self.root / "objects").iterdir()), [])
        self.assertEqual((self.root / "counter").read_text(), "1")

    def test_explicit_help_and_navigation_do_not_compute_or_save(self):
        for arguments in ([], ["result", "--", "--help"], ["Snapshot", "--", "--help"]):
            code, output, errors = self.run_worker(arguments)
            self.assertEqual(code, 0, errors)
            self.assertIn("SYNOPSIS", output + errors)
            self.assertFalse((self.root / "objects").exists())
            self.assertFalse((self.root / "counter").exists())

    def test_native_values_text_and_iterators_stay_native(self):
        for kind, expected in (
            ("list", "1\n2\n"),
            ("none", ""),
            ("generator", "1\n2\n"),
        ):
            code, output, errors = self.run_worker(["values", kind])
            self.assertEqual(code, 0, errors)
            self.assertEqual(output, expected)
        code, output, errors = self.run_worker(
            ["result", "text", str(self.root / "counter")]
        )
        self.assertEqual(code, 0, errors)
        self.assertEqual(output, "native text\n")
        self.assertFalse((self.root / "objects").exists())

    def test_explicit_save_bypasses_json_export(self):
        code, output, errors = self.run_worker(
            ["result", "json", str(self.root / "counter")], {"--save-object": "chosen"}
        )
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)["saved_objects"][0]["label"], "chosen")
        self.assertNotIn("exported as JSON", errors)

    @unittest.skipUnless(
        os.environ.get("NETMED_PROCESS_TESTS") == "1", "Enable native process tests"
    )
    def test_background_jobs_finish_only_after_output_or_snapshot(self):
        from netmed.runtime.jobs import launch, read_status

        driver = self.root / "driver.py"
        driver.write_text(
            "import sys,runpy;sys.path.insert(0,"
            + repr(str(self.root))
            + ");runpy.run_path("
            + repr(str(self.worker))
            + ",run_name='__main__')"
        )
        environment = {
            "id": "fixture",
            "directory": str(self.root),
            "python": self.python,
            "worker": str(driver),
        }
        catalog = self.root / "catalog.json"
        catalog.write_text(
            json.dumps(
                {"sources": {"fixture": {"kind": "python", "module": "fixture"}}}
            )
        )
        with (
            patch.dict(os.environ, {"NETMED_DATA_DIR": str(self.root)}),
            patch("netmed.runtime.python.prepare", return_value=environment),
        ):
            for kind, expected in (
                ("json", "completed"),
                ("snapshot", "completed"),
                ("unpicklable", "failed"),
            ):
                counter = self.root / ("background-" + kind)
                job = launch(
                    catalog,
                    ["fixture", "result", kind, str(counter)],
                    self.root / "jobs",
                )
                directory = Path(job["directory"])
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    status = read_status(directory)
                    if status["state"] in ("completed", "failed"):
                        break
                    time.sleep(0.05)
                self.assertEqual(
                    status["state"], expected, (directory / "worker.log").read_text()
                )
                self.assertEqual(counter.read_text(), "1")
                if expected == "completed":
                    result = json.loads((directory / "result.txt").read_text())
                    if kind == "snapshot":
                        identity = result["saved_objects"][0]["id"]
                        self.assertTrue(
                            (self.root / "objects" / identity / "object.pkl").exists()
                        )
                else:
                    self.assertNotEqual(status["exit_code"], 0)
                # The worker records its terminal state before exiting; wait for the
                # process to end so its log handle is released (required on Windows).
                from netmed.runtime.processes import worker_is_active

                deadline = time.monotonic() + 20
                while worker_is_active(job["pid"], directory):
                    self.assertLess(time.monotonic(), deadline, "worker did not exit")
                    time.sleep(0.05)

    def test_show_uses_fire_exports_help_and_metadata_without_new_snapshot(self):
        code, output, errors = self.run_worker(
            ["result", "snapshot", str(self.root / "counter")]
        )
        self.assertEqual(code, 0, errors)
        identity = json.loads(output)["saved_objects"][0]["id"]
        before = sorted(path.name for path in (self.root / "objects").iterdir())
        for arguments, expected in (
            ([], '"metadata"'),
            (["to_csv", "--index=False"], "gene;EGFR"),
            (["--", "--help"], "to_csv"),
        ):
            request = self.request(arguments)
            request.update(
                action="show_object",
                object_id=identity,
                object_metadata={"id": identity, "type": "fixture.Snapshot"},
            )
            result = subprocess.run(
                [self.python, "-c", self.driver, str(self.root), str(self.worker)],
                input=json.dumps(request),
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, result.stdout + result.stderr)
            if not arguments:
                preview = json.loads(result.stdout)
                self.assertIn("--help", preview["hint"])
                self.assertNotIn("saved as", preview["reason"])
            self.assertEqual(
                sorted(path.name for path in (self.root / "objects").iterdir()), before
            )
        self.assertEqual((self.root / "counter").read_text(), "1")

    def test_dictionary_summary_and_native_fire_key_navigation(self):
        code, output, errors = self.run_worker(["bundle"], {"--save-object": "bundle"})
        self.assertEqual(code, 0, errors)
        identity = json.loads(output)["saved_objects"][0]["id"]
        for arguments in ([], ["--help"], ["z_score", "-", "to_csv", "--index=False"]):
            request = self.request(arguments)
            # Missing structure models an older snapshot's metadata.
            request.update(
                action="show_object",
                object_id=identity,
                object_metadata={"id": identity},
            )
            result = subprocess.run(
                [self.python, "-c", self.driver, str(self.root), str(self.worker)],
                input=json.dumps(request),
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            if not arguments:
                summary = json.loads(result.stdout)["structure"]
                self.assertEqual(summary["length"], 2)
                self.assertEqual(summary["items"][0]["key"], "z_score")
                self.assertEqual(summary["items"][0]["type"], "fixture.Snapshot")
            elif arguments == ["--help"]:
                self.assertIn("z_score", result.stdout + result.stderr)
            else:
                self.assertEqual(result.stdout.strip(), "gene;EGFR")
        self.assertEqual(len(list((self.root / "objects").iterdir())), 1)
