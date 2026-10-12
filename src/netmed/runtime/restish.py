"""Shared Restish execution for API discovery, help and background workers."""

import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
from .layout import data_directory
from .processes import process_environment
from .restish_binary import ensure, VERSION
from ..errors import UserError


def environment(cache):
    env = process_environment()
    env["RSH_CACHE_DIR"] = str(cache)
    return env


def prepare(source, name, document, *, directory=None):
    binary = ensure()
    identity = {
        "name": name,
        "base_url": source["base_url"],
        "spec": source["spec"],
        "document": document,
        "restish": VERSION,
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    root = (
        Path(directory) if directory is not None else data_directory() / "restish"
    ) / digest
    root.mkdir(parents=True, exist_ok=True)
    api = {"base_url": source["base_url"]}
    if source["spec"].startswith("https://"):
        api["spec_url"] = source["spec"]
    else:
        api["spec_files"] = [source["spec"]]
    config = root / "restish.json"
    config_text = json.dumps({"apis": {name: api}}, indent=2)
    if not config.exists():
        config.write_text(config_text)
    config.chmod(0o600)
    backend = {
        "version": VERSION,
        "config": str(config),
        "cache": str(root / "cache"),
        "source": name,
    }
    # Remote help only uses an existing cache; sync explicitly loads new APIs.
    # Local specification files are compiled when their source help is loaded.
    preparation = (
        ["api", "sync", name]
        if source["spec"].startswith("https://")
        else [name, "--help"]
    )
    sync_result = subprocess.run(
        [binary, "--rsh-config", str(config), *preparation],
        env=environment(backend["cache"]),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if sync_result.returncode:
        raise UserError(
            "Restish could not generate API commands; check the OpenAPI specification"
        )
    result = subprocess.run(
        [binary, "--rsh-config", str(config), "api", "list", "-o", "json"],
        env=environment(backend["cache"]),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode:
        raise UserError(
            "Restish could not discover the API; check its OpenAPI 3 specification and base URL"
        )
    entries = json.loads(result.stdout)
    entry = next((x for x in entries if x["name"] == name), None)
    if entry is None:
        raise UserError("Restish did not register the configured source")
    if (
        source["spec"].startswith("https://")
        and document.get("paths")
        and not entry["operation_count"]
    ):
        raise UserError(
            "Restish generated no API commands; check the OpenAPI specification"
        )
    return {"restish": backend, "operation_count": entry["operation_count"]}


def resolve(source):
    """Materialize machine-local backend state from portable source references."""
    backend = source.get("restish")
    if backend and backend.get("version") == VERSION and "config" not in backend:
        from ..importers.openapi import load_document
        from .environments import installation_lock

        descriptor = {key: source[key] for key in ("base_url", "spec")}
        descriptor.update(version=VERSION, source=backend["source"])
        key = hashlib.sha256(
            json.dumps(descriptor, sort_keys=True).encode()
        ).hexdigest()
        directory = data_directory() / "restish" / "references"
        directory.mkdir(parents=True, exist_ok=True)
        reference = directory / (key + ".json")
        with installation_lock(directory / (key + ".lock")):
            if reference.is_file():
                local = json.loads(reference.read_text())
                if Path(local["config"]).is_file():
                    return local
            local = prepare(source, backend["source"], load_document(source["spec"]))[
                "restish"
            ]
            temporary = reference.with_suffix(".tmp")
            temporary.write_text(json.dumps(local))
            temporary.replace(reference)
            return local
    return backend


def invoke(source, arguments, name="netmed", stdout=None, stderr=None):
    backend = resolve(source)
    if not backend or backend.get("version") != VERSION:
        raise UserError(
            "API catalog requires rebuilding: run netmed build sources.toml"
        )
    if not Path(backend["config"]).is_file():
        raise UserError("Restish source configuration is missing; rebuild the catalog")
    # Source/operation help is native Restish help, preserving its argument syntax.
    args = list(arguments) or ["--help"]
    # Do not allow changing the isolated configuration/profile through a source call.
    for arg in args:
        if arg.split("=", 1)[0] in {"--rsh-config", "--rsh-profile"}:
            raise UserError("Restish config/profile overrides are managed by netmed")
    command = [
        ensure(),
        "--rsh-config",
        backend["config"],
        backend["source"],
        "--rsh-output-format",
        "json",
        "--rsh-no-cache",
        "--rsh-retry",
        "0",
        "--rsh-timeout",
        str(source.get("timeout", 30)) + "s",
        *args,
    ]
    if any(arg in ("--help", "-h", "--help-all") for arg in args):
        result = subprocess.run(
            command, env=environment(backend["cache"]), capture_output=True, text=True
        )
        output = stdout or sys.stdout
        output.write(result.stdout.replace("restish " + backend["source"], name))
        if result.returncode == 0:
            output.write(
                "\nnetmed validates JSON request bodies by default; use --rsh-validate=false to disable.\n"
            )
        (stderr or sys.stderr).write(result.stderr)
        return result.returncode
    # Restish's validation flag belongs to body operations, not the API root.
    # Ask native help about the selected operation; do not duplicate schema parsing.
    options = args[: args.index("--")] if "--" in args else args
    if not any(arg.split("=", 1)[0] == "--rsh-validate" for arg in options):
        help_command = command[: command.index("--")] if "--" in command else command
        result = subprocess.run(
            [*help_command, "--help"],
            env=environment(backend["cache"]),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
        match = re.search(r"^Request Schema \(([^)]+)\):", result.stdout, re.MULTILINE)
        media_type = match.group(1) if match else ""
        for index, arg in enumerate(options):
            if arg.startswith("--rsh-content-type="):
                media_type = arg.split("=", 1)[1]
            elif arg in ("--rsh-content-type", "-c") and index + 1 < len(options):
                media_type = options[index + 1]
        media_type = media_type.split(";", 1)[0].strip().lower()
        if (
            result.returncode == 0
            and "--rsh-validate" in result.stdout
            and (
                media_type in ("json", "application/json")
                or media_type.endswith("+json")
            )
        ):
            position = command.index("--") if "--" in command else len(command)
            command.insert(position, "--rsh-validate")
    return subprocess.call(
        command, env=environment(backend["cache"]), stdout=stdout, stderr=stderr
    )
