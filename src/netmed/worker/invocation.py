"""Source loading, setup and native Fire invocation."""

import contextlib
import importlib
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


def configure(module, steps):
    for step in steps:
        target = module
        for segment in step["call"].split("."):
            if segment.startswith("_"):
                raise ValueError("Private setup targets are not supported")
            target = getattr(target, segment)
        target(*step.get("args", []), **step.get("kwargs", {}))


def invoke(request):
    import fire

    options = request.get("object_options", {})
    with saved_output() if options else contextlib.nullcontext(None) as output:
        load, serialize = object_io(request)
        if request.get("action") == "show_object":
            module = load("@object:" + request["object_id"])
        else:
            module = importlib.import_module(request["module"])
            load_modules(module, request.get("submodules", False))
            configure(module, request.get("setup", []))
        # Scoped interception of the pinned Fire default parser, not adapters.
        default_parse = fire.parser.DefaultParseValue

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
