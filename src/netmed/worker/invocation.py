"""Source loading, setup and native Fire invocation."""

import contextlib
import importlib
import pkgutil
import sys
from .objects import ObjectError, object_io, saved_output
from .callbacks import parse_callback


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
        module = importlib.import_module(request["module"])
        load_modules(module, request.get("submodules", False))
        configure(module, request.get("setup", []))
        load, serialize = object_io(request)
        # Scoped interception of the pinned Fire default parser, not adapters.
        default_parse = fire.parser.DefaultParseValue

        def parse(value):
            if value.startswith("@lambda:"):
                return parse_callback(value)
            if value.startswith("@object:"):
                return load(value)
            return load(default_parse(value))

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
                fire.Fire(module, command=request["arguments"], name=request["name"])
        except ObjectError as error:
            print(f"Object error: {error}", file=sys.stderr)
            raise SystemExit(1)
        finally:
            fire.parser.DefaultParseValue = default_parse
