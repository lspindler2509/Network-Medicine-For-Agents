"""Export a relocatable, target-specific catalog and exact dependency locks."""

import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from .catalog import python_configuration_hash
from .errors import UserError
from .runtime.environments import UvEnvironmentManager, platform_target
from .runtime.processes import process_environment


def export(catalog_path, destination, names=None, *, use_updates=False):
    from .runtime.source_updates import active_catalog

    catalog = active_catalog(catalog_path, use_updates=use_updates)
    selected = list(dict.fromkeys(names or catalog["sources"]))
    if any(name not in catalog["sources"] for name in selected):
        raise UserError("Unknown release source")
    destination = Path(destination).resolve()
    if destination.exists():
        raise UserError("Release destination already exists; choose a new directory")
    for name in selected:
        source = catalog["sources"][name]
        if source.get("path"):
            raise UserError("Release bundles cannot contain local packages")
    destination.parent.mkdir(parents=True, exist_ok=True)
    manager = UvEnvironmentManager()
    with tempfile.TemporaryDirectory(dir=destination.parent) as staging:
        root = Path(staging) / "bundle"
        (root / "locks").mkdir(parents=True)
        result = {
            "sources": {},
            "disabled_sources": {
                name: {
                    key: item[key]
                    for key in ("kind", "description", "disabled_reason")
                    if key in item
                }
                for name, item in catalog.get("disabled_sources", {}).items()
            },
        }
        manifest = {
            "target": platform_target(),
            "locks": {},
            "api_specs": "Bundled OpenAPI and GraphQL schema snapshots; remote database contents are not pinned.",
        }
        for name in selected:
            source = copy.deepcopy(catalog["sources"][name])
            if source["kind"] == "python":
                env = manager.ensure(source)
                actual = subprocess.run(
                    [
                        env["python"],
                        "-c",
                        "import platform; print(platform.python_version())",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=process_environment(),
                ).stdout.strip()
                if not re.fullmatch(r"\d+\.\d+\.\d+", actual):
                    raise UserError(
                        "Could not identify an exact release Python version"
                    )
                lock_bytes = (Path(env["directory"]) / "requirements.lock").read_bytes()
                observed_digest = hashlib.sha256(lock_bytes).hexdigest()
                text = lock_bytes.decode()
                # Generated uv comments contain local paths, not dependency semantics.
                text = (
                    "\n".join(
                        line
                        for line in text.splitlines()
                        if not line.lstrip().startswith("#")
                    )
                    + "\n"
                )
                digest = hashlib.sha256(text.encode()).hexdigest()
                relative = f"locks/{name}.txt"
                (root / relative).write_bytes(text.encode())
                source["python"] = actual
                source["lock"] = {
                    "path": relative,
                    "sha256": digest,
                    "target": platform_target(),
                }
                from .catalog import discovery_metadata

                metadata = discovery_metadata(source)
                if metadata:
                    from .importers.python import discover

                    original = catalog["sources"][name]
                    if (
                        metadata.get("configuration_hash")
                        != python_configuration_hash(original)
                        or metadata.get("lock_sha256") != observed_digest
                    ):
                        metadata = discover(original)
                        if metadata.get("lock_sha256") != observed_digest:
                            raise UserError(
                                "Dependency lock changed during export; rebuild the catalog"
                            )
                        source["source_metadata"] = metadata.pop(
                            "source_metadata", source.get("source_metadata", {})
                        )
                    source["discovery_metadata"] = metadata
                    metadata.pop("environment_id", None)
                    metadata["configuration_hash"] = python_configuration_hash(source)
                    metadata["lock_sha256"] = digest
                manifest["locks"][name] = {"sha256": digest, "python": actual}
            elif source["kind"] == "graphql":
                from .graphql.schema import read_snapshot

                document = read_snapshot(source)
                (root / "schemas").mkdir(exist_ok=True)
                relative = f"schemas/{name}.json"
                content = json.dumps(document, ensure_ascii=False).encode()
                (root / relative).write_bytes(content)
                source["graphql"] = {
                    "schema": relative,
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            else:
                from .runtime.restish_binary import VERSION
                from .importers.openapi import load_document, require_self_contained

                document = load_document(source["spec"])
                require_self_contained(document)
                (root / "specs").mkdir(exist_ok=True)
                relative = f"specs/{name}.json"
                (root / relative).write_text(json.dumps(document))
                source["spec"] = relative
                source["restish"] = {"version": VERSION, "source": name}
            result["sources"][name] = source
        from .catalog import write

        write(result, root / "catalog.json")
        manifest["catalog_sha256"] = hashlib.sha256(
            (root / "catalog.json").read_bytes()
        ).hexdigest()
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        root.rename(destination)
    return {
        "directory": str(destination),
        "target": platform_target(),
        "sources": selected,
    }
