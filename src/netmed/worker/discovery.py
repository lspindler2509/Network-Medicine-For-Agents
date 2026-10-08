"""Introspect public Python interfaces without invoking them."""

import inspect
import importlib.metadata


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


def discover(module):
    operations, omitted = {}, []
    namespace = vars(module)
    exported = namespace.get("__all__")
    names = exported if isinstance(exported, (list, tuple)) else sorted(namespace)
    for name in names:
        if not isinstance(name, str) or name.startswith("_"):
            continue
        if name not in namespace:
            omitted.append({"name": name, "reason": "dynamic attribute"})
            continue
        target = namespace[name]
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
        ],
    }
