"""Generic GraphQL contracts, independent of biomedical provider schemas."""

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from graphql import build_schema, introspection_from_schema
from netmed.catalog import build, load
from netmed.errors import UserError
from netmed.graphql.schema import load_schema, describe_type
from netmed.graphql.transport import post
from netmed.runtime.graphql import invoke

SDL = """
"Example root" type Query {
  greeting(name: String!): String
  bundle: Bundle
  labels: [String!]!
}
type Bundle { text: String, broken: String }
type Mutation { write: String }
"""
SCHEMA = build_schema(SDL)
INTROSPECTION = introspection_from_schema(SCHEMA)


class GraphQLTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.snapshot()

    def snapshot(self):
        content = json.dumps(INTROSPECTION).encode()
        path = self.root / "schema.json"
        path.write_bytes(content)
        return {
            "kind": "graphql",
            "endpoint": "https://example.org/graphql",
            "graphql": {
                "schema": str(path),
                "sha256": hashlib.sha256(content).hexdigest(),
            },
        }

    def call(self, arguments, response=None, status=200):
        output, errors = io.StringIO(), io.StringIO()
        with patch(
            "netmed.runtime.graphql.post",
            return_value=(response or {"data": {"greeting": "hello"}}, status),
        ) as request:
            code = invoke(self.source, arguments, "netmed example", output, errors)
        return code, output.getvalue(), errors.getvalue(), request

    def test_direct_query_variables_and_operation_name_preserved(self):
        document = "query G($name: String!) { greeting(name: $name) }"
        result = {"data": {"greeting": "hello"}, "extensions": {"trace": "x"}}
        code, output, _, request = self.call(
            [
                "query",
                document,
                "--variables",
                '{"name":"EGFR"}',
                "--operation-name",
                "G",
            ],
            result,
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), result)
        request.assert_called_once_with(self.source, document, {"name": "EGFR"}, "G")

    def test_validation_prevents_requests_for_invalid_queries_and_variables(self):
        for arguments in (
            ["query", "{ absent }"],
            ["query", "{ greeting }"],
            ["query", "query G($name: String!) { greeting(name:$name) }"],
            ["query", "{ labels }", "--variables", "[]"],
            ["query", "{ labels }", "--variables", "not json"],
            ["query", "query A { labels } query B { labels }"],
            ["query", "mutation { write }"],
            ["query", "subscription { labels }"],
            ["query", "{"],
            ["query", "{ labels }", "--limt", "2"],
        ):
            with self.subTest(arguments=arguments):
                code, _, errors, request = self.call(arguments)
                self.assertEqual(code, 2)
                self.assertTrue(errors)
                request.assert_not_called()

    def test_errors_preserve_partial_data_and_fail(self):
        for status in (200, 400, 503):
            result = {
                "data": {"bundle": {"text": "kept", "broken": None}},
                "errors": [
                    {"message": "resolver failed", "path": ["bundle", "broken"]}
                ],
            }
            code, output, errors, _ = self.call(
                ["query", "{ bundle { text broken } }"], result, status
            )
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output), result)
            self.assertIn("failed", errors)

    def test_http_failure_and_null_data_fail(self):
        for payload, status in (({"data": None}, 200), ({"data": {}}, 500)):
            self.assertEqual(self.call(["query", "{ labels }"], payload, status)[0], 1)

    def test_schema_and_help_are_offline_and_show_native_types(self):
        for arguments in ([], ["--help"], ["schema"], ["schema", "Query"]):
            code, output, _, request = self.call(arguments)
            self.assertEqual(code, 0)
            self.assertIn("greeting", output)
            self.assertIn("String!", output)
            request.assert_not_called()
        self.assertEqual(
            describe_type(load_schema(self.source), "Bundle")["fields"]["text"]["type"],
            "String",
        )

    def test_input_enum_union_and_default_value_descriptions(self):
        schema = build_schema(
            "enum E { A B } input I { count: Int = 2 } type A { x: Int } type B { x: Int } union U = A | B type Query { use(i:I,e:E = A): U }"
        )
        self.assertEqual(
            describe_type(schema, "I")["input_fields"]["count"]["default"], "2"
        )
        self.assertEqual(set(describe_type(schema, "E")["values"]), {"A", "B"})
        self.assertEqual(describe_type(schema, "U")["possible_types"], ["A", "B"])
        self.assertEqual(
            describe_type(schema, "Query")["fields"]["use"]["arguments"]["e"][
                "default"
            ],
            "A",
        )

    def test_missing_or_modified_snapshot_is_rejected(self):
        with self.assertRaisesRegex(UserError, "schema missing"):
            load_schema({})
        Path(self.source["graphql"]["schema"]).write_text("{}")
        with self.assertRaisesRegex(UserError, "checksum"):
            load_schema(self.source)

    def test_build_uses_introspection_and_export_is_relocatable(self):
        config = self.root / "sources.toml"
        config.write_text(
            '[sources.example]\nkind="graphql"\nendpoint="https://example.org/graphql"\ndescription="Test source"\n'
        )
        catalog = self.root / "catalog.json"
        with patch(
            "netmed.importers.graphql.post", return_value=({"data": INTROSPECTION}, 200)
        ) as request:
            built = build(config, catalog)
        self.assertIn("__schema", request.call_args.args[1])
        self.assertEqual(built["sources"]["example"]["operation_count"], 3)
        from netmed.release import export

        destination = self.root / "bundle"
        with patch(
            "netmed.runtime.environments.UvEnvironmentManager.ensure"
        ) as environment:
            export(catalog, destination)
            environment.assert_not_called()
        exported = json.loads((destination / "catalog.json").read_text())["sources"][
            "example"
        ]
        self.assertFalse(Path(exported["graphql"]["schema"]).is_absolute())
        moved = self.root / "moved"
        destination.rename(moved)
        self.assertEqual(
            load_schema(
                load(moved / "catalog.json")["sources"]["example"]
            ).query_type.name,
            "Query",
        )

    def test_introspection_disabled_does_not_publish_catalog(self):
        config = self.root / "sources.toml"
        config.write_text(
            '[sources.example]\nkind="graphql"\nendpoint="https://example.org/graphql"\n'
        )
        catalog = self.root / "catalog.json"
        with patch(
            "netmed.importers.graphql.post",
            return_value=({"errors": [{"message": "disabled"}]}, 200),
        ):
            with self.assertRaisesRegex(UserError, "introspection failed"):
                build(config, catalog)
        self.assertFalse(catalog.exists())

    def test_transport_envelope_and_no_redirects(self):
        with patch("netmed.graphql.transport.requests.post") as request:
            request.return_value = Mock(status_code=200)
            request.return_value.json.return_value = {"data": {"labels": []}}
            self.assertEqual(post(self.source, "query Q { labels }", {}, "Q")[1], 200)
            self.assertEqual(
                request.call_args.kwargs["json"],
                {"query": "query Q { labels }", "variables": {}, "operationName": "Q"},
            )
            self.assertFalse(request.call_args.kwargs["allow_redirects"])
            request.return_value.status_code = 302
            with self.assertRaisesRegex(UserError, "redirected"):
                post(self.source, "{ labels }")

    def test_background_worker_shares_runtime_and_retains_partial_results(self):
        from netmed.runtime import jobs

        catalog = self.root / "catalog.json"
        catalog.write_text(json.dumps({"sources": {"example": self.source}}))
        result = {
            "data": {"bundle": {"text": "kept", "broken": None}},
            "errors": [{"message": "failed"}],
        }
        with patch("netmed.runtime.jobs.start_worker", return_value=123):
            job = jobs.launch(
                catalog,
                ["example", "query", "{ bundle { text broken } }"],
                self.root / "jobs",
            )
        path = Path(job["directory"])
        execution = json.loads((path / "execution.json").read_text())["sources"][
            "example"
        ]
        self.assertEqual(execution["graphql"], self.source["graphql"])
        self.assertNotIn("source_metadata", execution)
        with patch("netmed.runtime.graphql.post", return_value=(result, 200)):
            jobs.worker(path)
        self.assertEqual(jobs.read_status(path)["state"], "failed")
        self.assertEqual(jobs.read_status(path)["exit_code"], 1)
        self.assertEqual(json.loads((path / "result.txt").read_text()), result)


@unittest.skipUnless(
    os.environ.get("NETMED_GRAPHQL_TESTS"),
    "Set NETMED_GRAPHQL_TESTS=1 for local HTTP contracts",
)
class GraphQLHTTPTests(unittest.TestCase):
    setUp = GraphQLTests.setUp
    snapshot = GraphQLTests.snapshot

    def test_real_http_transport_and_cli(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        from graphql import graphql_sync
        import subprocess
        import sys

        command = (
            [os.environ["NETMED_GRAPHQL_BINARY"]]
            if os.environ.get("NETMED_GRAPHQL_BINARY")
            else [sys.executable, "-m", "netmed"]
        )
        captured = []
        from graphql import GraphQLError

        def fail(info):
            raise GraphQLError("expected resolver failure")

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                captured.append(body)
                response = graphql_sync(
                    SCHEMA,
                    body["query"],
                    root_value={
                        "greeting": lambda info, name: "hello " + name,
                        "bundle": {"text": "kept", "broken": fail},
                    },
                    variable_values=body.get("variables"),
                    operation_name=body.get("operationName"),
                )
                content = json.dumps(response.formatted).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.source["endpoint"] = f"http://127.0.0.1:{server.server_port}/graphql"
            catalog = self.root / "catalog.json"
            catalog.write_text(json.dumps({"sources": {"example": self.source}}))
            environment = {**os.environ, "NETMED_DATA_DIR": str(self.root / "data")}
            query = "query G($name: String!) { greeting(name:$name) }"
            result = subprocess.run(
                [
                    *command,
                    "--catalog",
                    str(catalog),
                    "example",
                    "query",
                    query,
                    "--variables",
                    '{"name":"EGFR"}',
                ],
                env=environment,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout)["data"]["greeting"], "hello EGFR"
            )
            self.assertEqual(captured[0]["variables"], {"name": "EGFR"})
            # Actual detached workers must complete on success and fail while
            # retaining partial JSON data on GraphQL resolver errors.
            import time
            from netmed.runtime.jobs import read_status

            for document, state in (
                (query, "completed"),
                ("{ bundle { text broken } }", "failed"),
            ):
                result = subprocess.run(
                    [
                        *command,
                        "--catalog",
                        str(catalog),
                        "--background",
                        "example",
                        "query",
                        document,
                        "--variables",
                        '{"name":"EGFR"}',
                    ],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                directory = Path(json.loads(result.stdout)["directory"])
                deadline = time.monotonic() + 15
                status = read_status(directory)
                while (
                    status["state"] in ("queued", "running")
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.05)
                    status = read_status(directory)
                self.assertEqual(status["state"], state)
                response = json.loads((directory / "result.txt").read_text())
                if state == "failed":
                    self.assertEqual(response["data"]["bundle"]["text"], "kept")
                    self.assertTrue(response["errors"])
                    self.assertEqual(status["exit_code"], 1)
                else:
                    self.assertEqual(response["data"]["greeting"], "hello EGFR")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
