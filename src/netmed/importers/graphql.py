"""Discover any public introspectable GraphQL source into a hashed schema file."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from graphql import build_client_schema, get_introspection_query, assert_valid_schema
from ..errors import UserError
from ..graphql.transport import post


def discover(source, name, directory):
    # Use the baseline standard query for compatibility with older servers.
    # New optional introspection features are deliberately not required.
    payload, status = post(source, get_introspection_query(descriptions=True))
    if not 200 <= status < 300 or payload.get("errors"):
        raise UserError(
            f"GraphQL introspection failed for {name} (HTTP {status}); no schema-file fallback is supported"
        )
    data = payload.get("data")
    if not isinstance(data, dict) or not data.get("__schema"):
        raise UserError(f"GraphQL introspection returned no schema for {name}")
    schema = build_client_schema(data)
    if schema.query_type is None:
        raise UserError("GraphQL source must expose a query root")
    assert_valid_schema(schema)
    content = json.dumps(data, ensure_ascii=False).encode()
    digest = hashlib.sha256(content).hexdigest()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}-{digest}.json"
    # Content-addressed immutable snapshots also keep existing job references valid.
    descriptor, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {
        "graphql": {"schema": str(path), "sha256": digest},
        "operation_count": len(schema.query_type.fields),
        "source_metadata": {"title": name, "summary": ""},
    }
