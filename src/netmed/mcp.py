"""Generic remote MCP transport and immutable tool-interface snapshots."""

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import anyio
from jsonschema.validators import validator_for
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .errors import UserError


def check_schema(schema):
    # Schemas are supplied by remote servers; never resolve external references.
    def check(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("$ref", "$dynamicRef") and (
                    not isinstance(item, str) or not item.startswith("#")
                ):
                    raise UserError("MCP schemas must use only local references")
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    check(schema)
    validator_for(schema).check_schema(schema)


def read_snapshot(source):
    reference = source.get("mcp", {})
    if not reference.get("schema") or not reference.get("sha256"):
        raise UserError("MCP tools missing; rebuild the catalog or update the source")
    content = Path(reference["schema"]).read_bytes()
    if hashlib.sha256(content).hexdigest() != reference["sha256"]:
        raise UserError("MCP snapshot checksum mismatch; rebuild the catalog")
    return json.loads(content)


async def request(source, tool=None, arguments=None):
    """One bounded session per CLI call; the SDK owns MCP negotiation/transport."""
    from .catalog import validate_url

    validate_url(source["endpoint"])
    timeout = source.get("timeout", 60)
    try:
        with anyio.fail_after(timeout):
            async with streamablehttp_client(
                source["endpoint"], timeout=timeout, sse_read_timeout=timeout
            ) as (read, write, _):
                async with ClientSession(
                    read, write, read_timeout_seconds=timedelta(seconds=timeout)
                ) as session:
                    initialized = await session.initialize()
                    if tool is not None:
                        result = await session.call_tool(tool, arguments=arguments)
                        return result.model_dump(
                            mode="json", by_alias=True, exclude_none=True
                        )
                    if not initialized.capabilities.tools:
                        raise UserError("MCP server does not advertise tools")
                    tools, cursors, names = [], set(), set()
                    cursor = None
                    for _ in range(100):
                        page = await session.list_tools(cursor=cursor)
                        for item in page.tools:
                            if item.name in names:
                                raise UserError(
                                    "MCP server returned duplicate tool names"
                                )
                            names.add(item.name)
                            check_schema(item.inputSchema)
                            if item.outputSchema is not None:
                                check_schema(item.outputSchema)
                            tools.append(
                                item.model_dump(
                                    mode="json", by_alias=True, exclude_none=True
                                )
                            )
                        cursor = page.nextCursor
                        if not cursor:
                            return {
                                "serverInfo": initialized.serverInfo.model_dump(
                                    mode="json", by_alias=True
                                ),
                                "instructions": initialized.instructions,
                                "protocolVersion": initialized.protocolVersion,
                                "tools": sorted(tools, key=lambda item: item["name"]),
                            }
                        if cursor in cursors:
                            raise UserError(
                                "MCP tool-list pagination repeated a cursor"
                            )
                        cursors.add(cursor)
                    raise UserError("MCP tool-list pagination exceeded 100 pages")
    except Exception as error:
        # Async transport failures may be nested in task-group ExceptionGroups.
        def details(exc):
            if isinstance(exc, BaseExceptionGroup):
                return "; ".join(details(child) for child in exc.exceptions)
            return str(exc) or type(exc).__name__

        raise UserError(f"MCP request failed: {details(error)}") from error


def exchange(source, tool=None, arguments=None):
    return anyio.run(request, source, tool, arguments)
