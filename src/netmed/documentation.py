"""On-demand provider descriptions; never read checkout README files."""

import json
import re
import subprocess
from urllib.parse import quote
import requests
from .errors import UserError
from .runtime.environments import UvEnvironmentManager
from .runtime.processes import process_environment


def documentation(source):
    if source["kind"] == "openapi":
        from .importers.openapi import documentation as api_documentation

        return api_documentation(source["spec"])
    if source["kind"] == "graphql":
        from .graphql.schema import load_schema, overview

        return overview(load_schema(source))
    return python_documentation(source)


def python_documentation(source):
    if not source.get("path"):
        return pypi_documentation(source)
    environment = UvEnvironmentManager().ensure(source)
    process = subprocess.run(
        [environment["python"], environment["worker"]],
        input=json.dumps(
            {
                "action": "docs",
                "module": source["module"],
                "package": source.get("package"),
            }
        ),
        text=True,
        capture_output=True,
        timeout=source.get("discovery_timeout", 60),
        env=process_environment(),
    )
    if process.returncode:
        raise UserError("Could not read installed package metadata")
    return json.loads(process.stdout)


def pypi_documentation(source):
    package = source.get("package", "").split("[", 1)[0]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", package):
        raise UserError(
            "PyPI docs require a distribution name in package; module names may differ"
        )
    normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
    versions = source.get("discovery_metadata", {}).get("packages", {})
    version = next(
        (
            value
            for name, value in versions.items()
            if normalize(name) == normalize(package)
        ),
        None,
    )
    constraint = source.get("version", "").strip()
    if version is None and constraint:
        if not constraint.startswith("==") or not re.fullmatch(
            r"[A-Za-z0-9.!+_-]+", constraint[2:]
        ):
            raise UserError(
                "Version-constrained PyPI docs require an exact ==version or a built catalog with a resolved package version"
            )
        version = constraint[2:]
    url = f"https://pypi.org/pypi/{quote(package, safe='')}"
    if version:
        url += "/" + quote(version, safe="")
    response = requests.get(url + "/json", timeout=30, allow_redirects=False)
    if 300 <= response.status_code < 400:
        raise UserError("PyPI metadata redirects are not supported")
    if response.status_code == 404:
        raise UserError(
            "Package or version not found on PyPI; docs do not install packages as a fallback"
        )
    response.raise_for_status()
    info = response.json()["info"]
    text = info.get("description") or ""
    return (
        [
            {
                "name": info["name"],
                "version": info["version"],
                "content_type": info.get("description_content_type") or "text/plain",
                "text": text,
                "origin": "PyPI metadata",
            }
        ]
        if text.strip()
        else []
    )
