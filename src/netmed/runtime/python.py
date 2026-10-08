"""Shared Python-worker execution for foreground calls and background jobs."""

import json
import subprocess
from .environments import UvEnvironmentManager
from .processes import process_environment
from ..errors import UserError


def prepare(source):
    metadata = source.get("discovery_metadata")
    from ..catalog import python_configuration_hash

    if metadata and metadata.get("configuration_hash") != python_configuration_hash(
        source
    ):
        raise UserError("Package environment changed; rebuild the catalog")
    return UvEnvironmentManager().ensure(source)


def invoke(
    source, arguments, name="netmed", *, environment=None, stdout=None, stderr=None
):
    if environment is None:
        environment = prepare(source)
    from .object_store import execution_options, directory_for

    parsed_arguments, options = execution_options(arguments)
    request = {
        "module": source["module"],
        "arguments": parsed_arguments,
        "name": name,
        "object_options": options,
        "objects_root": str(directory_for()),
        "environment_id": environment["id"],
        "original_arguments": arguments,
        "submodules": source.get("submodules", False),
        "setup": source.get("setup", []),
    }
    process = subprocess.run(
        [environment["python"], environment["worker"]],
        input=json.dumps(request),
        text=True,
        env=process_environment(),
        stdout=stdout,
        stderr=stderr,
    )
    return process.returncode
