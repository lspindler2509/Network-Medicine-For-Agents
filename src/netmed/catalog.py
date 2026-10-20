import gzip
import json
import hashlib
import re
import sys
import math
import tomllib
from pathlib import Path
from urllib.parse import urlsplit


RESERVED_COMMANDS = {
    "clean",
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
    "find",
}


def discovery_failure(source, error):
    """Disabled-source entry for a Python source whose discovery failed here."""
    from .runtime.environments import platform_target

    lines = [line.strip() for line in str(error).splitlines() if line.strip()]
    reason = lines[0] if lines else type(error).__name__
    if len(lines) > 1:
        reason += " " + lines[-1]
    return {
        **source,
        "enabled": False,
        "discovery_failed": True,
        "disabled_reason": f"Discovery failed on {platform_target()}: {reason[:500]}",
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

                try:
                    item["discovery_metadata"] = discover_python(item)
                except Exception as error:
                    # Native requirements differ per target (e.g. a system OpenMP
                    # runtime). Without an explicit selection, record the source
                    # as disabled for this target instead of failing the build.
                    if names is not None:
                        raise
                    catalog["disabled_sources"][name] = discovery_failure(source, error)
                    print(
                        f"Warning: skipped {name}: "
                        + catalog["disabled_sources"][name]["disabled_reason"],
                        file=sys.stderr,
                    )
                    continue
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
            if spec.startswith("https://"):
                item["spec_origin"] = spec
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
        elif item["kind"] == "graphql":
            from .importers.graphql import discover as discover_graphql

            validate_url(item["endpoint"])
            timeout = item.get("timeout", 60)
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout)
                or timeout <= 0
            ):
                raise ValueError("timeout must be a finite positive number")
            directory = (
                Path(snapshot_directory) / "graphql"
                if snapshot_directory is not None
                else Path(destination).resolve().parent / "graphql-schemas"
            )
            item.update(discover_graphql(item, name, directory))
        else:
            raise ValueError(f"Unsupported source kind: {item['kind']}")
        if item.get("execution", "foreground") not in ("foreground", "background"):
            raise ValueError("execution must be foreground or background")
        catalog["sources"][name] = item
    write(catalog, destination)
    return catalog


def discovery_directory(destination):
    """Per-catalog folder for discovery files, so catalogs can share a directory."""
    destination = Path(destination)
    return destination.parent / (destination.stem + "-discovery")


def write(catalog, destination):
    """Write a catalog; Python discovery goes to one gzip file per source.

    The main catalog keeps routing, overview metadata and a small reference
    (path, checksum, configuration and lock hashes), so loading it stays cheap
    and only the invoked source's discovery is read. ``catalog`` is not changed.
    """
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    folder = discovery_directory(destination)
    written = {}
    sources = {}
    loaded = {}  # discovery already in memory, reused for the search index
    for name, source in catalog.get("sources", {}).items():
        item = dict(source)
        metadata = item.pop("discovery_metadata", None)
        reference = item.get("discovery_file")
        if metadata is None and reference:
            # Not loaded: keep the existing file, relative when it is in this folder.
            existing = Path(reference["path"])
            if not existing.is_absolute():
                existing = destination.parent / existing
            existing = existing.resolve()
            if existing.parent == folder.resolve():
                written[existing.name] = True
                item["discovery_file"] = {
                    **reference,
                    "path": f"{folder.name}/{existing.name}",
                }
            else:
                metadata = discovery_metadata(dict(source))
        if metadata is not None:
            content = gzip.compress(
                json.dumps(
                    metadata, separators=(",", ":"), ensure_ascii=False
                ).encode(),
                mtime=0,
            )
            folder.mkdir(exist_ok=True)
            file = folder / (name + ".json.gz")
            file.write_bytes(content)
            written[file.name] = True
            loaded[name] = metadata
            item["discovery_file"] = {
                "path": f"{folder.name}/{file.name}",
                "sha256": hashlib.sha256(content).hexdigest(),
                "configuration_hash": metadata.get("configuration_hash"),
                "lock_sha256": metadata.get("lock_sha256"),
                "operation_count": len(metadata.get("operations", {})),
            }
        sources[name] = item
    if folder.is_dir():
        # Remove discovery files of sources no longer in this catalog.
        for stale in folder.glob("*.json.gz"):
            if stale.name not in written:
                stale.unlink()
    destination.write_text(json.dumps({**catalog, "sources": sources}, indent=2) + "\n")
    write_search_index(sources, destination, loaded)


def write_search_index(sources, destination, loaded=None):
    """Index all operations of the written catalog for `netmed find`.

    Search is optional: if indexing fails (for example SQLite without FTS5),
    the catalog stays usable, a warning is printed and no stale index remains.
    """
    import sys
    from .search import (
        api_documents,
        graphql_documents,
        index_path,
        python_documents,
        write_index,
    )

    destination = Path(destination).resolve()
    loaded = loaded or {}

    def relative(path):
        path = Path(path)
        return path if path.is_absolute() else destination.parent / path

    descriptions = {
        name: item.get("description")
        or (item.get("source_metadata") or {}).get("summary")
        or ""
        for name, item in sources.items()
    }

    def documents():
        for name, item in sources.items():
            try:
                if item["kind"] == "python" and item.get("discovery_file"):
                    metadata = loaded.get(name)
                    if metadata is None:
                        reference = {
                            **item["discovery_file"],
                            "path": str(relative(item["discovery_file"]["path"])),
                        }
                        metadata = discovery_metadata({"discovery_file": reference})
                    yield from python_documents(name, metadata, item["module"])
                elif item["kind"] == "openapi":
                    from .runtime.restish import native_commands

                    spec = item["spec"]
                    if not spec.startswith("https://"):
                        spec = str(relative(spec))
                    rows = native_commands({**item, "spec": spec})
                    yield from api_documents(name, rows)
                elif item["kind"] == "graphql":
                    schema = relative(item["graphql"]["schema"])
                    yield from graphql_documents(name, json.loads(schema.read_text()))
            except Exception as error:  # one source must not block the catalog
                print(
                    f"Search index skips {name}: {type(error).__name__}: {error}",
                    file=sys.stderr,
                )

    target = index_path(destination)
    try:
        write_index(target, documents(), descriptions)
    except Exception as error:
        target.unlink(missing_ok=True)
        print(
            f"Search index unavailable ({type(error).__name__}: {error}); "
            "netmed find is disabled for this catalog",
            file=sys.stderr,
        )


def discovery_metadata(source):
    """Return a Python source's discovery metadata, loading its file on demand."""
    if "discovery_metadata" in source:
        return source["discovery_metadata"]
    reference = source.get("discovery_file")
    if not reference:
        return None
    content = Path(reference["path"]).read_bytes()
    if hashlib.sha256(content).hexdigest() != reference["sha256"]:
        from .errors import UserError

        raise UserError("Discovery file checksum mismatch; rebuild the catalog")
    source["discovery_metadata"] = json.loads(gzip.decompress(content))
    return source["discovery_metadata"]


def discovery_hashes(source):
    """Configuration and lock hashes of the discovery, without loading it."""
    if "discovery_metadata" in source:
        metadata = source["discovery_metadata"] or {}
    else:
        metadata = source.get("discovery_file") or {}
    if not metadata:
        return None
    return metadata.get("configuration_hash"), metadata.get("lock_sha256")


def load(path):
    path = Path(path).resolve()
    catalog = json.loads(path.read_text())
    for source in catalog.get("sources", {}).values():
        if source.get("discovery_file"):
            source["discovery_file"]["path"] = str(
                (path.parent / source["discovery_file"]["path"]).resolve()
            )
        if source.get("graphql"):
            source["graphql"]["schema"] = str(
                (path.parent / source["graphql"]["schema"]).resolve()
            )
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
