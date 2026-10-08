import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from netmed.runtime.environments import UvEnvironmentManager
from netmed.runtime.processes import process_environment


class EnvironmentTests(unittest.TestCase):
    def test_requirement_injection_rejected_before_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = UvEnvironmentManager(root=directory, executable="uv")
            invalid = [
                {"package": "demo\n--extra-index-url https://example.org"},
                {"package": "demo", "version": "==1\r\n-r other.txt"},
                {"dependencies": ["--extra-index-url https://example.org"]},
                {"dependencies": ["demo\nother"]},
            ]
            with patch.object(manager, "_run") as installer:
                for source in invalid:
                    with self.subTest(source=source), self.assertRaises(ValueError):
                        manager.ensure({"module": "demo", **source})
                installer.assert_not_called()

    def test_failed_installation_is_not_published_and_unlocks(self):
        with tempfile.TemporaryDirectory() as d:
            manager = UvEnvironmentManager(root=d, executable="uv")
            with patch.object(
                manager, "_run", side_effect=RuntimeError("installation failed")
            ):
                with self.assertRaises(RuntimeError):
                    manager.ensure({"module": "json"})
            self.assertEqual(list((Path(d) / "environments").glob("*.lock")), [])
            self.assertEqual(manager.list(), [])

    def test_worker_does_not_inherit_arbitrary_variables_or_pythonpath(self):
        with patch.dict(
            os.environ,
            {
                "UNRELATED_SETTING": "example",
                "CUSTOM_SETTING": "example",
                "PYTHONPATH": "bad",
            },
        ):
            env = process_environment()
        self.assertNotIn("UNRELATED_SETTING", env)
        self.assertNotIn("PYTHONPATH", env)
        self.assertNotIn("CUSTOM_SETTING", env)

    def test_environment_reused_and_new_version_gets_new_identity(self):
        with tempfile.TemporaryDirectory() as d:
            manager = UvEnvironmentManager(root=d, executable="uv")

            def run(args):
                if args[0] == "venv":
                    directory = Path(args[-1])
                    binary = directory / (
                        "Scripts/python.exe" if os.name == "nt" else "bin/python"
                    )
                    binary.parent.mkdir(parents=True)
                    binary.touch()

            with (
                patch.object(manager, "_run", side_effect=run) as installer,
                patch("netmed.runtime.environments.subprocess.run") as freeze,
            ):
                freeze.return_value.stdout = "fire==0.7.1\n"
                source = {"module": "json", "python": "3.11"}
                first = manager.ensure(source)
                self.assertEqual(manager.ensure(source), first)
                self.assertEqual(installer.call_count, 3)
                second = manager.ensure({**source, "python": "3.12"})
                self.assertNotEqual(first["id"], second["id"])
                self.assertEqual(installer.call_count, 6)

    def test_editable_reuses_environment_for_code_and_reinstalls_for_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local = root / "package"
            local.mkdir()
            code = local / "demo.py"
            code.write_text("def value(): return 1")
            metadata = local / "pyproject.toml"
            metadata.write_text('[project]\nname="demo"\nversion="0.1"\n')
            manager = UvEnvironmentManager(root=root / "runtime", executable="uv")

            def run(args):
                if args[0] == "venv":
                    target = Path(args[-1])
                    binary = target / (
                        "Scripts/python.exe" if os.name == "nt" else "bin/python"
                    )
                    binary.parent.mkdir(parents=True)
                    binary.touch()

            with (
                patch.object(manager, "_run", side_effect=run) as installer,
                patch("netmed.runtime.environments.subprocess.run") as freeze,
            ):
                freeze.return_value.stdout = "fire==0.7.1\n"
                source = {"module": "demo", "path": str(local), "dev": True}
                first = manager.ensure(source)
                self.assertIn("--editable", installer.call_args.args[0])
                code.write_text("def value(): return 200")
                self.assertEqual(manager.ensure(source), first)
                self.assertEqual(installer.call_count, 4)
                metadata.write_text('[project]\nname="demo"\nversion="0.2"\n')
                second = manager.ensure(source)
                self.assertNotEqual(first["id"], second["id"])
                self.assertEqual(installer.call_count, 8)

    def test_editable_requires_local_path(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = UvEnvironmentManager(root=directory)
            with self.assertRaises(ValueError):
                manager.ensure({"module": "demo", "package": "demo", "dev": True})
