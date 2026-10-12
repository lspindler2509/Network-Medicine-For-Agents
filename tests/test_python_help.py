import contextlib
import copy
import io
import unittest

from netmed.importers.python import cached_help


def item(origin, kind="function"):
    return {
        "defined_in": origin,
        "kind": kind,
        "signature": "(value)",
        "doc": "Analyze values.\nMore details.",
        "parameters": [],
    }


class PythonHelpTests(unittest.TestCase):
    def source(self, operations):
        return {"module": "example", "discovery_metadata": {"operations": operations}}

    def render(self, source, arguments):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            handled = cached_help(source, arguments, "netmed example")
        return handled, output.getvalue()

    def test_small_source_stays_flat_and_unknown_origins_remain(self):
        source = self.source(
            {"analyze": item("example.analysis"), "unknown": item(None)}
        )
        handled, output = self.render(source, ["--help"])
        self.assertTrue(handled)
        self.assertIn("netmed example analyze (value)", output)
        self.assertIn("netmed example unknown (value)", output)
        self.assertNotIn("Help groups (", output)

    def test_foreign_exports_hidden_full_restores_and_explicit_help_works(self):
        source = self.source(
            {
                "analyze": item("example.core"),
                "Adapter": item("requests.adapters"),
                "similar": item("example_extra"),
            }
        )
        before = copy.deepcopy(source)
        _, output = self.render(source, ["--help"])
        self.assertNotIn("netmed example Adapter", output)
        self.assertNotIn("netmed example similar", output)
        self.assertIn("Foreign re-exports hidden", output)
        _, output = self.render(source, ["--full", "--help"])
        self.assertIn("netmed example Adapter", output)
        self.assertIn("netmed example similar", output)
        handled, output = self.render(source, ["Adapter", "--help"])
        self.assertTrue(handled)
        self.assertIn("Parameters:", output)
        self.assertEqual(source, before)
        self.assertFalse(self.render(source, ["Adapter", "--value=1"])[0])

    def test_large_reexported_root_groups_by_definition_and_keeps_call_paths(self):
        source = self.source(
            {f"f{index}": item("example.algorithms.centrality") for index in range(60)}
        )
        _, output = self.render(source, ["--help"])
        self.assertIn("netmed example algorithms --help", output)
        self.assertNotIn("netmed example f0 (value)", output)
        handled, output = self.render(source, ["algorithms", "--help"])
        self.assertTrue(handled)
        self.assertIn("netmed example algorithms centrality --help", output)
        _, output = self.render(
            source, ["algorithms", "centrality", "--help", "--full"]
        )
        self.assertIn("netmed example f0 (value)", output)
        self.assertNotIn("netmed example algorithms centrality f0", output)

    def test_exposed_paths_group_without_origin_and_unknown_path_defers_to_fire(self):
        source = self.source({f"sub.f{index}": item(None) for index in range(60)})
        _, output = self.render(source, ["--help"])
        self.assertIn("netmed example sub --help", output)
        _, output = self.render(source, ["sub", "--help", "--full"])
        self.assertIn("netmed example sub f0", output)
        self.assertFalse(self.render(source, ["missing", "--help"])[0])

    def test_private_definition_modules_are_not_exposed_as_group_paths(self):
        source = self.source(
            {
                f"f{index}": item("example.algorithms._implementation")
                for index in range(60)
            }
        )
        _, output = self.render(source, ["--help"])
        self.assertIn("netmed example algorithms --help", output)
        self.assertNotIn("_implementation --help", output)

    def test_full_class_help_includes_members_and_execution_is_not_intercepted(self):
        source = self.source(
            {"Model": item("example", "class"), "Model.fit": item("example")}
        )
        _, output = self.render(source, ["Model", "--help", "--full"])
        self.assertIn("netmed example Model fit", output)
        self.assertFalse(self.render(source, ["Model", "--full"])[0])

    def test_unknown_class_member_origins_group_with_class_definition(self):
        operations = {"Model": item("example.models", "class")}
        operations.update(
            {f"Model.f{index}": item(None, "method") for index in range(60)}
        )
        _, output = self.render(self.source(operations), ["--help"])
        self.assertIn("netmed example models --help", output)
        self.assertNotIn("netmed example Model --help", output)
