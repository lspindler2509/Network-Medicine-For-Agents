import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from netmed.worker.discovery import discover
from netmed.worker.invocation import (
    load_modules,
    configure,
    import_requested_submodules,
)
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

    def write_traversal_fixture(self, directory):
        root = Path(directory) / "traversal_fixture"
        (root / "sub").mkdir(parents=True)
        (root / "tests").mkdir()
        (root / "__init__.py").write_text(
            "import json\n"
            "from . import attached as tools\n"
            "from .unattached import helper\n"
            'def top():\n    """Top-level function."""\n'
        )
        (root / "attached.py").write_text(
            'def cluster(data):\n    """Cluster observations."""\n'
        )
        (root / "unattached.py").write_text(
            'def helper():\n    """Re-exported helper."""\n'
            'def align(a, b):\n    """Align two sequences."""\n    return a + b\n'
        )
        (root / "sub" / "__init__.py").write_text("")
        (root / "sub" / "deep.py").write_text(
            'def nested():\n    """Nested function."""\n'
        )
        (root / "_private.py").write_text("def hidden():\n    pass\n")
        (root / "tests" / "__init__.py").write_text("def test_x():\n    pass\n")
        (root / "broken.py").write_text("raise ImportError('optional dependency')\n")
        # Like a moved package: any missing attribute raises ImportError.
        (root / "moved").mkdir()
        (root / "moved" / "__init__.py").write_text(
            "def __getattr__(name):\n    raise ImportError('moved elsewhere')\n"
        )
        (root / "moved" / "leaf.py").write_text(
            "def __getattr__(name):\n    raise ImportError('moved elsewhere')\n"
        )
        (root / "exits.py").write_text("import sys\nsys.exit('cli module')\n")
        return root

    def remove_fixture_modules(self, name):
        for module in list(sys.modules):
            if module == name or module.startswith(name + "."):
                del sys.modules[module]

    def test_discovery_traverses_package_submodules_generically(self):
        import os
        import subprocess

        with tempfile.TemporaryDirectory() as directory:
            self.write_traversal_fixture(directory)
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parents[1] / "src/netmed/worker/entry.py"),
                ],
                input=json.dumps(
                    {
                        "action": "discover",
                        "module": "traversal_fixture",
                        "traversal_budget": 30,
                    }
                ),
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "PYTHONPATH": directory},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            metadata = json.loads(result.stdout)
            operations = metadata["operations"]
            # An attached module is listed once under one callable attribute path.
            aliases = {"attached.cluster", "tools.cluster"} & operations.keys()
            self.assertEqual(len(aliases), 1)
            # Unattached and nested submodules are imported and listed.
            self.assertIn("unattached.align", operations)
            self.assertIn("sub.deep.nested", operations)
            # Re-exports appear once, under the shorter path.
            self.assertIn("helper", operations)
            self.assertNotIn("unattached.helper", operations)
            # Private, test and foreign modules are not traversed.
            self.assertFalse(any(key.startswith("_private") for key in operations))
            self.assertFalse(any(key.startswith("tests") for key in operations))
            self.assertFalse(any(key.startswith("json") for key in operations))
            omitted = {item["name"]: item["reason"] for item in metadata["omitted"]}
            self.assertEqual(omitted["broken"], "submodule import failed")
            self.assertEqual(omitted["exits"], "submodule import failed")
            self.assertNotIn("moved", omitted)
            self.assertEqual(omitted["json"], "nested/imported module not traversed")
            # The second name of the attached module is reported as an alias.
            alias = ({"attached", "tools"} - {next(iter(aliases)).split(".")[0]}).pop()
            self.assertTrue(omitted[alias].startswith("alias of traversed submodule"))

    def test_importer_retries_without_traversal_after_worker_failure(self):
        import subprocess
        from netmed.importers import python as importer

        source = {"module": "example", "discovery_timeout": 10}
        environment = {"python": "python", "worker": "entry.py", "directory": "."}
        failed = subprocess.CompletedProcess([], 1, "", "Segmentation fault\n")
        succeeded = subprocess.CompletedProcess(
            [], 0, json.dumps({"operations": {"run": {}}, "omitted": []}), ""
        )
        with (
            patch.object(
                importer.UvEnvironmentManager, "ensure", return_value=environment
            ),
            patch.object(
                importer, "run_discovery", side_effect=[failed, succeeded]
            ) as run,
            patch.object(importer.Path, "read_bytes", return_value=b"lock"),
        ):
            result = importer.discover(source)
        self.assertEqual(
            [call.kwargs["traverse"] for call in run.call_args_list], [True, False]
        )
        self.assertIn("run", result["operations"])
        self.assertEqual(
            result["omitted"][-1]["reason"],
            "submodule traversal disabled after discovery failure: Segmentation fault",
        )
        with (
            patch.object(
                importer.UvEnvironmentManager, "ensure", return_value=environment
            ),
            patch.object(importer, "run_discovery", side_effect=[failed, failed]),
        ):
            with self.assertRaisesRegex(RuntimeError, "module example"):
                importer.discover(source)

    def test_explicit_submodules_are_not_depth_or_count_limited(self):
        from netmed.worker import discovery

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "deep_fixture"
            package = root
            for part in ("a", "b", "c", "d"):
                package.mkdir(parents=True, exist_ok=True)
                (package / "__init__.py").write_text("")
                package = package / part
            package.mkdir()
            (package / "__init__.py").write_text("def leaf():\n    pass\n")
            sys.path.insert(0, directory)
            try:
                module = importlib.import_module("deep_fixture")
                bounded, _ = discovery.package_submodules(module)
                complete, _ = discovery.package_submodules(module, bounded=False)
                self.assertNotIn("a.b.c.d", [path for path, _ in bounded])
                self.assertIn("a.b.c.d", [path for path, _ in complete])
                with patch.object(discovery, "SUBMODULE_LIMIT", 1):
                    limited, notes = discovery.package_submodules(module)
                    unlimited, _ = discovery.package_submodules(module, bounded=False)
                self.assertEqual(len(limited), 1)
                self.assertTrue(any("limit reached" in n["reason"] for n in notes))
                self.assertEqual(len(unlimited), 4)
            finally:
                sys.path.remove(directory)
                self.remove_fixture_modules("deep_fixture")

    def test_traversal_respects_time_budget(self):
        import time
        from netmed.worker.discovery import package_submodules

        with tempfile.TemporaryDirectory() as directory:
            self.write_traversal_fixture(directory)
            sys.path.insert(0, directory)
            try:
                module = importlib.import_module("traversal_fixture")
                found, omitted = package_submodules(module, time.monotonic() - 1)
                paths = [path for path, _ in found]
                # Already imported modules remain; nothing new is imported.
                self.assertTrue({"attached", "tools"} & set(paths))
                self.assertNotIn("sub", paths)
                self.assertNotIn("traversal_fixture.sub", sys.modules)
                self.assertIn(
                    ("sub", "submodule traversal time budget exhausted"),
                    {(item["name"], item["reason"]) for item in omitted},
                )
            finally:
                sys.path.remove(directory)
                self.remove_fixture_modules("traversal_fixture")

    def test_invocation_imports_requested_submodules_on_demand(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write_traversal_fixture(directory)
            sys.path.insert(0, directory)
            try:
                module = importlib.import_module("traversal_fixture")
                self.assertNotIn("sub", vars(module))
                import_requested_submodules(module, ["sub", "deep", "nested", "--x"])
                self.assertEqual(module.sub.deep.nested.__doc__, "Nested function.")
                # Unknown names, private names and flags are left to Fire.
                import_requested_submodules(module, ["missing", "value"])
                import_requested_submodules(module, ["_private"])
                self.assertNotIn("_private", vars(module))
                import_requested_submodules(module, ["--help"])
                with self.assertRaisesRegex(ImportError, "optional dependency"):
                    import_requested_submodules(module, ["broken"])
            finally:
                sys.path.remove(directory)
                self.remove_fixture_modules("traversal_fixture")

    def test_fire_arg_spec_tolerates_builtins_without_self(self):
        from netmed.worker.invocation import tolerant_arg_spec_info

        class ExtensionFunction:
            """Callable passing isbuiltin without __self__, like Boost.Python."""

            def __call__(self, smiles):
                return smiles

        extension = ExtensionFunction()
        original_calls = []

        def original(fn):
            original_calls.append(fn)
            return fn, True

        wrapped = tolerant_arg_spec_info(original)
        with patch(
            "netmed.worker.invocation.inspect.isbuiltin",
            side_effect=lambda fn: fn is extension,
        ):
            self.assertEqual(wrapped(extension), (extension, False))
            self.assertEqual(original_calls, [])
            # Ordinary builtins and other callables keep Fire's behavior.
            self.assertEqual(wrapped(len), (len, True))
            self.assertEqual(original_calls, [len])

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
