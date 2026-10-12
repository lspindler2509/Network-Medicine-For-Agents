"""Discover Python interfaces and show their cached help."""

import json
import hashlib
import subprocess
from pathlib import Path
from ..runtime.environments import UvEnvironmentManager
from ..runtime.processes import process_environment


def discover(source):
    environment = UvEnvironmentManager().ensure(source)
    process = subprocess.run(
        [environment["python"], environment["worker"]],
        input=json.dumps(
            {
                "action": "discover",
                "module": source["module"],
                "package": source.get("package"),
                "submodules": source.get("submodules", False),
            }
        ),
        text=True,
        capture_output=True,
        timeout=source.get("discovery_timeout", 60),
        env=process_environment(),
    )
    if process.returncode:
        raise RuntimeError(
            "Package discovery failed; check importability in its worker environment"
        )
    result = json.loads(process.stdout)
    from ..catalog import python_configuration_hash

    result["configuration_hash"] = python_configuration_hash(source)
    result["lock_sha256"] = hashlib.sha256(
        (Path(environment["directory"]) / "requirements.lock").read_bytes()
    ).hexdigest()
    return result


HELP_GROUP_THRESHOLD = 50


def help_location(operation, item, module, operations):
    """Group aliases by their defining module; retain their actual call paths."""
    origin = item.get("defined_in")
    if not origin:
        parent = operation.rpartition(".")[0]
        while parent:
            owner = operations.get(parent, {})
            if owner.get("kind") == "class":
                origin = owner.get("defined_in")
                break
            parent = parent.rpartition(".")[0]
    if isinstance(origin, str) and module and origin.startswith(module + "."):
        parts = origin[len(module) + 1 :].split(".")
        public = []
        for part in parts:
            if part.startswith("_"):
                break
            public.append(part)
        return ".".join(public)
    return operation.rpartition(".")[0]


def package_member(item, module):
    origin = item.get("defined_in")
    root = module.split(".")[0] if module else ""
    # Unknown provenance stays visible; never guess ownership from an alias name.
    return (
        not root
        or not isinstance(origin, str)
        or not origin
        or origin == root
        or origin.startswith(root + ".")
    )


def print_operations(operations, name):
    for operation, item in sorted(operations.items()):
        summary = item["doc"].splitlines()[0] if item["doc"] else "(no docstring)"
        print(
            f"  {name} {operation.replace('.', ' ')} {item['signature'] or ''}\n    {summary}"
        )


def cached_help(source, arguments, name):
    metadata = source.get("discovery_metadata")
    if not metadata:
        return False
    if arguments and not any(arg in ("--help", "-h") for arg in arguments):
        return False
    tokens = [arg for arg in arguments if arg not in ("--help", "-h", "--full")]
    if any(not token.isidentifier() for token in tokens):
        return False
    path = ".".join(tokens)
    full = "--full" in arguments
    operations = metadata["operations"]
    module = source.get("module") or metadata.get("module", "")

    # Explicit help for an operation is always available, including foreign exports.
    if path in operations:
        item = operations[path]
        print(
            f"{name} {path.replace('.', ' ')} {item['signature'] or '(signature unavailable)'}"
        )
        print(item["doc"] or "No docstring provided by package.")
        print("\nParameters:\n" + json.dumps(item["parameters"], indent=2))
        if full:
            children = {
                key: value
                for key, value in operations.items()
                if key.startswith(path + ".")
            }
            if children:
                print("\nMembers:")
                print_operations(children, name)
        print(f"Package documentation: netmed docs {name.split()[-1]}")
        return True

    locations = {
        key: help_location(key, item, module, operations)
        for key, item in operations.items()
    }
    selected = {
        key: item
        for key, item in operations.items()
        if not path or locations[key] == path or locations[key].startswith(path + ".")
    }
    if path and not selected:
        return False
    visible = (
        selected
        if full
        else {
            key: item for key, item in selected.items() if package_member(item, module)
        }
    )
    print(
        f"{name}{' ' + path.replace('.', ' ') if path else ''}: cached Python interface (build-time snapshot)"
    )
    hidden = len(selected) - len(visible)
    if full or len(visible) <= HELP_GROUP_THRESHOLD:
        print_operations(visible, name)
    else:
        direct = {key: item for key, item in visible.items() if locations[key] == path}
        groups = set()
        for key in visible:
            location = locations[key]
            if location == path:
                continue
            remainder = location[len(path) + 1 :] if path else location
            groups.add((path + "." if path else "") + remainder.split(".")[0])
        if groups:
            print("\nHelp groups (definition modules or exposed object paths):")
            for group in sorted(groups):
                print(f"  {name} {group.replace('.', ' ')} --help")
        if direct:
            print("\nDirect operations:")
            if len(direct) <= HELP_GROUP_THRESHOLD:
                print_operations(direct, name)
            else:
                for operation in sorted(direct)[:HELP_GROUP_THRESHOLD]:
                    print(f"  {name} {operation.replace('.', ' ')}")
                print("  Further direct operations are available with --full.")
        print(
            "\nUse the exact operation call paths printed in each group; grouping does not rewrite calls."
        )
    if not visible:
        print("  No package-owned operations in this help group.")
    if hidden:
        print(
            f"\nForeign re-exports hidden from this overview: {hidden}. Their call paths remain available."
        )
    print(
        f"Full overview, including foreign exports: {name}{' ' + path.replace('.', ' ') if path else ''} --help --full"
    )
    print(
        "\nThis list is a static snapshot, not exhaustive: dynamic attributes and methods created after initialization may be missing."
    )
    print(
        "Known operation paths remain callable; uncached operation help falls back to Fire."
    )
    print(
        'Use discovery="lazy" in the source registry for live Fire help; live help may also be incomplete.'
    )
    print(f"Package documentation: netmed docs {name.split()[-1]}")
    return True
