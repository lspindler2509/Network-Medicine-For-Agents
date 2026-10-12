"""Shared foreground/background GraphQL invocation and schema-driven help."""

import argparse
import json
import sys
import requests
from graphql import parse, validate, get_operation_ast, GraphQLError, OperationType
from graphql.execution.values import get_variable_values
from graphql.language import OperationDefinitionNode
from ..errors import UserError
from ..graphql.schema import load_schema, overview, describe_type
from ..graphql.transport import post


def parser_for(name):
    parser = argparse.ArgumentParser(
        prog=name,
        description="Read-only GraphQL queries. Explore the cached introspection schema before selecting fields.",
    )
    commands = parser.add_subparsers(dest="command")
    schema = commands.add_parser(
        "schema", help="Show query fields or details of one type"
    )
    schema.add_argument("type", nargs="?", help="Case-sensitive GraphQL type name")
    query = commands.add_parser(
        "query", help="Execute a directly supplied GraphQL query"
    )
    query.add_argument(
        "query", help="GraphQL document as a quoted argument; no file required"
    )
    query.add_argument("--variables", default="{}", help="Variables as a JSON object")
    query.add_argument(
        "--operation-name", help="Select a named operation in a multi-query document"
    )
    return parser


def query_body(schema, query, variables, operation_name):
    try:
        variables = json.loads(variables)
    except ValueError as error:
        raise UserError("--variables must be a valid JSON object") from error
    if not isinstance(variables, dict):
        raise UserError("--variables must be a JSON object")
    document = parse(query)
    if any(
        isinstance(node, OperationDefinitionNode)
        and node.operation != OperationType.QUERY
        for node in document.definitions
    ):
        raise UserError("Only read-only GraphQL queries are supported")
    errors = validate(schema, document)
    if errors:
        raise UserError(
            "GraphQL validation failed: " + "; ".join(e.message for e in errors)
        )
    operation = get_operation_ast(document, operation_name)
    if operation is None:
        raise UserError(
            "Choose a valid --operation-name; multiple queries require an explicit name"
        )
    coerced = get_variable_values(
        schema, operation.variable_definitions or (), variables
    )
    if isinstance(coerced, list):
        raise UserError(
            "GraphQL variables invalid: " + "; ".join(e.message for e in coerced)
        )
    # Preserve supplied JSON values: coercion validates them, but may produce
    # Python enum values unsuitable for wire serialization.
    return variables


def invoke(source, arguments, name="netmed", stdout=None, stderr=None):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = parser_for(name)
    # argparse writes to the current process streams; background query calls
    # still capture usage errors in their normal result/stderr files.
    import contextlib

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            selected = parser.parse_args(
                [] if arguments in (["--help"], ["-h"]) else arguments
            )
        except SystemExit as error:
            return int(error.code)
        if selected.command is None:
            parser.print_help()
            schema = load_schema(source)
            print("\nQuery fields (from cached introspection):")
            for key, field in schema.query_type.fields.items():
                args = ", ".join(f"{k}: {v.type}" for k, v in field.args.items())
                print(f"  {key}({args}): {field.type}")
            print(
                f"\nExplore: {name} schema <Type>\nExecute: {name} query '<GraphQL>' --variables '{{}}'"
            )
            print(
                "JSON response preserves data, errors and extensions. GraphQL errors exit nonzero,"
            )
            print(
                "including partial data; background jobs then fail and retain result.txt."
            )
            print("Pagination is explicit in the query. No automatic cursor traversal.")
            return 0
        schema = load_schema(source)
        if selected.command == "schema":
            result = (
                describe_type(schema, selected.type)
                if selected.type
                else overview(schema)
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        try:
            variables = query_body(
                schema, selected.query, selected.variables, selected.operation_name
            )
        except (UserError, GraphQLError) as error:
            print(f"Query invalid: {error}", file=stderr)
            return 2
        try:
            payload, status = post(
                source, selected.query, variables, selected.operation_name
            )
        except UserError as error:
            print(f"GraphQL request failed: {error}", file=stderr)
            return 1
        except requests.RequestException:
            print(
                "GraphQL request failed; check connectivity and the configured endpoint.",
                file=stderr,
            )
            return 1
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        if (
            not 200 <= status < 300
            or payload.get("errors")
            or payload.get("data") is None
        ):
            print(
                f"GraphQL query failed (HTTP {status}); inspect the response data/errors.",
                file=stderr,
            )
            return 1
        return 0
