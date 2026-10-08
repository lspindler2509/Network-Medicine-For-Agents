"""Exercise downloaded bundle installation without modifying the user's machine."""

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    @unittest.skipUnless(
        os.name == "posix" and shutil.which("curl"), "POSIX installer needs curl"
    )
    def test_shell_install_and_checksum_failure(self):
        target = {"Darwin": "darwin-arm64", "Linux": "linux-amd64"}.get(
            platform.system()
        )
        if not target or platform.machine().lower() not in ("arm64", "x86_64", "amd64"):
            self.skipTest("Unsupported installer platform")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "fixture/netmed"
            bundle.mkdir(parents=True)
            executable = bundle / "netmed"
            executable.write_text("#!/bin/sh\necho fixture\n")
            executable.chmod(0o755)
            (bundle / "support").write_text("keep bundle together")
            archive = root / f"netmed-{target}.tar.gz"
            with tarfile.open(archive, "w:gz") as stream:
                stream.add(bundle, arcname="netmed")
            checksum = Path(str(archive) + ".sha256")
            checksum.write_text(
                hashlib.sha256(archive.read_bytes()).hexdigest()
                + "  "
                + archive.name
                + "\n"
            )
            env = {
                **os.environ,
                "NETMED_RELEASE_BASE_URL": root.as_uri(),
                "NETMED_INSTALL_DIR": str(root / "app"),
                "NETMED_BIN_DIR": str(root / "bin"),
                "NETMED_MODIFY_PATH": "0",
            }

            def install(*arguments):
                return subprocess.run(
                    ["sh", str(ROOT / "installers/install.sh"), *arguments],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

            # Default discovery must work with the initial pre-release, without
            # requiring a Python/JSON tool in the shell installer.
            metadata = root / "releases.json"
            metadata.write_text(
                json.dumps(
                    [{"tag_name": "v0.0.1", "draft": False, "prerelease": True}],
                    indent=2,
                )
            )
            env["NETMED_RELEASE_API_URL"] = metadata.as_uri()
            result = install()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                subprocess.check_output([str(root / "bin/netmed")], text=True).strip(),
                "fixture",
            )
            self.assertTrue((root / "app/v0.0.1/support").exists())
            metadata.write_text("[]")
            pinned = install("--version", "v0.0.2")
            self.assertEqual(pinned.returncode, 0, pinned.stderr)
            self.assertTrue((root / "app/v0.0.2/support").exists())
            original = (root / "bin/netmed").resolve()
            checksum.write_text("0" * 64 + "  " + archive.name)
            self.assertNotEqual(install("--version", "v0.0.3").returncode, 0)
            self.assertEqual((root / "bin/netmed").resolve(), original)
            self.assertFalse((root / "app/v0.0.3").exists())

    @unittest.skipUnless(os.name == "nt", "Windows installer needs Windows PowerShell")
    def test_powershell_install_and_checksum_failure(self):
        self.check_windows_installer("powershell")

    @unittest.skipUnless(
        os.name == "nt" and shutil.which("pwsh"),
        "PowerShell 7 test needs Windows and pwsh",
    )
    def test_pwsh_install_and_checksum_failure(self):
        self.check_windows_installer("pwsh")

    def check_windows_installer(self, executable):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "netmed-windows-amd64.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr("netmed/netmed.exe", b"fixture")
                stream.writestr("netmed/support", b"keep bundle together")
            checksum = Path(str(archive) + ".sha256")
            checksum.write_text(
                hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name
            )
            env = {
                **os.environ,
                "NETMED_RELEASE_BASE_URL": root.as_uri(),
                "NETMED_INSTALL_DIR": str(root / "app"),
                "NETMED_MODIFY_PATH": "0",
            }

            def install(*arguments):
                return subprocess.run(
                    [
                        executable,
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(ROOT / "installers/install.ps1"),
                        *arguments,
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

            # Default discovery must work with the initial pre-release, without
            # requiring a Python/JSON tool in the shell installer.
            metadata = root / "releases.json"
            metadata.write_text(
                json.dumps(
                    [{"tag_name": "v0.0.1", "draft": False, "prerelease": True}],
                    indent=2,
                )
            )
            env["NETMED_RELEASE_API_URL"] = metadata.as_uri()
            result = install()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "app/v0.0.1/support").exists())
            metadata.write_text("[]")
            pinned = install("-Version", "v0.0.2")
            self.assertEqual(pinned.returncode, 0, pinned.stderr)
            self.assertTrue((root / "app/v0.0.2/support").exists())
            checksum.write_text("0" * 64)
            self.assertNotEqual(install("-Version", "v0.0.3").returncode, 0)
            self.assertTrue((root / "app/v0.0.1/netmed.exe").exists())
            self.assertFalse((root / "app/v0.0.3").exists())
