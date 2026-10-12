"""Introspection snapshots; graphql-core owns schema parsing and validation."""

import hashlib
import json
from pathlib import Path
from graphql import build_client_schema
from ..errors import UserError


def read_snapshot(source):
    reference = source.get("graphql", {})
    if not reference.get("schema") or not reference.get("sha256"):
        raise UserError(
            "GraphQL schema missing; rebuild with netmed build sources.toml"
        )
    content = Path(reference["schema"]).read_bytes()
    if hashlib.sha256(content).hexdigest() != reference["sha256"]:
        raise UserError("GraphQL schema checksum mismatch; rebuild the catalog")
    return json.loads(content)


def load_schema(source):
    return build_client_schema(read_snapshot(source))


def describe_type(schema, name):
    from graphql import (
        is_enum_type,
        is_input_object_type,
        is_object_type,
        is_interface_type,
        is_union_type,
        ast_from_value,
        print_ast,
        Undefined,
    )

    type_ = schema.get_type(name)
    if type_ is None:
        raise UserError(f"Unknown GraphQL type: {name}. Use schema to list type names")
    result = {"name": name, "description": type_.description}

    def argument(value):
        result = {"type": str(value.type), "description": value.description}
        if getattr(value, "default_value", Undefined) is not Undefined:
            node = ast_from_value(value.default_value, value.type)
            result["default"] = print_ast(node) if node is not None else None
        if value.deprecation_reason is not None:
            result["deprecated"] = value.deprecation_reason
        return result

    if is_object_type(type_) or is_interface_type(type_):
        result["fields"] = {
            key: {
                **argument(field),
                "arguments": {k: argument(v) for k, v in field.args.items()},
            }
            for key, field in type_.fields.items()
        }
        result["interfaces"] = [interface.name for interface in type_.interfaces]
        if is_interface_type(type_):
            result["possible_types"] = [
                t.name for t in schema.get_possible_types(type_)
            ]
    elif is_input_object_type(type_):
        result["input_fields"] = {k: argument(v) for k, v in type_.fields.items()}
    elif is_enum_type(type_):
        result["values"] = {
            k: {"description": v.description, "deprecated": v.deprecation_reason}
            for k, v in type_.values.items()
        }
    elif is_union_type(type_):
        result["possible_types"] = [t.name for t in type_.types]
    return result


def overview(schema):
    return {
        "query": describe_type(schema, schema.query_type.name),
        "types": sorted(n for n in schema.type_map if not n.startswith("__")),
        "scope": "Read-only queries; mutations and subscriptions are unsupported",
    }
