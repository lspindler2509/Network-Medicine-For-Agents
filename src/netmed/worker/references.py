"""Resolve local snapshot IDs and labels without loading Python objects."""

import json
import re


class ObjectError(ValueError):
    pass


def resolve_identity(root, value):
    if re.fullmatch(r"[0-9a-f]{32}", value):
        return value
    if not value or "/" in value or "\\" in value or root.is_symlink():
        raise ObjectError("Invalid object label or symlink objects root")
    matches = []
    for path in sorted(root.glob("*/metadata.json")):
        if path.is_symlink() or path.parent.is_symlink():
            raise ObjectError("Symlink object artifacts are not supported")
        try:
            metadata = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise ObjectError("Cannot read object metadata") from error
        identity = path.parent.name
        if metadata.get("label") == value:
            if (
                not re.fullmatch(r"[0-9a-f]{32}", identity)
                or metadata.get("id") != identity
            ):
                raise ObjectError("Invalid object metadata ID")
            if not (path.parent / "object.pkl").is_file():
                raise ObjectError(f"Object {identity} is incomplete")
            matches.append(identity)
    if not matches:
        raise ObjectError(f"Object label {value!r} not found")
    if len(matches) != 1:
        raise ObjectError(
            f"Ambiguous object label {value!r}; use an ID: {', '.join(matches)}"
        )
    return matches[0]
