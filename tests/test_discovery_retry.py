"""Build-time discovery retries transient failures; user queries never do."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from graphql import build_schema, introspection_from_schema

from netmed.errors import UserError
from netmed.graphql.transport import StatusError
from netmed.importers import graphql as graphql_importer
from netmed.importers import mcp as mcp_importer
from netmed.importers.openapi import fetch_spec

URL = "https://example.org/openapi.json"
INTROSPECTION = introspection_from_schema(build_schema("type Query { label: String }"))
MCP_DOCUMENT = {"serverInfo": {"name": "Example"}, "tools": []}


def response(status):
    result = requests.Response()
    result.status_code = status
    return result


class RetryTests(unittest.TestCase):
    def setUp(self):
        sleep = patch("netmed.importers.retry.time.sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_openapi_retries_timeout_and_server_error(self):
        ok = response(200)
        with patch(
            "netmed.importers.openapi.requests.get",
            side_effect=[requests.ReadTimeout(), response(503), ok],
        ) as get:
            self.assertIs(fetch_spec(URL), ok)
        self.assertEqual(get.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_openapi_client_error_is_not_retried(self):
        with patch(
            "netmed.importers.openapi.requests.get", return_value=response(404)
        ) as get:
            self.assertEqual(fetch_spec(URL).status_code, 404)
        get.assert_called_once()
        self.sleep.assert_not_called()

    def test_openapi_persistent_timeout_is_raised(self):
        with patch(
            "netmed.importers.openapi.requests.get",
            side_effect=requests.ReadTimeout(),
        ) as get:
            with self.assertRaises(requests.ReadTimeout):
                fetch_spec(URL)
        self.assertEqual(get.call_count, 3)

    def test_graphql_retries_bad_gateway(self):
        with patch(
            "netmed.importers.graphql.post",
            side_effect=[
                StatusError("non-JSON output (HTTP 502)", 502),
                ({"data": INTROSPECTION}, 503),
                ({"data": INTROSPECTION}, 200),
            ],
        ) as post:
            result = graphql_importer.discover(
                {"endpoint": "https://example.org/graphql"}, "example", self.root
            )
        self.assertEqual(post.call_count, 3)
        self.assertEqual(result["operation_count"], 1)

    def test_graphql_persistent_server_error_names_source(self):
        with patch(
            "netmed.importers.graphql.post",
            return_value=({"errors": [{"message": "down"}]}, 502),
        ) as post:
            with self.assertRaisesRegex(UserError, "example.*HTTP 502"):
                graphql_importer.discover({}, "example", self.root)
        self.assertEqual(post.call_count, 3)

    def test_graphql_disabled_introspection_is_not_retried(self):
        with patch(
            "netmed.importers.graphql.post",
            return_value=({"errors": [{"message": "disabled"}]}, 200),
        ) as post:
            with self.assertRaisesRegex(UserError, "introspection failed"):
                graphql_importer.discover({}, "example", self.root)
        post.assert_called_once()

    def test_mcp_tool_listing_is_retried(self):
        with patch(
            "netmed.importers.mcp.exchange",
            side_effect=[UserError("MCP request failed: 502"), MCP_DOCUMENT],
        ) as exchange:
            result = mcp_importer.discover({}, "example", self.root)
        self.assertEqual(exchange.call_count, 2)
        self.assertEqual(result["operation_count"], 0)

    def test_unexpected_errors_are_not_retried(self):
        call = Mock(side_effect=KeyError("bug"))
        with patch("netmed.importers.mcp.exchange", call):
            with self.assertRaises(KeyError):
                mcp_importer.discover({}, "example", self.root)
        call.assert_called_once()


if __name__ == "__main__":
    unittest.main()
