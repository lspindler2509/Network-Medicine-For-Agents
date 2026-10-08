"""Bind registry inputs to explicitly versioned, target-specific locks."""

import hashlib
import json
from pathlib import Path
from ..errors import UserError
from ..runtime.environments import platform_target


def input_hash(source):
    fields = ("package", "version", "dependencies", "python")
    return hashlib.sha256(
        json.dumps(
            {k: source[k] for k in fields if k in source}, sort_keys=True
        ).encode()
    ).hexdigest()


def apply_lock(source, name, directory):
    if source.get("path"):
        raise UserError("Release locks cannot contain local packages")
    directory = Path(directory).resolve()
    try:
        manifest = json.loads((directory / "manifest.json").read_text())
        entry = manifest["sources"][name]
        path = directory / (name + ".txt")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        target = manifest["target"]
        expected_input, expected_digest, python = (
            entry["input_sha256"],
            entry["sha256"],
            entry["python"],
        )
    except (OSError, KeyError, ValueError) as error:
        raise UserError(f"Missing or invalid release lock for {name}") from error
    if target != platform_target() or expected_input != input_hash(source):
        raise UserError(
            f"Release lock target or registry inputs changed for {name}; update locks explicitly"
        )
    if digest != expected_digest:
        raise UserError(f"Release lock checksum mismatch for {name}")
    source["python"] = python
    source["lock"] = {"path": str(path), "sha256": digest, "target": target}
