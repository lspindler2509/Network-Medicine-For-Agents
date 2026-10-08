"""Inspect and clean trusted local object artifacts without loading Pickle."""

import json
import re
import shutil
from pathlib import Path
from .layout import data_directory
from ..errors import UserError


def directory_for():
    return data_directory() / "objects"


def validate_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise UserError("Invalid object ID")
    return value


def inspect_object(value):
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
        validate_id(options["--save-updated-object"])
    return args, options
