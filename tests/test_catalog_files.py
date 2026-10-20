import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from netmed.errors import UserError
from netmed.catalog import (
    discovery_directory,
    discovery_hashes,
    discovery_metadata,
    load,
    write,
)


def catalog(*names):
    return {
        "sources": {
            name: {
                "kind": "python",
                "module": name,
                "discovery_metadata": {
                    "operations": {"run": {"doc": f"Run {name}."}},
                    "configuration_hash": "config-" + name,
                    "lock_sha256": "lock-" + name,
                },
            }
            for name in names
        },
        "disabled_sources": {},
    }


class CatalogFileTests(unittest.TestCase):
    def test_discovery_is_written_per_source_and_loaded_on_demand(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            original = catalog("alpha", "beta")
            write(original, path)
            # The in-memory catalog keeps its metadata.
            self.assertIn("discovery_metadata", original["sources"]["alpha"])
            stored = json.loads(path.read_text())["sources"]["alpha"]
            self.assertNotIn("discovery_metadata", stored)
            self.assertEqual(
                stored["discovery_file"]["path"], "catalog-discovery/alpha.json.gz"
            )
            self.assertEqual(stored["discovery_file"]["operation_count"], 1)
            source = load(path)["sources"]["alpha"]
            self.assertEqual(discovery_hashes(source), ("config-alpha", "lock-alpha"))
            self.assertNotIn("discovery_metadata", source)
            self.assertEqual(
                discovery_metadata(source)["operations"]["run"]["doc"], "Run alpha."
            )

    def test_checksum_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            write(catalog("alpha"), path)
            file = discovery_directory(path) / "alpha.json.gz"
            file.write_bytes(file.read_bytes() + b"tampered")
            with self.assertRaisesRegex(UserError, "checksum mismatch"):
                discovery_metadata(load(path)["sources"]["alpha"])

    def test_catalogs_in_one_directory_do_not_collide_and_stale_files_go(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(catalog("alpha", "beta"), root / "dev.json")
            write(catalog("alpha"), root / "experimental.json")
            self.assertTrue((root / "dev-discovery/beta.json.gz").exists())
            self.assertTrue((root / "experimental-discovery/alpha.json.gz").exists())
            write(catalog("alpha"), root / "dev.json")
            self.assertFalse((root / "dev-discovery/beta.json.gz").exists())
            self.assertTrue((root / "dev-discovery/alpha.json.gz").exists())

    def test_rewriting_a_loaded_catalog_keeps_unloaded_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            write(catalog("alpha"), path)
            loaded = load(path)
            write(loaded, path)
            again = load(path)["sources"]["alpha"]
            self.assertEqual(
                again["discovery_file"]["path"],
                str(discovery_directory(path).resolve() / "alpha.json.gz"),
            )
            self.assertEqual(
                discovery_metadata(again)["operations"]["run"]["doc"], "Run alpha."
            )
            # Writing elsewhere copies the discovery into the new catalog's folder.
            other = Path(directory) / "copy" / "catalog.json"
            write(load(path), other)
            self.assertTrue((discovery_directory(other) / "alpha.json.gz").exists())

    def test_calls_check_hashes_without_reading_discovery(self):
        from netmed.runtime import python

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            write(catalog("alpha"), path)
            source = load(path)["sources"]["alpha"]
            with (
                patch(
                    "netmed.catalog.python_configuration_hash",
                    return_value="config-alpha",
                ),
                patch(
                    "netmed.catalog.discovery_metadata",
                    side_effect=AssertionError("must not load"),
                ),
                patch.object(
                    python.UvEnvironmentManager, "ensure", return_value={"id": "env"}
                ),
            ):
                self.assertEqual(python.prepare(source), {"id": "env"})
