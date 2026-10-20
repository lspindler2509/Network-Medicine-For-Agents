"""Introspect public Python interfaces without invoking them."""

import importlib
import importlib.metadata
import inspect
import pkgutil
import time

# Generic, package-independent naming conventions for non-API submodules.
NON_API_SUBMODULES = frozenset(
    {"test", "tests", "testing", "conftest", "setup", "examples", "benchmarks"}
)
SUBMODULE_DEPTH = 3
SUBMODULE_LIMIT = 400


def annotation(value):
    if value is inspect.Signature.empty:
        return None
    if isinstance(value, str):
        return value
    return inspect.formatannotation(value)


def describe(target, kind):
    try:
        signature = inspect.signature(target, eval_str=False)
    except (TypeError, ValueError):
        signature = None
    parameters = []
    if signature:
        for name, parameter in signature.parameters.items():
            default = parameter.default
            parameters.append(
                {
                    "name": name,
                    "kind": parameter.kind.name,
                    "annotation": annotation(parameter.annotation),
                    "required": default is inspect.Signature.empty
                    and parameter.kind
                    not in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD),
                    "default": default
                    if type(default) in (str, int, float, bool, type(None))
                    else None,
                    "has_default": default is not inspect.Signature.empty,
                }
            )
    return {
        "kind": kind,
        "signature": str(signature) if signature else None,
        "parameters": parameters,
        "returns": annotation(signature.return_annotation) if signature else None,
        "doc": inspect.getdoc(target) or "",
        "defined_in": getattr(target, "__module__", None),
    }


def discover(module, seen=None):
    """Describe a module's public members.

    ``seen`` holds ids of objects already described under another module path;
    those re-exports are skipped so that traversed submodules do not duplicate
    entries. Members of this module are added to ``seen`` afterwards.
    """
    operations, omitted = {}, []
    namespace = vars(module)
    exported = namespace.get("__all__")
    names = exported if isinstance(exported, (list, tuple)) else sorted(namespace)
    described = set()
    for name in names:
        if not isinstance(name, str) or name.startswith("_"):
            continue
        if name not in namespace:
            omitted.append({"name": name, "reason": "dynamic attribute"})
            continue
        target = namespace[name]
        if seen is not None and not inspect.ismodule(target):
            if id(target) in seen:
                continue
            described.add(id(target))
        try:
            if inspect.isclass(target):
                operations[name] = describe(target, "class")
                for member, method in inspect.getmembers_static(target):
                    if member.startswith("_"):
                        continue
                    if isinstance(method, (staticmethod, classmethod)):
                        method = method.__func__
                    if (
                        inspect.isfunction(method)
                        or inspect.ismethoddescriptor(method)
                        or inspect.isbuiltin(method)
                    ):
                        operations[name + "." + member] = describe(method, "method")
                    elif isinstance(method, property):
                        omitted.append(
                            {
                                "name": name + "." + member,
                                "reason": "property not evaluated",
                            }
                        )
            elif inspect.isroutine(target):
                operations[name] = describe(target, "function")
            elif inspect.ismodule(target):
                omitted.append(
                    {"name": name, "reason": "nested/imported module not traversed"}
                )
            elif callable(target):
                operations[name] = describe(target, "callable")
        except Exception as error:
            # A single member must not fail discovery of the whole source.
            operations.pop(name, None)
            omitted.append(
                {
                    "name": name,
                    "reason": "introspection failed: " + type(error).__name__,
                }
            )
    if seen is not None:
        seen.update(described)
    versions = {
        d.metadata["Name"]: d.version
        for d in importlib.metadata.distributions()
        if d.metadata["Name"]
    }
    return {
        "module": module.__name__,
        "operations": operations,
        "packages": versions,
        "complete": False,
        "omitted": omitted,
        "limitations": [
            "Static public exports only; dynamic attributes and runtime-generated methods may be absent.",
            "Methods are described without constructing classes or evaluating properties.",
            "Missing docstrings, schemas inside dictionaries and imported members are not resolved.",
            f"Package submodules are traversed up to depth {SUBMODULE_DEPTH} and {SUBMODULE_LIMIT} modules within a time budget; objects re-exported under a shorter path are listed once.",
        ],
    }


def package_submodules(module, deadline=None, bounded=True):
    """Find public submodules of ``module``'s own package, breadth-first.

    Yields ``(path, submodule)`` with ``path`` relative to ``module``. Attached
    module attributes keep their attribute name, which is the path Fire calls.
    Unattached submodules are imported; invocation imports them on demand.
    Foreign modules, private names and conventional test/example packages are
    skipped. Returns failures and limit notes through ``omitted``. With
    ``bounded=False`` (sources declaring ``submodules = true``) depth and count
    limits do not apply, as those sources request complete discovery.
    """
    root = module.__name__.split(".")[0]
    omitted = []
    visited = {id(module): ""}
    queue = [("", module)]
    found = []
    while queue:
        prefix, parent = queue.pop(0)
        if bounded and prefix and prefix.count(".") + 1 >= SUBMODULE_DEPTH:
            continue
        candidates = {}
        for name, value in sorted(vars(parent).items()):
            if (
                isinstance(name, str)
                and not name.startswith("_")
                and name not in NON_API_SUBMODULES
                and inspect.ismodule(value)
            ):
                candidates[name] = value
        # Read module dunders from the namespace: a module-level __getattr__ may
        # raise other errors than AttributeError for missing attributes.
        package_path = vars(parent).get("__path__")
        if package_path is not None:
            try:
                children = list(pkgutil.iter_modules(package_path))
            except Exception:
                children = []
            for child in children:
                name = child.name
                if (
                    name in candidates
                    or name.startswith("_")
                    or name in NON_API_SUBMODULES
                ):
                    continue
                if deadline is not None and time.monotonic() > deadline:
                    omitted.append(
                        {
                            "name": (prefix + "." if prefix else "") + name,
                            "reason": "submodule traversal time budget exhausted",
                        }
                    )
                    continue
                try:
                    candidates[name] = importlib.import_module(
                        vars(parent)["__name__"] + "." + name
                    )
                except (Exception, SystemExit):
                    omitted.append(
                        {
                            "name": (prefix + "." if prefix else "") + name,
                            "reason": "submodule import failed",
                        }
                    )
        for name, value in candidates.items():
            owner = vars(value).get("__name__") or ""
            if not (owner == root or owner.startswith(root + ".")):
                continue
            path = (prefix + "." if prefix else "") + name
            if id(value) in visited:
                if visited[id(value)]:
                    omitted.append(
                        {
                            "name": path,
                            "reason": "alias of traversed submodule "
                            + visited[id(value)],
                        }
                    )
                continue
            visited[id(value)] = path
            if bounded and len(found) >= SUBMODULE_LIMIT:
                omitted.append(
                    {"name": path, "reason": "submodule traversal limit reached"}
                )
                continue
            found.append((path, value))
            queue.append((path, value))
    return found, omitted
