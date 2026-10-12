"""Explicit cleanup of managed subfolders, coordinated with active CLI calls."""

import contextlib
import json
import os
from pathlib import Path
import shutil
import time
import uuid

from ..errors import UserError
from .layout import data_directory
from .processes import (
    activity_process_identity,
    activity_process_alive,
    worker_is_active,
)
from .job_state import TERMINAL_STATES

MANAGED_FOLDERS = (
    "jobs",
    "objects",
    "environments",
    "runtimes",
    "restish",
    "api-updates",
)


def checked_root():
    configured = os.environ.get("NETMED_DATA_DIR")
    raw = Path(configured).expanduser().absolute() if configured else data_directory()
    if any(path.is_symlink() for path in (raw, *raw.parents)):
        raise UserError("Data directory must not traverse symlinks for cleanup")
    root = raw.resolve()
    if root in (Path(root.anchor), Path.home().resolve(), Path.cwd().resolve()):
        raise UserError(
            "Refusing cleanup in the filesystem root, home or working directory"
        )
    return root


@contextlib.contextmanager
def gate(root):
    path = root / ".netmed-data-gate"
    if path.is_symlink():
        raise UserError("Data coordination path must not be a symlink")
    deadline = time.monotonic() + 2
    while True:
        try:
            path.mkdir()
            break
        except FileExistsError as error:
            if time.monotonic() >= deadline:
                raise UserError(
                    "Data directory is busy; retry after the current operation"
                ) from error
            time.sleep(0.02)
    try:
        yield
    finally:
        path.rmdir()


@contextlib.contextmanager
def activity():
    root = data_directory()
    root.mkdir(parents=True, exist_ok=True)
    leases = root / ".netmed-activity"
    lease = leases / uuid.uuid4().hex
    with gate(root):
        if (root / ".netmed-cleaning").exists():
            raise UserError("Data cleanup is in progress; retry afterwards")
        if leases.is_symlink():
            raise UserError("Data coordination path must not be a symlink")
        leases.mkdir(exist_ok=True)
        lease.write_text(json.dumps(activity_process_identity()))
    try:
        yield
    finally:
        # Cleanup never removes leases while a recorded process is alive.
        lease.unlink(missing_ok=True)


def validate_idle(root):
    leases = root / ".netmed-activity"
    if leases.is_symlink():
        raise UserError("Data coordination path must not be a symlink")
    for lease in leases.glob("*"):
        if lease.is_symlink() or not lease.is_file():
            raise UserError("Invalid activity record; cleanup refused")
        try:
            record = json.loads(lease.read_text())
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise UserError("Cannot verify activity record; cleanup refused") from error
        if activity_process_alive(record):
            raise UserError("An active netmed invocation prevents cleanup")
    jobs = root / "jobs"
    if jobs.exists():
        for path in jobs.iterdir():
            if path.is_symlink() or not path.is_dir():
                raise UserError("Unexpected job artifact; cleanup refused")
            try:
                status_path = path / "status.json"
                if status_path.is_symlink():
                    raise UserError("Symlink job status; cleanup refused")
                status = json.loads(status_path.read_text())
            except (OSError, ValueError) as error:
                raise UserError("Cannot verify job status; cleanup refused") from error
            if status.get("state") not in TERMINAL_STATES or worker_is_active(
                status.get("pid"), path
            ):
                raise UserError(f"Job {path.name} prevents cleanup; stop it first")
    if (
        any((root / "environments").glob("*.lock"))
        or any((root / "runtimes").rglob("*.lock"))
        or any((root / "restish").rglob("*.lock"))
    ):
        raise UserError("Provisioning lock prevents cleanup")


def clean_all(dry_run=False):
    root = checked_root()
    if not root.exists():
        return {
            "dry_run": dry_run,
            "data_directory": str(root),
            "would_remove" if dry_run else "removed": [],
        }
    targets = [
        root / name
        for name in MANAGED_FOLDERS
        if (root / name).exists() or (root / name).is_symlink()
    ]
    # Validate every target before deleting any of them. Never follow symlinks.
    for target in targets:
        if target.is_symlink() or not target.is_dir():
            raise UserError(f"Managed folder {target.name} must be a real directory")
    cleaning = root / ".netmed-cleaning"
    with gate(root):
        if cleaning.exists() or cleaning.is_symlink():
            raise UserError("Cleanup is already in progress")
        validate_idle(root)
        if not dry_run:
            cleaning.mkdir()
    try:
        if not dry_run:
            for target in targets:
                shutil.rmtree(target)
    finally:
        if not dry_run:
            cleaning.rmdir()
    return {
        "dry_run": dry_run,
        "data_directory": str(root),
        "would_remove" if dry_run else "removed": [str(path) for path in targets],
    }
