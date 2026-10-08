"""Trusted object snapshots, selectors and serialization in the package interpreter."""

import contextlib
import importlib.metadata
import json
import sys


class ObjectError(ValueError):
    pass


def object_io(request):
    """Keep object code in the standalone worker where scientific classes exist."""
    import pickle
    import re
    import shutil
    import uuid
    from pathlib import Path
    from datetime import datetime, timezone

    root = Path(request["objects_root"])
    loaded = {}

    def load(value):
        if isinstance(value, list):
            return [load(item) for item in value]
        if isinstance(value, tuple):
            return tuple(load(item) for item in value)
        if isinstance(value, dict):
            return {key: load(item) for key, item in value.items()}
        if not isinstance(value, str) or not value.startswith("@object:"):
            return value
        match = re.fullmatch(r"@object:([0-9a-f]{32})(.*)", value)
        if not match:
            raise ObjectError("Invalid object reference; use @object:<32-character ID>")
        identity, suffix = match.groups()
        selectors = []
        if suffix:
            import ast

            try:
                tree = ast.parse("object" + suffix, mode="eval").body
                while isinstance(tree, ast.Subscript):
                    key = ast.literal_eval(tree.slice)
                    if type(key) not in (int, str):
                        raise ValueError(
                            "selectors must be integer indices or string keys"
                        )
                    selectors.append(key)
                    tree = tree.value
                if (
                    not isinstance(tree, ast.Name)
                    or tree.id != "object"
                    or not selectors
                ):
                    raise ValueError("expected bracket selectors")
            except (SyntaxError, ValueError, TypeError) as error:
                raise ObjectError(f"Invalid object selector: {error}") from error
        if identity not in loaded:
            path = root / identity
            if any(
                p.is_symlink()
                for p in (root, path, path / "metadata.json", path / "object.pkl")
            ):
                raise ObjectError("Symlink object artifacts are not supported")
            if (
                not (path / "metadata.json").is_file()
                or not (path / "object.pkl").is_file()
            ):
                raise ObjectError(f"Object {identity} not found or incomplete")
            try:
                with (path / "object.pkl").open("rb") as stream:
                    loaded[identity] = pickle.load(stream)
            except Exception as error:
                raise ObjectError(
                    f"Cannot load object {identity} in this environment ({type(error).__name__}: {error}). Check required packages and versions."
                ) from error
        result = loaded[identity]
        for key in reversed(selectors):
            try:
                if type(result) not in (list, tuple, dict):
                    raise TypeError(
                        "selection supports lists, tuples and dictionaries only"
                    )
                if type(result) in (list, tuple) and type(key) is not int:
                    raise TypeError("list/tuple indices must be integers")
                result = result[key]
            except (KeyError, IndexError, TypeError) as error:
                raise ObjectError(
                    f"Cannot select {key!r} from object {identity}: {error}"
                ) from error
        return result

    def save(value, label, parent=None):
        if root.is_symlink():
            raise ObjectError("Objects root must not be a symlink")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        identity = uuid.uuid4().hex
        staging = root / (".tmp-" + identity)
        staging.mkdir(mode=0o700)
        try:
            with (staging / "object.pkl").open("wb") as stream:
                pickle.dump(value, stream, protocol=4)
            metadata = {
                "id": identity,
                "label": label,
                "type": type(value).__module__ + "." + type(value).__qualname__,
                "source": request["module"],
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "environment_id": request["environment_id"],
                "arguments": request["original_arguments"],
                "input_objects": list(loaded),
                "packages": {
                    dist.metadata["Name"]: dist.version
                    for dist in importlib.metadata.distributions()
                },
            }
            if type(value) in (list, tuple, dict):
                items = value.items() if type(value) is dict else enumerate(value)
                entries = []
                for key, item in items:
                    if len(entries) >= 20:
                        break
                    if type(key) in (int, str):
                        entries.append(
                            {
                                "selector": "[" + repr(key) + "]",
                                "type": type(item).__module__
                                + "."
                                + type(item).__qualname__,
                            }
                        )
                metadata["structure"] = {
                    "length": len(value),
                    "items": entries,
                    "complete": len(entries) == len(value),
                }
            if parent:
                metadata["parent_object"] = parent
            (staging / "metadata.json").write_text(json.dumps(metadata))
            staging.rename(root / identity)
            return {key: metadata[key] for key in ("id", "label", "type")}
        except Exception as error:
            shutil.rmtree(staging)
            raise ObjectError(
                f"Cannot save object ({type(error).__name__}: {error}); use a package-native exporter for unsupported objects."
            ) from error

    def serialize(result):
        saved = []
        options = request["object_options"]
        if (
            "--save-updated-object" in options
            and options["--save-updated-object"] not in loaded
        ):
            raise ObjectError(
                "--save-updated-object must name an object loaded by this invocation"
            )
        if "--save-object" in options:
            saved.append(save(result, options["--save-object"]))
        if "--save-updated-object" in options:
            identity = options["--save-updated-object"]
            saved.append(save(loaded[identity], "updated-" + identity, parent=identity))
        return json.dumps({"saved_objects": saved})

    return load, serialize


@contextlib.contextmanager
def saved_output():
    """Redirect diagnostics including inherited child-process stdout."""
    import os

    sys.stdout.flush()
    with os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8") as output:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        try:
            with contextlib.redirect_stdout(sys.stderr):
                yield output
        finally:
            sys.stderr.flush()
            os.dup2(output.fileno(), 1)
