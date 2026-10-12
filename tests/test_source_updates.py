"""API refresh selection, activation, isolation and retained job references."""

import contextlib
import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from graphql import build_schema, introspection_from_schema
from netmed.errors import UserError
from netmed.graphql.schema import load_schema
from netmed.runtime import source_updates as updates
from netmed.catalog import load, build
from netmed.cli import main


class SourceUpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        environment = patch.dict(os.environ, {"NETMED_DATA_DIR": str(self.root)})
        environment.start()
        self.addCleanup(environment.stop)
        self.catalog = self.root / "catalog.json"
        self.sources = {
            "graph": self.graphql_source(self.root, "old"),
            "api": {
                "kind": "openapi",
                "spec": str(self.root / "old-api.json"),
                "spec_origin": "https://example.org/schema",
                "base_url": "https://example.org",
                "operation_count": 0,
                "source_metadata": {"title": "Old"},
            },
            "python": {
                "kind": "python",
                "module": "example",
                "lock": {"path": "locked.txt", "sha256": "fixed", "target": "test"},
            },
        }
        (self.root / "old-api.json").write_text(
            json.dumps({"openapi": "3.0.3", "info": {"title": "Old"}, "paths": {}})
        )
        self.catalog.write_text(
            json.dumps(
                {
                    "sources": self.sources,
                    "disabled_sources": {"disabled": {"kind": "graphql"}},
                }
            )
        )
        self.original_bytes = self.catalog.read_bytes()
        self.progress = io.StringIO()

    def graphql_source(self, root, field):
        data = introspection_from_schema(
            build_schema("type Query { " + field + ": String }")
        )
        content = json.dumps(data).encode()
        path = root / (field + ".json")
        path.write_bytes(content)
        return {
            "kind": "graphql",
            "endpoint": "https://example.org/graphql",
            "graphql": {
                "schema": str(path),
                "sha256": hashlib.sha256(content).hexdigest(),
            },
            "operation_count": 1,
            "source_metadata": {"title": "graph", "summary": ""},
        }

    def refreshed(self, source, name, staging):
        if name == "graph":
            return {**source, **self.graphql_source(staging, "new")}
        document = {"openapi": "3.0.3", "info": {"title": "New"}, "paths": {}}
        path = staging / "new-api.json"
        path.write_text(json.dumps(document))
        return {
            **source,
            "spec": str(path),
            "source_metadata": {"title": "New"},
            "restish": {"config": str(staging / "temporary.json")},
        }

    def run_update(self, names=None, **options):
        with patch.object(updates, "refresh", side_effect=self.refreshed):
            return updates.update(
                self.catalog, names, progress=self.progress, **options
            )

    def test_all_refreshes_only_apis_and_activates_overlay(self):
        result = self.run_update()
        self.assertEqual([r["source"] for r in result["sources"]], ["graph", "api"])
        self.assertTrue(all(r["status"] == "updated" for r in result["sources"]))
        self.assertEqual(self.catalog.read_bytes(), self.original_bytes)
        active = updates.active_catalog(self.catalog)["sources"]
        self.assertIn("new", load_schema(active["graph"]).query_type.fields)
        self.assertEqual(active["api"]["source_metadata"]["title"], "New")
        self.assertEqual(active["python"], load(self.catalog)["sources"]["python"])
        self.assertTrue(Path(active["api"]["spec"]).is_file())
        self.assertNotIn("config", active["api"]["restish"])

    def test_targeted_dry_run_never_publishes(self):
        result = self.run_update(["graph"], dry_run=True)
        self.assertEqual(result["sources"][0]["status"], "would_update")
        self.assertFalse(updates.directory().exists())
        self.assertEqual(self.catalog.read_bytes(), self.original_bytes)
        self.assertIn(
            "old",
            load_schema(
                updates.active_catalog(self.catalog)["sources"]["graph"]
            ).query_type.fields,
        )

    def test_invalid_selection_rejected_before_any_refresh(self):
        for name in ("python", "missing", "disabled"):
            with self.subTest(name=name), patch.object(updates, "refresh") as refresh:
                with self.assertRaises(UserError):
                    updates.update(self.catalog, ["graph", name])
                refresh.assert_not_called()
        self.assertFalse(updates.directory().exists())

    def test_failure_preserves_one_source_while_others_update(self):
        def refresh(source, name, staging):
            if name == "api":
                raise UserError("Intended test failure")
            return self.refreshed(source, name, staging)

        with patch.object(updates, "refresh", side_effect=refresh):
            result = updates.update(self.catalog, progress=self.progress)
        self.assertEqual(
            [r["status"] for r in result["sources"]], ["updated", "failed"]
        )
        active = updates.active_catalog(self.catalog)["sources"]
        self.assertEqual(active["api"], load(self.catalog)["sources"]["api"])
        self.assertIn("new", load_schema(active["graph"]).query_type.fields)

    def test_repeat_update_is_unchanged_and_keeps_snapshot(self):
        self.run_update(["graph"])
        first = updates.read_overrides()
        files = set((updates.directory() / "snapshots").iterdir())
        result = self.run_update(["graph"])
        self.assertEqual(result["sources"][0]["status"], "unchanged")
        self.assertEqual(first, updates.read_overrides())
        self.assertEqual(files, set((updates.directory() / "snapshots").iterdir()))

    def test_explicit_catalog_ignores_overrides_and_updates_only_that_file(self):
        self.run_update(["graph"])
        self.assertIn(
            "old",
            load_schema(
                updates.active_catalog(self.catalog, use_updates=False)["sources"][
                    "graph"
                ]
            ).query_type.fields,
        )
        other = self.root / "custom.json"
        other.write_bytes(self.original_bytes)
        with patch.object(updates, "refresh", side_effect=self.refreshed):
            result = updates.update(
                other, ["graph"], use_updates=False, progress=self.progress
            )
        self.assertEqual(result["target"], str(other))
        self.assertIn(
            "new", load_schema(load(other)["sources"]["graph"]).query_type.fields
        )
        self.assertEqual(self.catalog.read_bytes(), self.original_bytes)

    def test_override_is_bound_to_configuration_and_preserves_registry_description(
        self,
    ):
        self.run_update(["graph"])
        base = json.loads(self.catalog.read_text())
        base["sources"]["graph"]["description"] = "Updated registry description"
        self.catalog.write_text(json.dumps(base))
        self.assertEqual(
            updates.active_catalog(self.catalog)["sources"]["graph"]["description"],
            "Updated registry description",
        )
        base["sources"]["graph"]["endpoint"] = "https://changed.org/graphql"
        self.catalog.write_text(json.dumps(base))
        self.assertIn(
            "old",
            load_schema(
                updates.active_catalog(self.catalog)["sources"]["graph"]
            ).query_type.fields,
        )

    def test_existing_jobs_keep_old_reference_new_jobs_use_updated_reference(self):
        from netmed.runtime.jobs import launch

        with patch("netmed.runtime.jobs.start_worker", return_value=123):
            old = launch(
                self.catalog,
                ["graph", "query", "{ old }"],
                self.root / "jobs",
                use_updates=True,
            )
            self.run_update(["graph"])
            new = launch(
                self.catalog,
                ["graph", "query", "{ new }"],
                self.root / "jobs",
                use_updates=True,
            )
        old_source = load(Path(old["directory"]) / "execution.json")["sources"]["graph"]
        new_source = load(Path(new["directory"]) / "execution.json")["sources"]["graph"]
        self.assertIn("old", load_schema(old_source).query_type.fields)
        self.assertIn("new", load_schema(new_source).query_type.fields)
        self.assertNotEqual(
            old_source["graphql"]["schema"], new_source["graphql"]["schema"]
        )

    def test_broken_old_snapshot_can_be_repaired(self):
        Path(self.sources["graph"]["graphql"]["schema"]).unlink()
        result = self.run_update(["graph"])
        self.assertEqual(result["sources"][0]["status"], "updated")
        self.assertIn(
            "new",
            load_schema(
                updates.active_catalog(self.catalog)["sources"]["graph"]
            ).query_type.fields,
        )

    def test_failed_catalog_publication_keeps_previous_catalog(self):
        with (
            patch.object(updates, "refresh", side_effect=self.refreshed),
            patch.object(updates, "atomic_json", side_effect=OSError),
        ):
            with self.assertRaises(OSError):
                updates.update(self.catalog, use_updates=False, progress=self.progress)
        self.assertEqual(self.catalog.read_bytes(), self.original_bytes)

    def test_cli_help_and_explicit_catalog_precedence(self):
        self.run_update(["graph"])
        for arguments, expected in (
            (["graph", "--help"], "new"),
            (["--catalog", str(self.catalog), "graph", "--help"], "old"),
            (["sources", "--help"], "update"),
            (["sources", "update", "--help"], "--dry-run"),
        ):
            with (
                self.subTest(arguments=arguments),
                patch.object(sys, "argv", ["netmed", *arguments]),
                contextlib.redirect_stdout(io.StringIO()) as output,
                patch("netmed.runtime.command_log.record_command"),
            ):
                try:
                    code = main()
                except SystemExit as error:
                    code = error.code
                self.assertEqual(code, 0)
                self.assertIn(expected, output.getvalue())

    def test_cli_partial_failure_exit_code(self):
        result = {"sources": [{"status": "failed"}]}
        with (
            patch.object(sys, "argv", ["netmed", "sources", "update"]),
            patch.object(updates, "update", return_value=result),
            patch("netmed.runtime.command_log.record_command"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(main(), 1)

    def test_build_retains_remote_openapi_origin(self):
        config = self.root / "sources.toml"
        config.write_text(
            '[sources.api]\nkind="openapi"\nspec="https://example.org/spec"\nbase_url="https://example.org"\n'
        )
        document = {"openapi": "3.0.3", "info": {"title": "Test"}, "paths": {}}
        with (
            patch("netmed.importers.openapi.load_document", return_value=document),
            patch("netmed.importers.openapi.discover", return_value={}),
        ):
            result = build(
                config,
                self.root / "built.json",
                snapshot_directory=self.root / "build-specs",
            )
        source = result["sources"]["api"]
        self.assertEqual(source["spec_origin"], "https://example.org/spec")
        self.assertFalse(source["spec"].startswith("https://"))

    def test_openapi_refresh_uses_staged_native_backend(self):
        document = {"openapi": "3.0.3", "info": {"title": "Updated"}, "paths": {}}
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "netmed.importers.openapi.load_document", return_value=document
            ) as fetch,
            patch(
                "netmed.runtime.restish.prepare",
                return_value={"operation_count": 0, "restish": {}},
            ) as prepare,
        ):
            staging = Path(temporary)
            result = updates.refresh(self.sources["api"], "api", staging)
            fetch.assert_called_once_with("https://example.org/schema")
            self.assertEqual(prepare.call_args.kwargs["directory"], staging / "restish")
            self.assertEqual(result["spec_origin"], "https://example.org/schema")
