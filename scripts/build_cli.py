"""Build a native application directory; no publishing or user-runtime downloads."""

import argparse
import hashlib
import json
from importlib.metadata import distribution, version as package_version
import os
from pathlib import Path
import shutil
import subprocess
import sys

from netmed.building.restish import download
from netmed.catalog import build
from netmed.release import export
from netmed.runtime.environments import platform_target

UV_VERSION = "0.12.23"


def main():
    parser = argparse.ArgumentParser(
        description="Build the CLI for this OS/architecture. Fetches specs and provisions build-time package environments."
    )
    parser.add_argument("--sources", default="sources.toml")
    parser.add_argument(
        "--source", action="append", help="Optional source subset; repeat as needed"
    )
    parser.add_argument(
        "--lock-directory",
        help="Override versioned lock directory (default: release-locks/<current-target>); fail if inputs differ",
    )
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    cache = project / ".build"
    cache.mkdir(exist_ok=True)
    # Build caches stay in the checkout, never become user application assets.
    os.environ.setdefault("NETMED_DATA_DIR", str(cache / "data"))
    native = cache / "native"
    restish = download(native)
    os.environ["NETMED_RESTISH"] = restish
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv must be installed on the build machine")
    version = subprocess.check_output([uv, "--version"], text=True).split()[1]
    if version != UV_VERSION:
        raise RuntimeError(f"Build requires uv {UV_VERSION}; found {version}")
    resources = cache / "resources"
    if resources.exists():
        shutil.rmtree(resources)
    locks = args.lock_directory or project / "release-locks" / platform_target()
    build(
        args.sources,
        cache / "catalog.json",
        args.source,
        snapshot_directory=cache / "specs",
        lock_directory=locks,
    )
    export(cache / "catalog.json", resources, args.source)
    shutil.copy2(project / "LICENSE", resources / "LICENSE")
    licenses = resources / "licenses"
    licenses.mkdir()
    graphql_distribution = distribution("graphql-core")
    shutil.copy2(
        graphql_distribution.locate_file(
            "graphql_core-"
            + package_version("graphql-core")
            + ".dist-info/licenses/LICENSE"
        ),
        licenses / "graphql-core.txt",
    )
    (resources / "bin").mkdir()
    suffix = ".exe" if os.name == "nt" else ""
    for name, origin in [("restish", restish), ("uv", uv)]:
        shutil.copy2(origin, resources / "bin" / (name + suffix))
    manifest = json.loads((resources / "manifest.json").read_text())
    manifest["graphql_core_version"] = graphql_distribution.version
    manifest["uv_version"] = version
    manifest["native_sha256"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (resources / "bin").iterdir()
    }
    (resources / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    worker = cache / "worker"
    if worker.exists():
        shutil.rmtree(worker)
    shutil.copytree(
        project / "src/netmed/worker",
        worker,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "netmed",
        "--paths",
        str(project / "src"),
        "--distpath",
        str(project / "dist"),
        "--workpath",
        str(cache / "pyinstaller"),
        "--specpath",
        str(cache),
        "--collect-submodules",
        "netmed",
        "--exclude-module",
        "netmed.building",
        "--exclude-module",
        "netmed.worker",
        "--add-data",
        str(resources) + os.pathsep + "netmed/assets",
        "--add-data",
        str(worker) + os.pathsep + "netmed/worker",
        str(project / "scripts/cli_entry.py"),
    ]
    with (cache / "pyinstaller.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=log, check=True)
    # Preserve POSIX symlinks by using tar; ZIP is used only on Windows.
    archive = shutil.make_archive(
        str(project / "dist" / ("netmed-" + platform_target())),
        "zip" if os.name == "nt" else "gztar",
        root_dir=project / "dist",
        base_dir="netmed",
    )
    Path(archive + ".sha256").write_text(
        hashlib.sha256(Path(archive).read_bytes()).hexdigest()
        + "  "
        + Path(archive).name
        + "\n"
    )
    print(
        json.dumps(
            {
                "executable": str(project / "dist/netmed" / ("netmed" + suffix)),
                "archive": archive,
            }
        )
    )


if __name__ == "__main__":
    main()
