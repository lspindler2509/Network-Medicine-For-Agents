import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from netmed.runtime.restish import command_rows
from netmed.search import (
    api_documents,
    graphql_documents,
    index_path,
    python_documents,
    search,
    write_index,
)
from data_isolation import setUpModule, tearDownModule  # noqa: F401

RESTISH_HELP = """An API for accessing the database.
  Indented description text that is not a command.

Usage:
  restish trials [flags]
  restish trials [command]

Examples:
  restish trials list-studies

Studies
  list-studies           Studies
  fetch-study            Single Study

Very long names
  get-a-very-long-command-name-with-one-space Summary after one space
  no-summary

Flags:
  -h, --help   help for trials
"""


def operation(doc, module="pkg", parameters=()):
    return {
        "doc": doc,
        "defined_in": module,
        "parameters": [{"name": name} for name in parameters],
    }


class SearchDocumentTests(unittest.TestCase):
    def test_python_documents_skip_private_foreign_and_exception_types(self):
        metadata = {
            "operations": {
                "tl.leiden": operation(
                    "Cluster cells.\n\nLong details.", "pkg.tools", ["adata"]
                ),
                "_hidden": operation("Private."),
                "Session": operation("Foreign client.", "requests.sessions"),
                "LookupError": operation("Raised when missing."),
                "Client.NotFoundError.add_note": operation("Inherited."),
            }
        }
        documents = list(python_documents("pkg", metadata, "pkg"))
        self.assertEqual(
            documents,
            [("pkg", "netmed pkg tl leiden", "tl.leiden", "Cluster cells.", "adata")],
        )

    def test_api_documents_come_from_native_restish_help(self):
        rows = command_rows(RESTISH_HELP)
        self.assertEqual(
            rows,
            [
                ("list-studies", "Studies", "Studies"),
                ("fetch-study", "Single Study", "Studies"),
                (
                    "get-a-very-long-command-name-with-one-space",
                    "Summary after one space",
                    "Very long names",
                ),
                ("no-summary", "", "Very long names"),
            ],
        )
        documents = list(api_documents("trials", rows[:1]))
        self.assertEqual(
            documents,
            [
                (
                    "trials",
                    "netmed trials list-studies",
                    "list-studies Studies",
                    "Studies",
                    "",
                )
            ],
        )

    def test_graphql_documents_cover_root_and_returned_type_fields(self):
        def named(name, kind="OBJECT"):
            return {"kind": kind, "name": name, "ofType": None}

        schema = {
            "__schema": {
                "queryType": {"name": "Query"},
                "types": [
                    {
                        "name": "Query",
                        "kind": "OBJECT",
                        "fields": [
                            {
                                "name": "target",
                                "description": "Retrieve a target",
                                "args": [{"name": "ensemblId"}],
                                "type": {
                                    "kind": "NON_NULL",
                                    "name": None,
                                    "ofType": named("Target"),
                                },
                            }
                        ],
                    },
                    {
                        "name": "Target",
                        "kind": "OBJECT",
                        "description": "Retrieve a target",
                        "fields": [
                            {
                                "name": "drugAndClinicalCandidates",
                                "description": "",
                                "args": [],
                                "type": named("Candidates"),
                            }
                        ],
                    },
                ],
            }
        }
        documents = list(graphql_documents("ot", schema))
        self.assertEqual(
            [document[1] for document in documents],
            [
                "netmed ot query '{ target { ... } }'",
                "netmed ot query '{ target { drugAndClinicalCandidates } }'",
            ],
        )
        # The type description is not appended when it repeats the field's.
        self.assertEqual(documents[0][3], "Retrieve a target")


class SearchIndexTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "catalog-search.sqlite"
        documents = [
            (
                "netx",
                "netmed netx shortest_path",
                "shortest_path",
                "Shortest path between nodes.",
                "graph source target",
            ),
            (
                "netx",
                "netmed netx shortest_path_length",
                "shortest_path_length",
                "Length of the shortest path.",
                "graph",
            ),
            (
                "netx",
                "netmed netx all_shortest_paths",
                "all_shortest_paths",
                "All shortest paths.",
                "graph",
            ),
            (
                "igr",
                "netmed igr get_shortest_path",
                "get_shortest_path",
                "Shortest path in igraph.",
                "v to",
            ),
            ("other", "netmed other plot", "plot", "Plot a figure.", "data"),
        ]
        descriptions = {
            "netx": "Graph algorithms.",
            "igr": "Graph library.",
            "other": "Plots.",
        }
        write_index(self.path, documents, descriptions)

    def tearDown(self):
        self.directory.cleanup()

    def test_results_are_ranked_and_limited_per_source(self):
        results = search(self.path, "shortest path between nodes")
        calls = [result["call"] for result in results]
        self.assertEqual(calls[0], "netmed netx shortest_path")
        self.assertEqual(sum(call.startswith("netmed netx") for call in calls), 2)
        self.assertIn("netmed igr get_shortest_path", calls)
        self.assertNotIn("netmed other plot", calls)

    def test_source_filter_offset_and_empty_queries(self):
        selected = search(self.path, "shortest path", source="netx")
        self.assertEqual(len(selected), 3)
        self.assertEqual(
            search(self.path, "shortest path", source="netx", offset=2, limit=1),
            selected[2:3],
        )
        self.assertEqual(search(self.path, "the of a"), [])
        self.assertIsNone(search(Path(self.directory.name) / "missing.sqlite", "x"))

    def test_pagination_continues_beyond_one_chunk_with_per_source_limit(self):
        from netmed import search as module

        documents = [
            ("big", f"netmed big path_{i}", f"path_{i}", "Shortest path.", "")
            for i in range(30)
        ] + [
            (f"src{i}", f"netmed src{i} path", "path", "Path search.", "")
            for i in range(25)
        ]
        path = Path(self.directory.name) / "many.sqlite"
        write_index(path, documents, {})
        with patch.object(module, "CHUNK", 5):
            first = search(path, "path", limit=10)
            later = search(path, "path", limit=10, offset=20)
        self.assertEqual(len(first), 10)
        self.assertEqual(len(later), 7)  # 2 from "big" + 25 others = 27 results
        sources = [result["source"] for result in first + later]
        self.assertEqual(sources.count("big"), 2)

    def test_query_text_cannot_break_fts_syntax(self):
        self.assertEqual(
            search(self.path, 'path" OR NOT ( *'), search(self.path, "path")
        )


class CatalogSearchTests(unittest.TestCase):
    def test_index_failure_keeps_catalog_and_removes_stale_index(self):
        from netmed.catalog import write

        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.json"
            index_path(catalog).write_text("stale")
            with (
                patch(
                    "netmed.search.write_index",
                    side_effect=__import__("sqlite3").OperationalError("no fts5"),
                ),
                contextlib.redirect_stderr(io.StringIO()) as errors,
            ):
                write({"sources": {}, "disabled_sources": {}}, catalog)
            self.assertTrue(catalog.is_file())
            self.assertFalse(index_path(catalog).exists())
            self.assertIn("netmed find is disabled", errors.getvalue())

    def test_overlay_index_is_used_only_while_it_matches_the_base_catalog(self):
        from netmed.runtime import source_updates

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            base = root / "assets" / "catalog.json"
            base.parent.mkdir()
            base.write_text("{}")
            overlay = root / "updates"
            overlay.mkdir()
            index_path(overlay / "catalog.json").write_text("index")
            with (
                patch.object(source_updates, "default_catalog", return_value=base),
                patch.object(source_updates, "directory", return_value=overlay),
            ):
                self.assertEqual(source_updates.search_index(base), index_path(base))
                (overlay / "catalog-search.json").write_text(
                    json.dumps(
                        {"base_catalog_sha256": source_updates.catalog_digest(base)}
                    )
                )
                self.assertEqual(
                    source_updates.search_index(base),
                    index_path(overlay / "catalog.json"),
                )
                self.assertEqual(
                    source_updates.search_index(base, use_updates=False),
                    index_path(base),
                )
                base.write_text('{"upgraded": true}')
                self.assertEqual(source_updates.search_index(base), index_path(base))

    def test_catalog_write_builds_index_and_find_prints_results(self):
        from netmed.catalog import write
        from netmed.cli import main

        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.json"
            write(
                {
                    "sources": {
                        "netx": {
                            "kind": "python",
                            "module": "netx",
                            "description": "Graph algorithms.",
                            "discovery_metadata": {
                                "operations": {
                                    "shortest_path": operation(
                                        "Shortest path between nodes.", "netx"
                                    )
                                }
                            },
                        }
                    },
                    "disabled_sources": {},
                },
                catalog,
            )
            self.assertTrue(index_path(catalog).is_file())
            with (
                patch(
                    "sys.argv",
                    [
                        "netmed",
                        "--catalog",
                        str(catalog),
                        "find",
                        "shortest",
                        "path",
                        "--json",
                    ],
                ),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                main()
            results = json.loads(output.getvalue())
            self.assertEqual(results[0]["call"], "netmed netx shortest_path")
