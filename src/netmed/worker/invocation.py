"""Source loading, setup and native Fire invocation."""

import contextlib
import importlib
import importlib.util
import inspect
import json
import pkgutil
import sys
from .objects import ObjectError, object_io, saved_output, structure_overview
from .callbacks import parse_callback
from .results import result_serializer


def load_modules(module, enabled):
    modules = [module]
    failures = []
    if enabled and hasattr(module, "__path__"):
        for candidate in pkgutil.walk_packages(module.__path__, module.__name__ + "."):
            if any(part.startswith("_") for part in candidate.name.split(".")[1:]):
                continue
            try:
                modules.append(importlib.import_module(candidate.name))
            except Exception:
                failures.append(
                    {"name": candidate.name, "reason": "submodule import failed"}
                )
    return modules, failures


def import_requested_submodules(module, arguments):
    """Import package submodules named by the leading call path, on demand.

    Fire resolves paths with getattr, which only finds submodules a package
    already imported. Each leading identifier that is not an attribute but an
    existing submodule is imported, so discovered submodule paths stay callable
    without importing every submodule for each invocation. Import errors of an
    existing submodule are raised rather than hidden.
    """
    current = module
    for token in arguments:
        if not inspect.ismodule(current) or not token.isidentifier():
            return
        if token.startswith("_"):
            return
        if token in vars(current):
            current = vars(current)[token]
            continue
        namespace = vars(current)
        name = namespace["__name__"] + "." + token
        if namespace.get("__path__") is None or importlib.util.find_spec(name) is None:
            return
        current = importlib.import_module(name)


def configure(module, steps):
    for step in steps:
        target = module
        for segment in step["call"].split("."):
            if segment.startswith("_"):
                raise ValueError("Private setup targets are not supported")
            target = getattr(target, segment)
        target(*step.get("args", []), **step.get("kwargs", {}))


def tolerant_arg_spec_info(original):
    """Wrap Fire's arg-spec helper for builtins that lack ``__self__``.

    Fire 0.7 assumes every object ``inspect.isbuiltin`` accepts has ``__self__``.
    Extension functions (for example Boost.Python) can pass that check without
    the attribute; they are unbound like module functions, so no argument is
    skipped. Every other callable keeps Fire's own behavior.
    """

    def arg_spec_info(fn):
        if inspect.isbuiltin(fn) and not hasattr(fn, "__self__"):
            return fn, False
        return original(fn)

    return arg_spec_info


def invoke(request):
    import fire
    import fire.inspectutils

    options = request.get("object_options", {})
    with saved_output() if options else contextlib.nullcontext(None) as output:
        load, serialize = object_io(request)
        if request.get("action") == "show_object":
            module = load("@object:" + request["object_id"])
        else:
            module = importlib.import_module(request["module"])
            load_modules(module, request.get("submodules", False))
            import_requested_submodules(module, request["arguments"])
            configure(module, request.get("setup", []))
        # Scoped interception of the pinned Fire default parser, not adapters.
        default_parse = fire.parser.DefaultParseValue
        default_spec_info = getattr(fire.inspectutils, "_GetArgSpecInfo", None)

        def parse(value):
            if value.startswith("@lambda:"):
                return parse_callback(value)
            if value.startswith("@object:"):
                return load(value)
            return load(default_parse(value))

        def object_preview(value, reason):
            structure = structure_overview(value)
            metadata = dict(request["object_metadata"])
            if structure is not None:
                metadata.pop("structure", None)
            return json.dumps(
                {
                    **({"structure": structure} if structure is not None else {}),
                    "metadata": metadata,
                    "reason": reason.replace("; saved as a Python object", ""),
                    "hint": "Explore methods with "
                    + request["name"]
                    + " --help; call them with "
                    + request["name"]
                    + " - <method> [arguments]",
                },
                ensure_ascii=False,
            )

        fire.parser.DefaultParseValue = parse
        if default_spec_info is not None:
            fire.inspectutils._GetArgSpecInfo = tolerant_arg_spec_info(
                default_spec_info
            )
        try:
            if options:

                def save_output(result):
                    output.write(serialize(result) + "\n")
                    output.flush()
                    return ""

                fire.Fire(
                    module,
                    command=request["arguments"],
                    name=request["name"],
                    serialize=save_output,
                )
            else:
                fire.Fire(
                    module,
                    command=request["arguments"],
                    name=request["name"],
                    serialize=result_serializer(
                        serialize,
                        fallback=object_preview
                        if request.get("action") == "show_object"
                        else None,
                    ),
                )
        except ObjectError as error:
            print(f"Object error: {error}", file=sys.stderr)
            raise SystemExit(1)
        finally:
            fire.parser.DefaultParseValue = default_parse
            if default_spec_info is not None:
                fire.inspectutils._GetArgSpecInfo = default_spec_info
