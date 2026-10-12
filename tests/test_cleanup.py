import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from netmed.runtime.cleanup import activity, clean_all, MANAGED_FOLDERS
from netmed.errors import UserError


class CleanupTests(unittest.TestCase):
    def test_dry_run_and_cleanup_keep_root_and_foreign_contents(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": str(Path(directory).resolve())}),
        ):
            root = Path(directory)
            for name in MANAGED_FOLDERS:
                (root / name).mkdir()
            (root / "foreign").mkdir()
            (root / "catalog.json").write_text("keep")
            result = clean_all(dry_run=True)
            self.assertEqual(len(result["would_remove"]), len(MANAGED_FOLDERS))
            self.assertTrue((root / "objects").exists())
            clean_all()
            self.assertTrue(root.exists())
            self.assertTrue((root / "foreign").exists())
            self.assertEqual((root / "catalog.json").read_text(), "keep")
            self.assertFalse((root / "objects").exists())

    def test_active_calls_jobs_and_provisioning_prevent_cleanup(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NETMED_DATA_DIR": str(Path(directory).resolve())}),
        ):
            root = Path(directory)
            with activity():
                with self.assertRaisesRegex(UserError, "active netmed"):
                    clean_all()
            path = root / "jobs" / ("a" * 32)
            path.mkdir(parents=True)
            (path / "status.json").write_text(json.dumps({"state": "queued"}))
            with self.assertRaisesRegex(UserError, "prevents cleanup"):
                clean_all(dry_run=True)
            (path / "status.json").write_text(json.dumps({"state": "completed"}))
            lock = root / "environments" / "abc.lock"
            lock.mkdir(parents=True)
            with self.assertRaisesRegex(UserError, "Provisioning"):
                clean_all()
            self.assertTrue(path.exists())

    def test_symlink_refusal_is_atomic_and_keeps_destination(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            tempfile.TemporaryDirectory() as other,
            patch.dict(os.environ, {"NETMED_DATA_DIR": str(Path(directory).resolve())}),
        ):
            root = Path(directory)
            (root / "jobs").mkdir()
            destination = Path(other) / "keep"
            destination.write_text("keep")
            try:
                (root / "objects").symlink_to(other, target_is_directory=True)
            except OSError:
                self.skipTest("Symlinks unavailable")
            with self.assertRaisesRegex(UserError, "real directory"):
                clean_all()
            self.assertTrue((root / "jobs").exists())
            self.assertTrue(destination.exists())

    def test_dangerous_root_refused(self):
        with patch.dict(os.environ, {"NETMED_DATA_DIR": str(Path.home())}):
            with self.assertRaisesRegex(UserError, "Refusing cleanup"):
                clean_all(dry_run=True)
