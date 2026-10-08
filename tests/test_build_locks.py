import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from netmed.building.locks import apply_lock, input_hash


class BuildLockTests(unittest.TestCase):
    def test_target_inputs_and_checksum_must_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = {"package": "demo", "version": "==1", "python": "3.11"}
            lock = root / "demo.txt"
            lock.write_text("demo==1\n")
            manifest = {
                "target": "test-target",
                "sources": {
                    "demo": {
                        "input_sha256": input_hash(source),
                        "python": "3.11.17",
                        "sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
                    }
                },
            }
            (root / "manifest.json").write_text(json.dumps(manifest))
            with patch(
                "netmed.building.locks.platform_target", return_value="test-target"
            ):
                updated = dict(source)
                apply_lock(updated, "demo", root)
                self.assertEqual(updated["python"], "3.11.17")
                self.assertEqual(updated["lock"]["path"], str(lock.resolve()))
                with self.assertRaisesRegex(ValueError, "inputs changed"):
                    apply_lock({**source, "version": "==2"}, "demo", root)
                lock.write_text("demo==2\n")
                with self.assertRaisesRegex(ValueError, "checksum"):
                    apply_lock(dict(source), "demo", root)
            with patch(
                "netmed.building.locks.platform_target", return_value="wrong-target"
            ):
                with self.assertRaisesRegex(ValueError, "target"):
                    apply_lock(dict(source), "demo", root)
            with self.assertRaisesRegex(ValueError, "Missing"):
                apply_lock(source, "missing", root)
