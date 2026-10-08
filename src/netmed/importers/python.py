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


def cached_help(source, arguments, name):
    metadata = source.get("discovery_metadata")
    if not metadata:
        return False
    if not arguments or arguments in (["--help"], ["-h"]):
        print(f"{name}: cached Python interface (build-time snapshot)")
        for operation, item in metadata["operations"].items():
            summary = item["doc"].splitlines()[0] if item["doc"] else "(no docstring)"
            print(
                f"  {operation.replace('.', ' ')} {item['signature'] or ''}\n    {summary}"
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
    if arguments[-1] not in ("--help", "-h"):
        return False
    operation = ".".join(arguments[:-1])
    if operation not in metadata["operations"]:
        return False
    item = metadata["operations"][operation]
    print(
        f"{name} {operation.replace('.', ' ')} {item['signature'] or '(signature unavailable)'}"
    )
    print(item["doc"] or "No docstring provided by package.")
    print("\nParameters:\n" + json.dumps(item["parameters"], indent=2))
    print(f"Package documentation: netmed docs {name.split()[-1]}")
    return True
