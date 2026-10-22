import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from netmed.catalog import discovery_metadata, load
from netmed.release import export
from netmed.runtime.environments import UvEnvironmentManager, platform_target
from data_isolation import setUpModule, tearDownModule  # noqa: F401


class ReleaseTests(unittest.TestCase):
    def test_relocatable_export_preserves_locks_and_strips_machine_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = root / "env"
            env.mkdir()
            (env / "requirements.lock").write_text(
                "# local /private/path\nfire==0.7.1 \\\n --hash=sha256:abc\n"
            )
            catalog = root / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "sources": {
                            "example": {
                                "kind": "python",
                                "module": "example",
                                "package": "example",
                                "python": "3.11",
                                "discovery_metadata": {
                                    "environment_id": "local",
                                    "operations": {},
                                },
                            },
                            "api": {
                                "kind": "openapi",
                                "spec": "https://example.org/spec",
                                "base_url": "https://example.org",
                                "restish": {
                                    "config": "/local/config",
                                    "cache": "/local/cache",
                                    "version": "2.3.0",
                                    "source": "api",
                                },
                            },
                        }
                    }
                )
            )
            with (
                patch(
                    "netmed.importers.openapi.load_document",
                    return_value={"openapi": "3.0.3", "paths": {}},
                ),
                patch(
                    "netmed.importers.python.discover",
                    return_value={
                        "operations": {},
                        "lock_sha256": hashlib.sha256(
                            (env / "requirements.lock").read_bytes()
                        ).hexdigest(),
                    },
                ),
                patch(
                    "netmed.release.UvEnvironmentManager.ensure",
                    return_value={"directory": str(env), "python": "python"},
                ),
                patch(
                    "netmed.release.subprocess.run",
                    return_value=Mock(stdout="3.11.14\n"),
                ),
            ):
                export(catalog, root / "release")
            (root / "release").rename(root / "moved")
            text = (root / "moved/catalog.json").read_text()
            self.assertNotIn("/local", text)
            self.assertNotIn("environment_id", text)
            restored = load(root / "moved/catalog.json")["sources"]["example"]
            self.assertEqual(restored["python"], "3.11.14")
            self.assertTrue(Path(restored["lock"]["path"]).is_file())
            self.assertNotIn("/private", Path(restored["lock"]["path"]).read_text())

    def test_pinned_install_skips_resolution_and_worker_update_reuses_dependencies(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / "lock.txt"
            lock.write_text("fire==0.7.1\n")
            source = {
                "module": "json",
                "python": "3.11.14",
                "lock": {
                    "path": str(lock),
                    "sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
                    "target": platform_target(),
                },
            }
            manager = UvEnvironmentManager(root=root, executable="uv")

            def run(args):
                if args[0] == "venv":
                    binary = Path(args[-1]) / (
                        "Scripts/python.exe" if os.name == "nt" else "bin/python"
                    )
                    binary.parent.mkdir(parents=True)
                    binary.touch()

            with (
                patch.object(manager, "_run", side_effect=run) as install,
                patch(
                    "netmed.runtime.environments.subprocess.run",
                    return_value=Mock(stdout="fire==0.7.1"),
                ),
            ):
                first = manager.ensure(source)
                code = root / "different_worker.py"
                code.write_text('print("new version")')
                with patch("netmed.runtime.environments.WORKER", code):
                    second = manager.ensure(source)
                self.assertEqual(first["id"], second["id"])
                self.assertNotEqual(first["worker"], second["worker"])
                self.assertTrue(Path(first["worker"]).exists())
                self.assertEqual(second["worker"], str(code.resolve()))
                self.assertFalse((root / "workers").exists())
                self.assertEqual(install.call_count, 2)
                self.assertEqual(install.call_args.args[0][0:2], ["pip", "sync"])
            lock.write_text("tampered")
            with self.assertRaisesRegex(ValueError, "checksum"):
                manager.ensure(source)
            source["lock"]["target"] = "different-platform"
            with self.assertRaisesRegex(ValueError, "platform"):
                manager.ensure(source)

    def test_local_sources_refused_without_publishing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {"sources": {"local": {"kind": "python", "path": str(root)}}}
                )
            )
            with self.assertRaisesRegex(ValueError, "local packages"):
                export(catalog, root / "bundle")
            self.assertFalse((root / "bundle").exists())

    def test_matching_discovery_is_reused_but_changed_lock_is_refreshed(self):
        from netmed.catalog import python_configuration_hash

        for stale in (None, "lock", "configuration"):
            with self.subTest(stale=stale), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                env = root / "env"
                env.mkdir()
                lock = env / "requirements.lock"
                lock.write_text("example==1.0\n")
                digest = hashlib.sha256(lock.read_bytes()).hexdigest()
                source = {
                    "kind": "python",
                    "module": "example",
                    "package": "example",
                    "python": "3.11",
                }
                metadata = {
                    "operations": {"run": {"doc": "Original"}},
                    "configuration_hash": "stale"
                    if stale == "configuration"
                    else python_configuration_hash(source),
                    "lock_sha256": "stale" if stale == "lock" else digest,
                }
                source["discovery_metadata"] = metadata
                catalog = root / "catalog.json"
                catalog.write_text(json.dumps({"sources": {"example": source}}))
                refreshed = {
                    **metadata,
                    "lock_sha256": digest,
                    "operations": {"run": {"doc": "Refreshed"}},
                }
                with (
                    patch(
                        "netmed.release.UvEnvironmentManager.ensure",
                        return_value={"directory": str(env), "python": "python"},
                    ),
                    patch(
                        "netmed.release.subprocess.run",
                        return_value=Mock(stdout="3.11.14\n"),
                    ),
                    patch(
                        "netmed.importers.python.discover", return_value=refreshed
                    ) as discover,
                ):
                    export(catalog, root / "bundle")
                    self.assertEqual(discover.call_count, int(bool(stale)))
                result = load(root / "bundle/catalog.json")["sources"]["example"]
                manifest = json.loads((root / "bundle/manifest.json").read_text())
                index = root / "bundle/catalog-search.sqlite"
                self.assertEqual(
                    manifest["search_index_sha256"],
                    hashlib.sha256(index.read_bytes()).hexdigest(),
                )
                # Discovery is a relocatable per-source file, loaded on demand.
                self.assertEqual(
                    Path(result["discovery_file"]["path"]),
                    (root / "bundle/catalog-discovery/example.json.gz").resolve(),
                )
                self.assertNotIn("discovery_metadata", result)
                metadata = discovery_metadata(result)
                self.assertEqual(
                    metadata["operations"]["run"]["doc"],
                    "Refreshed" if stale else "Original",
                )
                self.assertEqual(
                    metadata["configuration_hash"], python_configuration_hash(result)
                )

    def test_api_build_and_export_use_one_snapshot(self):
        from netmed.catalog import build
        from netmed.importers.openapi import load_document

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "sources.toml"
            config.write_text(
                '[sources.api]\nkind="openapi"\nspec="https://example.org/openapi.json"\nbase_url="https://example.org"\n'
            )
            document = {
                "openapi": "3.0.3",
                "info": {"title": "Snapshot A", "version": "1"},
                "paths": {},
            }
            response = Mock(status_code=200, text=json.dumps(document))

            def prepare(source, name, discovered):
                self.assertEqual(load_document(source["spec"]), discovered)
                self.assertFalse(source["spec"].startswith("https://"))
                return {
                    "operation_count": 0,
                    "restish": {"version": "2.3.0", "source": name},
                }

            with (
                patch(
                    "netmed.importers.openapi.requests.get", return_value=response
                ) as request,
                patch("netmed.runtime.restish.prepare", side_effect=prepare),
            ):
                build(
                    config, root / "catalog.json", snapshot_directory=root / "snapshots"
                )
                export(root / "catalog.json", root / "bundle")
                request.assert_called_once()
            self.assertEqual(
                json.loads((root / "bundle/specs/api.json").read_text()), document
            )

    def test_changed_lock_during_refresh_is_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = root / "env"
            env.mkdir()
            (env / "requirements.lock").write_text("example==1\n")
            catalog = root / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "sources": {
                            "example": {
                                "kind": "python",
                                "module": "example",
                                "discovery_metadata": {
                                    "operations": {},
                                    "lock_sha256": "old",
                                },
                            }
                        }
                    }
                )
            )
            with (
                patch(
                    "netmed.release.UvEnvironmentManager.ensure",
                    return_value={"directory": str(env), "python": "python"},
                ),
                patch(
                    "netmed.release.subprocess.run",
                    return_value=Mock(stdout="3.11.14\n"),
                ),
                patch(
                    "netmed.importers.python.discover",
                    return_value={"lock_sha256": "changed"},
                ),
            ):
                with self.assertRaisesRegex(ValueError, "changed during export"):
                    export(catalog, root / "bundle")
            self.assertFalse((root / "bundle").exists())
