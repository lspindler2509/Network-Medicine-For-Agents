"""Generic MCP contracts: schemas, discovery, routing and error envelopes."""

import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, Mock

from mcp.types import Tool, ListToolsResult

from netmed.catalog import build, load
from netmed.errors import UserError
from netmed.mcp import check_schema, read_snapshot, request
from netmed.runtime.mcp import invoke
from netmed.runtime.source_updates import update
from netmed.search import search, index_path


DOCUMENT = {
    "serverInfo": {"name": "Example", "version": "1"},
    "instructions": "Example instructions",
    "protocolVersion": "2025-11-25",
    "tools": [
        {
            "name": "lookup",
            "description": "Look up a record by identifier.",
            "inputSchema": {
                "type": "object",
                "properties": {"identifier": {"type": "string"}},
                "required": ["identifier"],
                "additionalProperties": False,
            },
        }
    ],
}


class MCPTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = {"kind": "mcp", "endpoint": "https://example.org/mcp"}
        self.config = self.root / "sources.toml"
        self.config.write_text(
            '[sources.example]\nkind="mcp"\nendpoint="https://example.org/mcp"\n'
        )
        self.catalog = self.root / "catalog.json"
        with patch("netmed.importers.mcp.exchange", return_value=DOCUMENT):
            build(self.config, self.catalog)
        self.source = load(self.catalog)["sources"]["example"]

    def call(self, arguments, result=None):
        output, errors = io.StringIO(), io.StringIO()
        with patch(
            "netmed.runtime.mcp.exchange",
            return_value=result or {"content": [], "isError": False},
        ) as request:
            code = invoke(self.source, arguments, "netmed example", output, errors)
        return code, output.getvalue(), errors.getvalue(), request

    def test_help_and_search_use_snapshot_without_network(self):
        for args in ([], ["--help"], ["lookup", "--help"]):
            code, output, _, request = self.call(args)
            self.assertEqual(code, 0)
            self.assertIn("lookup", output)
            request.assert_not_called()
        hits = search(index_path(self.catalog), "identifier")
        self.assertEqual(hits[0]["call"], "netmed example lookup")

    def test_invalid_arguments_never_execute(self):
        for value in (
            "[]",
            '{"identifier":4}',
            "{}",
            "invalid",
            '{"identifier":"x","extra":1}',
        ):
            code, _, _, request = self.call(["lookup", "--arguments", value])
            self.assertEqual(code, 2)
            request.assert_not_called()

    def test_native_result_and_tool_errors(self):
        result = {
            "content": [{"type": "text", "text": "failure"}],
            "structuredContent": {"partial": True},
            "isError": True,
        }
        code, output, _, request = self.call(
            ["lookup", "--arguments", '{"identifier":"x"}'], result
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output), result)
        request.assert_called_once_with(self.source, "lookup", {"identifier": "x"})

    def test_checksum_and_external_schema_refs(self):
        Path(self.source["mcp"]["schema"]).write_text("{}")
        with self.assertRaises(UserError):
            read_snapshot(self.source)
        with self.assertRaises(UserError):
            check_schema({"$ref": "https://example.org/schema"})
        check_schema({"$defs": {"text": {"type": "string"}}, "$ref": "#/$defs/text"})

    def test_refresh_retains_old_snapshot_and_dry_run(self):
        old = self.source["mcp"]["schema"]
        changed = copy.deepcopy(DOCUMENT)
        changed["tools"][0]["description"] = "Updated description"
        with (
            patch.dict(os.environ, {"NETMED_DATA_DIR": str(self.root / "data")}),
            patch("netmed.importers.mcp.exchange", return_value=changed),
        ):
            preview = update(
                self.catalog,
                ["example"],
                dry_run=True,
                use_updates=False,
                progress=io.StringIO(),
            )
            self.assertEqual(preview["sources"][0]["status"], "would_update")
            self.assertEqual(
                load(self.catalog)["sources"]["example"]["mcp"]["schema"], old
            )
            result = update(
                self.catalog, ["example"], use_updates=False, progress=io.StringIO()
            )
        self.assertEqual(result["sources"][0]["status"], "updated")
        self.assertTrue(Path(old).is_file())
        fresh = load(self.catalog)["sources"]["example"]
        self.assertEqual(read_snapshot(fresh), changed)

    def test_portable_export(self):
        from netmed.release import export

        destination = self.root / "bundle"
        export(self.catalog, destination)
        source = load(destination / "catalog.json")["sources"]["example"]
        self.assertEqual(read_snapshot(source), DOCUMENT)
        self.assertTrue(Path(source["mcp"]["schema"]).is_relative_to(destination))

    def test_timeout_rejected_before_discovery(self):
        self.config.write_text(
            '[sources.example]\nkind="mcp"\nendpoint="https://example.org/mcp"\ntimeout=0\n'
        )
        with (
            patch("netmed.importers.mcp.exchange") as request,
            self.assertRaises(ValueError),
        ):
            build(self.config, self.catalog)
        request.assert_not_called()


class MCPTransportTests(unittest.IsolatedAsyncioTestCase):
    async def discover(self, pages):
        session = AsyncMock()
        session.__aenter__.return_value = session
        session.initialize.return_value = SimpleNamespace(
            capabilities=SimpleNamespace(tools=True),
            serverInfo=Mock(model_dump=lambda **kwargs: DOCUMENT["serverInfo"]),
            instructions=None,
            protocolVersion="2025-11-25",
        )
        session.list_tools.side_effect = pages

        @asynccontextmanager
        async def transport(*args, **kwargs):
            yield (None, None, None)

        with (
            patch("netmed.mcp.streamablehttp_client", transport),
            patch("netmed.mcp.ClientSession", return_value=session),
        ):
            result = await request({"endpoint": "https://example.org/mcp"})
        return result, session

    async def test_all_tool_pages_are_discovered(self):
        tool = Tool(**DOCUMENT["tools"][0])
        result, session = await self.discover(
            [
                ListToolsResult(tools=[], nextCursor="second"),
                ListToolsResult(tools=[tool]),
            ]
        )
        self.assertEqual(result["tools"][0]["name"], "lookup")
        self.assertEqual(
            session.list_tools.await_args_list[1].kwargs, {"cursor": "second"}
        )

    async def test_repeated_cursor_and_duplicate_names_fail(self):
        tool = Tool(**DOCUMENT["tools"][0])
        for pages in (
            [
                ListToolsResult(tools=[], nextCursor="again"),
                ListToolsResult(tools=[], nextCursor="again"),
            ],
            [ListToolsResult(tools=[tool, tool])],
        ):
            with self.assertRaises(UserError):
                await self.discover(pages)
