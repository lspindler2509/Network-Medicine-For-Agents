"""Discover remote MCP tools without provider-specific adapters."""

import hashlib
import json
from pathlib import Path

from ..mcp import exchange


def discover(source, name, directory):
    document = exchange(source)
    content = (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode()
    digest = hashlib.sha256(content).hexdigest()
    path = Path(directory).resolve() / f"{name}-{digest}.json"
    from ..runtime.source_updates import atomic_json

    atomic_json(path, document)
    return {
        "mcp": {"schema": str(path), "sha256": digest},
        "operation_count": len(document["tools"]),
        "source_metadata": {
            "title": document["serverInfo"].get("title")
            or document["serverInfo"]["name"],
            "summary": "",
        },
    }
