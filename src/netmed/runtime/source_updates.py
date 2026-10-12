"""Explicit API schema refresh and a local overlay over the shipped catalog."""

import contextlib
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import requests

from ..catalog import load, validate_url
from ..errors import UserError
from .layout import data_directory, default_catalog, asset_directory
from .environments import installation_lock

API_KINDS = {"openapi", "graphql"}


def directory():
    return data_directory() / "api-updates"


def identity(source):
    """Bind overrides to the declared interface, not a bundle's absolute paths."""
    keys = ("kind", "endpoint", "base_url", "spec_origin")
    values = {key: source[key] for key in keys if key in source}
    if source["kind"] == "openapi" and not source.get("spec_origin"):
        values["spec"] = source.get("spec")
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def read_overrides():
    root = directory()
    path = root / "catalog.json"
    if root.is_symlink() or path.is_symlink():
        raise UserError("API update metadata must not be a symlink")
    if not path.exists():
        return {"sources": {}}
    result = json.loads(path.read_text())
    if not isinstance(result, dict) or not isinstance(result.get("sources"), dict):
        raise UserError("Invalid local API update catalog")
    return result


def active_catalog(path, *, use_updates=True):
    catalog = load(path)
    if not use_updates or Path(path).resolve() != default_catalog().resolve():
        return catalog
    for name, entry in read_overrides()["sources"].items():
        original = catalog["sources"].get(name)
        if (
            original
            and original["kind"] in API_KINDS
            and entry.get("identity") == identity(original)
        ):
            # Preserve current registry settings/descriptions across CLI upgrades;
            # only generated interface metadata and snapshot references override.
            refreshed = copy.deepcopy(original)
            refreshed.update(entry["interface"])
            catalog["sources"][name] = refreshed
    return catalog


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(value, output, indent=2, ensure_ascii=False)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def snapshot(content):
    root = directory() / "snapshots"
    if root.is_symlink():
        raise UserError("API snapshot directory must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    path = root / (hashlib.sha256(content).hexdigest() + ".json")
    if path.is_symlink():
        raise UserError("API snapshot must not be a symlink")
    if path.exists():
        if path.read_bytes() != content:
            raise UserError("API snapshot checksum mismatch")
        return str(path)
    descriptor, temporary = tempfile.mkstemp(dir=root, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return str(path)


def schema_digest(source):
    if source["kind"] == "graphql":
        from ..graphql.schema import read_snapshot

        document = read_snapshot(source)
    elif source.get("schema_sha256"):
        return source["schema_sha256"]
    elif source.get("spec") and not source["spec"].startswith("https://"):
        from ..importers.openapi import load_document

        document = load_document(source["spec"])
    else:
        return None  # Older remote catalogs have no saved previous schema.
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def refresh(source, name, staging):
    """Reuse importers; all discovery/preparation artifacts remain in staging."""
    candidate = copy.deepcopy(source)
    if source["kind"] == "openapi":
        from ..importers.openapi import discover, load_document, require_self_contained

        origin = source.get("spec_origin") or source.get("spec")
        if not origin or not origin.startswith("https://"):
            raise UserError(
                "No remote OpenAPI specification URL; rebuild the catalog from sources.toml"
            )
        validate_url(origin)
        document = load_document(origin)
        require_self_contained(document)
        path = staging / "spec.json"
        path.write_text(json.dumps(document, ensure_ascii=False))
        candidate["spec"] = str(path)
        candidate["spec_origin"] = origin
        candidate.update(
            discover(
                candidate,
                name,
                document=document,
                backend_directory=staging / "restish",
            )
        )
    else:
        from ..importers.graphql import discover

        validate_url(source["endpoint"])
        candidate.update(discover(candidate, name, staging / "graphql"))
    return candidate


def publish_interface(candidate, name):
    keys = ("source_metadata", "operation_count", "schema_sha256")
    interface = {key: candidate[key] for key in keys if key in candidate}
    if candidate["kind"] == "graphql":
        reference = dict(candidate["graphql"])
        reference["schema"] = snapshot(Path(reference["schema"]).read_bytes())
        interface["graphql"] = reference
    else:
        from .restish_binary import VERSION

        interface["spec"] = snapshot(Path(candidate["spec"]).read_bytes())
        interface["spec_origin"] = candidate["spec_origin"]
        interface["restish"] = {"version": VERSION, "source": name}
    return interface


def update(catalog_path, names=None, *, dry_run=False, use_updates=True, progress=None):
    path = Path(catalog_path).resolve()
    overlay = use_updates and path == default_catalog().resolve()
    if not overlay and path.is_relative_to(asset_directory().resolve()):
        raise UserError(
            "Bundled catalogs are read-only; omit --catalog or select a writable catalog"
        )
    # Validate the complete selection before making requests or publishing.
    catalog = active_catalog(path, use_updates=overlay)
    selected = list(
        dict.fromkeys(
            names
            or [
                name
                for name, source in catalog["sources"].items()
                if source["kind"] in API_KINDS
            ]
        )
    )
    for name in selected:
        if name not in catalog["sources"]:
            raise UserError(f"Unknown or disabled source: {name}")
        if catalog["sources"][name]["kind"] not in API_KINDS:
            raise UserError(
                f"Source {name} is Python; sources update supports only OpenAPI and GraphQL. Use build for Python discovery"
            )
    root = directory()
    if root.is_symlink():
        raise UserError("API update directory must not be a symlink")
    if not dry_run:
        root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    results = []
    progress = progress or sys.stderr
    with (
        contextlib.nullcontext() if dry_run else installation_lock(root / "update.lock")
    ):
        # Reload under the lock so concurrent updates cannot overwrite each other.
        catalog = active_catalog(path, use_updates=overlay)
        overrides = read_overrides() if overlay else None
        changed = False
        for index, name in enumerate(selected, 1):
            print(
                f"Checking {name} ({index}/{len(selected)})...",
                file=progress,
                flush=True,
            )
            original = catalog["sources"][name]
            result = {"source": name, "kind": original["kind"]}
            try:
                with tempfile.TemporaryDirectory(
                    prefix="netmed-api-update-"
                ) as temporary:
                    candidate = refresh(original, name, Path(temporary))
                    try:
                        previous_digest = schema_digest(original)
                    except (UserError, OSError, ValueError):
                        previous_digest = None
                    different = (
                        previous_digest != schema_digest(candidate)
                        or original.get("source_metadata")
                        != candidate.get("source_metadata")
                        or original.get("operation_count")
                        != candidate.get("operation_count")
                    )
                    result["schema_changed"] = different
                    # Restish's local spec-files backend does not reliably report
                    # command counts via api list. Report native query counts only
                    # for GraphQL rather than presenting zero as a real API count.
                    if original["kind"] == "graphql":
                        result.update(
                            operations_before=original.get("operation_count"),
                            operations_after=candidate.get("operation_count"),
                        )
                    result["status"] = (
                        ("would_update" if dry_run else "updated")
                        if different
                        else "unchanged"
                    )
                    if different and not dry_run:
                        interface = publish_interface(candidate, name)
                        if overlay:
                            overrides["sources"][name] = {
                                "identity": identity(original),
                                "interface": interface,
                            }
                        else:
                            catalog["sources"][name] = {**original, **interface}
                        changed = True
            except (
                UserError,
                ValueError,
                TypeError,
                OSError,
                requests.RequestException,
                subprocess.SubprocessError,
            ) as error:
                result.update(
                    status="failed",
                    reason=str(error)
                    if isinstance(error, UserError)
                    else f"Refresh failed ({type(error).__name__}); previous interface retained",
                )
            results.append(result)
        if changed:
            atomic_json(
                root / "catalog.json" if overlay else path,
                overrides if overlay else catalog,
            )
    return {
        "dry_run": dry_run,
        "target": "local API overrides" if overlay else str(path),
        "sources": results,
        "seconds": round(time.monotonic() - started, 2),
    }
