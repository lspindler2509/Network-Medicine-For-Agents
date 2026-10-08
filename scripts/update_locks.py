"""Explicitly resolve candidate release locks; CI must validate each native target."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib
from netmed.building.locks import input_hash
from netmed.runtime.environments import platform_target, validate_requirements

TARGETS = {
    "darwin-arm64": "aarch64-apple-darwin",
    "linux-amd64": "x86_64-unknown-linux-gnu",
    "windows-amd64": "x86_64-pc-windows-msvc",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default="sources.toml")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--target", choices=TARGETS, help="One target (default: current platform)"
    )
    selection.add_argument(
        "--all", action="store_true", help="Update all three supported target platforms"
    )
    args = parser.parse_args()
    sources = tomllib.loads(Path(args.sources).read_text())["sources"]
    targets = list(TARGETS) if args.all else [args.target or platform_target()]
    if any(target not in TARGETS for target in targets):
        parser.error("Current platform is unsupported; choose --target or --all")
    for target in targets:
        update_target(sources, target)


def update_target(sources, target):
    destination = Path("release-locks") / target
    destination.parent.mkdir(exist_ok=True)
    # Publish only a complete set. An interrupted resolution leaves the old set intact.
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        root = Path(temporary)
        manifest = {"target": target, "sources": {}}
        for name, source in sources.items():
            if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
                raise ValueError("Invalid source name")
            if source["kind"] != "python" or not source.get("enabled", True):
                continue
            validate_requirements(source)
            if source.get("path"):
                raise ValueError("Local packages cannot be release inputs")
            version = source.get("python", "3.11")
            if version.count(".") != 2:
                result = subprocess.check_output(
                    [
                        "uv",
                        "run",
                        "--no-project",
                        "--python",
                        version,
                        "python",
                        "-c",
                        "import platform; print(platform.python_version())",
                    ],
                    text=True,
                )
                version = result.strip()
            requirements = root / "requirements.in"
            requirements.write_text(
                "\n".join(
                    [
                        "fire==0.7.1",
                        source["package"] + source.get("version", ""),
                        *source.get("dependencies", []),
                    ]
                )
                + "\n"
            )
            lock = root / (name + ".txt")
            subprocess.run(
                [
                    "uv",
                    "--no-config",
                    "pip",
                    "compile",
                    str(requirements),
                    "--python-version",
                    version,
                    "--python-platform",
                    TARGETS[target],
                    "--generate-hashes",
                    "--no-header",
                    "--no-annotate",
                    "--output-file",
                    str(lock),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            # Keep exact-byte hashes stable across Windows and POSIX generators.
            lock.write_bytes(lock.read_bytes().replace(b"\r\n", b"\n"))
            manifest["sources"][name] = {
                "python": version,
                "input_sha256": input_hash(source),
                "sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
            }
        requirements.unlink(missing_ok=True)
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        # All resolution has succeeded before replacing any tracked lock.
        destination.mkdir(exist_ok=True)
        for path in root.glob("*.txt"):
            path.replace(destination / path.name)
        (root / "manifest.json").replace(destination / "manifest.json")
        for path in destination.glob("*.txt"):
            if path.stem not in manifest["sources"]:
                path.unlink()
    print(
        f"Candidate locks written to {destination}; validate on that target before release."
    )


if __name__ == "__main__":
    main()
