"""Inspect and clean trusted local object artifacts without loading Pickle."""

import json
import re
import shutil
from pathlib import Path
from .layout import data_directory
from ..errors import UserError
from ..worker.references import ObjectError, resolve_identity


def directory_for():
    return data_directory() / "objects"


def validate_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise UserError("Invalid object ID")
    return value


def resolve_object(value):
    try:
        return resolve_identity(directory_for(), value)
    except ObjectError as error:
        raise UserError(str(error)) from error


def inspect_object(value):
    value = resolve_object(value)
    root = directory_for()
    path = root / validate_id(value)
    if any(
        p.is_symlink()
        for p in (root, path, path / "metadata.json", path / "object.pkl")
    ):
        raise UserError("Symlink object artifacts are not supported")
    if not (path / "metadata.json").is_file() or not (path / "object.pkl").is_file():
        raise UserError(f"Object {value} not found or incomplete")
    metadata = json.loads((path / "metadata.json").read_text())
    if metadata.get("id") != value:
        raise UserError("Object metadata ID does not match its directory")
    return {
        **metadata,
        "path": str((path / "object.pkl").resolve()),
        "bytes": (path / "object.pkl").stat().st_size,
    }


def list_objects():
    return [
        {k: item[k] for k in ("id", "label", "type", "source", "created_at", "bytes")}
        for path in sorted(directory_for().glob("*/metadata.json"))
        for item in [inspect_object(path.parent.name)]
    ]


def clean(ids, dry_run=False):
    selected = list(dict.fromkeys(ids))
    entries = (
        [inspect_object(value) for value in selected] if selected else list_objects()
    )
    # An ID and its label may identify the same immutable snapshot.
    entries = list({item["id"]: item for item in entries}.values())
    if not dry_run:
        for item in entries:
            shutil.rmtree(directory_for() / item["id"])
    return {
        "dry_run": dry_run,
        "would_remove" if dry_run else "removed": [
            {"id": item["id"], "label": item["label"], "type": item["type"]}
            for item in entries
        ],
    }


def execution_options(arguments):
    args, options = [], {}
    iterator = iter(arguments)
    for arg in iterator:
        key, sep, value = arg.partition("=")
        if key in ("--save-object", "--save-updated-object"):
            if not sep:
                value = next(iterator, "")
            if not value or value.startswith("--") or key in options:
                raise UserError(f"{key} requires one value and may be used once")
            options[key] = value
        else:
            args.append(arg)
    if "--save-updated-object" in options:
        options["--save-updated-object"] = resolve_object(
            options["--save-updated-object"]
        )
    return args, options


def display_metadata(value, full=False):
    metadata = inspect_object(value)
    if full:
        return metadata
    arguments = json.dumps(metadata.pop("arguments", []), ensure_ascii=False)
    metadata["arguments_preview"] = arguments[:500]
    metadata["arguments_truncated"] = len(arguments) > 500
    if metadata["arguments_truncated"]:
        metadata["arguments_note"] = (
            "Use --full to show the complete original arguments"
        )
    return metadata


def show(value, arguments):
    import os
    import subprocess
    from .environments import WORKER
    from .processes import process_environment

    metadata = inspect_object(value)
    identity = metadata.get("environment_id", "")
    if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{24}", identity):
        raise UserError("Snapshot has no valid original environment reference")
    root = data_directory() / "environments"
    environment = root / identity
    ready = environment / "environment.json"
    if any(path.is_symlink() for path in (root, environment, ready)):
        raise UserError("Symlink environment metadata is not supported")
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not ready.is_file() or not python.is_file():
        raise UserError(
            "Original snapshot environment is unavailable; no packages are installed automatically"
        )
    if json.loads(ready.read_text()).get("id") != identity:
        raise UserError("Original environment metadata ID does not match")
    parsed, options = execution_options(arguments)
    request = {
        "action": "show_object",
        "object_id": metadata["id"],
        "object_metadata": display_metadata(metadata["id"]),
        "module": metadata["source"],
        "environment_id": identity,
        "objects_root": str(directory_for()),
        "object_options": options,
        "arguments": parsed[1:] if parsed[:1] == ["-"] else parsed,
        "original_arguments": arguments,
        "name": "netmed objects show " + metadata["id"],
    }
    return subprocess.run(
        [str(python), str(WORKER)],
        input=json.dumps(request),
        text=True,
        env=process_environment(),
    ).returncode
