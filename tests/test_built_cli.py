"""Opt-in checks against the shipped executable, without developer tools on PATH."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


@unittest.skipUnless(
    os.environ.get("NETMED_BINARY_TESTS") == "1",
    "Build CLI and set NETMED_BINARY_TESTS=1",
)
class BuiltCliTests(unittest.TestCase):
    def test_objects_and_detached_worker(self):
        executable = (
            Path(__file__).resolve().parents[1]
            / "dist/netmed"
            / ("netmed.exe" if os.name == "nt" else "netmed")
        )
        self.assertTrue(executable.is_file())
        with tempfile.TemporaryDirectory() as directory:
            env = {
                **os.environ,
                "NETMED_DATA_DIR": directory,
                "PATH": os.environ.get("SystemRoot", "C:\\Windows") + "\\System32"
                if os.name == "nt"
                else "/usr/bin:/bin",
            }
            for key in ("NETMED_UV", "NETMED_RESTISH", "PYTHONPATH"):
                env.pop(key, None)

            def run(*args):
                result = subprocess.run(
                    [str(executable), *args],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout

            self.assertIn("networkx", run("--help"))
            saved = json.loads(
                run("networkx", "path_graph", "4", "--save-object", "graph")
            )
            reference = "@object:" + saved["saved_objects"][0]["id"]
            self.assertEqual(run("networkx", "number_of_nodes", reference).strip(), "4")
            run(
                "reactome", "--help"
            )  # Bundled specification, not a live provider query.
            job = json.loads(
                run("--background", "networkx", "number_of_nodes", reference)
            )
            for _ in range(100):
                status = json.loads(run("jobs", job["id"]))
                if status["state"] in ("completed", "failed"):
                    break
                time.sleep(0.1)
            self.assertEqual(status["state"], "completed", status)
            slow = json.loads(
                run(
                    "--background",
                    "networkx",
                    "is_isomorphic",
                    "--G1=" + reference,
                    "--G2=" + reference,
                    '--node_match=@lambda:lambda a,b: (__import__("time").sleep(30) or True)',
                )
            )
            for _ in range(100):
                active = json.loads(run("jobs", "active"))
                if any(item["id"] == slow["id"] for item in active):
                    break
                time.sleep(0.1)
            self.assertTrue(any(item["id"] == slow["id"] for item in active))
            run("jobs", "kill", slow["id"])
            self.assertEqual(json.loads(run("jobs", slow["id"]))["state"], "cancelled")
            self.assertFalse((Path(directory) / "tools").exists())
            self.assertFalse((Path(directory) / "workers").exists())
