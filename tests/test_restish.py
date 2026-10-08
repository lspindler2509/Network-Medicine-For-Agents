import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch
from netmed.errors import UserError
from netmed.runtime import restish, restish_binary
from netmed.building import restish as build_restish


class RestishTests(unittest.TestCase):
    def test_portable_reference_materializes_once_in_current_data_directory(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
        ):
            config = Path(directory) / "local-config"
            config.write_text("{}")
            local = {
                "version": restish_binary.VERSION,
                "source": "demo",
                "config": str(config),
                "cache": directory,
            }
            source = {
                "spec": "https://example.org/spec",
                "base_url": "https://example.org",
                "restish": {"version": restish_binary.VERSION, "source": "demo"},
            }
            with (
                patch(
                    "netmed.importers.openapi.load_document", return_value={}
                ) as fetch,
                patch(
                    "netmed.runtime.restish.prepare", return_value={"restish": local}
                ) as prepare,
            ):
                self.assertEqual(restish.resolve(source), local)
                self.assertEqual(restish.resolve(source), local)
                fetch.assert_called_once()
                prepare.assert_called_once()

    def test_portable_release_selection(self):
        for system, machine, expected in [
            ("Darwin", "arm64", ("darwin", "arm64")),
            ("Linux", "x86_64", ("linux", "amd64")),
            ("Windows", "AMD64", ("windows", "amd64")),
        ]:
            with (
                patch("platform.system", return_value=system),
                patch("platform.machine", return_value=machine),
            ):
                self.assertEqual(restish_binary.target(), expected)
        with (
            patch("platform.system", return_value="Other"),
            self.assertRaises(UserError),
        ):
            restish_binary.target()

    def test_archive_checksum_failure_is_not_published(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}, clear=True),
            patch("netmed.building.restish.target", return_value=("darwin", "arm64")),
            patch(
                "netmed.building.restish.requests.get",
                return_value=Mock(content=b"bad"),
            ),
        ):
            with self.assertRaisesRegex(UserError, "checksum"):
                build_restish.download(directory)
            self.assertFalse(list(Path(directory).rglob("restish")))
            self.assertFalse(list(Path(directory).rglob("*.lock")))

    def test_verified_archive_extracts_only_executable_and_reuses(self):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as tar:
            member = tarfile.TarInfo("../../restish")
            member.size = 4
            tar.addfile(member, io.BytesIO(b"tool"))
        data = archive.getvalue()
        import hashlib

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}, clear=True),
            patch("netmed.building.restish.target", return_value=("darwin", "arm64")),
            patch.dict(
                restish_binary.CHECKSUMS,
                {("darwin", "arm64"): hashlib.sha256(data).hexdigest()},
            ),
            patch(
                "netmed.building.restish.requests.get", return_value=Mock(content=data)
            ) as download,
            patch("netmed.building.restish.verify"),
        ):
            binary = build_restish.download(directory)
            self.assertEqual(Path(binary).read_bytes(), b"tool")
            self.assertEqual(build_restish.download(directory), binary)
            download.assert_called_once()
            self.assertTrue(Path(binary).is_relative_to(Path(directory).resolve()))

    def test_prepare_isolated_config_and_native_count(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {"NETMED_DATA_DIR": directory, "UNRELATED_API_KEY": "secret"},
            ),
            patch("netmed.runtime.restish.ensure", return_value="/restish"),
            patch(
                "netmed.runtime.restish.subprocess.run",
                return_value=Mock(
                    returncode=0, stdout='[{"name":"demo","operation_count":12}]'
                ),
            ) as run,
        ):
            result = restish.prepare(
                {
                    "base_url": "https://example.org",
                    "spec": "https://example.org/openapi.json",
                },
                "demo",
                {"openapi": "3.0.3"},
            )
            self.assertEqual(result["operation_count"], 12)
            config = json.loads(Path(result["restish"]["config"]).read_text())
            self.assertEqual(list(config["apis"]), ["demo"])
            self.assertNotIn("UNRELATED_API_KEY", run.call_args.kwargs["env"])
            self.assertEqual(
                run.call_args.kwargs["env"]["RSH_CACHE_DIR"], result["restish"]["cache"]
            )
            self.assertEqual(
                run.call_args_list[0].args[0][-3:], ["api", "sync", "demo"]
            )
            self.assertEqual(
                run.call_args_list[0].kwargs["stdin"], restish.subprocess.DEVNULL
            )

    def test_nonempty_spec_cannot_silently_build_zero_commands(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}),
            patch("netmed.runtime.restish.ensure", return_value="/restish"),
            patch(
                "netmed.runtime.restish.subprocess.run",
                return_value=Mock(
                    returncode=0, stdout='[{"name":"demo","operation_count":0}]'
                ),
            ),
        ):
            with self.assertRaisesRegex(UserError, "no API commands"):
                restish.prepare(
                    {
                        "base_url": "https://example.org",
                        "spec": "https://example.org/openapi.json",
                    },
                    "demo",
                    {"openapi": "3.0.3", "paths": {"/items": {"get": {}}}},
                )

    def test_execution_forwards_native_arguments_and_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "restish.json"
            config.write_text("{}")
            source = {
                "restish": {
                    "version": restish_binary.VERSION,
                    "config": str(config),
                    "cache": directory,
                    "source": "demo",
                }
            }
            arguments = [
                "query",
                "network-id",
                "searchString: EGFR",
                "--rsh-content-type",
                "application/json",
            ]
            with (
                patch("netmed.runtime.restish.ensure", return_value="/restish"),
                patch("netmed.runtime.restish.subprocess.call", return_value=5) as run,
                patch(
                    "netmed.runtime.restish.subprocess.run",
                    return_value=Mock(
                        returncode=0,
                        stdout="Request Schema (application/json):\n--rsh-validate",
                    ),
                ),
            ):
                self.assertEqual(restish.invoke(source, arguments), 5)
                command = run.call_args.args[0]
                self.assertEqual(command[-len(arguments) - 1 : -1], arguments)
                self.assertIn("--rsh-config", command)
                self.assertIn("--rsh-no-cache", command)
                self.assertIn("--rsh-retry", command)
                self.assertIn("--rsh-validate", command)
                with self.assertRaises(UserError):
                    restish.invoke(source, ["--rsh-config=/other"])
            with self.assertRaisesRegex(UserError, "rebuilding"):
                restish.invoke({}, [])

    def test_windows_zip_provisioning(self):
        import zipfile
        import hashlib

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zip:
            zip.writestr("release/restish.exe", b"windows-tool")
        data = archive.getvalue()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": directory}, clear=True),
            patch("netmed.building.restish.target", return_value=("windows", "amd64")),
            patch.dict(
                restish_binary.CHECKSUMS,
                {("windows", "amd64"): hashlib.sha256(data).hexdigest()},
            ),
            patch(
                "netmed.building.restish.requests.get", return_value=Mock(content=data)
            ),
            patch("netmed.building.restish.verify"),
        ):
            binary = Path(build_restish.download(directory))
            self.assertEqual(binary.name, "restish.exe")
            self.assertEqual(binary.read_bytes(), b"windows-tool")

    def test_api_help_rewrites_examples_and_preserves_status(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "restish.json"
            config.write_text("{}")
            source = {
                "restish": {
                    "version": restish_binary.VERSION,
                    "config": str(config),
                    "cache": directory,
                    "source": "demo",
                }
            }
            out, err = io.StringIO(), io.StringIO()
            with (
                patch("netmed.runtime.restish.ensure", return_value="/restish"),
                patch(
                    "netmed.runtime.restish.subprocess.run",
                    return_value=Mock(
                        returncode=0, stdout="restish demo get-item <id>", stderr=""
                    ),
                ),
            ):
                self.assertEqual(
                    restish.invoke(
                        source, ["--help"], name="netmed demo", stdout=out, stderr=err
                    ),
                    0,
                )
            self.assertIn("netmed demo get-item <id>", out.getvalue())
            self.assertIn("--rsh-validate=false", out.getvalue())
