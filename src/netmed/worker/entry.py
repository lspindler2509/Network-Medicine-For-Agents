"""Entry point executed directly with a scientific package interpreter."""

import contextlib
import importlib
import json
from pathlib import Path
import sys

# Direct script execution has no package context; import only this sibling package.
# Installed worker sources are read-only application resources; cache only package code.
previous = sys.dont_write_bytecode
sys.dont_write_bytecode = True
try:
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from worker.discovery import discover
        from worker.metadata import package_summary, package_documentation
        from worker.invocation import load_modules, invoke
    else:
        from .discovery import discover
        from .metadata import package_summary, package_documentation
        from .invocation import load_modules, invoke
finally:
    sys.dont_write_bytecode = previous


def main():
    request = json.load(sys.stdin)
    if request.get("action") == "discover":
        # Import-time prints must not corrupt the discovery protocol.
        with contextlib.redirect_stdout(sys.stderr):
            module = importlib.import_module(request["module"])
            modules, failures = load_modules(module, request.get("submodules", False))
            result = discover(module)
            for child in modules[1:]:
                prefix = child.__name__[len(module.__name__) + 1 :]
                child_metadata = discover(child)
                result["operations"].update(
                    {
                        prefix + "." + key: value
                        for key, value in child_metadata["operations"].items()
                    }
                )
                result["omitted"].extend(
                    {"name": prefix + "." + item["name"], "reason": item["reason"]}
                    for item in child_metadata["omitted"]
                )
            result["omitted"].extend(failures)
            result["source_metadata"] = package_summary(
                request["module"], request.get("package")
            )
        print(json.dumps(result))
    elif request.get("action") == "docs":
        print(
            json.dumps(package_documentation(request["module"], request.get("package")))
        )
    else:
        invoke(request)


if __name__ == "__main__":
    main()
