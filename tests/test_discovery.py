import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from netmed.worker.discovery import discover
from netmed.worker.invocation import load_modules, configure
from netmed.worker.metadata import package_documentation, package_summary
from netmed.catalog import build
from netmed.importers.python import cached_help
import contextlib
import io
import importlib
import sys
from email.parser import Parser


class DiscoveryTests(unittest.TestCase):
    def test_disabled_sources_are_visible_without_installing_or_importing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "sources.toml"
            config.write_text(
                '[sources.pending]\nkind="graphql"\nenabled=false\ndisabled_reason="Importer missing"\n'
            )
            with patch(
                "netmed.runtime.environments.UvEnvironmentManager.ensure"
            ) as install:
                catalog = build(config, root / "catalog.json")
                install.assert_not_called()
            self.assertEqual(catalog["sources"], {})
            self.assertEqual(
                catalog["disabled_sources"]["pending"]["disabled_reason"],
                "Importer missing",
            )

    def test_docs_use_distribution_metadata_without_reading_local_files(self):
        metadata = Parser().parsestr(
            "Name: distribution-name\nVersion: 1.2\nSummary: Short summary\nDescription-Content-Type: text/markdown\n\n# Package docs\nAlgorithm options."
        )
        with (
            patch(
                "netmed.worker.metadata.importlib.metadata.packages_distributions",
                return_value={"import_name": ["distribution-name"]},
            ),
            patch(
                "netmed.worker.metadata.importlib.metadata.metadata",
                return_value=metadata,
            ) as read,
            patch.object(
                Path, "read_text", side_effect=AssertionError("No README fallback")
            ),
        ):
            docs = package_documentation("import_name.submodule")
        read.assert_called_once_with("distribution-name")
        self.assertEqual(docs[0]["text"], "# Package docs\nAlgorithm options.")
        self.assertEqual(docs[0]["version"], "1.2")
        with patch(
            "netmed.worker.metadata.importlib.metadata.metadata", return_value=metadata
        ):
            self.assertEqual(
                package_summary("import_name", "distribution-name"),
                {"title": "distribution-name", "summary": "Short summary"},
            )
        with patch(
            "netmed.worker.metadata.importlib.metadata.metadata",
            return_value=Parser().parsestr("Name: empty\n\n"),
        ):
            self.assertEqual(package_documentation("example", "empty"), [])

    def test_metadata_does_not_execute_functions_constructors_or_properties(self):
        module = types.ModuleType("example")
        exec(
            '''def map_nodes(nodes: list, threshold: float = 0.5) -> dict:
    """Map gene identifiers."""
    raise AssertionError("must not execute")
class Tool:
    def __init__(self):
        raise AssertionError("must not construct")
    @property
    def data(self):
        raise AssertionError("must not evaluate")
    def run(self, gene: str):
        """Run analysis."""
        raise AssertionError("must not execute")
''',
            module.__dict__,
        )
        result = discover(module)
        self.assertEqual(
            result["operations"]["map_nodes"]["parameters"][0]["annotation"], "list"
        )
        self.assertEqual(
            result["operations"]["map_nodes"]["parameters"][1]["default"], 0.5
        )
        self.assertIn("Tool.run", result["operations"])
        self.assertTrue(any(x["name"] == "Tool.data" for x in result["omitted"]))
        json.dumps(result)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertTrue(
                cached_help(
                    {"discovery_metadata": result},
                    ["map_nodes", "--help"],
                    "netmed example",
                )
            )
        self.assertIn("Map gene identifiers", output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertTrue(
                cached_help(
                    {"discovery_metadata": result}, ["--help"], "netmed example"
                )
            )
        self.assertIn("dynamic attributes", output.getvalue())
        self.assertIn("uncached operation help falls back to Fire", output.getvalue())

    def test_callable_instance_discovered_without_execution(self):
        class Analysis:
            """Analyze a network."""

            def __call__(self, data: dict, threshold: float = 0.5):
                raise AssertionError("Discovery must not invoke instances")

        module = types.ModuleType("example")
        module.analysis = Analysis()
        result = discover(module)["operations"]["analysis"]
        self.assertEqual(result["kind"], "callable")
        self.assertEqual(result["parameters"][0]["name"], "data")
        self.assertIn("Analyze", result["doc"])

    def test_build_discovers_default_and_skips_lazy(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            config = root / "sources.toml"
            config.write_text(
                '[sources.eager]\nkind="python"\nmodule="json"\n[sources.lazy]\nkind="python"\nmodule="json"\ndiscovery="lazy"\n'
            )
            with patch(
                "netmed.importers.python.discover", return_value={"operations": {}}
            ) as discovery:
                result = build(config, root / "catalog.json")
            self.assertEqual(discovery.call_count, 1)
            self.assertIn("discovery_metadata", result["sources"]["eager"])
            self.assertNotIn("discovery_metadata", result["sources"]["lazy"])

    def test_generic_submodule_loading_and_declarative_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture_package"
            root.mkdir()
            (root / "__init__.py").write_text(
                "class Config:\n    value=None\n    def set_url(self, value): self.value=value\nconfig=Config()\n"
            )
            (root / "core.py").write_text(
                'def get_nodes(limit: int = 3):\n    """Fetch nodes."""\n    return limit\n'
            )
            sys.path.insert(0, directory)
            try:
                module = importlib.import_module("fixture_package")
                modules, failures = load_modules(module, True)
                self.assertEqual(failures, [])
                self.assertEqual(len(modules), 2)
                self.assertIsNone(module.config.value)
                configure(
                    module,
                    [{"call": "config.set_url", "args": ["https://example.org"]}],
                )
                self.assertEqual(module.config.value, "https://example.org")
                self.assertEqual(module.core.get_nodes(), 3)
            finally:
                sys.path.remove(directory)
                for name in list(sys.modules):
                    if name == "fixture_package" or name.startswith("fixture_package."):
                        del sys.modules[name]

    def test_selection_happens_before_discovery_or_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "sources.toml"
            config.write_text(
                '[sources.selected]\nkind="python"\nmodule="json"\n'
                '[sources.other]\nkind="python"\nmodule="must_not_install"\n'
            )
            with patch(
                "netmed.importers.python.discover", return_value={"operations": {}}
            ) as discover:
                result = build(config, root / "catalog.json", ["selected"])
                discover.assert_called_once()
                self.assertEqual(discover.call_args.args[0]["module"], "json")
                self.assertEqual(list(result["sources"]), ["selected"])
                discover.reset_mock()
                with self.assertRaisesRegex(ValueError, "Unknown source selection"):
                    build(config, root / "invalid.json", ["missing"])
                discover.assert_not_called()
                self.assertFalse((root / "invalid.json").exists())

    def test_standalone_worker_runs_without_core_package(self):
        import shutil
        import subprocess

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "worker"
            shutil.copytree(
                Path(__file__).parents[1] / "src/netmed/worker",
                folder,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            result = subprocess.run(
                [sys.executable, "-I", str(folder / "entry.py")],
                input=json.dumps({"action": "discover", "module": "json"}),
                capture_output=True,
                text=True,
                timeout=30,
                cwd=directory,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("dumps", json.loads(result.stdout)["operations"])
            self.assertEqual(list(folder.rglob("*.pyc")), [])
