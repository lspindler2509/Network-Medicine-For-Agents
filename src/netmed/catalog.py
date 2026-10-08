import json
import hashlib
import re
import tomllib
from pathlib import Path
from urllib.parse import urlsplit


RESERVED_COMMANDS = {
    "build",
    "sources",
    "docs",
    "prepare",
    "environments",
    "objects",
    "jobs",
    "logs",
    "help",
    "release-bundle",
}


def validate_url(url):
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or "@" in parts.netloc
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            "Expected an HTTPS URL with a plain host, without query or fragment"
        )
    return url


def build(
    config, destination, names=None, *, snapshot_directory=None, lock_directory=None
):
    from .importers.openapi import discover

    config = Path(config).resolve()
    sources = tomllib.loads(config.read_text()).get("sources", {})
    if names is not None:
        selected = set(names)
        missing = selected - sources.keys()
        if missing:
            raise ValueError("Unknown source selection: " + ", ".join(sorted(missing)))
        if any(not sources[name].get("enabled", True) for name in selected):
            raise ValueError("Cannot build a disabled source")
        sources = {name: source for name, source in sources.items() if name in selected}
    catalog = {"sources": {}, "disabled_sources": {}}
    for name, source in sources.items():
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
            raise ValueError(f"Invalid source name: {name}")
        if name in RESERVED_COMMANDS:
            raise ValueError(f"Source name conflicts with CLI command: {name}")
        item = dict(source)
        if not isinstance(item.get("enabled", True), bool):
            raise ValueError("enabled must be a boolean")
        if not item.get("enabled", True):
            catalog["disabled_sources"][name] = item
            continue
        if "description" in item and not isinstance(item["description"], str):
            raise ValueError("description must be a string")
        if item["kind"] == "python":
            from .runtime.environments import validate_requirements

            validate_requirements(item)
            if lock_directory is not None:
                from .building.locks import apply_lock

                apply_lock(item, name, lock_directory)
            if not isinstance(item.get("dev", False), bool):
                raise ValueError("dev must be a boolean")
            if item.get("dev") and not item.get("path"):
                raise ValueError("dev requires a local package path")
            if item.get("path"):
                item["path"] = str((config.parent / item["path"]).resolve())
                if not Path(item["path"]).is_dir():
                    raise ValueError("Local package path does not exist")
            # Python discovery occurs inside the managed environment.
            if not re.fullmatch(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*", item["module"]):
                raise ValueError("Invalid module name")
            mode = item.get("discovery", "build")
            if mode not in ("build", "lazy"):
                raise ValueError("discovery must be build or lazy")
            if mode == "build":
                from .importers.python import discover as discover_python

                item["discovery_metadata"] = discover_python(item)
            item["source_metadata"] = item.get("discovery_metadata", {}).pop(
                "source_metadata",
                {
                    "title": item.get("package") or item["module"].split(".")[0],
                    "summary": "",
                },
            )

        elif item["kind"] == "openapi":
            validate_url(item["base_url"])
            spec = item["spec"]
            if not spec.startswith("https://"):
                spec = str((config.parent / spec).resolve())
            item["spec"] = spec
            if snapshot_directory is not None:
                from .importers.openapi import load_document, require_self_contained

                document = load_document(spec)
                require_self_contained(document)
                snapshot = Path(snapshot_directory).resolve() / (name + ".json")
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot.write_text(json.dumps(document))
                item["spec"] = str(snapshot)
                item.update(discover(item, name, document=document))
            else:
                item.update(discover(item, name))
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
    path = Path(path).resolve()
    catalog = json.loads(path.read_text())
    for source in catalog.get("sources", {}).values():
        if source.get("lock"):
            source["lock"]["path"] = str(
                (path.parent / source["lock"]["path"]).resolve()
            )
        if source.get("spec") and not source["spec"].startswith("https://"):
            source["spec"] = str((path.parent / source["spec"]).resolve())
    return catalog


def python_configuration_hash(source):
    keys = (
        "module",
        "package",
        "version",
        "python",
        "dependencies",
        "path",
        "dev",
        "submodules",
        "setup",
    )
    config = {k: source[k] for k in keys if k in source}
    if source.get("lock"):
        config["lock"] = {k: source["lock"][k] for k in ("sha256", "target")}
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
