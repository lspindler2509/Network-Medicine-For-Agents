"""Discover remote MCP tools without provider-specific adapters."""

import hashlib
from pathlib import Path

from ..errors import UserError
from ..mcp import exchange
from .retry import retry_transient


def discover(source, name, directory):
    # tools/list is read-only; the SDK reports all failures as one UserError.
    document = retry_transient(
        lambda: exchange(source), lambda error: isinstance(error, UserError)
    )
    from ..runtime.source_updates import atomic_bytes, json_bytes

    content = json_bytes(document)
    digest = hashlib.sha256(content).hexdigest()
    path = Path(directory).resolve() / f"{name}-{digest}.json"
    atomic_bytes(path, content)
    return {
        "mcp": {"schema": str(path), "sha256": digest},
        "operation_count": len(document["tools"]),
        "source_metadata": {
            "title": document["serverInfo"].get("title")
            or document["serverInfo"]["name"],
            "summary": "",
        },
    }
