"""Locate shipped Restish; user runtime never downloads executables."""

import os
from pathlib import Path
import platform
import shutil
import subprocess
from .processes import process_environment
from .layout import asset_directory
from ..errors import UserError

VERSION = "2.3.0"
CHECKSUMS = {
    (
        "darwin",
        "amd64",
    ): "fbd4bf1aa2e741c59a54dd916554454b94b9b9638a0f32db78111d5f0d4f0e02",
    (
        "darwin",
        "arm64",
    ): "5dc8d53c319e044fbef01954f90ea59b13ff1b570e8a1382102b0c62e7e702d2",
    (
        "linux",
        "amd64",
    ): "5de24353560597562ffc99799ea79a0cd22c5f3cabbb3ffba3ff5e9b97473357",
    (
        "linux",
        "arm64",
    ): "d55ae3ebd2a79e6fda8e0ea125eed2530eed60e27e61e3ffa243ae72ae973c91",
    (
        "windows",
        "amd64",
    ): "8d9f468996c986a5ad49e53c5224fec9f86670328b05675a02891e3c4d54225b",
    (
        "windows",
        "arm64",
    ): "ad44895f2ad7e45f69d6ccba5fe61995b127fd7a2ba55e68a92a2d6de916fd6a",
}


def target():
    system = platform.system().lower()
    machine = platform.machine().lower()
    architecture = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine)
    if (system, architecture) not in CHECKSUMS:
        raise UserError(f"No bundled Restish release for {system}/{machine}")
    return system, architecture


def verify(executable):
    result = subprocess.run(
        [str(executable), "--version"],
        env=process_environment(),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode or result.stdout.strip() != f"restish version {VERSION}":
        raise UserError(f"netmed requires Restish {VERSION}; check NETMED_RESTISH")
    return str(executable)


def ensure():
    executable = (
        asset_directory() / "bin" / ("restish.exe" if os.name == "nt" else "restish")
    )
    if executable.is_file():
        return str(executable)
    override = os.environ.get("NETMED_RESTISH")
    if override:
        return verify(Path(shutil.which(override) or override).expanduser().resolve())
    raise UserError(
        "Restish is not bundled. Build the CLI, or set NETMED_RESTISH for source development."
    )
