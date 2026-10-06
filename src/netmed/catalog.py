import json
import re
import tomllib
from pathlib import Path
from urllib.parse import urlsplit


def validate_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Expected an HTTPS URL without credentials, query or fragment")
    return url


def build(config, destination):
    from .importers.openapi import discover
    config = Path(config).resolve()
    sources = tomllib.loads(config.read_text()).get("sources", {})
    catalog = {"version": 1, "sources": {}}
    for name, source in sources.items():
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
            raise ValueError(f"Invalid source name: {name}")
        item = dict(source)
        if item["kind"] == "python":
            # Discovery happens on demand through Fire, not during catalog build.
            if not re.fullmatch(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*", item["module"]):
                raise ValueError("Invalid module name")
        elif item["kind"] == "openapi":
            validate_url(item["base_url"])
            spec = item["spec"]
            if not spec.startswith("https://"):
                spec = str((config.parent / spec).resolve())
            item["operations"] = discover(spec)
        else:
            raise ValueError(f"Unsupported source kind: {item['kind']}")
        if item.get("execution", "foreground") not in ("foreground", "background"):
            raise ValueError("execution must be foreground or background")
        catalog["sources"][name] = item
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(catalog, indent=2) + "\n")
    return catalog


def load(path):
    return json.loads(Path(path).read_text())
