"""Discover remote MCP tools without provider-specific adapters."""

import hashlib
from pathlib import Path

from ..mcp import exchange


def discover(source, name, directory):
    document = exchange(source)
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
