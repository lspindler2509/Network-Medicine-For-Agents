"""Schema-driven MCP CLI shared by foreground and background execution."""

import argparse
import contextlib
import json
import sys

from jsonschema import ValidationError
from jsonschema.validators import validator_for

from ..errors import UserError
from ..mcp import check_schema, exchange, read_snapshot


def invoke(source, arguments, name="netmed", stdout=None, stderr=None):
    stdout, stderr = stdout or sys.stdout, stderr or sys.stderr
    document = read_snapshot(source)
    tools = {item["name"]: item for item in document["tools"]}
    parser = argparse.ArgumentParser(
        prog=name,
        description="Remote MCP tools over Streamable HTTP. Tool descriptions and schemas come from the server.",
    )
    parser.add_argument("tool", nargs="?", help="Exact MCP tool name")
    parser.add_argument(
        "--arguments", default="{}", help="Native tool arguments as a JSON object"
    )
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        # Tool-specific help preserves arbitrary JSON Schema, including nested inputs.
        if (
            arguments
            and arguments[0] in tools
            and any(a in ("--help", "-h") for a in arguments[1:])
        ):
            print(json.dumps(tools[arguments[0]], indent=2, ensure_ascii=False))
            print(f"\nCall: {name} {arguments[0]} --arguments '<JSON object>'")
            return 0
        if not arguments or arguments in (["--help"], ["-h"]):
            parser.print_help()
            print("\nTools (cached server interface; no tool calls are made):")
            for tool in tools.values():
                print(f"  {tool['name']}: {tool.get('description', '')}")
            print("\nTools may have side effects. Inspect tool help before execution.")
            return 0
        try:
            selected = parser.parse_args(arguments)
        except SystemExit as error:
            return int(error.code)
        if selected.tool not in tools:
            print(
                "Unknown MCP tool; inspect --help or run sources update.", file=stderr
            )
            return 2
        try:
            values = json.loads(selected.arguments)
            if not isinstance(values, dict):
                raise UserError("--arguments must be a JSON object")
            schema = tools[selected.tool]["inputSchema"]
            check_schema(schema)
            validator_for(schema)(schema).validate(values)
        except (ValueError, ValidationError, UserError) as error:
            print(f"MCP arguments invalid: {error}", file=stderr)
            return 2
        try:
            result = exchange(source, selected.tool, values)
        except UserError as error:
            print(str(error), file=stderr)
            return 1
        # Preserve text, structuredContent, resource links and binary content blocks.
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if result.get("isError"):
            print(
                "MCP tool reported an error; inspect the result content.", file=stderr
            )
            return 1
        return 0
