import re

"""Persistent per-source environments; dependency resolution is delegated to uv."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import platform
import subprocess
import time
from contextlib import contextmanager
from ..errors import UserError
from .layout import data_directory
from .processes import process_environment

WORKER = Path(__file__).resolve().parents[1] / "worker/entry.py"


def platform_target():
    machine = platform.machine().lower()
    arch = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine, machine)
    return platform.system().lower() + "-" + arch


def validate_requirements(source):
    """Reject installer options and multiline requirements before writing files."""
    import re

    package = source.get("package")
    if package is not None and (
        not isinstance(package, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", package)
    ):
        raise UserError("package must be a distribution name")
    dependencies = source.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise UserError("dependencies must be a list")
    values = [source.get("version", ""), *dependencies]
    for value in values:
        if (
            not isinstance(value, str)
            or any(c in value for c in ("\r", "\n", "\0"))
            or value.lstrip().startswith("-")
        ):
            raise UserError(
                "Requirements must be single-line values without installer options"
            )


@contextmanager
def installation_lock(path, timeout=180):
    deadline = time.monotonic() + timeout
    while True:
        try:
            path.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError("Environment installation is locked")
            time.sleep(0.1)
    try:
        yield
    finally:
        path.rmdir()


def redacted_tail(text, lines=3):
    """Last diagnostic lines with URL credentials removed.

    Installer diagnostics can contain index credentials (user:token@host);
    only the closing lines are shown, with the userinfo part of URLs redacted.
    """
    tail = [line.strip() for line in (text or "").splitlines() if line.strip()][-lines:]
    if not tail:
        return ""
    cleaned = [
        re.sub(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/@\s]+@", r"\1***@", line)
        for line in tail
    ]
    return ": " + " | ".join(cleaned)


class UvEnvironmentManager:
    def __init__(self, root=None, executable=None):
        self.root = Path(root or data_directory())
        from .layout import bundled_uv

        self.uv = (
            executable
            or bundled_uv()
            or os.environ.get("NETMED_UV")
            or shutil.which("uv")
        )

    def _run(self, args):
        if not self.uv:
            raise UserError("uv is required; install uv or set NETMED_UV")
        result = subprocess.run(
            [self.uv, "--no-config", *args],
            env=process_environment(),
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise UserError(
                "uv could not prepare the package environment; check the package requirements and connectivity"
                + redacted_tail(result.stderr)
            )

    def ensure(self, source):
        validate_requirements(source)
        editable = source.get("dev", False)
        if not isinstance(editable, bool) or (editable and not source.get("path")):
            raise UserError("dev must be a boolean and requires a local package path")
        requirements = ["fire==0.7.1", *source.get("dependencies", [])]
        if source.get("package") and not source.get("path"):
            requirements.append(source["package"] + source.get("version", ""))
        pinned = source.get("lock")
        lock_bytes = None
        if pinned:
            if source.get("path"):
                raise UserError("Release locks cannot be used with local packages")
            if pinned["target"] != platform_target():
                raise UserError("Dependency lock is for a different platform")
            lock_bytes = Path(pinned["path"]).read_bytes()
            if hashlib.sha256(lock_bytes).hexdigest() != pinned["sha256"]:
                raise UserError("Dependency lock checksum mismatch")
        identity = {
            "python": source.get("python", "3.11"),
            "requirements": sorted(requirements),
            "target": platform_target(),
        }
        if pinned:
            identity["lock_sha256"] = pinned["sha256"]
        if source.get("path"):
            local = Path(source["path"]).resolve()
            # Local development sources are explicitly mutable, never advertised as locked.
            identity["path"] = str(local)
            identity["dev"] = editable
            # Packaging/dependency changes need reinstalling even in editable mode.
            identity["packaging"] = {
                name: hashlib.sha256((local / name).read_bytes()).hexdigest()
                for name in ("pyproject.toml", "setup.py", "setup.cfg")
                if (local / name).is_file()
            }
            if not editable:
                identity["mtime"] = max(
                    (
                        p.stat().st_mtime_ns
                        for p in local.rglob("*.py")
                        if not any(
                            x in p.parts for x in (".venv", ".git", "__pycache__")
                        )
                    ),
                    default=0,
                )
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[
            :24
        ]
        root = self.root / "environments"
        root.mkdir(parents=True, exist_ok=True)
        directory = root / key
        ready = directory / "environment.json"
        python = directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        with installation_lock(root / (key + ".lock")):
            if ready.exists() and python.exists():
                return self._reference(key, directory, python)
            if directory.exists():
                shutil.rmtree(directory)
            self._run(["venv", "--python", identity["python"], str(directory)])
            inputs = directory / "requirements.in"
            lock = directory / "requirements.lock"
            inputs.write_text("\n".join(requirements) + "\n")
            if lock_bytes is None:
                self._run(
                    [
                        "pip",
                        "compile",
                        "--python",
                        str(python),
                        "--generate-hashes",
                        str(inputs),
                        "--output-file",
                        str(lock),
                    ]
                )
            else:
                lock.write_bytes(lock_bytes)
            self._run(
                ["pip", "sync", "--python", str(python), "--require-hashes", str(lock)]
            )
            if source.get("path"):
                self._run(
                    [
                        "pip",
                        "install",
                        "--python",
                        str(python),
                        *(["--editable"] if editable else []),
                        str(local),
                    ]
                )
            installed = subprocess.run(
                [self.uv, "--no-config", "pip", "freeze", "--python", str(python)],
                env=process_environment(),
                capture_output=True,
                text=True,
                check=True,
            )
            (directory / "installed.txt").write_text(installed.stdout)
            ready.write_text(
                json.dumps(
                    {
                        "id": key,
                        "identity": identity,
                        "local_development": bool(source.get("path")),
                    },
                    indent=2,
                )
            )
        return self._reference(key, directory, python)

    def _reference(self, key, directory, python):
        return {
            "id": key,
            "directory": str(directory),
            "python": str(python),
            "worker": str(WORKER.resolve()),
        }

    def list(self):
        return [
            json.loads(p.read_text())
            for p in (self.root / "environments").glob("*/environment.json")
        ]
