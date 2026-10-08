import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from netmed.runtime.python import invoke, prepare


class PythonRuntimeTests(unittest.TestCase):
    def test_foreground_and_saved_environment_use_same_worker_request(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = {
                "id": "demo",
                "directory": directory,
                "python": "python",
                "worker": str(Path(directory) / "worker.py"),
            }
            source = {
                "module": "demo",
                "submodules": True,
                "setup": [
                    {"call": "config.set_url_base", "args": ["https://example.org"]}
                ],
            }
            output, errors = io.StringIO(), io.StringIO()
            with (
                patch(
                    "netmed.runtime.python.prepare", return_value=environment
                ) as install,
                patch(
                    "netmed.runtime.python.subprocess.run",
                    return_value=Mock(returncode=0),
                ) as run,
            ):
                self.assertEqual(invoke(source, ["query"], name="netmed demo"), 0)
                first = run.call_args
                self.assertEqual(
                    invoke(
                        source,
                        ["query"],
                        name="netmed demo",
                        environment=environment,
                        stdout=output,
                        stderr=errors,
                    ),
                    0,
                )
                second = run.call_args
                install.assert_called_once_with(source)
                self.assertEqual(first.kwargs["input"], second.kwargs["input"])
                self.assertEqual(
                    json.loads(second.kwargs["input"])["setup"], source["setup"]
                )
                self.assertIs(second.kwargs["stdout"], output)
                self.assertIs(second.kwargs["stderr"], errors)
                self.assertEqual(
                    second.args[0], ["python", str(Path(directory) / "worker.py")]
                )

    def test_stale_catalog_refuses_changed_configuration_before_install(self):
        source = {"module": "demo", "discovery_metadata": {"configuration_hash": "old"}}
        with patch("netmed.runtime.python.UvEnvironmentManager.ensure") as install:
            with self.assertRaisesRegex(ValueError, "rebuild the catalog"):
                prepare(source)
            install.assert_not_called()
