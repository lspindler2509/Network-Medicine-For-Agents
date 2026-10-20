"""Entry point executed directly with a scientific package interpreter."""

import contextlib
import importlib
import json
from pathlib import Path
import sys
import time

# Direct script execution has no package context; import only this sibling package.
# Installed worker sources are read-only application resources; cache only package code.
previous = sys.dont_write_bytecode
sys.dont_write_bytecode = True
try:
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from worker.discovery import discover, package_submodules
        from worker.metadata import package_summary, package_documentation
        from worker.invocation import load_modules, invoke
    else:
        from .discovery import discover, package_submodules
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
            _, failures = load_modules(module, request.get("submodules", False))
            budget = request.get("traversal_budget")
            deadline = time.monotonic() + budget if budget else None
            seen = set()
            result = discover(module, seen)
            if request.get("traverse", True):
                # Explicit full submodule discovery keeps its previous, unbounded scope.
                complete = request.get("submodules", False)
                children, traversal_notes = package_submodules(
                    module, None if complete else deadline, bounded=not complete
                )
            else:
                children, traversal_notes = [], []
            traversed = {path for path, _ in children} | {
                item["name"]
                for item in traversal_notes
                if item["reason"].startswith("alias of traversed submodule")
            }
            for prefix, child in children:
                child_metadata = discover(child, seen)
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
            # Traversed modules are covered above; keep notes for the rest.
            result["omitted"] = [
                item
                for item in result["omitted"]
                if not (
                    item["reason"] == "nested/imported module not traversed"
                    and item["name"] in traversed
                )
            ]
            result["omitted"].extend(failures)
            result["omitted"].extend(traversal_notes)
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
